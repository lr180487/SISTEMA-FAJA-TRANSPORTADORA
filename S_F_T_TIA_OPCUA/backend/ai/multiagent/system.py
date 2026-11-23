from __future__ import annotations

import asyncio
import json
import math
import os
import re
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from backend.ai.multiagent.markdown import (
    _char_trigrams,
    _extract_docx_bytes,
    _extract_pdf_bytes,
    _parse_agent_markdown,
    _slugify_filename,
    _strip_accents,
    _tokenize,
)



class MultiAgentRAGSystem:
    """
    Sistema RAG Multiagente sincronizado con:
    - Agentes definidos en archivos Markdown (/agents/*.md)
    - Biblioteca documental indexada (/knowledge_base/*.md + documentos subidos)
    - Búsqueda Web en vivo: Tavily API (Primario) -> DuckDuckGo API (Fallback)
    - Proveedores LLM sincronizados: OpenAI (Primario) -> Groq -> Gemini -> Ollama
    """

    BUILTIN_DOCS = {
        "manual_operacion_scada_pid.md",
        "guia_control_pid_faja.md",
        "protocolo_seguridad_y_alarmas.md",
    }

    PROVIDER_ORDER = ["openai", "groq", "gemini", "ollama"]
    SEARCH_ORDER = ["tavily", "duckduckgo"]

    def __init__(self, base_dir: Path, db_manager: Optional[Any] = None) -> None:
        self._lock = threading.RLock()
        self.db = db_manager
        self.base_dir = base_dir
        self.agents_dir = base_dir / "agents"
        self.kb_dir = base_dir / "knowledge_base"
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        self.kb_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.kb_dir / ".rag_sync_config.json"

        self.llm_config: Dict[str, Any] = {
            "preferred_provider": os.environ.get("PREFERRED_LLM_PROVIDER", "auto").strip() or "auto",
            "openai_api_key": os.environ.get("OPENAI_API_KEY", "").strip(),
            "openai_base_url": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").strip(),
            "openai_model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip(),
            "groq_api_key": os.environ.get("GROQ_API_KEY", "").strip(),
            "groq_base_url": os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1").strip(),
            "groq_model": os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile").strip(),
            "gemini_api_key": os.environ.get("GEMINI_API_KEY", "").strip(),
            "gemini_model": os.environ.get("GEMINI_MODEL", "gemini-2.0-flash").strip(),
            "ollama_base_url": os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip(),
            "ollama_model": os.environ.get("OLLAMA_MODEL", "llama3.2").strip(),
            # Búsqueda Web: Tavily API -> DuckDuckGo Fallback
            "web_search_mode": os.environ.get("WEB_SEARCH_MODE", "always").strip() or "always",
            "tavily_api_key": os.environ.get("TAVILY_API_KEY", "").strip(),
            "tavily_search_depth": os.environ.get("TAVILY_SEARCH_DEPTH", "basic").strip() or "basic",
        }

        self._load_persisted_config()

        self.agents: Dict[str, Dict[str, Any]] = {}
        self.agent_policies: List[Dict[str, str]] = []
        self.documents: List[Dict[str, Any]] = []
        self.chunks: List[Dict[str, Any]] = []
        self.chat_history: List[Dict[str, Any]] = []
        self.web_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self.last_synced_at: str = datetime.now().strftime("%H:%M:%S")
        self.ollama_online: bool = False

        if self.db is not None:
            self._hydrate_from_database()
        self.reload_all()
        if self.db is not None:
            self._sync_documents_to_database()

    def _hydrate_from_database(self) -> None:
        if self.db is None:
            return
        try:
            saved_cfg = self.db.get_kv_json("rag_llm_config")
            if isinstance(saved_cfg, dict):
                for k, v in saved_cfg.items():
                    if k in self.llm_config and v is not None and str(v).strip() != "":
                        self.llm_config[k] = v

            # Restaurar en disco documentos guardados en BD que no estén aún en knowledge_base/
            db_docs = self.db.load_all_rag_documents()
            for d in db_docs:
                fname = Path(d["filename"]).name
                fpath = self.kb_dir / fname
                if not fpath.exists() and d.get("content"):
                    fpath.write_text(d["content"], encoding="utf-8")

            # Restaurar turnos recientes de conversación
            self.chat_history = self.db.load_recent_chat_turns(limit=30)
        except Exception:
            pass

    def _sync_documents_to_database(self) -> None:
        if self.db is None:
            return
        try:
            for d in self.documents:
                fpath = self.kb_dir / d["filename"]
                if fpath.exists():
                    raw_txt = fpath.read_text(encoding="utf-8", errors="replace")
                    self.db.upsert_rag_document(
                        filename=d["filename"],
                        title=d["title"],
                        content=raw_txt,
                        builtin=bool(d.get("builtin", False)),
                        chunks_count=int(d.get("chunks_count", 1)),
                    )
        except Exception:
            pass

    def _load_persisted_config(self) -> None:
        if not self.config_path.exists():
            return
        try:
            saved = json.loads(self.config_path.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                for k, v in saved.items():
                    if k in self.llm_config and v is not None and str(v).strip() != "":
                        self.llm_config[k] = v
        except Exception:
            pass

    def _save_persisted_config(self) -> None:
        try:
            self.config_path.write_text(
                json.dumps(self.llm_config, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass
        if self.db is not None:
            self.db.set_kv_json("rag_llm_config", self.llm_config)

    # ------------------------------------------------------------------
    # Carga e Indexación Sincronizada de Agentes (.md) y Documentos RAG
    # ------------------------------------------------------------------
    def reload_all(self) -> Dict[str, Any]:
        with self._lock:
            self._load_agents()
            self._load_agent_policies()
            self._index_knowledge_base()
            self.last_synced_at = datetime.now().strftime("%H:%M:%S")
            return {
                "agents": len(self.agents),
                "agent_policies": len(self.agent_policies),
                "documents": len(self.documents),
                "chunks": len(self.chunks),
                "last_synced_at": self.last_synced_at,
            }

    def _load_agents(self) -> None:
        loaded: Dict[str, Dict[str, Any]] = {}
        for md_file in sorted(self.agents_dir.glob("*.md")):
            try:
                parsed = _parse_agent_markdown(md_file)
                loaded[parsed["id"]] = parsed
            except Exception:
                continue
        self.agents = loaded

    def _load_agent_policies(self) -> None:
        """Carga directrices compartidas; no las registra como agentes especialistas."""
        policy_dir = self.agents_dir / "policies"
        loaded: List[Dict[str, str]] = []
        if not policy_dir.exists():
            self.agent_policies = loaded
            return
        for md_file in sorted(policy_dir.glob("*.md")):
            if md_file.name.lower() == "readme.md":
                continue
            try:
                content = md_file.read_text(encoding="utf-8").strip()
                if content:
                    loaded.append({"filename": md_file.name, "content": content})
            except (OSError, UnicodeError):
                continue
        self.agent_policies = loaded

    def _chunk_markdown(self, doc_name: str, text: str) -> List[Dict[str, Any]]:
        lines = text.splitlines()
        sections: List[Tuple[str, List[str]]] = []
        current_heading = Path(doc_name).stem.replace("_", " ").title()
        current_buf: List[str] = []

        for line in lines:
            heading_match = re.match(r"^(#{1,3})\s+(.+)$", line.strip())
            if heading_match:
                if current_buf:
                    sections.append((current_heading, current_buf))
                    current_buf = []
                current_heading = heading_match.group(2).strip()
            else:
                current_buf.append(line)
        if current_buf:
            sections.append((current_heading, current_buf))

        doc_chunks: List[Dict[str, Any]] = []
        chunk_idx = 0
        for heading, sec_lines in sections:
            body = "\n".join(sec_lines).strip()
            if not body:
                continue
            paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
            acc = ""
            for p in paragraphs:
                candidate = f"{acc}\n\n{p}".strip() if acc else p
                if len(candidate) <= 680:
                    acc = candidate
                else:
                    if acc:
                        full_txt = f"### {heading}\n{acc}"
                        doc_chunks.append(self._build_chunk_dict(doc_name, chunk_idx, heading, full_txt))
                        chunk_idx += 1
                    acc = p
            if acc:
                full_txt = f"### {heading}\n{acc}"
                doc_chunks.append(self._build_chunk_dict(doc_name, chunk_idx, heading, full_txt))
                chunk_idx += 1

        if not doc_chunks and text.strip():
            doc_chunks.append(
                self._build_chunk_dict(doc_name, 0, current_heading, text.strip()[:900])
            )
        return doc_chunks

    def _build_chunk_dict(self, doc_name: str, idx: int, section: str, content: str) -> Dict[str, Any]:
        tokens = _tokenize(f"{doc_name} {section} {content}")
        return {
            "chunk_id": f"{doc_name}#c{idx}",
            "document": doc_name,
            "section": section,
            "content": content,
            "tokens": tokens,
            "tf": Counter(tokens),
            "trigrams": _char_trigrams(f"{section} {content}"),
        }

    def _index_knowledge_base(self) -> None:
        docs: List[Dict[str, Any]] = []
        all_chunks: List[Dict[str, Any]] = []

        supported_exts = {".md", ".txt", ".csv", ".json"}
        for fpath in sorted(self.kb_dir.iterdir()):
            if not fpath.is_file() or fpath.name.startswith("."):
                continue
            if fpath.suffix.lower() not in supported_exts:
                continue
            try:
                raw_txt = fpath.read_text(encoding="utf-8", errors="replace").strip()
            except Exception:
                continue
            if not raw_txt:
                continue

            title_match = re.search(r"^#\s+(.+)$", raw_txt, flags=re.MULTILINE)
            title = title_match.group(1).strip() if title_match else fpath.stem.replace("_", " ").title()
            c_list = self._chunk_markdown(fpath.name, raw_txt)
            all_chunks.extend(c_list)

            stat = fpath.stat()
            docs.append(
                {
                    "filename": fpath.name,
                    "title": title,
                    "builtin": fpath.name in self.BUILTIN_DOCS,
                    "size_bytes": stat.st_size,
                    "chunks_count": len(c_list),
                    "updated_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                    "preview": re.sub(r"\s+", " ", re.sub(r"#+\s*", "", raw_txt))[:180].strip(),
                }
            )

        self.documents = docs
        self.chunks = all_chunks

    # ------------------------------------------------------------------
    # Gestión de Documentos RAG
    # ------------------------------------------------------------------
    def add_markdown_document(self, title: str, content: str, filename: Optional[str] = None) -> Dict[str, Any]:
        clean_title = (title or "").strip() or "Documento de Usuario"
        clean_content = (content or "").strip()
        if not clean_content:
            raise ValueError("El contenido del documento no puede estar vacío.")

        slug = _slugify_filename(filename or clean_title)
        target_name = f"{slug}.md"
        target_path = self.kb_dir / target_name

        if target_name in self.BUILTIN_DOCS:
            target_name = f"{slug}_usuario.md"
            target_path = self.kb_dir / target_name

        if not clean_content.lstrip().startswith("#"):
            final_md = f"# {clean_title}\n\n{clean_content}\n"
        else:
            final_md = f"{clean_content}\n"

        target_path.write_text(final_md, encoding="utf-8")
        self.reload_all()
        doc_meta = next((d for d in self.documents if d["filename"] == target_name), None)
        if self.db is not None and doc_meta is not None:
            self.db.upsert_rag_document(
                filename=target_name,
                title=doc_meta["title"],
                content=final_md,
                builtin=False,
                chunks_count=int(doc_meta.get("chunks_count", 1)),
            )
        return {"ok": True, "document": doc_meta, "total_documents": len(self.documents)}

    def add_uploaded_file(self, original_filename: str, raw_bytes: bytes) -> Dict[str, Any]:
        if not raw_bytes:
            raise ValueError("El archivo seleccionado está vacío.")
        if len(raw_bytes) > 8 * 1024 * 1024:
            raise ValueError("El archivo supera el límite máximo de 8 MB.")

        ext = Path(original_filename or "documento.txt").suffix.lower()
        stem_title = Path(original_filename or "Documento").stem.replace("_", " ").replace("-", " ").strip()

        if ext in {".md", ".txt", ".csv"}:
            extracted = raw_bytes.decode("utf-8", errors="replace").strip()
        elif ext == ".json":
            parsed = json.loads(raw_bytes.decode("utf-8", errors="replace"))
            extracted = "```json\n" + json.dumps(parsed, indent=2, ensure_ascii=False) + "\n```"
        elif ext == ".docx":
            extracted = _extract_docx_bytes(raw_bytes)
        elif ext == ".pdf":
            extracted = _extract_pdf_bytes(raw_bytes)
        else:
            extracted = raw_bytes.decode("utf-8", errors="replace").strip()

        if not extracted.strip():
            raise ValueError(f"No se encontró contenido de texto en '{original_filename}'.")

        slug = _slugify_filename(original_filename)
        return self.add_markdown_document(
            title=stem_title or "Documento Subido",
            content=extracted,
            filename=f"{slug}.md",
        )

    def get_document_content(self, filename: str) -> Dict[str, Any]:
        safe_name = Path(filename).name
        if filename.startswith("agent:"):
            ag_file = Path(filename.split(":", 1)[1]).name
            target = self.agents_dir / ag_file
            kind = "agent"
        else:
            target = self.kb_dir / safe_name
            kind = "document"

        if not target.exists() or not target.is_file():
            raise FileNotFoundError(f"Archivo '{safe_name}' no encontrado.")
        return {
            "filename": target.name,
            "kind": kind,
            "content": target.read_text(encoding="utf-8", errors="replace"),
        }

    def delete_document(self, filename: str) -> Dict[str, Any]:
        safe_name = Path(filename).name
        if safe_name in self.BUILTIN_DOCS:
            raise ValueError("Los documentos guía base del sistema no se pueden eliminar.")
        target = self.kb_dir / safe_name
        if not target.exists():
            raise FileNotFoundError(f"El documento '{safe_name}' no existe.")
        target.unlink()
        if self.db is not None:
            self.db.delete_rag_document(safe_name)
        self.reload_all()
        return {"ok": True, "deleted": safe_name, "total_documents": len(self.documents)}

    # ------------------------------------------------------------------
    # Búsqueda Híbrida RAG Local (BM25 + Trigramas)
    # ------------------------------------------------------------------
    def retrieve(self, query: str, top_k: int = 4) -> List[Dict[str, Any]]:
        if not self.chunks:
            return []

        q_tokens = _tokenize(query)
        q_tris = _char_trigrams(query)
        n_docs = len(self.chunks)
        avg_len = sum(len(c["tokens"]) for c in self.chunks) / max(1, n_docs)

        df: Counter = Counter()
        for c in self.chunks:
            for tok in set(c["tokens"]):
                df[tok] += 1

        k1 = 1.5
        b = 0.75
        scored: List[Tuple[float, Dict[str, Any]]] = []

        for c in self.chunks:
            bm25 = 0.0
            c_len = len(c["tokens"])
            for tok in q_tokens:
                if tok not in c["tf"]:
                    continue
                tf_val = c["tf"][tok]
                idf = math.log(1.0 + (n_docs - df[tok] + 0.5) / (df[tok] + 0.5))
                denom = tf_val + k1 * (1.0 - b + b * (c_len / max(1.0, avg_len)))
                bm25 += idf * ((tf_val * (k1 + 1.0)) / max(1e-6, denom))

            tri_score = 0.0
            if q_tris and c["trigrams"]:
                common = sum((q_tris & c["trigrams"]).values())
                norm = math.sqrt(sum(q_tris.values()) * sum(c["trigrams"].values()))
                if norm > 0:
                    tri_score = common / norm

            total = bm25 + (tri_score * 2.2)
            scored.append((total, c))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        top = [
            {
                "chunk_id": item["chunk_id"],
                "document": item["document"],
                "section": item["section"],
                "content": item["content"],
                "score": round(score, 3),
            }
            for score, item in scored[:top_k]
            if score >= 0.55
        ]
        return top

    # ------------------------------------------------------------------
    # Limpieza de Consultas y Detección de Saludos Conversacionales
    # ------------------------------------------------------------------
    @staticmethod
    def _is_greeting_or_chitchat(query: str) -> bool:
        q = re.sub(r"[^a-z0-9\s]", " ", _strip_accents(query.lower()))
        q = re.sub(r"\s+", " ", q).strip()
        exact_greetings = {
            "hola", "hola buenas", "buenos dias", "buenas tardes", "buenas noches",
            "buenas", "hey", "saludos", "que tal", "como estas", "gracias",
            "muchas gracias", "ok", "okay", "listo", "vale", "quien eres",
            "que eres", "que puedes hacer", "ayuda",
        }
        return q in exact_greetings

    @staticmethod
    def _prepare_search_queries(raw_query: str) -> List[str]:
        q = re.sub(r"[¿?¡!\"'`]+", " ", raw_query or "").strip()
        # Quitar verbos/prefijos conversacionales que empeoran los motores de búsqueda
        q_clean = re.sub(
            r"^(por favor\s+)?(busca(r)?|investiga(r)?|encuentra|dime|dame|muestrame|explicame|consultar?|buscar en (la )?web|en internet)\s+(sobre\s+|acerca de\s+|informacion (de|sobre)\s+)?",
            "",
            q,
            flags=re.IGNORECASE,
        ).strip()
        if not q_clean:
            q_clean = q

        variants: List[str] = [q_clean]
        # Variante compacta con palabras clave principales (máx. 5 términos significativos)
        core_words = [
            w for w in re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9_-]+", q_clean)
            if len(w) > 2 and _strip_accents(w.lower()) not in SPANISH_STOPWORDS
        ]
        if len(core_words) >= 2:
            compact = " ".join(core_words[:5])
            if compact.lower() != q_clean.lower():
                variants.append(compact)
        return variants

    # ------------------------------------------------------------------
    # Búsqueda Web en Vivo: Tavily API (Primario) -> DuckDuckGo (Fallback)
    # ------------------------------------------------------------------
    async def _search_tavily(self, query: str, max_results: int = 4) -> Dict[str, Any]:
        raw_key = (self.llm_config.get("tavily_api_key") or "").strip().strip("\"'")
        if raw_key.lower().startswith("bearer "):
            raw_key = raw_key[7:].strip()
        if not raw_key:
            raise RuntimeError("Sin API Key configurada para Tavily.")

        search_q = self._prepare_search_queries(query)[0]
        depth = self.llm_config.get("tavily_search_depth") or "basic"
        payload = {
            "api_key": raw_key,
            "query": search_q,
            "search_depth": depth if depth in ("basic", "advanced") else "basic",
            "include_answer": True,
            "max_results": max_results,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {raw_key}",
        }
        async with httpx.AsyncClient(timeout=14.0) as client:
            resp = await client.post("https://api.tavily.com/search", headers=headers, json=payload)
            if resp.status_code >= 400:
                raise RuntimeError(f"Tavily HTTP {resp.status_code}: {resp.text[:160]}")
            data = resp.json()

        results: List[Dict[str, Any]] = []
        for item in (data.get("results") or [])[:max_results]:
            title = (item.get("title") or "Resultado Web").strip()
            url = (item.get("url") or "").strip()
            snippet = re.sub(r"\s+", " ", (item.get("content") or "").strip())[:360]
            if url:
                results.append(
                    {
                        "title": title,
                        "url": url,
                        "snippet": snippet,
                        "source": "Tavily",
                    }
                )
        if not results:
            raise RuntimeError("Tavily no devolvió resultados para esta consulta.")

        return {
            "answer": (data.get("answer") or "").strip(),
            "results": results,
        }

    def _run_ddgs_sync(self, query: str, max_results: int = 4) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        seen_urls = set()
        query_variants = self._prepare_search_queries(query)

        # 1) DuckDuckGo / Motores integrados en ddgs con región en español y rotación anti-bloqueo
        try:
            from ddgs import DDGS  # type: ignore

            for q_var in query_variants:
                for bk in ("html", "bing", "lite", "auto"):
                    try:
                        raw_items = list(
                            DDGS(timeout=9).text(
                                q_var,
                                region="es-es",
                                backend=bk,
                                max_results=max_results + 2,
                            )
                        )
                    except Exception:
                        continue

                    for r in raw_items:
                        title = (r.get("title") or "").strip()
                        href = (r.get("href") or r.get("url") or "").strip()
                        body = re.sub(r"\s+", " ", (r.get("body") or r.get("snippet") or "").strip())[:360]
                        if not href or not title or href in seen_urls:
                            continue
                        seen_urls.add(href)
                        results.append(
                            {
                                "title": title,
                                "url": href,
                                "snippet": body,
                                "source": "DuckDuckGo",
                            }
                        )
                        if len(results) >= max_results:
                            return results
                if results:
                    return results[:max_results]
        except Exception:
            pass

        # 2) Fallback HTTP directo a DuckDuckGo Instant Answer JSON API
        for q_var in query_variants:
            try:
                resp = httpx.get(
                    "https://api.duckduckgo.com/",
                    params={"q": q_var, "format": "json", "no_html": "1", "skip_disambig": "1"},
                    timeout=7.0,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("AbstractText") and data.get("AbstractURL"):
                        u = data["AbstractURL"]
                        if u not in seen_urls:
                            seen_urls.add(u)
                            results.append(
                                {
                                    "title": data.get("Heading") or q_var,
                                    "url": u,
                                    "snippet": str(data["AbstractText"])[:360],
                                    "source": "DuckDuckGo API",
                                }
                            )
                    for topic in data.get("RelatedTopics") or []:
                        if isinstance(topic, dict) and topic.get("Text") and topic.get("FirstURL"):
                            u = topic["FirstURL"]
                            if u not in seen_urls:
                                seen_urls.add(u)
                                results.append(
                                    {
                                        "title": str(topic["Text"]).split(" - ")[0][:90],
                                        "url": u,
                                        "snippet": str(topic["Text"])[:320],
                                        "source": "DuckDuckGo API",
                                    }
                                )
                        if len(results) >= max_results:
                            return results[:max_results]
            except Exception:
                pass

        # 3) Respaldo enciclopédico abierto (Wikipedia Español API) si DDG limita temporalmente la IP
        for q_var in query_variants:
            try:
                w_resp = httpx.get(
                    "https://es.wikipedia.org/w/api.php",
                    params={
                        "action": "query",
                        "list": "search",
                        "srsearch": q_var,
                        "srlimit": max_results,
                        "format": "json",
                    },
                    headers={"User-Agent": "SCADA-PID-Assistant/1.0"},
                    timeout=7.0,
                )
                if w_resp.status_code == 200:
                    search_hits = w_resp.json().get("query", {}).get("search", [])
                    for hit in search_hits:
                        title = (hit.get("title") or "").strip()
                        raw_snip = re.sub(r"<[^>]+>", "", hit.get("snippet") or "").strip()
                        url = f"https://es.wikipedia.org/wiki/{title.replace(' ', '_')}"
                        if title and url not in seen_urls:
                            seen_urls.add(url)
                            results.append(
                                {
                                    "title": f"{title} — Enciclopedia Técnica",
                                    "url": url,
                                    "snippet": raw_snip[:340],
                                    "source": "DuckDuckGo / Wiki",
                                }
                            )
                        if len(results) >= max_results:
                            return results[:max_results]
            except Exception:
                pass

        return results[:max_results]

    async def search_web(self, query: str, max_results: int = 4) -> Dict[str, Any]:
        """
        Ejecuta búsqueda web siguiendo la cadena:
        1. Tavily API (Primario)
        2. DuckDuckGo (Fallback automático multi-canal sin necesidad de API Key)
        """
        cache_key = f"{bool(self.llm_config.get('tavily_api_key'))}:{_strip_accents(query.lower()).strip()}:{max_results}"
        cached = self.web_cache.get(cache_key)
        now = time.time()
        if cached and (now - cached[0]) < 600 and cached[1].get("results"):
            return cached[1]

        attempts: List[Dict[str, Any]] = []
        web_results: List[Dict[str, Any]] = []
        tavily_summary = ""
        provider_used = "none"

        # 1. Intentar Tavily API
        t0 = time.perf_counter()
        try:
            tav = await self._search_tavily(query, max_results=max_results)
            dt_ms = round((time.perf_counter() - t0) * 1000, 1)
            web_results = tav["results"]
            tavily_summary = tav.get("answer", "")
            provider_used = "tavily"
            attempts.append(
                {
                    "provider": "tavily",
                    "status": "ok",
                    "latency_ms": dt_ms,
                    "detail": f"{len(web_results)} resultados obtenidos",
                }
            )
            out = {
                "provider_used": provider_used,
                "summary": tavily_summary,
                "results": web_results,
                "attempts": attempts,
            }
            self.web_cache[cache_key] = (now, out)
            return out
        except Exception as exc:
            dt_ms = round((time.perf_counter() - t0) * 1000, 1)
            attempts.append(
                {
                    "provider": "tavily",
                    "status": "fallback",
                    "latency_ms": dt_ms,
                    "detail": str(exc)[:140],
                }
            )

        # 2. Fallback automático a DuckDuckGo
        t1 = time.perf_counter()
        try:
            ddg_items = await asyncio.to_thread(self._run_ddgs_sync, query, max_results)
            dt_ms = round((time.perf_counter() - t1) * 1000, 1)
            if ddg_items:
                web_results = ddg_items
                provider_used = "duckduckgo"
                attempts.append(
                    {
                        "provider": "duckduckgo",
                        "status": "ok",
                        "latency_ms": dt_ms,
                        "detail": f"{len(web_results)} resultados obtenidos",
                    }
                )
            else:
                attempts.append(
                    {
                        "provider": "duckduckgo",
                        "status": "empty",
                        "latency_ms": dt_ms,
                        "detail": "Sin coincidencias externas",
                    }
                )
        except Exception as exc:
            dt_ms = round((time.perf_counter() - t1) * 1000, 1)
            attempts.append(
                {
                    "provider": "duckduckgo",
                    "status": "error",
                    "latency_ms": dt_ms,
                    "detail": str(exc)[:140],
                }
            )

        out = {
            "provider_used": provider_used,
            "summary": tavily_summary,
            "results": web_results,
            "attempts": attempts,
        }
        if web_results:
            self.web_cache[cache_key] = (now, out)
        return out

    # ------------------------------------------------------------------
    # Selección Multiagente (.md)
    # ------------------------------------------------------------------
    def route_agents(
        self,
        query: str,
        retrieved: List[Dict[str, Any]],
        web_used: bool = False,
    ) -> List[Dict[str, Any]]:
        q_norm = _strip_accents(query.lower())
        q_tokens = set(_tokenize(query))

        specialists: List[Tuple[float, Dict[str, Any]]] = []
        for ag_id, ag in self.agents.items():
            if ag_id == "orquestador":
                continue
            score = 0.0
            for kw in ag.get("keywords", []):
                if kw and kw in q_norm:
                    score += 2.0
                elif kw in q_tokens:
                    score += 1.5
            if ag_id == "agente_documental_rag" and retrieved:
                if any(r["document"] not in self.BUILTIN_DOCS for r in retrieved):
                    score += 3.0
                else:
                    score += 0.9
            if ag_id == "agente_busqueda_web" and web_used:
                score += 2.6
            specialists.append((score, ag))

        specialists.sort(key=lambda x: x[0], reverse=True)
        chosen: List[Dict[str, Any]] = []
        if "orquestador" in self.agents:
            chosen.append(self.agents["orquestador"])

        active_specs = [ag for sc, ag in specialists if sc >= 1.5][:3]
        if not active_specs and specialists:
            active_specs = [specialists[0][1]]
        chosen.extend(active_specs)
        return chosen

    # ------------------------------------------------------------------
    # Estado y Sincronización de Proveedores LLM + Búsqueda Web
    # ------------------------------------------------------------------
    def _mask_key(self, key: str) -> str:
        k = (key or "").strip()
        if not k:
            return ""
        if len(k) <= 8:
            return "••••"
        return f"{k[:4]}••••{k[-4:]}"

    async def probe_ollama_status(self) -> bool:
        base_url = (self.llm_config.get("ollama_base_url") or "http://127.0.0.1:11434").rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=1.8) as client:
                r = await client.get(f"{base_url}/api/tags")
                self.ollama_online = r.status_code == 200
        except Exception:
            self.ollama_online = False
        return self.ollama_online

    async def sync_all(self) -> Dict[str, Any]:
        """
        Sincroniza archivos .md de agentes, re-indexa documentos RAG, guarda y verifica
        el estado de conexión de los proveedores LLM y de Búsqueda Web (Tavily / DuckDuckGo).
        """
        self.reload_all()
        await self.probe_ollama_status()
        self._save_persisted_config()
        return self.get_overview()

    def get_llm_status(self) -> Dict[str, Any]:
        return {
            "preferred_provider": self.llm_config["preferred_provider"],
            "fallback_chain": ["openai", "groq", "gemini", "ollama"],
            "web_search_mode": self.llm_config["web_search_mode"],
            "search_chain": ["tavily", "duckduckgo"],
            "last_synced_at": self.last_synced_at,
            "providers": {
                "openai": {
                    "label": "OpenAI API (Primario)",
                    "configured": bool(self.llm_config["openai_api_key"]),
                    "masked_key": self._mask_key(self.llm_config["openai_api_key"]),
                    "base_url": self.llm_config["openai_base_url"],
                    "model": self.llm_config["openai_model"],
                },
                "groq": {
                    "label": "Groq Cloud (Fallback 1)",
                    "configured": bool(self.llm_config["groq_api_key"]),
                    "masked_key": self._mask_key(self.llm_config["groq_api_key"]),
                    "base_url": self.llm_config["groq_base_url"],
                    "model": self.llm_config["groq_model"],
                },
                "gemini": {
                    "label": "Google Gemini (Fallback 2)",
                    "configured": bool(self.llm_config["gemini_api_key"]),
                    "masked_key": self._mask_key(self.llm_config["gemini_api_key"]),
                    "model": self.llm_config["gemini_model"],
                },
                "ollama": {
                    "label": "Ollama (Fallback 3)",
                    "configured": bool(self.llm_config["ollama_base_url"]),
                    "online": self.ollama_online,
                    "base_url": self.llm_config["ollama_base_url"],
                    "model": self.llm_config["ollama_model"],
                },
            },
            "web_search": {
                "mode": self.llm_config["web_search_mode"],
                "tavily": {
                    "label": "Tavily Search API (Primario)",
                    "configured": bool(self.llm_config["tavily_api_key"]),
                    "masked_key": self._mask_key(self.llm_config["tavily_api_key"]),
                    "search_depth": self.llm_config["tavily_search_depth"],
                },
                "duckduckgo": {
                    "label": "DuckDuckGo Search (Fallback)",
                    "configured": True,
                    "ready": True,
                },
            },
        }

    def update_llm_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        allowed_str = [
            "preferred_provider",
            "openai_base_url",
            "openai_model",
            "groq_base_url",
            "groq_model",
            "gemini_model",
            "ollama_base_url",
            "ollama_model",
            "web_search_mode",
            "tavily_search_depth",
        ]
        for field in allowed_str:
            if field in updates and updates[field] is not None:
                val = str(updates[field]).strip()
                if val:
                    self.llm_config[field] = val

        for key_field in ("openai_api_key", "groq_api_key", "gemini_api_key", "tavily_api_key"):
            if key_field in updates and updates[key_field] is not None:
                raw_val = str(updates[key_field]).strip()
                if raw_val and "••••" not in raw_val:
                    self.llm_config[key_field] = raw_val

        self.last_synced_at = datetime.now().strftime("%H:%M:%S")
        self._save_persisted_config()
        return self.get_llm_status()

    # ------------------------------------------------------------------
    # Llamadas HTTP a cada proveedor LLM sincronizado con el contexto RAG
    # ------------------------------------------------------------------
    def _recent_conversation_messages(self) -> List[Dict[str, str]]:
        msgs: List[Dict[str, str]] = []
        for turn in self.chat_history[-3:]:
            q = (turn.get("query") or "").strip()
            a = (turn.get("answer") or "").strip()
            if q and a:
                msgs.append({"role": "user", "content": q})
                msgs.append({"role": "assistant", "content": a[:600]})
        return msgs

    async def _call_openai_compatible(
        self,
        provider_name: str,
        base_url: str,
        api_key: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        if not api_key:
            raise RuntimeError(f"Sin API Key configurada para {provider_name.upper()}.")
        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(self._recent_conversation_messages())
        messages.append({"role": "user", "content": user_prompt})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.25,
            "max_tokens": 1000,
        }
        async with httpx.AsyncClient(timeout=24.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:180]}")
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()

    async def _call_gemini(self, system_prompt: str, user_prompt: str) -> str:
        api_key = self.llm_config["gemini_api_key"]
        model = self.llm_config["gemini_model"] or "gemini-2.0-flash"
        if not api_key:
            raise RuntimeError("Sin API Key configurada para GEMINI.")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

        contents: List[Dict[str, Any]] = []
        for m in self._recent_conversation_messages():
            g_role = "model" if m["role"] == "assistant" else "user"
            contents.append({"role": g_role, "parts": [{"text": m["content"]}]})
        contents.append({"role": "user", "parts": [{"text": user_prompt}]})

        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": contents,
            "generationConfig": {"temperature": 0.25, "maxOutputTokens": 1000},
        }
        async with httpx.AsyncClient(timeout=24.0) as client:
            resp = await client.post(url, params={"key": api_key}, json=payload)
            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:180]}")
            data = resp.json()
            candidates = data.get("candidates") or []
            if not candidates:
                raise RuntimeError("Gemini no devolvió candidatos.")
            parts = candidates[0].get("content", {}).get("parts", [])
            return "\n".join(p.get("text", "") for p in parts).strip()

    async def _call_ollama(self, system_prompt: str, user_prompt: str) -> str:
        base_url = (self.llm_config["ollama_base_url"] or "http://127.0.0.1:11434").rstrip("/")
        model = self.llm_config["ollama_model"] or "llama3.2"
        url = f"{base_url}/api/chat"
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(self._recent_conversation_messages())
        messages.append({"role": "user", "content": user_prompt})

        payload = {
            "model": model,
            "stream": False,
            "messages": messages,
        }
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:160]}")
            data = resp.json()
            msg = (data.get("message") or {}).get("content", "").strip()
            if not msg:
                raise RuntimeError("Respuesta vacía de Ollama.")
            self.ollama_online = True
            return msg

    def _build_synchronized_local_synthesis(
        self,
        query: str,
        active_agents: List[Dict[str, Any]],
        retrieved: List[Dict[str, Any]],
        web_data: Dict[str, Any],
        scada_snapshot: Optional[Dict[str, Any]],
    ) -> str:
        agent_names = ", ".join(f"{a['icon']} {a['name']}" for a in active_agents)
        lines: List[str] = []
        q_low = _strip_accents(query.lower())

        if self._is_greeting_or_chitchat(query):
            state_txt = ""
            if scada_snapshot:
                plc = scada_snapshot.get("plc", {})
                kin = scada_snapshot.get("kinematics", {})
                state_es = {
                    "RUNNING": "en marcha",
                    "STOPPED": "detenida",
                    "PAUSED": "en pausa",
                    "FAULT": "en falla",
                    "E_STOP": "en parada de emergencia",
                }.get(plc.get("state", ""), "activa")
                state_txt = f" En este momento la faja está **{state_es}** a **{kin.get('actual_speed_mps', 0):.2f} m/s**."
            return (
                f"¡Hola! Soy tu asistente de **SCADA PID**.{state_txt}\n\n"
                "Puedo ayudarte a:\n"
                "- Consultar tus documentos guardados.\n"
                "- Buscar información en internet.\n"
                "- Orientarte sobre la velocidad y la operación de la faja."
            )

        if scada_snapshot and any(
            w in q_low for w in ["estado", "actual", "velocidad", "pid", "faja", "cuanto", "como esta", "resumen"]
        ):
            plc = scada_snapshot.get("plc", {})
            kin = scada_snapshot.get("kinematics", {})
            prod = scada_snapshot.get("production", {})
            pid = scada_snapshot.get("pid", {})
            state_es = {
                "RUNNING": "EN MARCHA",
                "STOPPED": "DETENIDA",
                "PAUSED": "EN PAUSA",
                "FAULT": "EN FALLA",
                "E_STOP": "PARADA DE EMERGENCIA",
            }.get(plc.get("state", ""), plc.get("state", "N/A"))
            modo_es = "Automático" if pid.get("mode", "AUTO") == "AUTO" else "Manual"
            lines.append(
                f"**Estado actual de la faja:** **{state_es}** a "
                f"**{kin.get('actual_speed_mps', 0):.2f} m/s** (meta: **{kin.get('target_speed_mps', 0):.2f} m/s**), "
                f"con **{prod.get('items_on_belt', 0)} cajas en banda** ({prod.get('dispatched_count', 0)} entregadas) "
                f"y control de velocidad en modo **{modo_es}**."
            )

        doc_titles = {d["filename"]: d["title"] for d in self.documents}
        if retrieved:
            lines.append("**Según tus documentos:**")
            for idx, chunk in enumerate(retrieved[:2], start=1):
                clean_body = re.sub(r"^###\s+.*\n?", "", chunk["content"]).strip()
                excerpt = clean_body if len(clean_body) <= 320 else clean_body[:317].rsplit(" ", 1)[0] + "..."
                d_title = doc_titles.get(chunk["document"], chunk["section"])
                lines.append(f"{idx}. **{chunk['section']}** (*{d_title}*): {excerpt}")

        web_results = web_data.get("results") or []
        if web_data.get("summary"):
            lines.append(f"**Resumen de internet:** {web_data['summary']}")
        if web_results:
            lines.append("**Información encontrada en internet:**")
            for idx, wr in enumerate(web_results[:4], start=1):
                snip = wr.get("snippet") or "Enlace disponible abajo."
                lines.append(f"{idx}. **{wr['title']}** — {snip}")

        if not retrieved and not web_results:
            lines.append("No se encontró información relacionada para esta consulta.")

        return "\n\n".join(lines)

    # ------------------------------------------------------------------
    # Ejecución Sincronizada: RAG (.md) + Web Search (Tavily->DDG) + LLM
    # ------------------------------------------------------------------
    async def ask(
        self,
        query: str,
        scada_snapshot: Optional[Dict[str, Any]] = None,
        preferred_provider: Optional[str] = None,
        web_search_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        clean_query = (query or "").strip()
        if not clean_query:
            raise ValueError("Escribe una consulta para el Agente RAG.")

        if preferred_provider and preferred_provider in ("auto", *self.PROVIDER_ORDER):
            self.llm_config["preferred_provider"] = preferred_provider
        if web_search_mode and web_search_mode in ("always", "auto", "off"):
            self.llm_config["web_search_mode"] = web_search_mode

        t_start = time.perf_counter()
        is_chitchat = self._is_greeting_or_chitchat(clean_query)

        # 1. Recuperar fragmentos de documentos .md locales (RAG) solo si no es un simple saludo
        retrieved = [] if is_chitchat else self.retrieve(clean_query, top_k=4)
        best_local_score = max((r["score"] for r in retrieved), default=0.0)

        # 2. Determinar si ejecutar Búsqueda Web (Tavily -> DuckDuckGo)
        effective_search_mode = (web_search_mode or self.llm_config.get("web_search_mode") or "always").lower()
        q_norm = _strip_accents(clean_query.lower())
        needs_web_auto = (
            best_local_score < 3.2
            or any(
                kw in q_norm
                for kw in [
                    "web", "internet", "busca", "buscar", "investiga", "norma", "iso",
                    "fabricante", "externo", "que es", "historia", "comparar", "actual",
                    "mantenimiento", "buenas practicas", "noticias", "precio", "hoy",
                ]
            )
        )
        should_run_web = (not is_chitchat) and (
            effective_search_mode == "always" or (effective_search_mode == "auto" and needs_web_auto)
        )

        web_data: Dict[str, Any] = {"provider_used": "off", "summary": "", "results": [], "attempts": []}
        if should_run_web:
            web_data = await self.search_web(clean_query, max_results=4)

        has_web_results = bool(web_data.get("results"))

        # 3. Seleccionar Agentes .md activos
        active_agents = self.route_agents(clean_query, retrieved, web_used=has_web_results)

        # 4. Construir contexto unificado y sincronizado para el LLM
        agents_prompt_blocks = [
            f"### {ag['icon']} {ag['name']} ({ag['filename']})\n{ag['instructions']}"
            for ag in active_agents
        ]
        rag_blocks = [
            f"[Documento Local: {c['document']} | Sección: {c['section']} | Relevancia: {c['score']}]\n{c['content']}"
            for c in retrieved
        ]
        web_blocks = [
            f"[Web #{idx} ({w['source']}): {w['title']} | URL: {w['url']}]\n{w['snippet']}"
            for idx, w in enumerate(web_data.get("results") or [], start=1)
        ]
        if web_data.get("summary"):
            web_blocks.insert(0, f"[Resumen Tavily AI]\n{web_data['summary']}")

        live_summary = ""
        if scada_snapshot:
            plc = scada_snapshot.get("plc", {})
            kin = scada_snapshot.get("kinematics", {})
            prod = scada_snapshot.get("production", {})
            pid = scada_snapshot.get("pid", {})
            motor = scada_snapshot.get("motor", {})
            live_summary = (
                f"Estado faja: {plc.get('state')} | Velocidad real: {kin.get('actual_speed_mps')} m/s | "
                f"Velocidad meta: {kin.get('target_speed_mps')} m/s | Carga actual: {prod.get('current_load_kg')} kg | "
                f"Cajas en banda: {prod.get('items_on_belt')} | Despachadas: {prod.get('dispatched_count')} | "
                f"Rechazadas: {prod.get('rejected_count')} | Temp motor: {motor.get('temp_c')} °C | "
                f"PID Modo: {pid.get('mode')} (P={pid.get('kp')}, I={pid.get('ki')}, D={pid.get('kd')}, Potencia={pid.get('cv_pct')}%)"
            )

        system_prompt = (
            "Eres el Sistema Multiagente RAG sincronizado de SCADA PID. Responde SIEMPRE en español claro, preciso y práctico.\n"
            "Combina de forma coherente:\n"
            "1) Los DOCUMENTOS LOCALES (.md) del RAG de SCADA PID.\n"
            "2) Los RESULTADOS DE BÚSQUEDA WEB (Tavily / DuckDuckGo) cuando estén presentes.\n"
            "3) El ESTADO EN VIVO de la faja transportadora.\n\n"
            "POLÍTICAS GLOBALES DEL MULTIAGENTE (.md):\\n"
            + (
                "\\n\\n---\\n\\n".join(
                    f"[Política: {p['filename']}]\\n{p['content']}"
                    for p in self.agent_policies
                )
                if self.agent_policies
                else "Aplicar principios de seguridad, fidelidad documental y transparencia."
            )
            + "\\n\\nAGENTES ACTIVOS (.md):\\n"
            + "\\n\\n".join(agents_prompt_blocks)
            + "\\n\\nESTADO EN VIVO DE LA FAJA TRANSPORTADORA:\\n"
            + (live_summary or "No disponible")
            + "\n\nCONTEXTO RAG LOCAL (ARCHIVOS .MD):\n"
            + ("\n\n---\n\n".join(rag_blocks) if rag_blocks else "Sin fragmentos locales.")
            + "\n\nCONTEXTO DE BÚSQUEDA WEB (TAVILY / DUCKDUCKGO):\n"
            + ("\n\n---\n\n".join(web_blocks) if web_blocks else "Búsqueda web no requerida o sin resultados.")
        )

        user_prompt = (
            f"Consulta del usuario: {clean_query}\n\n"
            "Entrega una respuesta clara y estructurada integrando el conocimiento RAG local, "
            "los hallazgos de búsqueda web (si los hay) y el estado actual de SCADA PID."
        )

        # 5. Ejecutar cadena LLM sincronizada: OpenAI -> Groq -> Gemini -> Ollama
        pref = (self.llm_config.get("preferred_provider") or "auto").lower()
        if pref in self.PROVIDER_ORDER:
            chain = [pref] + [p for p in self.PROVIDER_ORDER if p != pref]
        else:
            chain = list(self.PROVIDER_ORDER)

        attempts: List[Dict[str, Any]] = []
        answer_text: Optional[str] = None
        provider_used = "local-rag"
        model_used = "Síntesis Sincronizada RAG + Web"

        for prov in chain:
            p_t0 = time.perf_counter()
            try:
                if prov == "openai":
                    ans = await self._call_openai_compatible(
                        provider_name="openai",
                        base_url=self.llm_config["openai_base_url"],
                        api_key=self.llm_config["openai_api_key"],
                        model=self.llm_config["openai_model"],
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                    )
                    model_used = self.llm_config["openai_model"]
                elif prov == "groq":
                    ans = await self._call_openai_compatible(
                        provider_name="groq",
                        base_url=self.llm_config["groq_base_url"],
                        api_key=self.llm_config["groq_api_key"],
                        model=self.llm_config["groq_model"],
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                    )
                    model_used = self.llm_config["groq_model"]
                elif prov == "gemini":
                    ans = await self._call_gemini(system_prompt=system_prompt, user_prompt=user_prompt)
                    model_used = self.llm_config["gemini_model"]
                elif prov == "ollama":
                    ans = await self._call_ollama(system_prompt=system_prompt, user_prompt=user_prompt)
                    model_used = self.llm_config["ollama_model"]
                else:
                    continue

                dt_ms = round((time.perf_counter() - p_t0) * 1000, 1)
                attempts.append({"provider": prov, "status": "ok", "latency_ms": dt_ms, "detail": "Sincronizado OK"})
                answer_text = ans
                provider_used = prov
                break
            except Exception as exc:
                dt_ms = round((time.perf_counter() - p_t0) * 1000, 1)
                attempts.append(
                    {
                        "provider": prov,
                        "status": "fallback",
                        "latency_ms": dt_ms,
                        "detail": str(exc)[:140],
                    }
                )

        if not answer_text:
            answer_text = self._build_synchronized_local_synthesis(
                query=clean_query,
                active_agents=active_agents,
                retrieved=retrieved,
                web_data=web_data,
                scada_snapshot=scada_snapshot,
            )

        doc_titles_map = {d["filename"]: d["title"] for d in self.documents}
        total_ms = round((time.perf_counter() - t_start) * 1000, 1)
        turn_record = {
            "turn_id": f"turn-{int(time.time() * 1000)}-{len(self.chat_history) + 1}",
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "query": clean_query,
            "answer": answer_text,
            "provider_used": provider_used,
            "model_used": model_used,
            "latency_ms": total_ms,
            "active_agents": [
                {"id": a["id"], "name": a["name"], "icon": a["icon"], "filename": a["filename"], "role": a["role"]}
                for a in active_agents
            ],
            "sources": [
                {
                    "document": r["document"],
                    "title": doc_titles_map.get(r["document"], r["section"]),
                    "section": r["section"],
                    "score": r["score"],
                }
                for r in retrieved
            ],
            "web_search": {
                "provider_used": web_data.get("provider_used", "off"),
                "results": web_data.get("results", []),
                "attempts": web_data.get("attempts", []),
            },
            "attempts": attempts,
        }
        with self._lock:
            self.chat_history.append(turn_record)
            if len(self.chat_history) > 40:
                self.chat_history = self.chat_history[-40:]
        if self.db is not None:
            await asyncio.to_thread(self.db.insert_chat_turn, turn_record)
        return turn_record

    def clear_history(self) -> None:
        with self._lock:
            self.chat_history.clear()
        if self.db is not None:
            self.db.clear_chat_turns()

    def get_overview(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "agents": [
                    {
                        "id": a["id"],
                        "filename": a["filename"],
                        "name": a["name"],
                        "role": a["role"],
                        "icon": a["icon"],
                        "keywords": a["keywords"],
                    }
                    for a in self.agents.values()
                ],
                "agent_policies": [p["filename"] for p in self.agent_policies],
                "documents": list(self.documents),
                "total_chunks": len(self.chunks),
                "last_synced_at": self.last_synced_at,
                "llm": self.get_llm_status(),
                "history": list(self.chat_history[-15:]),
            }

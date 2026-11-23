"""Utilidades Markdown, normalización y extracción documental del Multiagent."""
from __future__ import annotations

import io
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

def _strip_accents(text: str) -> str:
    norm = unicodedata.normalize("NFD", text or "")
    return "".join(ch for ch in norm if unicodedata.category(ch) != "Mn")


SPANISH_STOPWORDS = {
    "de", "la", "que", "el", "en", "y", "a", "los", "del", "se", "las", "por",
    "un", "para", "con", "no", "una", "su", "al", "lo", "como", "mas", "pero",
    "sus", "le", "ya", "o", "este", "si", "porque", "esta", "entre", "cuando",
    "muy", "sin", "sobre", "tambien", "me", "hasta", "hay", "donde", "quien",
    "desde", "todo", "nos", "durante", "todos", "uno", "les", "ni", "contra",
    "otros", "ese", "eso", "ante", "ellos", "e", "esto", "mi", "antes", "algunos",
    "unos", "yo", "otro", "otras", "otra", "tanto", "esa", "estos", "mucho",
    "quienes", "nada", "muchos", "cual", "poco", "ella", "estar", "estas",
    "algunas", "algo", "nosotros", "es", "son", "cuales", "puedo", "puede",
}


def _tokenize(text: str) -> List[str]:
    clean = _strip_accents(text.lower())
    tokens = re.findall(r"[a-z0-9_]+", clean)
    return [t for t in tokens if len(t) > 1 and t not in SPANISH_STOPWORDS]


def _char_trigrams(text: str) -> Counter:
    clean = re.sub(r"\s+", " ", _strip_accents(text.lower())).strip()
    if len(clean) < 3:
        return Counter([clean]) if clean else Counter()
    return Counter(clean[i : i + 3] for i in range(len(clean) - 2))


def _slugify_filename(name: str) -> str:
    stem = Path(name).stem
    clean = _strip_accents(stem.lower())
    clean = re.sub(r"[^a-z0-9_-]+", "_", clean).strip("_")
    return clean or f"documento_{int(time.time())}"


def _extract_docx_bytes(raw: bytes) -> str:
    try:
        import docx  # type: ignore

        doc = docx.Document(io.BytesIO(raw))
        lines = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text and c.text.strip()]
                if cells:
                    lines.append(" | ".join(cells))
        if lines:
            return "\n\n".join(lines)
    except Exception:
        pass

    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        xml_bytes = zf.read("word/document.xml")
    root = ET.fromstring(xml_bytes)
    paragraphs: List[str] = []
    for elem in root.iter():
        if elem.tag.endswith("}p"):
            texts = [t.text for t in elem.iter() if t.tag.endswith("}t") and t.text]
            joined = "".join(texts).strip()
            if joined:
                paragraphs.append(joined)
    return "\n\n".join(paragraphs)


def _extract_pdf_bytes(raw: bytes) -> str:
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(io.BytesIO(raw))
        pages: List[str] = []
        for idx, page in enumerate(reader.pages, start=1):
            txt = (page.extract_text() or "").strip()
            if txt:
                pages.append(f"## Página {idx}\n\n{txt}")
        if pages:
            return "\n\n".join(pages)
    except Exception:
        pass

    decoded = raw.decode("latin-1", errors="ignore")
    matches = re.findall(r"\(([^\(\)\\]{4,})\)", decoded)
    cleaned = " ".join(m for m in matches if re.search(r"[A-Za-zÁÉÍÓÚáéíóúñÑ]{3,}", m))
    if cleaned.strip():
        return cleaned.strip()
    raise ValueError("No se pudo extraer texto legible del archivo PDF.")


def _parse_agent_markdown(md_path: Path) -> Dict[str, Any]:
    raw = md_path.read_text(encoding="utf-8")
    meta: Dict[str, str] = {}
    body = raw

    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            fm_lines = parts[1].strip().splitlines()
            body = parts[2].strip()
            for line in fm_lines:
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip().lower()] = v.strip()

    agent_id = meta.get("id") or md_path.stem
    keywords = [
        _strip_accents(k.strip().lower())
        for k in (meta.get("keywords") or "").split(",")
        if k.strip()
    ]
    return {
        "id": agent_id,
        "filename": md_path.name,
        "name": meta.get("name") or agent_id.replace("_", " ").title(),
        "role": meta.get("role") or "Agente Especialista",
        "icon": meta.get("icon") or "🤖",
        "keywords": keywords,
        "instructions": body,
    }


__all__ = [
    "SPANISH_STOPWORDS", "_strip_accents", "_tokenize", "_char_trigrams",
    "_slugify_filename", "_extract_docx_bytes", "_extract_pdf_bytes",
    "_parse_agent_markdown",
]

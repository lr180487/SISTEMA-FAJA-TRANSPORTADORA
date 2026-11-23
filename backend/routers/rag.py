<<<<<<< HEAD
"""Compatibilidad: router trasladado a backend.api.routers.rag."""
from backend.api.routers.rag import router  # noqa: F401
=======
from __future__ import annotations

import asyncio
import base64
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from backend.schemas import (
    RagAddTextDocumentRequest,
    RagAskRequest,
    RagLlmConfigRequest,
    RagUploadFileRequest,
    RagWebSearchRequest,
)
from backend.state import app_state

router = APIRouter(prefix="/api/v1/rag", tags=["Asistente IA y Documentos"])


@router.get("/overview")
async def get_rag_overview() -> Dict[str, Any]:
    await asyncio.to_thread(app_state.rag_system.reload_all)
    return app_state.rag_system.get_overview()


@router.post("/sync")
async def sync_rag_and_llm() -> Dict[str, Any]:
    await app_state.rag_system.sync_all()
    overview = await app_state.broadcast_rag_overview()
    return {"ok": True, "overview": overview}


@router.post("/ask")
async def ask_rag_multiagent(req: RagAskRequest) -> Dict[str, Any]:
    try:
        turn = await app_state.rag_system.ask(
            query=req.query,
            scada_snapshot=app_state.simulator.get_snapshot(),
            preferred_provider=req.preferred_provider,
            web_search_mode=req.web_search_mode,
        )
        await app_state.broadcast_rag_overview()
        return turn
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/web-search")
async def run_rag_web_search(req: RagWebSearchRequest) -> Dict[str, Any]:
    clean_q = (req.query or "").strip()
    if not clean_q:
        raise HTTPException(status_code=400, detail="Escribe un tema para buscar en internet.")

    web_res = await app_state.rag_system.search_web(clean_q, max_results=4)
    saved_doc = None
    if req.save_to_rag and web_res.get("results"):
        md_lines = [f"# Consulta: {clean_q}", ""]
        if web_res.get("summary"):
            md_lines.extend(["## Resumen", web_res["summary"], ""])
        md_lines.append("## Fuentes Consultadas")
        for idx, item in enumerate(web_res["results"], start=1):
            md_lines.append(f"### {idx}. {item['title']}")
            md_lines.append(f"- Enlace: {item['url']}")
            md_lines.append(f"- Resumen: {item['snippet']}")
            md_lines.append("")
        saved = await asyncio.to_thread(
            app_state.rag_system.add_markdown_document,
            f"Consulta · {clean_q[:48]}",
            "\n".join(md_lines),
        )
        saved_doc = saved.get("document")
        overview = await app_state.broadcast_rag_overview()
    else:
        overview = app_state.rag_system.get_overview()

    return {
        "ok": True,
        "web_search": web_res,
        "saved_document": saved_doc,
        "overview": overview,
    }


@router.post("/documents/text")
async def add_rag_text_document(req: RagAddTextDocumentRequest) -> Dict[str, Any]:
    try:
        res = await asyncio.to_thread(
            app_state.rag_system.add_markdown_document,
            req.title,
            req.content,
            req.filename,
        )
        overview = await app_state.broadcast_rag_overview()
        return {**res, "overview": overview}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/documents/upload")
async def upload_rag_document(req: RagUploadFileRequest) -> Dict[str, Any]:
    try:
        raw_bytes = base64.b64decode(req.content_base64)
        res = await asyncio.to_thread(
            app_state.rag_system.add_uploaded_file,
            req.filename,
            raw_bytes,
        )
        overview = await app_state.broadcast_rag_overview()
        return {**res, "overview": overview}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/documents/{filename:path}")
async def read_rag_document(filename: str) -> Dict[str, Any]:
    try:
        return await asyncio.to_thread(app_state.rag_system.get_document_content, filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/documents/{filename}")
async def remove_rag_document(filename: str) -> Dict[str, Any]:
    try:
        res = await asyncio.to_thread(app_state.rag_system.delete_document, filename)
        overview = await app_state.broadcast_rag_overview()
        return {**res, "overview": overview}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/llm-config")
async def configure_rag_llm(req: RagLlmConfigRequest) -> Dict[str, Any]:
    status = app_state.rag_system.update_llm_config(req.model_dump(exclude_none=True))
    overview = await app_state.broadcast_rag_overview()
    return {"ok": True, "llm": status, "overview": overview}


@router.post("/clear-history")
async def clear_rag_chat_history() -> Dict[str, Any]:
    app_state.rag_system.clear_history()
    overview = await app_state.broadcast_rag_overview()
    return {"ok": True, "overview": overview}
>>>>>>> 6b869b7 (Initial commit: S_F_T)

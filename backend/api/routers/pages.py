from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse, Response

from backend.core.config import settings

router = APIRouter(include_in_schema=False)


@router.get("/")
@router.get("/index.html")
async def serve_dashboard() -> Response:
    index_path = settings.frontend_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return JSONResponse({"message": "Panel SCADA PID no encontrado."})


@router.get("/ayuda")
@router.get("/ayuda.html")
async def serve_help_html() -> Response:
    help_path = settings.frontend_dir / "ayuda.html"
    if help_path.exists():
        return FileResponse(str(help_path))
    return JSONResponse({"message": "Guía de ayuda no encontrada."})

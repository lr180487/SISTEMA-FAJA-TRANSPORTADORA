<<<<<<< HEAD
"""Compatibilidad: router trasladado a backend.api.routers.database."""
from backend.api.routers.database import router  # noqa: F401
=======
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query

from backend.schemas import DatabaseReconnectRequest
from backend.state import app_state

router = APIRouter(prefix="/api/v1/db", tags=["Base de Datos (PostgreSQL / SQLite)"])


@router.get("/status")
async def get_database_status() -> Dict[str, Any]:
    """Devuelve el motor activo (`postgresql` o `sqlite`), estado de fallback y conteo de tablas."""
    return await asyncio.to_thread(app_state.db.get_status)


@router.post("/reconnect")
async def reconnect_database(
    req: Optional[DatabaseReconnectRequest] = None,
) -> Dict[str, Any]:
    """
    Recarga `.env` (o prueba una `database_url` explícita), intenta conectar a PostgreSQL
    y conmuta automáticamente a SQLite si PostgreSQL no está disponible.
    """
    custom_url = req.database_url if req else None
    status = await asyncio.to_thread(app_state.db.reconnect, custom_url)
    snap = app_state.simulator.get_snapshot()
    await asyncio.to_thread(app_state.db.save_runtime_state_from_snapshot, snap)
    await asyncio.to_thread(app_state.rag_system._sync_documents_to_database)
    return {
        "ok": True,
        "database": status,
    }


@router.get("/telemetry")
async def get_persisted_telemetry(
    limit: int = Query(default=100, ge=1, le=1000),
) -> Dict[str, Any]:
    rows = await asyncio.to_thread(app_state.db.query_telemetry_log, limit)
    return {
        "ok": True,
        "active_engine": app_state.db.active_backend,
        "count": len(rows),
        "items": rows,
    }


@router.get("/events")
async def get_persisted_events(
    limit: int = Query(default=100, ge=1, le=500),
    level: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    rows = await asyncio.to_thread(app_state.db.query_events_log, limit, level)
    return {
        "ok": True,
        "active_engine": app_state.db.active_backend,
        "count": len(rows),
        "items": rows,
    }
>>>>>>> 6b869b7 (Initial commit: S_F_T)

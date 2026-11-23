from __future__ import annotations

import asyncio
from typing import Any, Dict

from fastapi import APIRouter

from backend.core.config import settings
from backend.state import app_state

router = APIRouter(prefix="/api/v1", tags=["Sistema y Sincronización"])


@router.get("/health")
async def health_check() -> Dict[str, Any]:
    return {
        "status": "online",
        "service": settings.app_name,
        "version": settings.app_version,
        "plc_state": app_state.simulator.state,
        "seq": app_state.current_seq,
        "ws_clients": app_state.ws_hub.client_count,
        "database": {
            "active_engine": app_state.db.active_backend,
            "fallback_active": app_state.db.fallback_active,
        },
    }


@router.get("/bootstrap")
async def get_bootstrap_state() -> Dict[str, Any]:
    """
    Entrega en una sola respuesta el estado completo y sincronizado del sistema:
    simulación SCADA, controlador PID, estado de BD y asistente documental/web.
    """
    return app_state.get_bootstrap_bundle(reload_docs=False)


@router.post("/sync")
async def force_full_sync() -> Dict[str, Any]:
    """
    Re-sincroniza documentos, conexiones del asistente, persistencia en BD y telemetría
    en vivo, notificando simultáneamente a todos los clientes conectados vía WebSocket.
    """
    await app_state.rag_system.sync_all()
    bundle = app_state.get_bootstrap_bundle(reload_docs=False)
    await asyncio.to_thread(app_state.db.save_runtime_state_from_snapshot, bundle["snapshot"])
    if app_state.ws_hub.has_clients:
        await app_state.ws_hub.broadcast(
            {
                "type": "bootstrap",
                "seq": bundle["seq"],
                "snapshot": bundle["snapshot"],
                "rag_overview": bundle["rag_overview"],
            }
        )
    return bundle

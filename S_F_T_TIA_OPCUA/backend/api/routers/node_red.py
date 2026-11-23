from __future__ import annotations

import hmac
import time
from typing import Any

from fastapi import APIRouter, Header, HTTPException, WebSocket, WebSocketDisconnect

from backend.core.config import settings
from backend.realtime.node_red_monitor import node_red_monitor

router = APIRouter(prefix="/api/v1/node-red", tags=["Node-RED monitor"])


def _authorize(token: str | None) -> None:
    expected = settings.node_red_monitor_token
    if not expected:
        raise HTTPException(status_code=503, detail="Monitor Node-RED no configurado: define NODE_RED_MONITOR_TOKEN en .env")
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Token de monitor Node-RED inválido")


@router.get("/status")
async def get_node_red_status() -> dict[str, Any]:
    status = node_red_monitor.status(settings.node_red_stale_after_s)
    return {"ok": True, **status}


@router.get("/events")
async def get_node_red_events(limit: int = 50) -> dict[str, Any]:
    return {"ok": True, "events": node_red_monitor.history(limit), "status": node_red_monitor.status(settings.node_red_stale_after_s)}


@router.post("/events", status_code=202)
async def ingest_node_red_event(
    payload: dict[str, Any],
    x_node_red_token: str | None = Header(default=None, alias="X-Node-RED-Token"),
) -> dict[str, Any]:
    _authorize(x_node_red_token)
    event_type = str(payload.get("event") or payload.get("type") or "activity")[:64]
    event = {
        "event": event_type,
        "node_id": str(payload.get("node_id", ""))[:128],
        "node_type": str(payload.get("node_type", ""))[:80],
        "node_name": str(payload.get("node_name", ""))[:120],
        "flow_id": str(payload.get("flow_id", ""))[:128],
        "flow_name": str(payload.get("flow_name", ""))[:120],
        "level": str(payload.get("level", "info"))[:16].lower(),
        "message": str(payload.get("message", ""))[:1000],
        "timestamp": payload.get("timestamp") or time.time(),
        "source": "node-red",
    }
    await node_red_monitor.publish(event, settings.node_red_stale_after_s)
    return {"ok": True, "accepted": True, "seq": event.get("seq"), "status": node_red_monitor.status(settings.node_red_stale_after_s)}


@router.websocket("/ws")
async def node_red_websocket(ws: WebSocket) -> None:
    await node_red_monitor.connect(ws, settings.node_red_stale_after_s)
    try:
        while True:
            message = await ws.receive_text()
            if message == "ping":
                await node_red_monitor.send(ws, {"type": "pong", "server_ts": time.time()})
    except WebSocketDisconnect:
        await node_red_monitor.disconnect(ws)
    except Exception:
        await node_red_monitor.disconnect(ws)

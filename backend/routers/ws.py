<<<<<<< HEAD
"""Compatibilidad: router trasladado a backend.api.routers.ws."""
from backend.api.routers.ws import router  # noqa: F401
=======
from __future__ import annotations

import json
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.state import app_state

router = APIRouter()


@router.websocket("/ws/telemetry")
async def websocket_telemetry(ws: WebSocket) -> None:
    """
    Canal WebSocket bidireccional de sincronización en tiempo real:
    - Envía paquete `bootstrap` inmediato al conectar (SCADA + PID + Asistente IA).
    - Recibe comandos `command`, ajustes `pid`, solicitudes `request_sync` y latidos `ping`.
    """
    await app_state.ws_hub.connect(ws)
    try:
        initial = app_state.get_bootstrap_bundle(reload_docs=False)
        await app_state.ws_hub.send_json(
            ws,
            {
                "type": "bootstrap",
                "seq": initial["seq"],
                "snapshot": initial["snapshot"],
                "rag_overview": initial["rag_overview"],
            },
        )

        while True:
            msg_txt = await ws.receive_text()
            try:
                data = json.loads(msg_txt)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue

            msg_type = data.get("type")
            if msg_type == "ping":
                await app_state.ws_hub.send_json(
                    ws,
                    {
                        "type": "pong",
                        "client_ts": data.get("client_ts"),
                        "server_ts": int(time.time() * 1000),
                        "seq": app_state.current_seq,
                    },
                )
            elif msg_type == "request_sync":
                bundle = app_state.get_bootstrap_bundle(reload_docs=False)
                await app_state.ws_hub.send_json(
                    ws,
                    {
                        "type": "bootstrap",
                        "seq": bundle["seq"],
                        "snapshot": bundle["snapshot"],
                        "rag_overview": bundle["rag_overview"],
                    },
                )
            elif msg_type == "command" and data.get("action"):
                app_state.simulator.execute_command(
                    action=str(data["action"]),
                    value=data.get("value"),
                    source="HMI-WS",
                    params=data.get("params") or {},
                )
                await app_state.broadcast_telemetry(persist_state=True)
            elif msg_type == "pid" and isinstance(data.get("payload"), dict):
                p = data["payload"]
                app_state.simulator.update_pid_config(
                    mode=p.get("mode"),
                    kp=p.get("kp"),
                    ki=p.get("ki"),
                    kd=p.get("kd"),
                    p_enabled=p.get("p_enabled"),
                    i_enabled=p.get("i_enabled"),
                    d_enabled=p.get("d_enabled"),
                    filter_tf=p.get("filter_tf"),
                    cv_min=p.get("cv_min"),
                    cv_max=p.get("cv_max"),
                    manual_cv=p.get("manual_cv"),
                    setpoint_mps=p.get("setpoint_mps"),
                    disturbance_pct=p.get("disturbance_pct"),
                    preset=p.get("preset"),
                    reset_integral=bool(p.get("reset_integral", False)),
                    reset_metrics=bool(p.get("reset_metrics", False)),
                    pulse_disturbance=bool(p.get("pulse_disturbance", False)),
                    source="HMI-WS",
                )
                await app_state.broadcast_telemetry(persist_state=True)
    except WebSocketDisconnect:
        await app_state.ws_hub.disconnect(ws)
    except Exception:
        await app_state.ws_hub.disconnect(ws)
>>>>>>> 6b869b7 (Initial commit: S_F_T)

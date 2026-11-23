<<<<<<< HEAD
"""Compatibilidad: router trasladado a backend.api.routers.scada."""
from backend.api.routers.scada import router  # noqa: F401
=======
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Query, Response
from fastapi.responses import PlainTextResponse

from backend.schemas import ControlCommandRequest
from backend.state import app_state

router = APIRouter(prefix="/api/v1", tags=["Simulación y Control SCADA"])


@router.get("/status")
async def get_full_status() -> Dict[str, Any]:
    return app_state.get_synchronized_snapshot()


@router.get("/sensors")
async def get_sensor_registers() -> Dict[str, Any]:
    return app_state.simulator.get_register_map()


@router.get("/history")
async def get_telemetry_history(
    limit: int = Query(default=60, ge=5, le=180),
) -> Dict[str, Any]:
    snap = app_state.simulator.get_snapshot()
    return {
        "count": min(limit, len(app_state.simulator.history)),
        "items": list(app_state.simulator.history)[-limit:],
        "plc_state": snap["plc"]["state"],
    }


@router.get("/export/csv")
async def export_telemetry_csv() -> Response:
    csv_data = app_state.simulator.export_history_csv()
    return PlainTextResponse(
        content=csv_data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="telemetria_scada_pid.csv"'},
    )


@router.post("/control")
async def control_conveyor(cmd: ControlCommandRequest) -> Dict[str, Any]:
    result = app_state.simulator.execute_command(
        action=cmd.action,
        value=cmd.value,
        source=cmd.source or "HMI-WEB",
        params=cmd.params,
    )
    # Persistir cambio en PostgreSQL/SQLite y difundir a todos los clientes WebSocket
    snap = await app_state.broadcast_telemetry(persist_state=True)
    result["seq"] = snap["seq"]
    result["snapshot"] = snap
    return result
>>>>>>> 6b869b7 (Initial commit: S_F_T)

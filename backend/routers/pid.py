<<<<<<< HEAD
"""Compatibilidad: router trasladado a backend.api.routers.pid."""
from backend.api.routers.pid import router  # noqa: F401
=======
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from backend.schemas import PidConfigRequest
from backend.state import app_state

router = APIRouter(prefix="/api/v1/pid", tags=["Controlador PID"])


@router.get("")
async def get_pid_status() -> Dict[str, Any]:
    snap = app_state.get_synchronized_snapshot()
    return {
        "seq": snap["seq"],
        "pid": snap["pid"],
    }


@router.get("/presets")
async def get_pid_presets() -> Dict[str, Any]:
    return {
        "active_preset": app_state.simulator.pid_preset,
        "presets": app_state.simulator.PID_PRESETS,
    }


@router.post("")
async def configure_pid(cfg: PidConfigRequest) -> Dict[str, Any]:
    res = app_state.simulator.update_pid_config(
        mode=cfg.mode,
        kp=cfg.kp,
        ki=cfg.ki,
        kd=cfg.kd,
        p_enabled=cfg.p_enabled,
        i_enabled=cfg.i_enabled,
        d_enabled=cfg.d_enabled,
        filter_tf=cfg.filter_tf,
        cv_min=cfg.cv_min,
        cv_max=cfg.cv_max,
        manual_cv=cfg.manual_cv,
        setpoint_mps=cfg.setpoint_mps,
        disturbance_pct=cfg.disturbance_pct,
        preset=cfg.preset,
        reset_integral=cfg.reset_integral,
        reset_metrics=cfg.reset_metrics,
        pulse_disturbance=cfg.pulse_disturbance,
        source=cfg.source or "PID-TUNER",
    )
    # Persistir cambio PID en PostgreSQL/SQLite y difundir a todos los clientes WebSocket
    snap = await app_state.broadcast_telemetry(persist_state=True)
    res["seq"] = snap["seq"]
    res["snapshot"] = snap
    return res
>>>>>>> 6b869b7 (Initial commit: S_F_T)

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.core.config import settings
from backend.api.routers import database, node_red, pages, pid, rag, scada, system, ws
from backend.state import app_state

logger = logging.getLogger("scada_pid.main")


def _flush_db_batch(
    events: list[Dict[str, Any]],
    snap_for_telemetry: Optional[Dict[str, Any]],
    snap_for_state: Optional[Dict[str, Any]],
) -> None:
    """Persistir eventos, telemetría y estado fuera del event loop."""
    for event in events:
        app_state.db.insert_event(event)
    if snap_for_telemetry is not None:
        app_state.db.insert_telemetry_sample(snap_for_telemetry)
    if snap_for_state is not None:
        app_state.db.save_runtime_state_from_snapshot(snap_for_state)


async def _simulation_loop() -> None:
    """Simulación 20 Hz, difusión WebSocket 10 Hz y persistencia periódica."""
    tick_counter = 0
    last_telemetry_db_save = time.monotonic()
    last_state_db_save = time.monotonic()

    while True:
        try:
            app_state.simulator.step()
            tick_counter += 1

            if (
                tick_counter % max(1, settings.ws_broadcast_every_ticks) == 0
                and app_state.ws_hub.has_clients
            ):
                await app_state.broadcast_telemetry(persist_state=False)

            now_mono = time.monotonic()
            pending_events = app_state.drain_pending_events(max_items=25)
            need_telemetry_save = (
                now_mono - last_telemetry_db_save
                >= settings.db_telemetry_save_interval_s
            )
            need_state_save = (
                now_mono - last_state_db_save >= settings.db_state_save_interval_s
            )

            if pending_events or need_telemetry_save or need_state_save:
                current_snapshot = app_state.simulator.get_snapshot()
                if need_telemetry_save:
                    last_telemetry_db_save = now_mono
                if need_state_save:
                    last_state_db_save = now_mono

                await asyncio.to_thread(
                    _flush_db_batch,
                    pending_events,
                    current_snapshot if need_telemetry_save else None,
                    current_snapshot if need_state_save else None,
                )

        except asyncio.CancelledError:
            raise
        except Exception:
            # No ocultar fallos de simulación o persistencia: quedan visibles en logs.
            logger.exception("Error durante el ciclo de simulación/persistencia SCADA")

        await asyncio.sleep(max(0.01, settings.sim_dt_s))


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Inicializar y cerrar tareas de fondo con persistencia final segura."""
    db_info = app_state.db.get_status()
    active_engine = str(db_info.get("active_engine", "unknown")).upper()
    fallback = bool(db_info.get("fallback_active", False))
    logger.info(
        "SCADA PID iniciado | version=%s | db=%s | fallback_sqlite=%s | frontend=%s",
        settings.app_version,
        active_engine,
        fallback,
        settings.frontend_dir,
    )

    if not settings.frontend_dir.joinpath("index.html").is_file():
        logger.error("No se encontró frontend/index.html en %s", settings.frontend_dir)

    simulation_task = asyncio.create_task(
        _simulation_loop(),
        name="scada-pid-simulation",
    )
    application.state.simulation_task = simulation_task

    try:
        yield
    finally:
        simulation_task.cancel()
        try:
            await simulation_task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("La tarea de simulación terminó con un error")

        try:
            final_snapshot = app_state.simulator.get_snapshot()
            await asyncio.to_thread(
                app_state.db.save_runtime_state_from_snapshot,
                final_snapshot,
            )
        except Exception:
            logger.exception("No se pudo persistir el estado final de SCADA PID")

        logger.info("SCADA PID detenido correctamente")


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        description=settings.app_description,
        version=settings.app_version,
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.middleware("http")
    async def disable_static_cache(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if (
            path in ("/", "/index.html", "/ayuda", "/ayuda.html")
            or path.startswith("/static/")
        ):
            response.headers["Cache-Control"] = (
                "no-store, no-cache, must-revalidate, max-age=0"
            )
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    # Los endpoints de la API y la interfaz HMI usan el mismo origen.
    application.include_router(system.router)
    application.include_router(database.router)
    application.include_router(scada.router)
    application.include_router(pid.router)
    application.include_router(rag.router)
    application.include_router(ws.router)
    application.include_router(node_red.router)
    application.include_router(pages.router)

    # El path se resuelve desde la raíz real del proyecto, no desde backend/.
    if settings.frontend_dir.is_dir():
        application.mount(
            "/static",
            StaticFiles(directory=str(settings.frontend_dir), html=False),
            name="static",
        )
    else:
        logger.error("Directorio frontend inexistente: %s", settings.frontend_dir)

    return application


app = create_app()

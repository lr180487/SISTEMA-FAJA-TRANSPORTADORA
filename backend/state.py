from __future__ import annotations

import asyncio
import queue
import threading
import time
from typing import Any, Dict, List

<<<<<<< HEAD
from backend.core.config import settings
from backend.infrastructure.database import DatabaseManager
from backend.ai.multiagent.system import MultiAgentRAGSystem
from backend.domain.simulation import ConveyorSimulator, iso_now
from backend.realtime.ws_hub import RealtimeHub
=======
from backend.config import settings
from backend.database import DatabaseManager
from backend.rag_multiagent import MultiAgentRAGSystem
from backend.simulation import ConveyorSimulator, iso_now
from backend.ws_hub import RealtimeHub
>>>>>>> 6b869b7 (Initial commit: S_F_T)


class ApplicationState:
    """
    Contenedor central de servicios de dominio, persistencia relacional
    (PostgreSQL -> SQLite Fallback) y estado sincronizado para SCADA PID.
    """

    def __init__(self) -> None:
        self._seq_lock = threading.Lock()
        self._seq: int = 0
        self._event_db_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=300)

        self.ws_hub = RealtimeHub()
        self.db = DatabaseManager()

        # Inicializar simulador y restaurar estado guardado en BD si existe
        self.simulator = ConveyorSimulator(event_hook=self._on_sim_event)
        saved_state = self.db.load_runtime_state()
        if saved_state:
            self.simulator.restore_persisted_state(saved_state)
        else:
            # Aplicar valores iniciales configurados en `.env` y persistir semilla inicial
            self.simulator.update_pid_config(
                preset=settings.default_pid_preset,
                setpoint_mps=settings.default_setpoint_mps,
                source="ENV-INIT",
            )
            self.db.save_runtime_state_from_snapshot(self.simulator.get_snapshot())

        # Inicializar sistema multiagente sincronizado con la BD
        self.rag_system = MultiAgentRAGSystem(base_dir=settings.base_dir, db_manager=self.db)

    def _on_sim_event(self, evt: Dict[str, Any]) -> None:
        try:
            self._event_db_queue.put_nowait(evt)
        except queue.Full:
            pass

    def drain_pending_events(self, max_items: int = 25) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        while len(items) < max_items and not self._event_db_queue.empty():
            try:
                items.append(self._event_db_queue.get_nowait())
            except queue.Empty:
                break
        return items

    def next_seq(self) -> int:
        with self._seq_lock:
            self._seq += 1
            return self._seq

    @property
    def current_seq(self) -> int:
        with self._seq_lock:
            return self._seq

    def get_synchronized_snapshot(self) -> Dict[str, Any]:
        seq = self.next_seq()
        snap = self.simulator.get_snapshot()
        snap["seq"] = seq
        snap["server_epoch_ms"] = int(time.time() * 1000)
        return snap

    def get_bootstrap_bundle(self, reload_docs: bool = False) -> Dict[str, Any]:
        if reload_docs:
            self.rag_system.reload_all()
        snap = self.get_synchronized_snapshot()
        return {
            "ok": True,
            "seq": snap["seq"],
            "timestamp": iso_now(),
            "system": {
                "name": settings.app_name,
                "version": settings.app_version,
                "ws_clients": self.ws_hub.client_count,
                "database": {
                    "online": True,
                    "active_engine": self.db.active_backend,
                    "fallback_active": self.db.fallback_active,
                },
            },
            "snapshot": snap,
            "rag_overview": self.rag_system.get_overview(),
        }

    async def broadcast_telemetry(self, persist_state: bool = False) -> Dict[str, Any]:
        snap = self.get_synchronized_snapshot()
        if persist_state:
            await asyncio.to_thread(self.db.save_runtime_state_from_snapshot, snap)
        if self.ws_hub.has_clients:
            await self.ws_hub.broadcast(
                {
                    "type": "telemetry",
                    "seq": snap["seq"],
                    "snapshot": snap,
                }
            )
        return snap

    async def broadcast_rag_overview(self) -> Dict[str, Any]:
        overview = self.rag_system.get_overview()
        seq = self.next_seq()
        if self.ws_hub.has_clients:
            await self.ws_hub.broadcast(
                {
                    "type": "rag_overview",
                    "seq": seq,
                    "overview": overview,
                }
            )
        return overview


app_state = ApplicationState()

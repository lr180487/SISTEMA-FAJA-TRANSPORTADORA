<<<<<<< HEAD
from backend.realtime.ws_hub import *  # noqa: F401,F403
=======
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Set

from fastapi import WebSocket


class RealtimeHub:
    """
    Concentrador WebSocket asíncrono para sincronización bidireccional en tiempo real
    entre el backend Python y todos los clientes conectados del frontend.
    """

    def __init__(self) -> None:
        self._clients: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    @property
    def client_count(self) -> int:
        return len(self._clients)

    @property
    def has_clients(self) -> bool:
        return bool(self._clients)

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def send_json(self, ws: WebSocket, payload: Dict[str, Any]) -> bool:
        try:
            await ws.send_text(json.dumps(payload, ensure_ascii=False))
            return True
        except Exception:
            await self.disconnect(ws)
            return False

    async def broadcast(self, payload: Dict[str, Any]) -> None:
        if not self._clients:
            return
        encoded = json.dumps(payload, ensure_ascii=False)
        clients_snapshot: List[WebSocket] = list(self._clients)

        results = await asyncio.gather(
            *(self._safe_send_text(ws, encoded) for ws in clients_snapshot),
            return_exceptions=True,
        )
        dead_clients = [
            ws for ws, ok in zip(clients_snapshot, results) if ok is not True
        ]
        if dead_clients:
            async with self._lock:
                for ws in dead_clients:
                    self._clients.discard(ws)

    @staticmethod
    async def _safe_send_text(ws: WebSocket, text: str) -> bool:
        try:
            await ws.send_text(text)
            return True
        except Exception:
            return False
>>>>>>> 6b869b7 (Initial commit: S_F_T)

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any

from fastapi import WebSocket


class NodeRedMonitor:
    """Recibe actividad instrumentada de Node-RED y la distribuye por WebSocket."""

    def __init__(self, history_limit: int = 200) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=history_limit)
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._last_seen: float | None = None
        self._last_event_type = "never"
        self._sequence = 0

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def status(self, stale_after_s: int = 30) -> dict[str, Any]:
        now = time.time()
        age = None if self._last_seen is None else max(0.0, now - self._last_seen)
        online = age is not None and age <= stale_after_s
        return {
            "online": online,
            "state": "online" if online else "offline",
            "last_seen": self._last_seen,
            "last_seen_age_s": round(age, 2) if age is not None else None,
            "last_event_type": self._last_event_type,
            "event_count": len(self._events),
            "subscribers": self.client_count,
            "stale_after_s": stale_after_s,
        }

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(self._events)[:max(1, min(limit, 200))]

    async def connect(self, ws: WebSocket, stale_after_s: int) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)
        await self.send(ws, {"type": "node_red_snapshot", "status": self.status(stale_after_s), "events": self.history(50)})

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def send(self, ws: WebSocket, payload: dict[str, Any]) -> bool:
        try:
            await ws.send_json(payload)
            return True
        except Exception:
            await self.disconnect(ws)
            return False

    async def publish(self, event: dict[str, Any], stale_after_s: int) -> None:
        async with self._lock:
            self._sequence += 1
            event["seq"] = self._sequence
            self._events.appendleft(event)
            self._last_seen = time.time()
            self._last_event_type = str(event.get("event", "activity"))
            clients = list(self._clients)
        payload = {"type": "node_red_event", "event": event, "status": self.status(stale_after_s)}
        if clients:
            results = await asyncio.gather(*(self.send(ws, payload) for ws in clients), return_exceptions=True)
            dead = [ws for ws, result in zip(clients, results) if result is not True]
            if dead:
                async with self._lock:
                    for ws in dead:
                        self._clients.discard(ws)


node_red_monitor = NodeRedMonitor()

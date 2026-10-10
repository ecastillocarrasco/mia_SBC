"""Difusión SSE en tiempo real de eventos diagnósticos al panel de administración."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any


class LiveBroadcaster:
    """Hub de eventos en tiempo real basado en SSE (igual que el chat).

    Cada cliente conectado al panel obtiene una cola personal. Los eventos
    se publican asíncronamente de forma fire-and-forget: si una cola está
    llena, el evento más antiguo se descarta (el panel vive en tiempo real,
    no necesita un buffer histórico completo).
    """

    _MAX_QUEUE_SIZE = 256

    def __init__(self) -> None:
        self._queues: list[asyncio.Queue[dict[str, Any] | None]] = []

    def _alive_queues(self) -> list[asyncio.Queue[dict[str, Any] | None]]:
        return [q for q in self._queues if not q.full()]

    def subscribe(self) -> asyncio.Queue[dict[str, Any] | None]:
        q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=self._MAX_QUEUE_SIZE)
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any] | None]) -> None:
        try:
            self._queues.remove(q)
        except ValueError:
            pass
        # Desbloquea al consumidor enviando sentinel
        if not q.full():
            q.put_nowait(None)

    def publish(self, data: dict[str, Any]) -> None:
        """Publica un evento a todos los suscriptores activos (fire-and-forget)."""
        dead: list[asyncio.Queue[dict[str, Any] | None]] = []
        for q in list(self._queues):
            try:
                if q.full():
                    # Descarta el más antiguo para hacer hueco
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                q.put_nowait(data)
            except Exception:  # pragma: no cover
                dead.append(q)
        for q in dead:
            self.unsubscribe(q)

    async def stream(self, q: asyncio.Queue[dict[str, Any] | None]) -> AsyncIterator[str]:
        """Generador SSE para un cliente concreto."""
        try:
            while True:
                try:
                    data = await asyncio.wait_for(q.get(), timeout=30.0)
                except TimeoutError:
                    yield "event: ping\ndata: {}\n\n"
                    continue
                if data is None:  # sentinel: cliente desconectado
                    break
                yield f"event: diagnostic\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
        finally:
            self.unsubscribe(q)

    def subscriber_count(self) -> int:
        return len(self._queues)

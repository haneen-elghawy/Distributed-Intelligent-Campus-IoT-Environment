"""
src/nodes/coap_node.py
Composite node that pairs a physics room model with a CoAP server.

CoAP rooms: rooms 11-20 on every floor.
The node wraps :class:`~src.coap.server.RoomCoAPServer` and drives it from
whatever physics/engine object is provided, forwarding state updates as
CoAP Observe notifications.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from src.coap.server import RoomCoAPServer

logger = logging.getLogger(__name__)


class CoAPRoomNode:
    """Lifecycle manager for a CoAP-enabled room node.

    Parameters
    ----------
    floor:
        1-based floor index (1-10).
    room:
        Room number within the floor (11-20 for CoAP rooms).
    room_model:
        An object with a ``get_state() -> dict`` method supplied by the
        physics engine.  Pass ``None`` during standalone testing.
    publish_interval:
        Seconds between push-notifications when no external trigger fires.
    """

    def __init__(
        self,
        floor: int,
        room: int,
        room_model: Optional[Any] = None,
        *,
        publish_interval: float = 5.0,
    ) -> None:
        self.floor = floor
        self.room = room
        self._model = room_model
        self._interval = publish_interval
        self._server = RoomCoAPServer(floor=floor, room=room)
        self._task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the underlying CoAP server and the polling loop."""
        await self._server.start()
        self._task = asyncio.create_task(self._poll_loop(), name=self._task_name())
        logger.info(
            "CoAP room node started  floor=%d  room=%d  port=%d",
            self.floor, self.room, self._server.port,
        )

    async def stop(self) -> None:
        """Cancel the poll loop and shut down the CoAP server."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._server.stop()
        logger.info(
            "CoAP room node stopped  floor=%d  room=%d", self.floor, self.room
        )

    # ------------------------------------------------------------------
    # State push (called externally by the engine)
    # ------------------------------------------------------------------

    def push_state(self, state: dict) -> None:
        """Push an already-computed state snapshot immediately."""
        self._server.push(state)

    # ------------------------------------------------------------------
    # Internal poll loop (fallback when no external push is available)
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            if self._model is not None:
                try:
                    state = self._model.get_state()
                    self._server.push(state)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "CoAP poll error  floor=%d  room=%d  exc=%s",
                        self.floor, self.room, exc,
                    )

    def _task_name(self) -> str:
        return f"coap-poll-f{self.floor:02d}-r{self.room:02d}"

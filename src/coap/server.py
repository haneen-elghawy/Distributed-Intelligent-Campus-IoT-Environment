"""
src/coap/server.py
Per-room CoAP server with an Observable resource.

Each room on a CoAP-designated floor (rooms 11-20 per floor) runs its own
aiocoap server bound to a unique UDP port derived from COAP_BASE_PORT:

    port = COAP_BASE_PORT + (floor_index * 10) + room_offset

The room resource publishes sensor readings and supports CoAP Observe
(RFC 7641) so subscribed clients receive automatic notifications whenever
the physics engine updates the room state.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

import aiocoap
import aiocoap.resource as resource

logger = logging.getLogger(__name__)

COAP_BASE_PORT: int = int(os.getenv("COAP_BASE_PORT", "5683"))


# ---------------------------------------------------------------------------
# Observable room resource
# ---------------------------------------------------------------------------

class RoomResource(resource.ObservableResource):
    """CoAP Observable resource that represents a single physical room.

    Clients may GET the current state or subscribe via Observe.  The physics
    engine calls :meth:`update_state` whenever new telemetry is available,
    which triggers a notification to all observers.
    """

    def __init__(self, floor: int, room: int) -> None:
        super().__init__()
        self.floor = floor
        self.room = room
        self._state: dict = {}

    # ------------------------------------------------------------------
    # Public API called by the physics / engine layer
    # ------------------------------------------------------------------

    def update_state(self, state: dict) -> None:
        """Push a new state snapshot and notify observers."""
        self._state = state
        self.updated_state()          # signals aiocoap to push notifications

    # ------------------------------------------------------------------
    # CoAP handlers
    # ------------------------------------------------------------------

    async def render_get(self, request: aiocoap.Message) -> aiocoap.Message:
        payload = json.dumps(self._state).encode("utf-8")
        return aiocoap.Message(
            code=aiocoap.CONTENT,
            payload=payload,
            content_format=aiocoap.numbers.media_types_rev["application/json"],
        )


# ---------------------------------------------------------------------------
# Per-room CoAP server
# ---------------------------------------------------------------------------

class RoomCoAPServer:
    """Wraps a single aiocoap :class:`Context` for one room.

    Parameters
    ----------
    floor:
        1-based floor index.
    room:
        Room number within the floor (11-20 for CoAP rooms).
    port:
        UDP port to bind.  Defaults to the auto-calculated value.
    """

    def __init__(self, floor: int, room: int, port: Optional[int] = None) -> None:
        self.floor = floor
        self.room = room
        self.port = port or self._calc_port(floor, room)
        self._resource = RoomResource(floor, room)
        self._context: Optional[aiocoap.Context] = None

    @staticmethod
    def _calc_port(floor: int, room: int) -> int:
        """Derive a unique port from floor/room indices.

        Rooms 11-20 map to offsets 0-9 within a floor block of 10 ports.
        Floor blocks are 200 ports apart to avoid collisions across 10 floors.

        Example:
            floor=1, room=11 → COAP_BASE_PORT + 0   = 5683
            floor=1, room=12 → COAP_BASE_PORT + 1   = 5684
            floor=2, room=11 → COAP_BASE_PORT + 200 = 5883
        """
        floor_offset = (floor - 1) * 200
        room_offset = room - 11          # rooms 11-20 → offsets 0-9
        return COAP_BASE_PORT + floor_offset + room_offset

    async def start(self) -> None:
        """Bind the UDP socket and expose the room resource."""
        site = resource.Site()
        site.add_resource(
            [f"floor{self.floor}", f"room{self.room}"],
            self._resource,
        )
        self._context = await aiocoap.Context.create_server_context(
            site,
            bind=("::", self.port),
        )
        logger.info(
            "CoAP server started  floor=%d  room=%d  port=%d",
            self.floor, self.room, self.port,
        )

    async def stop(self) -> None:
        if self._context is not None:
            await self._context.shutdown()
            logger.info(
                "CoAP server stopped  floor=%d  room=%d", self.floor, self.room
            )

    def push(self, state: dict) -> None:
        """Convenience wrapper – update the observable resource state."""
        self._resource.update_state(state)

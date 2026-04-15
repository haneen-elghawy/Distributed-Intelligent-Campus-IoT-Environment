"""
src/nodes/coap_node.py
Lifecycle wrapper that pairs a Room with its aiocoap server instance.

CoAP rooms: rooms 11-20 on every floor.

Each CoapNode:
- Starts an aiocoap server on room.coap_port
- Holds the shared TelemetryResource so the engine can trigger Observe pushes
- Exposes notify() (called after each physics tick) and stop()
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from ..coap.server import TelemetryResource, run_coap_server

if TYPE_CHECKING:
    import aiocoap
    from src.models.room import Room

logger = logging.getLogger("nodes.coap_node")


class CoapNode:
    """One aiocoap server instance bound to a single Room.

    Parameters
    ----------
    room :
        The :class:`~src.models.room.Room` object this node represents.
        ``room.coap_port`` and ``room.node_id`` must already be set by fleet.py.
    """

    def __init__(self, room: "Room") -> None:
        self.room = room
        self.telemetry: TelemetryResource = TelemetryResource(room)
        self._protocol: "aiocoap.Context | None" = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Bind UDP port and expose CoAP resources."""
        self._protocol = await run_coap_server(self.room, self.telemetry)
        logger.info(
            "CoAP node %s started on port %d",
            self.room.node_id, self.room.coap_port,
        )

    async def stop(self) -> None:
        """Shut down the aiocoap server context."""
        if self._protocol is not None:
            await self._protocol.shutdown()
            logger.info("CoAP node %s stopped", self.room.node_id)
            self._protocol = None

    # ------------------------------------------------------------------
    # Physics-engine integration
    # ------------------------------------------------------------------

    async def notify(self) -> None:
        """Call after each physics tick to push RFC 7641 Observe notifications.

        Internally delegates to :meth:`TelemetryResource.notify_watchers`,
        which only triggers a push when the rounded temperature has changed.
        """
        await self.telemetry.notify_watchers()

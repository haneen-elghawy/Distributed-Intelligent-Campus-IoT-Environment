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
import os
import time
from typing import TYPE_CHECKING

from ..coap.alert_client import send_coap_alert
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
        self._last_coap_temp_alert_ts: float = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Bind UDP port and expose CoAP resources."""
        try:
            self._protocol = await run_coap_server(self.room, self.telemetry)
            logger.info(
                "CoAP node %s started on port %d",
                self.room.node_id, self.room.coap_port,
            )
        except Exception as e:
            self._protocol = None
            logger.warning(
                "CoAP node %s failed to bind on port %d: %s",
                self.room.node_id,
                self.room.coap_port,
                e,
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

    async def maybe_send_temperature_alert(
        self,
        *,
        temp_high: float,
        cooldown_s: float,
        gateway_host: str,
        gateway_port: int,
    ) -> None:
        """POST a CON alert to the floor gateway when temperature exceeds *temp_high*.

        Rate-limited by *cooldown_s* between alerts for this node.
        """
        temp = self.room.temperature
        if temp <= temp_high:
            return
        now = time.time()
        if now - self._last_coap_temp_alert_ts < cooldown_s:
            return
        try:
            await send_coap_alert(
                gateway_host,
                gateway_port,
                self.room.floor_id,
                self.room.room_id,
                "HIGH_TEMP",
                round(temp, 1),
            )
            self._last_coap_temp_alert_ts = now
        except OSError as e:
            logger.warning(
                "CoAP alert failed for %s (%s:%s): %s",
                self.room.node_id,
                gateway_host,
                gateway_port,
                e,
            )
        except Exception:
            logger.exception("CoAP alert unexpected error for %s", self.room.node_id)

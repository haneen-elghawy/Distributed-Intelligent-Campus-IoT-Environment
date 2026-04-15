"""
src/coap/server.py
Per-room aiocoap resources and server factory for CoAP rooms (11-20 per floor).

Resources exposed per room
--------------------------
GET/OBSERVE  /<f{FF}/r{RRR}/telemetry>       – RFC 7641 Observable telemetry
PUT          /<f{FF}/r{RRR}/actuators/hvac>  – Downstream actuation from gateway

The server is bound to a unique UDP port stored in room.coap_port (set by
fleet.py at startup, sequential from COAP_BASE_PORT=5683).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING

import aiocoap
import aiocoap.resource as resource
from aiocoap import Code, Message

if TYPE_CHECKING:
    from src.models.room import Room

logger = logging.getLogger("coap.server")


# ---------------------------------------------------------------------------
# TelemetryResource  – GET / OBSERVE
# ---------------------------------------------------------------------------

class TelemetryResource(resource.ObservableResource):
    """RFC 7641 Observable resource.

    aiocoap calls ``render_get`` for every GET and every Observe notification.
    ``notify_watchers()`` is driven externally (engine tick); it calls
    ``self.updated_state()`` only when the temperature value has changed, which
    causes aiocoap to re-render and push to all registered observers.
    """

    def __init__(self, room: "Room") -> None:
        super().__init__()
        self.room = room
        self._last_temp: float | None = None

    # ------------------------------------------------------------------
    # CoAP handler
    # ------------------------------------------------------------------

    async def render_get(self, request: Message) -> Message:
        payload = self._build_payload().encode()
        return Message(
            code=Code.CONTENT,
            payload=payload,
            content_format=aiocoap.numbers.media_types_rev["application/json"],
        )

    # ------------------------------------------------------------------
    # Observe trigger
    # ------------------------------------------------------------------

    async def notify_watchers(self) -> None:
        """Compare temperature with last notified value; push if changed.

        Called after every physics tick by :class:`~src.nodes.coap_node.CoapNode`.
        Only notifies observers when the rounded temperature differs so we avoid
        flooding the network with no-change notifications.
        """
        current = round(self.room.temperature, 1)
        if current != self._last_temp:
            self._last_temp = current
            self.updated_state()   # aiocoap sends Observe notifications to watchers

    # ------------------------------------------------------------------
    # Payload builder (shared between GET responses and Observe pushes)
    # ------------------------------------------------------------------

    def _build_payload(self) -> str:
        r = self.room
        return json.dumps({
            "node_id":     r.node_id,
            "ts":          int(time.time()),
            "temperature": round(r.temperature, 1),
            "humidity":    r.humidity,
            "occupancy":   r.occupancy,
            "light_level": r.light,
            "hvac_mode":   r.hvac_mode,
        })


# ---------------------------------------------------------------------------
# HvacActuatorResource  – PUT
# ---------------------------------------------------------------------------

class HvacActuatorResource(resource.Resource):
    """Accepts CON PUT commands from the Floor Gateway.

    Expected JSON body::

        {"hvac_mode": "ECO"}                    # change mode only
        {"hvac_mode": "ON", "target_temp": 24}  # ON resolves to HEATING/COOLING
        {"target_temp": 21.5}                   # change setpoint only
    """

    def __init__(self, room: "Room") -> None:
        super().__init__()
        self.room = room

    async def render_put(self, request: Message) -> Message:
        try:
            data = json.loads(request.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning(
                "CoAP PUT bad payload on %s: %r", self.room.node_id, request.payload
            )
            return Message(code=Code.BAD_REQUEST)

        # HVAC mode
        if "hvac_mode" in data:
            mode = data["hvac_mode"]
            valid_modes = {"ON", "OFF", "ECO", "COOLING", "HEATING"}
            if mode in valid_modes:
                if mode == "ON":
                    mode = "HEATING" if self.room.temperature < self.room.target_temp else "COOLING"
                self.room.hvac_mode = mode
                logger.info("CoAP PUT %s → hvac_mode=%s", self.room.node_id, mode)

        # Target temperature
        if "target_temp" in data:
            try:
                t = float(data["target_temp"])
                if 15.0 <= t <= 50.0:
                    self.room.target_temp = t
                    logger.info("CoAP PUT %s → target_temp=%.1f", self.room.node_id, t)
            except (ValueError, TypeError):
                pass

        return Message(code=Code.CHANGED)


# ---------------------------------------------------------------------------
# Server factory
# ---------------------------------------------------------------------------

async def run_coap_server(
    room: "Room",
    telemetry_resource: TelemetryResource,
) -> aiocoap.Context:
    """Create an aiocoap server context for *room* and return it.

    Resource tree::

        /<f{FF}>/
            <r{RRR}>/
                telemetry          ← TelemetryResource (Observable GET)
                actuators/
                    hvac           ← HvacActuatorResource (PUT)

    Parameters
    ----------
    room :
        Room object; must have ``floor_id``, ``room_id``, ``coap_port``,
        ``node_id`` already set.
    telemetry_resource :
        Pre-built :class:`TelemetryResource` instance (shared with
        :class:`~src.nodes.coap_node.CoapNode` so ``notify_watchers`` can be
        called from outside).
    """
    floor_seg = f"f{room.floor_id:02d}"
    room_seg  = f"r{room.floor_id * 100 + room.room_id:03d}"
    uri_prefix = (floor_seg, room_seg)

    root = resource.Site()
    root.add_resource(uri_prefix + ("telemetry",),         telemetry_resource)
    root.add_resource(uri_prefix + ("actuators", "hvac"),  HvacActuatorResource(room))

    context = await aiocoap.Context.create_server_context(
        root,
        bind=("0.0.0.0", room.coap_port),
    )
    logger.info(
        "CoAP server %s  UDP port=%d  paths=%s/*/telemetry|actuators/hvac",
        room.node_id, room.coap_port, "/".join(uri_prefix),
    )
    return context

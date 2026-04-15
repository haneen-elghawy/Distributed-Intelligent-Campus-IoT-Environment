"""
src/nodes/mqtt_node.py
One gmqtt Client per MQTT room, each with its own ClientID and LWT.

MQTT rooms: rooms 1-10 on every floor.
Each node connects to HiveMQ over TLS (port 8883) and publishes telemetry
on the topic:

    campus/<floor>/<room>/telemetry

Last-Will-and-Testament (LWT) is published to:

    campus/<floor>/<room>/status

with payload ``{"online": false}`` whenever the broker detects a disconnect.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import ssl
from typing import Optional

from gmqtt import Client as MQTTClient
from gmqtt.mqtt.constants import MQTTv50

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------
BROKER: str = os.getenv("HIVEMQ_BROKER", "localhost")
PORT: int = int(os.getenv("HIVEMQ_PORT", "8883"))
COMMAND_QOS: int = int(os.getenv("COMMAND_QOS", "2"))
ALERT_CON: bool = os.getenv("ALERT_CON", "true").lower() == "true"


def _build_ssl_context() -> ssl.SSLContext:
    """Return an SSL context for TLS connections to HiveMQ.

    Override certificate paths via environment variables if needed:
        MQTT_CA_CERT  – path to CA certificate (optional, uses system store)
    """
    ctx = ssl.create_default_context()
    ca_cert = os.getenv("MQTT_CA_CERT")
    if ca_cert:
        ctx.load_verify_locations(cafile=ca_cert)
    return ctx


# ---------------------------------------------------------------------------
# Per-room MQTT node
# ---------------------------------------------------------------------------

class MQTTRoomNode:
    """Manages a single gmqtt client dedicated to one physical room.

    Parameters
    ----------
    floor:
        1-based floor index (1-10).
    room:
        Room number within the floor (1-10 for MQTT rooms).
    tls:
        If ``True`` (default) connect on port 8883 with TLS; ``False`` uses
        plain port 1883.
    """

    def __init__(self, floor: int, room: int, *, tls: bool = True) -> None:
        self.floor = floor
        self.room = room
        self._tls = tls
        self._port = PORT if tls else int(os.getenv("HIVEMQ_PORT_PLAIN", "1883"))

        self._client_id = f"campus-f{floor:02d}-r{room:02d}"
        self._telemetry_topic = f"campus/{floor}/{room}/telemetry"
        self._status_topic = f"campus/{floor}/{room}/status"
        self._command_topic = f"campus/{floor}/{room}/command"

        self._client: MQTTClient = self._build_client()
        self._connected = asyncio.Event()

    # ------------------------------------------------------------------
    # Client construction
    # ------------------------------------------------------------------

    def _build_client(self) -> MQTTClient:
        will_payload = json.dumps({"online": False}).encode("utf-8")
        client = MQTTClient(
            client_id=self._client_id,
            will_message=MQTTClient.create_will_message(   # type: ignore[attr-defined]
                topic=self._status_topic,
                payload=will_payload,
                qos=1,
                retain=True,
            ),
        )
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        return client

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Connect to the broker (TLS or plain) and wait until ready."""
        ssl_ctx = _build_ssl_context() if self._tls else None
        await self._client.connect(
            host=BROKER,
            port=self._port,
            ssl=ssl_ctx,
            version=MQTTv50,
            keepalive=60,
        )
        await self._connected.wait()
        # Announce presence
        await self._publish_status(online=True)
        # Subscribe to command topic
        self._client.subscribe(self._command_topic, qos=COMMAND_QOS)
        logger.info(
            "MQTT node connected  client_id=%s  broker=%s:%d",
            self._client_id, BROKER, self._port,
        )

    async def disconnect(self) -> None:
        await self._publish_status(online=False)
        await self._client.disconnect()
        logger.info("MQTT node disconnected  client_id=%s", self._client_id)

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    async def publish_telemetry(self, payload: dict) -> None:
        """Publish a sensor-reading dict as JSON telemetry."""
        data = json.dumps(payload).encode("utf-8")
        qos = COMMAND_QOS if ALERT_CON and payload.get("alert") else 0
        self._client.publish(self._telemetry_topic, data, qos=qos)

    async def _publish_status(self, *, online: bool) -> None:
        data = json.dumps({"online": online}).encode("utf-8")
        self._client.publish(self._status_topic, data, qos=1, retain=True)

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _on_connect(self, client: MQTTClient, flags: int, rc: int, properties) -> None:
        if rc == 0:
            self._connected.set()
        else:
            logger.error(
                "MQTT connect failed  client_id=%s  rc=%d", self._client_id, rc
            )

    def _on_disconnect(
        self, client: MQTTClient, packet, exc: Optional[Exception] = None
    ) -> None:
        self._connected.clear()
        logger.warning(
            "MQTT disconnected  client_id=%s  exc=%s", self._client_id, exc
        )

    def _on_message(
        self, client: MQTTClient, topic: str, payload: bytes, qos: int, properties
    ) -> None:
        try:
            cmd = json.loads(payload)
        except json.JSONDecodeError:
            logger.warning(
                "Ignoring non-JSON command  topic=%s  payload=%r", topic, payload
            )
            return
        logger.info(
            "Command received  client_id=%s  topic=%s  cmd=%s",
            self._client_id, topic, cmd,
        )
        # TODO: dispatch command to room actuator logic

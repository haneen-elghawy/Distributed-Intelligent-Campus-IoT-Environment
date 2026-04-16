"""
src/nodes/mqtt_node.py
Per-room MQTT node — one dedicated gmqtt.Client per room.

Protocol assignment: rooms 1-10 on every floor → MQTT.

Each node has:
- Unique ClientID:  campus-mqtt-{room.node_id}
- LWT retained on: campus/b01/f{FF}/r{RRR}/status   (offline payload)
- Command sub:     campus/b01/f{FF}/r{RRR}/cmd       at QoS 2
- Telemetry pub:   campus/b01/f{FF}/r{RRR}/telemetry at QoS 1
- Alert pub:       campus/b01/f{FF}/r{RRR}/alert      at QoS 2
- Per-floor credentials from env (MQTT_USER_FLOOR01 / MQTT_PASS_FLOOR01)
- DUP-flag deduplication (MD5 hash of topic+payload, 60-second TTL)

TLS: set ``MQTT_USE_TLS=true`` and provide ``hivemq/certs/ca.crt`` (see Step 9).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import ssl
import time
from pathlib import Path
from typing import TYPE_CHECKING

from gmqtt import Client

from ..utils.topics import (
    alert_topic,
    cmd_topic,
    status_topic,
    telemetry_topic,
)

if TYPE_CHECKING:
    from src.models.room import Room

logger = logging.getLogger("nodes.mqtt_node")

# ---------------------------------------------------------------------------
# Module-level config (overridable via .env)
# ---------------------------------------------------------------------------
BROKER: str = os.getenv("HIVEMQ_BROKER", "hivemq")
INTERVAL: float = float(os.getenv("PUBLISH_INTERVAL", "5"))

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_CA = _REPO_ROOT / "hivemq" / "certs" / "ca.crt"


# ---------------------------------------------------------------------------
# Topic helpers
# ---------------------------------------------------------------------------

def _topic_base(room: "Room") -> str:
    """Canonical topic prefix for a room.

    Pattern: campus/b01/f{FF}/r{RRR}
    where FF = zero-padded floor, RRR = floor*100 + room_id
    """
    return f"campus/b01/f{room.floor_id:02d}/r{room.floor_id * 100 + room.room_id:03d}"


def _lwt_payload(room: "Room") -> bytes:
    return json.dumps({
        "node_id": room.node_id,
        "status": "offline",
        "ts": int(time.time()),
    }).encode()


# ---------------------------------------------------------------------------
# MqttNode
# ---------------------------------------------------------------------------

class MqttNode:
    """One gmqtt.Client instance bound to a single Room.

    Parameters
    ----------
    room :
        The :class:`~src.models.room.Room` object this node represents.
        ``room.node_id`` must already be set by fleet.py.
    """

    def __init__(self, room: "Room") -> None:
        self.room = room
        self.client: Client | None = None
        # DUP deduplication: {md5_hex: unix_timestamp}
        self._seen_msg_ids: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Build the client, connect, subscribe, announce online."""
        client_id = f"campus-mqtt-{self.room.node_id}"
        will_topic = status_topic(
            self.room.building_id, self.room.floor_id, self.room.room_id
        )

        self.client = Client(
            client_id,
            will_message=Client.Will(
                topic=will_topic,
                message=_lwt_payload(self.room),
                qos=1,
                retain=True,
            ),
        )

        # Per-floor credentials  ─  env: MQTT_USER_FLOOR01 / MQTT_PASS_FLOOR01
        floor_label = f"floor{self.room.floor_id:02d}"
        env_user = f"MQTT_USER_{floor_label.upper()}"
        env_pass = f"MQTT_PASS_{floor_label.upper()}"
        self.client.set_auth_credentials(
            username=os.getenv(env_user, floor_label),
            password=os.getenv(env_pass, f"{floor_label}pass"),
        )

        self.client.on_message = self._on_message

        await self.client.connect(BROKER, PORT, keepalive=30)

        # Subscribe to command topic at QoS 2 (Exactly Once)
        _cmd = cmd_topic(self.room.building_id, self.room.floor_id, self.room.room_id)
        self.client.subscribe(_cmd, qos=2)

        # Announce online presence (retained so late subscribers see it)
        _status = status_topic(self.room.building_id, self.room.floor_id, self.room.room_id)
        self.client.publish(
            _status,
            json.dumps({
                "node_id": self.room.node_id,
                "status": "online",
                "ts": int(time.time()),
            }),
            qos=1,
            retain=True,
        )

        logger.info(
            "MQTT node %s connected → broker=%s:%d tls=%s  cmd=%s",
            self.room.node_id, BROKER, port, use_tls, _cmd,
        )

    async def disconnect(self) -> None:
        """Gracefully disconnect (broker will NOT fire LWT on clean disconnect)."""
        if self.client:
            await self.client.disconnect()
            logger.info("MQTT node %s disconnected", self.room.node_id)

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    async def publish_telemetry(self) -> None:
        """Publish full sensor snapshot at QoS 1."""
        if not self.client:
            return
        payload = json.dumps({
            "node_id": self.room.node_id,
            "ts": int(time.time()),
            "temperature": round(self.room.temperature, 1),
            "humidity": self.room.humidity,
            "occupancy": self.room.occupancy,
            "light_level": self.room.light,
            "lighting_dimmer": self.room.lighting_dimmer,
            "hvac_mode": self.room.hvac_mode,
        })
        self.client.publish(
            telemetry_topic(self.room.building_id, self.room.floor_id, self.room.room_id),
            payload,
            qos=1,
        )

    async def publish_alert(self, alert_type: str, value: object) -> None:
        """Publish a critical alert at QoS 2 (Exactly Once)."""
        if not self.client:
            return
        payload = json.dumps({
            "node_id": self.room.node_id,
            "alert": alert_type,
            "value": value,
            "ts": int(time.time()),
        })
        self.client.publish(
            alert_topic(self.room.building_id, self.room.floor_id, self.room.room_id),
            payload,
            qos=2,
        )
        logger.warning(
            "ALERT QoS2  %s: %s=%s", self.room.node_id, alert_type, value
        )

    # ------------------------------------------------------------------
    # Command handling
    # ------------------------------------------------------------------

    def _on_message(
        self,
        client: Client,
        topic: str,
        payload: bytes,
        qos: int,
        properties,
    ) -> int:
        """Inbound command handler.

        Applies hvac_mode / target_temp / lighting_dimmer from JSON payload.
        Identical replays (same topic + raw payload) are dropped within a 60-second
        window using an MD5 fingerprint — covers MQTT QoS 2 redeliveries (DUP=1)
        and rapid duplicate publishes.
        """
        msg_key = hashlib.md5(
            topic.encode() + (payload if isinstance(payload, bytes) else payload.encode())
        ).hexdigest()
        if self._is_duplicate(msg_key):
            return 0

        # --- Decode ---
        if isinstance(payload, bytes):
            payload = payload.decode()
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            logger.warning(
                "Non-JSON command on %s — ignored  payload=%r",
                topic, payload,
            )
            return 0

        room = self.room

        # HVAC mode
        if "hvac_mode" in data:
            mode = data["hvac_mode"]
            valid_modes = {"ON", "OFF", "ECO", "COOLING", "HEATING"}
            if mode in valid_modes:
                if mode == "ON":
                    # "ON" resolves to the appropriate active mode
                    mode = "HEATING" if room.temperature < room.target_temp else "COOLING"
                room.hvac_mode = mode
                logger.info("CMD %s → hvac_mode=%s", room.node_id, mode)

        # Target temperature
        if "target_temp" in data:
            try:
                t = float(data["target_temp"])
                if 15.0 <= t <= 50.0:
                    room.target_temp = t
                    logger.info("CMD %s → target_temp=%.1f", room.node_id, t)
            except (ValueError, TypeError):
                pass

        # Lighting dimmer
        if "lighting_dimmer" in data:
            try:
                d = int(data["lighting_dimmer"])
                if 0 <= d <= 100:
                    room.lighting_dimmer = d
                    logger.info("CMD %s → lighting_dimmer=%d", room.node_id, d)
            except (ValueError, TypeError):
                pass

        return 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_duplicate(self, msg_key: str) -> bool:
        """Return True and log a warning if *msg_key* was seen within 60 s.

        On first sight of *msg_key*, record timestamp and return False so the
        handler still processes the message.
        """
        now = time.time()
        # Purge expired entries (60-second sliding window)
        self._seen_msg_ids = {
            k: ts for k, ts in self._seen_msg_ids.items() if now - ts < 60
        }
        if msg_key in self._seen_msg_ids:
            logger.warning("DUP detected key=%s — dropping", msg_key)
            return True
        self._seen_msg_ids[msg_key] = now
        return False

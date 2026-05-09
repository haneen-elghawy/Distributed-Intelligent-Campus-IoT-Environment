"""Phase 3.2 — OTA subscription and message handler.

Plug this into the existing MQTT node logic by calling:
    subscribe_ota(gmqtt_client, room)   — from your on_connect callback
    handle_ota_message(...)             — from your on_message callback when topic contains "/ota"

Report topic convention:
    campus/b01/fNN/rRRR/ota/report
"""

import json
import logging
import time

from . import ota as ota_engine

logger = logging.getLogger("engine.ota_handler")


def _room_number(room) -> int:
    n = getattr(room, "room_number", None)
    if isinstance(n, int):
        return n
    try:
        return int(n)
    except Exception:
        return int(room.floor_id) * 100 + int(room.room_id)


def subscribe_ota(gmqtt_client, room):
    """Subscribe this room's MQTT client to its 3 OTA scopes.

    Call this inside your on_connect callback.

    Scopes subscribed:
      campus/b01/ota/config          — broadcast to all rooms
      campus/b01/fNN/ota             — floor-level update
      campus/b01/fNN/rRRR/ota        — single room update
    """
    building = room.building_id
    floor_str = f"f{room.floor_id:02d}"
    room_str = f"r{_room_number(room):03d}"   # use room_number (e.g. 101, 215)

    gmqtt_client.subscribe(f"campus/{building}/ota/config", qos=1)
    gmqtt_client.subscribe(f"campus/{building}/{floor_str}/ota", qos=1)
    gmqtt_client.subscribe(f"campus/{building}/{floor_str}/{room_str}/ota", qos=1)

    logger.debug(
        "OTA subscriptions registered for %s (building=%s floor=%s room=%s)",
        room.room_key, building, floor_str, room_str,
    )


def handle_ota_message(gmqtt_client, topic, raw_payload, room):
    """Process an incoming OTA MQTT message and publish a report.

    Call this from your on_message callback when the topic ends with '/ota'
    or contains '/ota/'.

    The report is published to: campus/<building>/<floor>/<room>/ota/report
    with JSON:
    {
        "sensor_id": room.room_key,
        "topic": topic,
        "rejected": true/false,
        "reason": "...",
        "version": "1.1",
        "applied": {"alpha": 0.02, ...},
        "timestamp": 1234567890
    }

    Args:
        gmqtt_client: the connected gmqtt.Client instance for this room
        topic: the MQTT topic string (str or bytes)
        raw_payload: the raw MQTT payload (bytes or str)
        room: the Room model instance
    """
    if isinstance(topic, bytes):
        topic = topic.decode("utf-8")

    # Guard: only process if this topic actually targets this room
    if not ota_engine.topic_targets_room(topic, room):
        logger.debug("OTA topic %s does not target %s — skipping", topic, room.room_key)
        return

    # Parse payload
    try:
        if isinstance(raw_payload, bytes):
            raw_payload = raw_payload.decode("utf-8")
        data = json.loads(raw_payload)
    except Exception as exc:
        logger.warning("OTA malformed payload on topic %s for %s: %s", topic, room.room_key, exc)
        _publish_report(
            gmqtt_client,
            room,
            topic,
            rejected=True,
            reason=f"JSON parse error: {exc}",
            version="?",
            applied={},
        )
        return

    # Apply the OTA update (verify hash + apply params)
    result = ota_engine.apply_to_room(room, data, topic=topic)

    # Publish report back so p3_tamper_alert.py and the bridge can react
    _publish_report(
        gmqtt_client=gmqtt_client,
        room=room,
        topic=topic,
        rejected=result.get("rejected", False),
        reason=result.get("reason", ""),
        version=result.get("version") or getattr(room, "config_version", "?"),
        applied=result.get("applied", {}),
    )


def _publish_report(gmqtt_client, room, topic, rejected, reason, version, applied):
    """Publish an OTA result report on the room's report topic."""
    building = room.building_id
    floor_str = f"f{room.floor_id:02d}"
    room_str = f"r{_room_number(room):03d}"
    report_topic = f"campus/{building}/{floor_str}/{room_str}/ota/report"

    report = {
        "sensor_id": room.room_key,
        "topic": topic,
        "rejected": rejected,
        "reason": reason,
        "version": version,
        "applied": applied,
        "timestamp": int(time.time()),
    }

    try:
        gmqtt_client.publish(report_topic, json.dumps(report), qos=1)
        logger.info(
            "OTA report published → %s | rejected=%s version=%s",
            report_topic, rejected, version,
        )
    except Exception as exc:
        logger.warning("Failed to publish OTA report for %s: %s", room.room_key, exc)


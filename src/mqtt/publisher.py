import asyncio
import json
import logging
import os
import time
import uuid

from gmqtt import Client

logger = logging.getLogger("mqtt.publisher")

_mqtt_client = None
_mqtt_lock = asyncio.Lock()
_room_registry = {}
_command_callbacks = []


def _building_suffix(building_id):
    return building_id.replace("b", "")


def _room_number(floor_id, room_id):
    return floor_id * 100 + room_id


def _telemetry_topic(room):
    return (
        f"campus/bldg_{_building_suffix(room.building_id)}/"
        f"floor_{room.floor_id:02d}/room_{_room_number(room.floor_id, room.room_id):03d}/telemetry"
    )


def _heartbeat_topic(room):
    return (
        f"campus/bldg_{_building_suffix(room.building_id)}/"
        f"floor_{room.floor_id:02d}/room_{_room_number(room.floor_id, room.room_id):03d}/heartbeat"
    )


def _telemetry_payload(room):
    return {
        "sensor_id": f"{room.building_id}-f{room.floor_id:02d}-r{_room_number(room.floor_id, room.room_id):03d}",
        "timestamp": int(time.time()),
        "temperature": round(room.temperature, 1),
        "humidity": room.humidity,
        "occupancy": room.occupancy,
        "light_level": room.light,
        "lighting_dimmer": room.lighting_dimmer,
        "hvac_mode": room.hvac_mode,
    }


def _on_message(client, topic, payload, qos, properties):
    """Handle incoming MQTT command messages."""
    # gmqtt may pass topic as str or bytes
    if isinstance(topic, bytes):
        topic = topic.decode()
    if isinstance(payload, bytes):
        payload = payload.decode()

    logger.debug("MQTT message on %s: %s", topic, payload)

    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Received malformed command on %s", topic)
        return 0

    # Extract room key from topic: campus/bldg_XX/floor_XX/room_XXX/command
    parts = topic.split("/")
    if len(parts) < 5 or parts[-1] != "command":
        return 0

    # Build room_key from topic parts
    bldg = parts[1].replace("bldg_", "b")
    floor_str = parts[2].replace("floor_", "")
    room_str = parts[3].replace("room_", "")
    room_key = f"{bldg}-f{floor_str}-r{room_str}"

    room = _room_registry.get(room_key)
    if room is None:
        logger.warning("Command for unknown room: %s", room_key)
        return 0

    # Validate and apply command fields
    if "hvac_mode" in data:
        mode = data["hvac_mode"]
        if mode in ("ON", "OFF", "ECO", "COOLING", "HEATING"):
            if mode == "ON":
                mode = "HEATING" if room.temperature < room.target_temp else "COOLING"
            room.hvac_mode = mode
            logger.info("Command: %s hvac_mode -> %s", room_key, mode)
        else:
            logger.warning("Invalid hvac_mode '%s' for %s", mode, room_key)

    if "target_temp" in data:
        try:
            target = float(data["target_temp"])
            if 15.0 <= target <= 50.0:
                room.target_temp = target
                logger.info("Command: %s target_temp -> %.1f", room_key, target)
            else:
                logger.warning("target_temp %.1f out of range for %s", target, room_key)
        except (ValueError, TypeError):
            logger.warning("Invalid target_temp for %s", room_key)

    if "lighting_dimmer" in data:
        try:
            dimmer = int(data["lighting_dimmer"])
            if 0 <= dimmer <= 100:
                room.lighting_dimmer = dimmer
                logger.info("Command: %s lighting_dimmer -> %d", room_key, dimmer)
            else:
                logger.warning("lighting_dimmer %d out of range for %s", dimmer, room_key)
        except (ValueError, TypeError):
            logger.warning("Invalid lighting_dimmer for %s", room_key)

    return 0


def register_rooms(rooms):
    """Register room objects so commands can look them up by key."""
    for room in rooms:
        _room_registry[room.room_key] = room


async def connect_mqtt():
    global _mqtt_client
    async with _mqtt_lock:
        if _mqtt_client is not None:
            return _mqtt_client

        broker_host = os.getenv("MQTT_BROKER", "localhost")
        broker_port = int(os.getenv("MQTT_PORT", "1883"))
        client_id = os.getenv("MQTT_CLIENT_ID", f"campus-engine-{uuid.uuid4().hex[:8]}")
        username = os.getenv("MQTT_USERNAME")
        password = os.getenv("MQTT_PASSWORD")

        client = Client(client_id)
        if username:
            client.set_auth_credentials(username, password)

        client.on_message = _on_message

        logger.info("Connecting to MQTT broker %s:%d", broker_host, broker_port)
        await client.connect(broker_host, broker_port)
        _mqtt_client = client
        logger.info("MQTT connected as %s", client_id)

        # Subscribe to command topics for all rooms
        command_topic = "campus/+/+/+/command"
        client.subscribe(command_topic, qos=1)
        logger.info("Subscribed to %s", command_topic)

        return _mqtt_client


async def disconnect_mqtt():
    global _mqtt_client
    async with _mqtt_lock:
        if _mqtt_client is None:
            return

        client = _mqtt_client
        _mqtt_client = None
        logger.warning("MQTT disconnecting")
        await client.disconnect()


async def publish_telemetry(room):
    client = await connect_mqtt()
    topic = _telemetry_topic(room)
    payload = _telemetry_payload(room)
    client.publish(topic, json.dumps(payload), qos=1)


async def publish_heartbeat(room):
    client = await connect_mqtt()
    topic = _heartbeat_topic(room)
    payload = {
        "sensor_id": f"{room.building_id}-f{room.floor_id:02d}-r{_room_number(room.floor_id, room.room_id):03d}",
        "timestamp": int(time.time()),
        "status": "alive",
    }
    client.publish(topic, json.dumps(payload), qos=0)

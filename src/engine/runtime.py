"""
src/engine/runtime.py
Phase 2 unified async runtime — 100 MQTT nodes + 100 CoAP nodes.

Each node runs in its own asyncio coroutine, gathered concurrently by main().
Physics ticks, fault simulation, SQLite persistence and telemetry publishing
all happen inside the per-node coroutines.

Environment variables (all have defaults)
-----------------------------------------
PUBLISH_INTERVAL            seconds between ticks         (default 5)
STARTUP_JITTER              max random startup delay (s)  (default = PUBLISH_INTERVAL)
SQLITE_SAVE_INTERVAL_SECONDS persist cadence per room      (default 30)
TIME_ACCELERATION           virtual-clock speed multiplier (default 1)
OUTSIDE_TEMP / _AMPLITUDE   day/night outside temperature
OUTSIDE_HUMIDITY / _AMPLITUDE
TEMP_ALERT_HIGH             upper alert threshold °C       (default 35.0)
TEMP_ALERT_LOW              lower alert threshold °C       (default 15.5)
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import math
import os
import random
import time

from dotenv import load_dotenv

load_dotenv()

from ..utils.logging_config import setup_logging
from .fleet import mqtt_rooms, coap_rooms, rooms
from ..nodes.mqtt_node import MqttNode
from ..nodes.coap_node import CoapNode
from ..persistence import (
    init_db,
    initialize_defaults,
    is_db_empty,
    load_previous_state,
    persist_room_state,
)

logger = logging.getLogger("engine.runtime")

# ---------------------------------------------------------------------------
# Alert thresholds
# ---------------------------------------------------------------------------
TEMP_ALERT_HIGH: float = float(os.getenv("TEMP_ALERT_HIGH", "35.0"))
TEMP_ALERT_LOW:  float = float(os.getenv("TEMP_ALERT_LOW",  "15.5"))

# CoAP CON alerts → floor gateway ``POST /alerts`` (Step 13b). Disable if no gateway listener.
COAP_ALERTS_ENABLED: bool = os.getenv("COAP_ALERTS_ENABLED", "false").lower() in ("1", "true", "yes")
COAP_ALERT_GATEWAY_PORT: int = int(os.getenv("COAP_ALERT_GATEWAY_PORT", "5686"))
COAP_ALERT_COOLDOWN_S: float = float(os.getenv("COAP_ALERT_COOLDOWN_S", "120"))

# ---------------------------------------------------------------------------
# Virtual-clock state (module-level; shared across all coroutines)
# ---------------------------------------------------------------------------
_sim_start_real:    float | None            = None
_sim_start_virtual: datetime.datetime | None = None


# ---------------------------------------------------------------------------
# Time & environment helpers  (same physics as Phase 1)
# ---------------------------------------------------------------------------

def get_virtual_time() -> datetime.datetime:
    """Return a virtual datetime that respects the TIME_ACCELERATION factor."""
    accel = float(os.getenv("TIME_ACCELERATION", "1"))
    global _sim_start_real, _sim_start_virtual
    if _sim_start_real is None:
        _sim_start_real    = time.time()
        _sim_start_virtual = datetime.datetime.now()
    elapsed_virtual = (time.time() - _sim_start_real) * accel
    return _sim_start_virtual + datetime.timedelta(seconds=elapsed_virtual)


def get_outside_temperature(hour: float) -> float:
    """Day/night temperature cycle — peaks ~14:00, troughs ~02:00."""
    base = float(os.getenv("OUTSIDE_TEMP", "30"))
    amp  = float(os.getenv("OUTSIDE_TEMP_AMPLITUDE", "5"))
    return base + amp * math.sin(math.pi * (hour - 8) / 12)


def get_outside_humidity(hour: float) -> float:
    """Inverse day/night humidity cycle — high at night, low midday."""
    base = float(os.getenv("OUTSIDE_HUMIDITY", "60"))
    amp  = float(os.getenv("OUTSIDE_HUMIDITY_AMPLITUDE", "10"))
    return base - amp * math.sin(math.pi * (hour - 8) / 12)


def _tick_physics(room, delta_t: float) -> float:
    """Advance one physics step for *room* and return the current timestamp."""
    vt   = get_virtual_time()
    hour = vt.hour + vt.minute / 60.0
    room.update_occupancy(hour)
    room.update_hvac()
    room.update_temperature(get_outside_temperature(hour), delta_t=delta_t)
    room.update_light(hour)
    room.update_humidity(get_outside_humidity(hour))
    now = time.time()
    room.apply_sensor_faults(now=now)
    room.validate_state()
    room.last_update = now
    return now


# ---------------------------------------------------------------------------
# Per-node coroutines
# ---------------------------------------------------------------------------

async def run_mqtt_node(node: MqttNode) -> None:
    """Coroutine that owns one MQTT room for the simulation lifetime.

    Sequence per tick
    -----------------
    1. Advance physics (temperature, humidity, occupancy, …)
    2. Persist to SQLite every SQLITE_SAVE_INTERVAL_SECONDS
    3. Skip publish if fault simulation says "dropout"
    4. Inject telemetry delay if fault simulation says so
    5. Publish telemetry at QoS 1
    6. Publish high/low temperature alerts at QoS 2
    """
    interval         = float(os.getenv("PUBLISH_INTERVAL", "5"))
    persist_interval = int(os.getenv("SQLITE_SAVE_INTERVAL_SECONDS", "30"))
    max_jitter       = float(os.getenv("STARTUP_JITTER", str(interval)))
    last_persist     = 0.0

    # Startup jitter — stagger 100 connects to avoid thundering herd
    await asyncio.sleep(random.uniform(0, max_jitter))
    await node.start()

    while True:
        tick_start = time.time()
        now        = _tick_physics(node.room, delta_t=interval)

        # SQLite persistence (off the event loop thread)
        if now - last_persist >= persist_interval:
            await asyncio.to_thread(persist_room_state, node.room)
            last_persist = now

        # Telemetry publish (subject to fault simulation)
        faults = node.room.get_telemetry_faults(now=now)
        if not faults["dropout"]:
            if faults["delay_seconds"] > 0:
                await asyncio.sleep(faults["delay_seconds"])

            await node.publish_telemetry()
            await node.publish_heartbeat()

            # Temperature threshold alerts — QoS 2 (Exactly Once)
            temp = node.room.temperature
            if temp >= TEMP_ALERT_HIGH:
                await node.publish_alert("HIGH_TEMP", round(temp, 1))
            elif temp <= TEMP_ALERT_LOW:
                await node.publish_alert("LOW_TEMP", round(temp, 1))

        elapsed = time.time() - tick_start
        await asyncio.sleep(max(0.0, interval - elapsed))


async def run_coap_node(node: CoapNode) -> None:
    """Coroutine that owns one CoAP room for the simulation lifetime.

    Sequence per tick
    -----------------
    1. Advance physics
    2. Persist to SQLite every SQLITE_SAVE_INTERVAL_SECONDS
    3. Call node.notify() → triggers RFC 7641 Observe push if temp changed
    """
    interval         = float(os.getenv("PUBLISH_INTERVAL", "5"))
    persist_interval = int(os.getenv("SQLITE_SAVE_INTERVAL_SECONDS", "30"))
    max_jitter       = float(os.getenv("STARTUP_JITTER", str(interval)))
    last_persist     = 0.0

    # Startup jitter
    await asyncio.sleep(random.uniform(0, max_jitter))
    await node.start()

    while True:
        tick_start = time.time()
        now        = _tick_physics(node.room, delta_t=interval)

        # SQLite persistence
        if now - last_persist >= persist_interval:
            await asyncio.to_thread(persist_room_state, node.room)
            last_persist = now

        # Notify CoAP observers (no-op if temperature unchanged)
        await node.notify()

        if COAP_ALERTS_ENABLED:
            gw_host = os.getenv(
                "COAP_ALERT_GATEWAY_HOST_TEMPLATE",
                "gateway-f{floor:02d}",
            ).format(floor=node.room.floor_id)
            await node.maybe_send_temperature_alert(
                temp_high=TEMP_ALERT_HIGH,
                cooldown_s=COAP_ALERT_COOLDOWN_S,
                gateway_host=gw_host,
                gateway_port=COAP_ALERT_GATEWAY_PORT,
            )

        elapsed = time.time() - tick_start
        await asyncio.sleep(max(0.0, interval - elapsed))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    """Initialise infrastructure then gather all 200 node coroutines."""
    setup_logging()

    logger.info("Phase 2 runtime — initializing DB …")
    await asyncio.to_thread(init_db)

    if await asyncio.to_thread(is_db_empty):
        await asyncio.to_thread(initialize_defaults, rooms)
        logger.info("DB initialised with defaults for %d rooms", len(rooms))
    else:
        await asyncio.to_thread(load_previous_state, rooms)
        logger.info("DB: loaded previous state for %d rooms", len(rooms))

    # Build node objects (no I/O yet; start() happens inside coroutines)
    mqtt_nodes = [MqttNode(r) for r in mqtt_rooms]
    coap_disabled = os.getenv("COAP_ALERTS_ENABLED", "true").lower() == "false"
    if coap_disabled:
        coap_nodes = []
        logger.info("COAP_ALERTS_ENABLED=false -> skipping CoAP node startup")
    else:
        coap_nodes = [CoapNode(r) for r in coap_rooms]

    logger.info(
        "Launching %d MQTT nodes + %d CoAP nodes concurrently",
        len(mqtt_nodes), len(coap_nodes),
    )

    tasks: list[asyncio.coroutine] = [run_mqtt_node(n) for n in mqtt_nodes]
    if coap_nodes:
        tasks += [run_coap_node(n) for n in coap_nodes]

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logger.info("Runtime cancelled — shutting down")
    finally:
        logger.info("Phase 2 runtime stopped.")

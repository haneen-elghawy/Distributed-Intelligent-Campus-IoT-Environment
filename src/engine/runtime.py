import asyncio
import datetime
import logging
import math
import os
import random
import time

from ..utils.logging_config import setup_logging
from .fleet import rooms
from ..mqtt import connect_mqtt, disconnect_mqtt, publish_heartbeat, publish_telemetry, register_rooms
from ..persistence import (
    init_db,
    initialize_defaults,
    is_db_empty,
    load_previous_state,
    persist_room_state,
)

logger = logging.getLogger("engine.runtime")

# Simulation start time (for time acceleration)
_sim_start_real = None
_sim_start_virtual = None


def get_virtual_time():
    """Return a virtual datetime that respects the time acceleration factor."""
    time_accel = float(os.getenv("TIME_ACCELERATION", "1"))
    global _sim_start_real, _sim_start_virtual
    if _sim_start_real is None:
        _sim_start_real = time.time()
        _sim_start_virtual = datetime.datetime.now()
    elapsed_real = time.time() - _sim_start_real
    elapsed_virtual = elapsed_real * time_accel
    return _sim_start_virtual + datetime.timedelta(seconds=elapsed_virtual)


def get_outside_temperature(hour):
    """Simulate outside temperature with a day/night cycle using a sine curve.
    Peaks around 14:00, lowest around 04:00."""
    base_temp = float(os.getenv("OUTSIDE_TEMP", "30"))
    amplitude = float(os.getenv("OUTSIDE_TEMP_AMPLITUDE", "5"))
    # Sine curve: peak at hour 14, trough at hour 2
    return base_temp + amplitude * math.sin(math.pi * (hour - 8) / 12)


def get_outside_humidity(hour):
    """Simulate outside humidity with inverse day/night cycle.
    Higher at night, lower during hot daytime."""
    base_humidity = float(os.getenv("OUTSIDE_HUMIDITY", "60"))
    amplitude = float(os.getenv("OUTSIDE_HUMIDITY_AMPLITUDE", "10"))
    # Inverse of temperature: high at night, low at midday
    return base_humidity - amplitude * math.sin(math.pi * (hour - 8) / 12)


async def run_room(room):
    publish_interval = float(os.getenv("PUBLISH_INTERVAL", "5"))
    persist_interval_seconds = int(os.getenv("SQLITE_SAVE_INTERVAL_SECONDS", "30"))
    max_jitter = float(os.getenv("STARTUP_JITTER", str(publish_interval)))
    last_persist_time = 0

    # Startup jitter: prevent thundering herd
    await asyncio.sleep(random.uniform(0, max_jitter))

    while True:
        start = time.time()

        virtual_now = get_virtual_time()
        current_hour = virtual_now.hour + virtual_now.minute / 60.0
        outside_temp = get_outside_temperature(current_hour)
        outside_humidity = get_outside_humidity(current_hour)

        room.update_occupancy(current_hour)
        room.update_hvac()
        room.update_temperature(outside_temp)
        room.update_light(current_hour)
        room.update_humidity(outside_humidity)
        now = time.time()
        room.apply_sensor_faults(now=now)
        room.validate_state()
        room.last_update = now

        telemetry_faults = room.get_telemetry_faults(now=now)

        if now - last_persist_time >= persist_interval_seconds:
            await asyncio.to_thread(persist_room_state, room)
            last_persist_time = now

        if not telemetry_faults["dropout"]:
            if telemetry_faults["delay_seconds"] > 0:
                await asyncio.sleep(telemetry_faults["delay_seconds"])

            await publish_telemetry(room)
            await publish_heartbeat(room)

        processing_time = time.time() - start
        await asyncio.sleep(max(0, publish_interval - processing_time))


async def main():
    setup_logging()

    logger.info("Initializing database...")
    await asyncio.to_thread(init_db)
    db_empty = await asyncio.to_thread(is_db_empty)

    if db_empty:
        await asyncio.to_thread(initialize_defaults, rooms)
        logger.info("Initialized defaults for %d rooms", len(rooms))
    else:
        await asyncio.to_thread(load_previous_state, rooms)
        logger.info("Loaded previous state for %d rooms", len(rooms))

    register_rooms(rooms)
    await connect_mqtt()
    logger.info("MQTT connected — starting simulation with %d rooms", len(rooms))
    try:
        tasks = [run_room(room) for room in rooms]
        await asyncio.gather(*tasks)
    finally:
        logger.info("Shutting down...")
        await disconnect_mqtt()

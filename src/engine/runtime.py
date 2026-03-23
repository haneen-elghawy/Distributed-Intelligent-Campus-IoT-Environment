import asyncio
import os
import time

from .fleet import rooms
from ..mqtt import connect_mqtt, disconnect_mqtt, publish_heartbeat, publish_telemetry
from ..persistence import (
    init_db,
    initialize_defaults,
    is_db_empty,
    load_previous_state,
    persist_room_state,
)


async def run_room(room):
    persist_interval_seconds = int(os.getenv("SQLITE_SAVE_INTERVAL_SECONDS", "30"))
    last_persist_time = 0

    while True:
        start = time.time()

        room.update_temperature(outside_temp=30)
        now = time.time()
        room.apply_sensor_faults(now=now)
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
        await asyncio.sleep(max(0, 5 - processing_time))


async def main():
    await asyncio.to_thread(init_db)
    db_empty = await asyncio.to_thread(is_db_empty)

    if db_empty: 
        await asyncio.to_thread(initialize_defaults, rooms)
    else:
        await asyncio.to_thread(load_previous_state, rooms)

    await connect_mqtt()
    try:
        tasks = [run_room(room) for room in rooms]
        await asyncio.gather(*tasks)
    finally:
        await disconnect_mqtt()

import os

from ..models import Room


def create_room_fleet():
    """Build the campus room fleet, split by protocol.

    Env vars
    --------
    NUM_FLOORS        : total floors (default 10)
    NUM_MQTT_ROOMS    : rooms 1-N on each floor → MQTT (default 10)
    NUM_COAP_ROOMS    : next N rooms on each floor → CoAP (default 10)
    COAP_BASE_PORT    : first UDP port assigned to CoAP rooms (default 5683)

    Returns
    -------
    (mqtt_rooms, coap_rooms) : two lists of Room objects
        mqtt_rooms  – 100 rooms (floors 1-10, room IDs 1-10)
        coap_rooms  – 100 rooms (floors 1-10, room IDs 11-20)
    """
    num_floors = int(os.getenv("NUM_FLOORS", "10"))
    mqtt_per_floor = int(os.getenv("NUM_MQTT_ROOMS", "10"))   # rooms 1-10
    coap_per_floor = int(os.getenv("NUM_COAP_ROOMS", "10"))   # rooms 11-20
    coap_base_port = int(os.getenv("COAP_BASE_PORT", "5683"))

    mqtt_rooms: list[Room] = []
    coap_rooms: list[Room] = []
    coap_port_counter = coap_base_port

    for floor in range(1, num_floors + 1):
        # --- MQTT rooms: room IDs 1 … mqtt_per_floor ---
        for room_id in range(1, mqtt_per_floor + 1):
            r = Room("b01", floor, room_id)
            r.protocol = "mqtt"
            r.node_id = f"b01-f{floor:02d}-r{floor * 100 + room_id:03d}"
            mqtt_rooms.append(r)

        # --- CoAP rooms: room IDs (mqtt_per_floor+1) … (mqtt+coap per floor) ---
        for room_id in range(mqtt_per_floor + 1,
                             mqtt_per_floor + coap_per_floor + 1):
            r = Room("b01", floor, room_id)
            r.protocol = "coap"
            r.coap_port = coap_port_counter
            r.node_id = f"b01-f{floor:02d}-r{floor * 100 + room_id:03d}"
            coap_rooms.append(r)
            coap_port_counter += 1

    return mqtt_rooms, coap_rooms


# Module-level convenience exports
# mqtt_rooms / coap_rooms give typed access; `rooms` preserves backward
# compatibility with any existing code that iterates the full fleet.
mqtt_rooms, coap_rooms = create_room_fleet()
rooms = mqtt_rooms + coap_rooms

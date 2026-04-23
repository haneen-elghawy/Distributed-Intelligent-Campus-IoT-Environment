"""
src/utils/topics.py
Single source of truth for all MQTT topic strings and CoAP URIs.

Convention
----------
MQTT:  campus/{building_id}/f{FF}/r{RRR}/{type}
CoAP:  coap://{host}:{port}/f{FF}/r{RRR}/telemetry

where:
  FF  = zero-padded floor number          (e.g. 01)
  RRR = floor_id * 100 + room_id          (e.g. 101 for floor 1 room 1)
        floors 1-10, rooms 1-10  → 101-110, 201-210, …
        floors 1-10, rooms 11-20 → 111-120, 211-220, …
"""
from __future__ import annotations

import os


def mqtt_base(building_id: str, floor_id: int, room_id: int) -> str:
    """Return the shared topic prefix for a room.

    Example:
        mqtt_base('b01', 1, 5)  →  'campus/b01/f01/r105'
        mqtt_base('b01', 3, 14) →  'campus/b01/f03/r314'
    """
    rnum = floor_id * 100 + room_id
    return f"campus/{building_id}/f{floor_id:02d}/r{rnum:03d}"


def telemetry_topic(building_id: str, floor_id: int, room_id: int) -> str:
    """Sensor readings (QoS 1).

    Example: campus/b01/f01/r105/telemetry
    """
    return f"{mqtt_base(building_id, floor_id, room_id)}/telemetry"


def status_topic(building_id: str, floor_id: int, room_id: int) -> str:
    """Online/offline status + LWT (QoS 1, retained).

    Example: campus/b01/f01/r105/status
    """
    return f"{mqtt_base(building_id, floor_id, room_id)}/status"


def cmd_topic(building_id: str, floor_id: int, room_id: int) -> str:
    """Downstream actuation commands (QoS 2).

    Example: campus/b01/f01/r105/cmd
    """
    return f"{mqtt_base(building_id, floor_id, room_id)}/cmd"


def alert_topic(building_id: str, floor_id: int, room_id: int) -> str:
    """Critical threshold alerts (QoS 2).

    Example: campus/b01/f01/r105/alert
    """
    return f"{mqtt_base(building_id, floor_id, room_id)}/alert"


def coap_uri(host: str, port: int, floor_id: int, room_id: int) -> str:
    """Full CoAP URI for the Observable telemetry resource.

    The path mirrors the CoAP server's resource tree in coap/server.py.

    Example:
        coap_uri('sim-engine', 5683, 1, 11) →
            'coap://sim-engine:5683/f01/r111/telemetry'
    """
    rnum = floor_id * 100 + room_id
    scheme = os.getenv("COAP_SCHEME", "coap").strip().lower() or "coap"
    return f"{scheme}://{host}:{port}/f{floor_id:02d}/r{rnum:03d}/telemetry"

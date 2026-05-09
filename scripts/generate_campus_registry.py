#!/usr/bin/env python3
"""Emit deterministic ThingsBoard-oriented device + asset registry (no live API).

Outputs-------
- ``thingsboard/campus_registry_export.json`` — devices, assets, relations
- ``thingsboard/campus_devices.csv`` — flat device list for spreadsheets

Run after fleet constants change::
    python scripts/generate_campus_registry.py
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from campus_naming import canonical_room_key

ROOT = Path(__file__).resolve().parent.parent
OUT_JSON = ROOT / "thingsboard" / "campus_registry_export.json"
OUT_CSV = ROOT / "thingsboard" / "campus_devices.csv"

NUM_FLOORS = 10
MQTT_ROOMS = 10
COAP_ROOMS = 10


def main() -> None:
    devices: list[dict] = []
    for floor in range(1, NUM_FLOORS + 1):
        for room in range(1, MQTT_ROOMS + 1):
            rnum = floor * 100 + room
            nid = canonical_room_key(floor, room)
            devices.append(
                {
                    "name": nid,
                    "deviceProfile": "MQTT-ThermalSensor",
                    "protocol": "MQTT",
                    "floor": floor,
                    "room_id": room,
                    "room_number": rnum,
                }
            )
        for room in range(MQTT_ROOMS + 1, MQTT_ROOMS + COAP_ROOMS + 1):
            rnum = floor * 100 + room
            nid = canonical_room_key(floor, room)
            devices.append(
                {
                    "name": nid,
                    "deviceProfile": "CoAP-ThermalSensor",
                    "protocol": "CoAP",
                    "floor": floor,
                    "room_id": room,
                    "room_number": rnum,
                }
            )

    assets: list[dict] = [
        {"name": "Campus-B01", "type": "Campus", "parent": None},
        {"name": "Building-01", "type": "Building", "parent": "Campus-B01"},
    ]
    for floor in range(1, NUM_FLOORS + 1):
        assets.append(
            {"name": f"Floor-{floor:02d}", "type": "Floor", "parent": "Building-01"}
        )
    for d in devices:
        assets.append(
            {
                "name": d["name"],
                "type": "Room",
                "parent": f"Floor-{d['floor']:02d}",
            }
        )

    relations: list[dict] = []
    for a in assets:
        if a["parent"]:
            relations.append(
                {
                    "from": {"entityType": "ASSET", "name": a["parent"]},
                    "to": {"entityType": "ASSET", "name": a["name"]},
                    "type": "Contains",
                }
            )
    for d in devices:
        relations.append(
            {
                "from": {"entityType": "ASSET", "name": d["name"]},
                "to": {"entityType": "DEVICE", "name": d["name"]},
                "type": "Contains",
            }
        )

    payload = {
        "schema": "campus-registry-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "device_count": len(devices),
        "asset_count": len(assets),
        "devices": devices,
        "assets": assets,
        "relations": relations,
        "notes": "UUIDs are assigned by ThingsBoard on provision; use scripts/provision_tb.py to push live.",
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["name", "deviceProfile", "protocol", "floor", "room_id", "room_number"],
        )
        w.writeheader()
        for d in devices:
            w.writerow(d)

    print("Wrote", OUT_JSON)
    print("Wrote", OUT_CSV)


if __name__ == "__main__":
    main()

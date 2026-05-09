#!/usr/bin/env python3
"""Generate full 10-floor x 20-room polygon hotspots for image-map widgets."""
from __future__ import annotations

import json
from pathlib import Path

from campus_naming import canonical_room_key

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "thingsboard" / "floor_polygons.json"
FLOORS = 10
ROOMS_PER_FLOOR = 20


def room_polygon(index: int) -> list[list[int]]:
    # 5 columns x 4 rows grid layout per floor plan.
    col = index % 5
    row = index // 5
    x0 = 20 + col * 180
    y0 = 20 + row * 120
    x1 = x0 + 160
    y1 = y0 + 100
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def main() -> None:
    data: dict[str, object] = {
        "legend": {
            "temperature_range_c": [18, 30],
            "color_function_js": "function tempToColor(t){const min=18,max=30;const x=Math.max(0,Math.min(1,(t-min)/(max-min)));const r=Math.round(255*x);const b=Math.round(255*(1-x));return `rgb(${r},80,${b})`;}",
        },
        "tooltip_template": {
            "title": "${room}",
            "lines": [
                "Temp: ${temperature} C",
                "Occupancy: ${occupancy}",
                "HVAC: ${hvac_mode}",
                "Last Seen: ${last_seen}",
                "Sync: ${sync_status}",
            ],
        },
    }
    for floor in range(1, FLOORS + 1):
        hotspots = []
        for room_id in range(1, ROOMS_PER_FLOOR + 1):
            hotspots.append(
                {
                    "room": canonical_room_key(floor, room_id),
                    "polygon": room_polygon(room_id - 1),
                }
            )
        data[f"floor{floor:02d}"] = hotspots

    OUT.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()


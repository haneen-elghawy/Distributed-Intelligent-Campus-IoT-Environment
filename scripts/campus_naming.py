from __future__ import annotations

import re

CANONICAL_ROOM_RE = re.compile(r"^b01-f(\d{2})-r(\d{3})$")
LEGACY_ROOM_RE = re.compile(r"^Room-(b01-f\d{2}-r\d{3})$")


def room_number(floor: int, room_id: int) -> int:
    return floor * 100 + room_id


def canonical_room_key(floor: int, room_id: int) -> str:
    return f"b01-f{floor:02d}-r{room_number(floor, room_id):03d}"


def canonical_floor_summary_key(floor: int) -> str:
    return f"b01-f{floor:02d}-floor-summary"


def is_canonical_room_key(name: str) -> bool:
    return bool(CANONICAL_ROOM_RE.match((name or "").strip()))


def canonicalize_legacy_room_name(name: str) -> str | None:
    m = LEGACY_ROOM_RE.match((name or "").strip())
    return m.group(1) if m else None


def parse_room_key(room_key: str) -> tuple[str, str, str]:
    parts = (room_key or "").strip().split("-")
    if len(parts) != 3 or not parts[1].startswith("f") or not parts[2].startswith("r"):
        raise ValueError(f"Invalid room key: {room_key!r}; expected b01-fNN-rRRR")
    return parts[0], parts[1], parts[2]

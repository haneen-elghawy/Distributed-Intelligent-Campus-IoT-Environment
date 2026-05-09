"""Final-mile metadata verifier for ThingsBoard room/floor entities.

Checks:
1) Canonical naming conformity for room assets/devices (`b01-fNN-rRRR`)
2) Required SERVER_SCOPE metadata attributes for room assets
3) Required telemetry keys availability where applicable:
   - room devices: temperature, humidity, occupancy, hvac_mode, lighting_dimmer
   - floor-summary devices: avg_temperature, avg_humidity, occupied_rooms, total_rooms, occupancy_rate
"""
from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass

try:
    import httpx
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Missing dependency: httpx. Install project dependencies first "
        "(e.g., `pip install -r requirements.txt`)."
    ) from exc
from campus_naming import canonical_floor_summary_key, is_canonical_room_key
from dotenv import load_dotenv

load_dotenv(override=True)

TB_URL = os.getenv("TB_URL", "http://localhost:9090").rstrip("/")
TB_USERNAME = os.getenv("TB_USERNAME", "").strip()
TB_PASSWORD = os.getenv("TB_PASSWORD", "").strip()
REQ_ATTRS = {"square_footage", "occupant_capacity", "coordinates_x", "coordinates_y", "room_type"}
REQ_ROOM_TELEMETRY = {"temperature", "humidity", "occupancy", "hvac_mode", "lighting_dimmer"}
REQ_FLOOR_TELEMETRY = {"avg_temperature", "avg_humidity", "occupied_rooms", "total_rooms", "occupancy_rate"}
ROOM_LIKE = re.compile(r"^b01-f\d{2}-r\d{3}$")


def _headers(token: str) -> dict[str, str]:
    return {"X-Authorization": f"Bearer {token}", "Accept": "application/json"}


@dataclass
class VerifyResults:
    errors: list[str]
    warnings: list[str]

    def fail(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def _list_assets(client: httpx.Client, token: str) -> list[dict]:
    out: list[dict] = []
    page = 0
    while True:
        r = client.get(
            f"{TB_URL}/api/tenant/assets",
            params={"pageSize": 200, "page": page, "sortProperty": "name", "sortOrder": "ASC"},
            headers=_headers(token),
        )
        r.raise_for_status()
        data = r.json()
        out.extend(data.get("data", []))
        if not data.get("hasNext"):
            break
        page += 1
    return out


def _list_devices(client: httpx.Client, token: str) -> list[dict]:
    out: list[dict] = []
    page = 0
    while True:
        r = client.get(
            f"{TB_URL}/api/tenant/devices",
            params={"pageSize": 200, "page": page, "sortProperty": "name", "sortOrder": "ASC"},
            headers=_headers(token),
        )
        r.raise_for_status()
        data = r.json()
        out.extend(data.get("data", []))
        if not data.get("hasNext"):
            break
        page += 1
    return out


def _latest_keys(client: httpx.Client, token: str, entity_type: str, entity_id: str, keys: set[str]) -> set[str]:
    k = ",".join(sorted(keys))
    r = client.get(
        f"{TB_URL}/api/plugins/telemetry/{entity_type}/{entity_id}/values/timeseries",
        params={"keys": k, "limit": 1},
        headers=_headers(token),
    )
    r.raise_for_status()
    payload = r.json() or {}
    present = {key for key in keys if payload.get(key)}
    return present


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify TB metadata/naming/telemetry readiness")
    parser.add_argument("--max-room-devices", type=int, default=200, help="Limit room-device telemetry checks")
    args = parser.parse_args()

    if not TB_USERNAME or not TB_PASSWORD:
        raise RuntimeError("Missing TB_USERNAME/TB_PASSWORD")
    results = VerifyResults(errors=[], warnings=[])

    with httpx.Client(timeout=30) as client:
        login = client.post(f"{TB_URL}/api/auth/login", json={"username": TB_USERNAME, "password": TB_PASSWORD})
        login.raise_for_status()
        token = login.json()["token"]

        # 1) Asset naming + required attributes
        assets = _list_assets(client, token)
        room_assets = [a for a in assets if ROOM_LIKE.match(str(a.get("name", "")).strip())]
        legacy_room_assets = [a for a in assets if str(a.get("name", "")).startswith("Room-")]
        if legacy_room_assets:
            results.fail(f"Legacy room asset names still present: {len(legacy_room_assets)}")

        for asset in room_assets:
            name = str(asset.get("name", "")).strip()
            if not is_canonical_room_key(name):
                results.fail(f"Non-canonical room asset name: {name}")
                continue
            aid = asset["id"]["id"]
            a = client.get(
                f"{TB_URL}/api/plugins/telemetry/ASSET/{aid}/values/attributes/SERVER_SCOPE",
                headers=_headers(token),
            )
            a.raise_for_status()
            keys = {x.get("key") for x in (a.json() or [])}
            missing_attrs = sorted(REQ_ATTRS - keys)
            if missing_attrs:
                results.fail(f"Room asset {name} missing attrs: {missing_attrs}")

        # 2) Device naming + telemetry keys
        devices = _list_devices(client, token)
        room_devices = [d for d in devices if ROOM_LIKE.match(str(d.get("name", "")).strip())]
        floor_devices = [d for d in devices if str(d.get("name", "")).endswith("-floor-summary")]
        expected_floor = {canonical_floor_summary_key(i) for i in range(1, 11)}
        actual_floor = {str(d.get("name", "")).strip() for d in floor_devices}
        missing_floor_devices = sorted(expected_floor - actual_floor)
        if missing_floor_devices:
            results.fail(f"Missing floor-summary devices: {missing_floor_devices}")

        for d in room_devices[: max(1, args.max_room_devices)]:
            name = str(d.get("name", "")).strip()
            if not is_canonical_room_key(name):
                results.fail(f"Non-canonical room device name: {name}")
                continue
            present = _latest_keys(client, token, "DEVICE", d["id"]["id"], REQ_ROOM_TELEMETRY)
            missing = sorted(REQ_ROOM_TELEMETRY - present)
            if missing:
                results.warn(f"Room device {name} missing latest telemetry keys: {missing}")

        for d in floor_devices:
            name = str(d.get("name", "")).strip()
            present = _latest_keys(client, token, "DEVICE", d["id"]["id"], REQ_FLOOR_TELEMETRY)
            missing = sorted(REQ_FLOOR_TELEMETRY - present)
            if missing:
                results.warn(f"Floor-summary device {name} missing latest telemetry keys: {missing}")

    if results.warnings:
        print("WARNINGS:")
        for w in results.warnings[:50]:
            print(f"  - {w}")
    if results.errors:
        print("FAILED:")
        for e in results.errors[:50]:
            print(f"  - {e}")
        raise SystemExit(1)
    print("PASS: metadata/naming checks succeeded.")


if __name__ == "__main__":
    main()

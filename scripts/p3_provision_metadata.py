"""Phase 3 — Provision deterministic metadata to Room assets (SERVER_SCOPE).

Reads `thingsboard/campus_devices.csv` and, for each room_key, finds the asset
named `Room-<room_key>` and posts 5 server-scope attributes:
square_footage, occupant_capacity, coordinates_x, coordinates_y, room_type.
"""

from __future__ import annotations

import csv
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | p3_provision_metadata | %(levelname)s | %(message)s",
)
logger = logging.getLogger("p3_provision_metadata")

from dotenv import load_dotenv

load_dotenv(override=True)

TB_URL = os.getenv("TB_URL", "http://localhost:9090").rstrip("/")
TB_USERNAME = os.getenv("TB_USERNAME", "tenant@thingsboard.org")
TB_PASSWORD = os.getenv("TB_PASSWORD", "tenant")

CSV_PATH = Path("thingsboard") / "campus_devices.csv"

ROOM_TYPES = ["lecture_hall", "lab", "office", "corridor"]


class ThingsBoardError(RuntimeError):
    pass


@dataclass
class TokenCache:
    token: str | None = None
    issued_at: float = 0.0

    def valid(self) -> bool:
        # TB JWT default expiry is typically 1h; we refresh at 50 minutes.
        return bool(self.token) and (time.time() - self.issued_at) < (50 * 60)


def _raise_for_resp(resp: httpx.Response, what: str) -> None:
    if resp.status_code < 400:
        return
    detail: Any
    try:
        detail = resp.json()
    except Exception:
        detail = (resp.text or "")[:800]
    raise ThingsBoardError(f"{what} failed: HTTP {resp.status_code} — {detail}")


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "X-Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def tb_login(client: httpx.Client) -> str:
    resp = client.post(
        f"{TB_URL}/api/auth/login",
        json={"username": TB_USERNAME, "password": TB_PASSWORD},
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    _raise_for_resp(resp, "Login")
    data = resp.json()
    token = data.get("token")
    if not token:
        raise ThingsBoardError(f"Login response missing token: {data!r}")
    return token


def tb_request(
    client: httpx.Client,
    token_cache: TokenCache,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json: Any | None = None,
    what: str = "Request",
) -> httpx.Response:
    if not token_cache.valid():
        token_cache.token = tb_login(client)
        token_cache.issued_at = time.time()

    assert token_cache.token is not None
    resp = client.request(
        method,
        f"{TB_URL}{path}",
        params=params,
        json=json,
        headers=_auth_headers(token_cache.token),
    )
    if resp.status_code == 401:
        token_cache.token = tb_login(client)
        token_cache.issued_at = time.time()
        resp = client.request(
            method,
            f"{TB_URL}{path}",
            params=params,
            json=json,
            headers=_auth_headers(token_cache.token),
        )
    _raise_for_resp(resp, what)
    return resp


def find_first_asset_id(client: httpx.Client, token_cache: TokenCache, name: str) -> str | None:
    resp = tb_request(
        client,
        token_cache,
        "GET",
        "/api/tenant/assets",
        params={"pageSize": 1, "page": 0, "textSearch": name},
        what=f"Find asset {name!r}",
    )
    data = resp.json()
    items = data.get("data") or []
    if not items:
        return None
    return items[0]["id"]["id"]


def maybe_rename_campus_asset(client: httpx.Client, token_cache: TokenCache) -> None:
    resp = tb_request(
        client,
        token_cache,
        "GET",
        "/api/tenant/assets",
        params={"pageSize": 50, "page": 0, "textSearch": "Campus"},
        what="Search Campus assets",
    )
    payload = resp.json()
    assets = payload.get("data") or []
    for a in assets:
        name = a.get("name")
        if name not in ("Campus", "ZC-Main-Campus"):
            continue
        if name == "ZC-Main-Campus":
            logger.info("Campus asset already named ZC-Main-Campus (id=%s)", a["id"]["id"])
            return

        updated = dict(a)
        updated["name"] = "ZC-Main-Campus"
        tb_request(
            client,
            token_cache,
            "POST",
            "/api/asset",
            json=updated,
            what="Rename Campus asset to ZC-Main-Campus",
        )
        logger.info("Renamed Campus asset to ZC-Main-Campus (id=%s)", a["id"]["id"])
        return

    logger.info("No Campus/ZC-Main-Campus asset found to rename (skipping).")


def deterministic_metadata(*, floor: int, room_id: int) -> dict[str, Any]:
    local_idx = int(room_id)  # 1..20
    room_type = ROOM_TYPES[(local_idx - 1) % 4]
    square_footage = 30 + (((local_idx - 1) * 7) % 40)
    occupant_capacity = max(2, square_footage // 2)
    col = (local_idx - 1) % 5
    row = (local_idx - 1) // 5
    coordinates_x = 60 + col * 200 + 100
    coordinates_y = 40 + row * 140 + 70
    return {
        "square_footage": int(square_footage),
        "occupant_capacity": int(occupant_capacity),
        "coordinates_x": int(coordinates_x),
        "coordinates_y": int(coordinates_y),
        "room_type": room_type,
    }


def load_rooms_from_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"missing {path.as_posix()}")
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"name", "protocol", "floor", "room_id"}
        if not required.issubset(reader.fieldnames or []):
            raise ThingsBoardError(f"CSV missing required columns: {required} (got {reader.fieldnames})")
        return list(reader)


def main() -> None:
    rooms = load_rooms_from_csv(CSV_PATH)
    total = len(rooms)
    if total != 200:
        logger.warning("Expected 200 rooms, found %d rows in %s", total, CSV_PATH.as_posix())

    token_cache = TokenCache()
    tagged = 0

    with httpx.Client(timeout=60.0) as client:
        maybe_rename_campus_asset(client, token_cache)

        for idx, row in enumerate(rooms, start=1):
            room_key = (row.get("name") or "").strip()
            try:
                floor = int(row.get("floor") or "0")
                room_id = int(row.get("room_id") or "0")
            except ValueError:
                logger.warning("Skipping invalid CSV row %d: %r", idx, row)
                continue

            asset_name = room_key
            try:
                asset_id = find_first_asset_id(client, token_cache, asset_name)
                if not asset_id:
                    logger.warning("Asset not found: %s", asset_name)
                    continue

                body = deterministic_metadata(floor=floor, room_id=room_id)
                tb_request(
                    client,
                    token_cache,
                    "POST",
                    f"/api/plugins/telemetry/ASSET/{asset_id}/attributes/SERVER_SCOPE",
                    json=body,
                    what=f"Post metadata for {asset_name}",
                )
                tagged += 1
            except Exception as e:
                logger.warning("Failed %s: %s", asset_name, e)

            if idx % 25 == 0:
                logger.info("progress: %d/%d processed (%d tagged)", idx, total, tagged)

    print(f"done: {tagged}/{total} room assets metadata-tagged")


if __name__ == "__main__":
    main()




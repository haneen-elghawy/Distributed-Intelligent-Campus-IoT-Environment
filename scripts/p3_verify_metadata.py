"""Verify all room assets have required server attributes."""
from __future__ import annotations

import os

import httpx
from dotenv import load_dotenv

load_dotenv(override=True)

TB_URL = os.getenv("TB_URL", "http://localhost:9090").rstrip("/")
TB_USERNAME = os.getenv("TB_USERNAME", "").strip()
TB_PASSWORD = os.getenv("TB_PASSWORD", "").strip()
REQ = {"square_footage", "occupant_capacity", "coordinates_x", "coordinates_y", "room_type"}


def _headers(token: str) -> dict[str, str]:
    return {"X-Authorization": f"Bearer {token}", "Accept": "application/json"}


def main() -> None:
    if not TB_USERNAME or not TB_PASSWORD:
        raise RuntimeError("Missing TB_USERNAME/TB_PASSWORD")
    with httpx.Client(timeout=30) as client:
        login = client.post(f"{TB_URL}/api/auth/login", json={"username": TB_USERNAME, "password": TB_PASSWORD})
        login.raise_for_status()
        token = login.json()["token"]
        missing = []
        page = 0
        while True:
            r = client.get(
                f"{TB_URL}/api/tenant/assets",
                params={"pageSize": 100, "page": page, "textSearch": "b01-f"},
                headers=_headers(token),
            )
            r.raise_for_status()
            data = r.json()
            for asset in data.get("data", []):
                name = str(asset.get("name", ""))
                if not (name.startswith("b01-f") and "-r" in name):
                    continue
                aid = asset["id"]["id"]
                a = client.get(
                    f"{TB_URL}/api/plugins/telemetry/ASSET/{aid}/values/attributes/SERVER_SCOPE",
                    headers=_headers(token),
                )
                a.raise_for_status()
                keys = {x.get("key") for x in (a.json() or [])}
                if not REQ.issubset(keys):
                    missing.append(name)
            if not data.get("hasNext"):
                break
            page += 1
    if missing:
        raise RuntimeError(f"metadata missing for {len(missing)} room assets: {missing[:10]}")
    print("metadata verification passed for all discovered room assets")


if __name__ == "__main__":
    main()

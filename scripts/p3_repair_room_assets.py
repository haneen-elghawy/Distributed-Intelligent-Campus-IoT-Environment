"""Repair room asset naming drift for Phase 3 metadata compatibility.

Standard room asset name is: b01-fNN-rRRR
Legacy variant supported by this repair: Room-b01-fNN-rRRR
"""
from __future__ import annotations

import os
import re

import httpx
from dotenv import load_dotenv

load_dotenv(override=True)

TB_URL = os.getenv("TB_URL", "http://localhost:9090").rstrip("/")
TB_USERNAME = os.getenv("TB_USERNAME", "").strip()
TB_PASSWORD = os.getenv("TB_PASSWORD", "").strip()

_ROOM = re.compile(r"^b01-f\d{2}-r\d{3}$")
_ROOM_LEGACY = re.compile(r"^Room-(b01-f\d{2}-r\d{3})$")


def _headers(token: str) -> dict[str, str]:
    return {"X-Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"}


def main() -> None:
    if not TB_USERNAME or not TB_PASSWORD:
        raise RuntimeError("Missing TB_USERNAME/TB_PASSWORD")
    with httpx.Client(timeout=30) as client:
        login = client.post(
            f"{TB_URL}/api/auth/login",
            json={"username": TB_USERNAME, "password": TB_PASSWORD},
        )
        login.raise_for_status()
        token = login.json()["token"]
        page = 0
        renamed = 0
        while True:
            r = client.get(
                f"{TB_URL}/api/tenant/assets",
                params={"pageSize": 100, "page": page, "textSearch": "Room-"},
                headers=_headers(token),
            )
            r.raise_for_status()
            data = r.json()
            for item in data.get("data", []):
                name = str(item.get("name", "")).strip()
                m = _ROOM_LEGACY.match(name)
                if not m:
                    continue
                canonical = m.group(1)
                if not _ROOM.match(canonical):
                    continue
                body = dict(item)
                body["name"] = canonical
                u = client.post(f"{TB_URL}/api/asset", json=body, headers=_headers(token))
                u.raise_for_status()
                renamed += 1
            if not data.get("hasNext"):
                break
            page += 1
    print(f"repair complete: renamed {renamed} legacy room assets")


if __name__ == "__main__":
    main()

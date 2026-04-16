"""Provision 200 campus devices + Campus→Building→Floor→Room assets in ThingsBoard CE via REST.

Prerequisites (UI — Step 11a)
-----------------------------
Create two **Device profiles** named exactly ``MQTT-ThermalSensor`` and ``CoAP-ThermalSensor``
with the appropriate transports.

Authentication
--------------
Device and tenant APIs are **tenant-scoped**. By default this script uses the built-in tenant
admin (``tenant@thingsboard.org`` / ``tenant``). You can override with ``TB_USERNAME`` /
``TB_PASSWORD`` (e.g. service account). The **sysadmin** account is primarily for platform UI;
if you force sysadmin here, device calls may return403 unless your TB version allows it.

Usage::
    pip install requests
    python scripts/provision_tb.py
    python scripts/provision_tb.py --assets-only   # devices must exist
    python scripts/provision_tb.py --devices-only
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any

import requests

TB_URL = os.getenv("TB_URL", "http://localhost:9090").rstrip("/")
TB_USERNAME = os.getenv("TB_USERNAME", "tenant@thingsboard.org")
TB_PASSWORD = os.getenv("TB_PASSWORD", "tenant")
TB_VERIFY_SSL = os.getenv("TB_VERIFY_SSL", "true").lower() in ("1", "true", "yes")

PROFILE_MQTT = "MQTT-ThermalSensor"
PROFILE_COAP = "CoAP-ThermalSensor"


class ThingsBoardError(RuntimeError):
    """Raised for API errors with server detail when available."""


def _req_exc(resp: requests.Response, what: str) -> ThingsBoardError:
    detail = ""
    try:
        detail = resp.json()
    except Exception:
        detail = (resp.text or "")[:500]
    return ThingsBoardError(f"{what} failed: HTTP {resp.status_code} — {detail}")


def get_token(session: requests.Session) -> str:
    r = session.post(
        f"{TB_URL}/api/auth/login",
        json={"username": TB_USERNAME, "password": TB_PASSWORD},
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        timeout=60,
    )
    if not r.ok:
        raise _req_exc(r, "Login")
    data = r.json()
    token = data.get("token")
    if not token:
        raise ThingsBoardError(f"Login response missing token: {data!r}")
    return token


def headers(session: requests.Session, token: str) -> dict[str, str]:
    return {
        "X-Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def get_profile_id(session: requests.Session, token: str, name: str) -> dict[str, Any]:
    page = 0
    page_size = 50
    while True:
        r = session.get(
            f"{TB_URL}/api/deviceProfiles",
            params={"pageSize": page_size, "page": page, "sortProperty": "name", "sortOrder": "ASC"},
            headers=headers(session, token),
            timeout=60,
        )
        if not r.ok:
            raise _req_exc(r, f"List device profiles (page {page})")
        payload = r.json()
        for p in payload.get("data", []):
            if p.get("name") == name:
                pid = p.get("id", {})
                return {"id": pid["id"], "entityType": "DEVICE_PROFILE"}
        if not payload.get("hasNext", False):
            break
        page += 1
    raise ThingsBoardError(
        f'Device profile "{name}" not found. Create it in the UI (Step 11a) and re-run.'
    )


def get_default_asset_profile_id(session: requests.Session, token: str) -> dict[str, Any]:
    r = session.get(
        f"{TB_URL}/api/assetProfiles",
        params={"pageSize": 50, "page": 0, "sortProperty": "name", "sortOrder": "ASC"},
        headers=headers(session, token),
        timeout=60,
    )
    if not r.ok:
        raise _req_exc(r, "List asset profiles")
    rows = r.json().get("data") or []
    if not rows:
        raise ThingsBoardError("No asset profiles found; create a default asset profile in ThingsBoard.")
    preferred = next((p for p in rows if str(p.get("name", "")).lower() == "default"), None)
    pick = preferred or rows[0]
    pid = pick.get("id", {})
    return {"id": pid["id"], "entityType": "ASSET_PROFILE"}


def get_device_by_name(session: requests.Session, token: str, name: str) -> dict[str, Any] | None:
    r = session.get(
        f"{TB_URL}/api/tenant/device",
        params={"deviceName": name},
        headers=headers(session, token),
        timeout=60,
    )
    if r.status_code == 404:
        return None
    if not r.ok:
        raise _req_exc(r, f'Get device "{name}"')
    return r.json()


def create_device(
    session: requests.Session,
    token: str,
    name: str,
    profile_tb_name: str,
    profile_id: dict[str, Any],
) -> dict[str, Any]:
    existing = get_device_by_name(session, token, name)
    if existing:
        return existing
    body = {
        "name": name,
        "type": profile_tb_name,
        "deviceProfileId": profile_id,
    }
    r = session.post(
        f"{TB_URL}/api/device",
        json=body,
        headers=headers(session, token),
        timeout=60,
    )
    if not r.ok:
        raise _req_exc(r, f'Create device "{name}"')
    return r.json()


def get_asset_by_name(session: requests.Session, token: str, name: str) -> dict[str, Any] | None:
    r = session.get(
        f"{TB_URL}/api/tenant/asset",
        params={"assetName": name},
        headers=headers(session, token),
        timeout=60,
    )
    if r.status_code == 404:
        return None
    if not r.ok:
        raise _req_exc(r, f'Get asset "{name}"')
    return r.json()


def create_asset(
    session: requests.Session,
    token: str,
    name: str,
    asset_type: str,
    asset_profile_id: dict[str, Any],
) -> dict[str, Any]:
    existing = get_asset_by_name(session, token, name)
    if existing:
        return existing
    body = {
        "name": name,
        "type": asset_type,
        "assetProfileId": asset_profile_id,
    }
    r = session.post(
        f"{TB_URL}/api/asset",
        json=body,
        headers=headers(session, token),
        timeout=60,
    )
    if not r.ok:
        raise _req_exc(r, f'Create asset "{name}"')
    return r.json()


def save_relation(
    session: requests.Session,
    token: str,
    from_type: str,
    from_id: str,
    to_type: str,
    to_id: str,
    relation_type: str = "Contains",
) -> None:
    body = {
        "from": {"entityType": from_type, "id": from_id},
        "to": {"entityType": to_type, "id": to_id},
        "type": relation_type,
        "typeGroup": "COMMON",
    }
    r = session.post(
        f"{TB_URL}/api/relation",
        json=body,
        headers=headers(session, token),
        timeout=60,
    )
    if r.status_code in (200, 201, 204):
        return
    # Idempotent: duplicate relation may return error — ignore if already exists
    if r.status_code == 400:
        try:
            err = r.json().get("message", "")
        except Exception:
            err = r.text or ""
        if "already exists" in err.lower() or "duplicate" in err.lower():
            return
    raise _req_exc(r, "save_relation")


def provision_all_devices(session: requests.Session, token: str) -> dict[str, dict[str, Any]]:
    mqtt_prof = get_profile_id(session, token, PROFILE_MQTT)
    coap_prof = get_profile_id(session, token, PROFILE_COAP)
    devices: dict[str, dict[str, Any]] = {}
    for floor in range(1, 11):
        for room in range(1, 21):
            room_num = floor * 100 + room
            node_id = f"b01-f{floor:02d}-r{room_num:03d}"
            if room <= 10:
                profile_name = PROFILE_MQTT
                prof_id = mqtt_prof
            else:
                profile_name = PROFILE_COAP
                prof_id = coap_prof
            dev = create_device(session, token, node_id, profile_name, prof_id)
            devices[node_id] = dev
            print(f"Device OK  {node_id}  ({profile_name})  id={dev['id']['id']}")
    return devices


def create_asset_hierarchy(
    session: requests.Session,
    token: str,
    devices: dict[str, dict[str, Any]],
) -> None:
    ap_id = get_default_asset_profile_id(session, token)

    campus = create_asset(session, token, "Campus-B01", "Campus", ap_id)
    building = create_asset(session, token, "Building-01", "Building", ap_id)
    save_relation(
        session,
        token,
        "ASSET",
        campus["id"]["id"],
        "ASSET",
        building["id"]["id"],
    )
    print("Linked Campus-B01 Contains Building-01")

    floor_assets: dict[int, dict[str, Any]] = {}
    for floor in range(1, 11):
        fl_name = f"Floor-{floor:02d}"
        fl = create_asset(session, token, fl_name, "Floor", ap_id)
        floor_assets[floor] = fl
        save_relation(
            session,
            token,
            "ASSET",
            building["id"]["id"],
            "ASSET",
            fl["id"]["id"],
        )
        print(f"Linked Building-01 Contains {fl_name}")

    for floor in range(1, 11):
        fl = floor_assets[floor]
        for room in range(1, 21):
            room_num = floor * 100 + room
            node_id = f"b01-f{floor:02d}-r{room_num:03d}"
            room_asset = create_asset(session, token, node_id, "Room", ap_id)
            save_relation(
                session,
                token,
                "ASSET",
                fl["id"]["id"],
                "ASSET",
                room_asset["id"]["id"],
            )
            dev = devices.get(node_id)
            if not dev:
                raise ThingsBoardError(f"Missing device in map for {node_id}; run device provisioning first.")
            save_relation(
                session,
                token,
                "ASSET",
                room_asset["id"]["id"],
                "DEVICE",
                dev["id"]["id"],
            )
            print(f"Linked Floor-{floor:02d} Contains room asset {node_id}; room Contains device")


def main() -> int:
    parser = argparse.ArgumentParser(description="ThingsBoard CE campus provisioning")
    parser.add_argument("--devices-only", action="store_true", help="Only create/update200 devices")
    parser.add_argument("--assets-only", action="store_true", help="Only create assets & relations (devices must exist)")
    args = parser.parse_args()

    session = requests.Session()
    session.verify = TB_VERIFY_SSL

    try:
        token = get_token(session)
    except ThingsBoardError as e:
        print(e, file=sys.stderr)
        print(
            "Hint: use tenant admin (default tenant@thingsboard.org / tenant) or set TB_USERNAME/TB_PASSWORD.",
            file=sys.stderr,
        )
        return 1

    try:
        if args.assets_only:
            devices: dict[str, dict[str, Any]] = {}
            for floor in range(1, 11):
                for room in range(1, 21):
                    room_num = floor * 100 + room
                    node_id = f"b01-f{floor:02d}-r{room_num:03d}"
                    d = get_device_by_name(session, token, node_id)
                    if not d:
                        raise ThingsBoardError(f'Device "{node_id}" not found; run without --assets-only first.')
                    devices[node_id] = d
            create_asset_hierarchy(session, token, devices)
        elif args.devices_only:
            provision_all_devices(session, token)
        else:
            devs = provision_all_devices(session, token)
            create_asset_hierarchy(session, token, devs)
    except ThingsBoardError as e:
        print(e, file=sys.stderr)
        return 1
    except requests.RequestException as e:
        print(f"HTTP error: {e}", file=sys.stderr)
        return 1

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

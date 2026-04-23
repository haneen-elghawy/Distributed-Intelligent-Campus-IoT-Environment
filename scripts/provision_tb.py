"""Provision 200 room devices + 10 floor-summary devices + Campus→Building→Floor→Room assets in ThingsBoard CE via REST.

Prerequisites (UI — Step 11a)
-----------------------------
Create two **Device profiles** named exactly ``MQTT-ThermalSensor`` and ``CoAP-ThermalSensor``
with the appropriate transports.

Authentication
--------------
Uses your tenant admin account. Override with environment variables if needed:
    TB_USERNAME   (default: tenant@campus.io)
    TB_PASSWORD   (default: Tenant123!)
    TB_URL        (default: http://localhost:9090)

Usage::
    pip install requests
    python provision_tb.py
    python provision_tb.py --assets-only    # devices must already exist
    python provision_tb.py --devices-only
    python provision_tb.py --purge          # delete all campus devices + assets, then exit
    python provision_tb.py --reset          # purge then full re-provision

UI-only ThingsBoard (Step 11a / 11d / 11e) is documented in ``docs/thingsboard_step11.md``.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Any
from urllib.parse import quote

import requests

TB_URL      = os.getenv("TB_URL",      "http://localhost:9090").rstrip("/")
TB_USERNAME = os.getenv("TB_USERNAME", "tenant@campus.io")   # ← your tenant admin email
TB_PASSWORD = os.getenv("TB_PASSWORD", "Tenant123!")          # ← your tenant admin password
TB_VERIFY_SSL = os.getenv("TB_VERIFY_SSL", "true").lower() in ("1", "true", "yes")

PROFILE_MQTT = "MQTT-ThermalSensor"
PROFILE_COAP = "CoAP-ThermalSensor"
PROFILE_FLOOR = "FloorSummary"  # optional; falls back to PROFILE_MQTT (see ``docs/thingsboard_step11.md``)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class ThingsBoardError(RuntimeError):
    """Raised for API errors with server detail when available."""


def _req_exc(resp: requests.Response, what: str) -> ThingsBoardError:
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


def auth_headers(token: str) -> dict[str, str]:
    return {
        "X-Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


# ---------------------------------------------------------------------------
# Device profiles
# ---------------------------------------------------------------------------

def get_profile_id(session: requests.Session, token: str, name: str) -> dict[str, Any]:
    page = 0
    while True:
        r = session.get(
            f"{TB_URL}/api/deviceProfiles",
            params={"pageSize": 50, "page": page, "sortProperty": "name", "sortOrder": "ASC"},
            headers=auth_headers(token),
            timeout=60,
        )
        if not r.ok:
            raise _req_exc(r, f"List device profiles (page {page})")
        payload = r.json()
        for p in payload.get("data", []):
            if p.get("name") == name:
                return {"id": p["id"]["id"], "entityType": "DEVICE_PROFILE"}
        if not payload.get("hasNext", False):
            break
        page += 1
    raise ThingsBoardError(
        f'Device profile "{name}" not found. '
        f'Create it in the UI (Step 11a) and re-run.'
    )


def get_profile_id_optional(
    session: requests.Session, token: str, name: str
) -> dict[str, Any] | None:
    """Return profile id dict or None if the named profile does not exist."""
    page = 0
    while True:
        r = session.get(
            f"{TB_URL}/api/deviceProfiles",
            params={"pageSize": 50, "page": page, "sortProperty": "name", "sortOrder": "ASC"},
            headers=auth_headers(token),
            timeout=60,
        )
        if not r.ok:
            raise _req_exc(r, f"List device profiles (page {page})")
        payload = r.json()
        for p in payload.get("data", []):
            if p.get("name") == name:
                return {"id": p["id"]["id"], "entityType": "DEVICE_PROFILE"}
        if not payload.get("hasNext", False):
            break
        page += 1
    return None


# ---------------------------------------------------------------------------
# Asset profiles
# ---------------------------------------------------------------------------

def get_default_asset_profile_id(session: requests.Session, token: str) -> dict[str, Any]:
    r = session.get(
        f"{TB_URL}/api/assetProfiles",
        params={"pageSize": 50, "page": 0, "sortProperty": "name", "sortOrder": "ASC"},
        headers=auth_headers(token),
        timeout=60,
    )
    if not r.ok:
        raise _req_exc(r, "List asset profiles")
    rows = r.json().get("data") or []
    if not rows:
        raise ThingsBoardError("No asset profiles found; create a default asset profile in ThingsBoard.")
    preferred = next((p for p in rows if str(p.get("name", "")).lower() == "default"), None)
    pick = preferred or rows[0]
    return {"id": pick["id"]["id"], "entityType": "ASSET_PROFILE"}


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------

def _find_device_via_tenant_list(session: requests.Session, token: str, name: str) -> dict[str, Any] | None:
    """Resolve device by exact name. TB 4.x sometimes 404s on GET /api/tenant/device/{name}."""
    page = 0
    while True:
        r = session.get(
            f"{TB_URL}/api/tenant/devices",
            params={
                "page": page,
                "pageSize": 100,
                "textSearch": name,
                "sortProperty": "name",
                "sortOrder": "ASC",
            },
            headers=auth_headers(token),
            timeout=60,
        )
        if not r.ok:
            return None
        payload = r.json()
        for d in payload.get("data", []):
            if d.get("name") == name:
                return d
        if not payload.get("hasNext", False):
            break
        page += 1
    return None


def get_device_by_name(session: requests.Session, token: str, name: str) -> dict[str, Any] | None:
    # Prefer the path-parameter endpoint for compatibility across TB versions.
    r = session.get(
        f"{TB_URL}/api/tenant/device/{quote(name, safe='')}",
        headers=auth_headers(token),
        timeout=60,
    )
    if r.status_code == 200:
        return r.json()
    if r.status_code != 404:
        raise _req_exc(r, f'Get device "{name}"')
    return _find_device_via_tenant_list(session, token, name)


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
    r = session.post(
        f"{TB_URL}/api/device",
        json={"name": name, "type": profile_tb_name, "deviceProfileId": profile_id},
        headers=auth_headers(token),
        timeout=60,
    )
    if r.ok:
        return r.json()
    # Re-run: previous GET failed on TB 4.x but create reports duplicate
    if r.status_code == 400:
        try:
            err = r.json()
            msg = (err.get("message") or "").lower()
            if "already exists" in msg or err.get("errorCode") == 31:
                retry = _find_device_via_tenant_list(session, token, name)
                if retry:
                    return retry
        except Exception:
            pass
    raise _req_exc(r, f'Create device "{name}"')


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------

def _find_asset_via_tenant_list(session: requests.Session, token: str, name: str) -> dict[str, Any] | None:
    """Resolve asset by exact name. TB 4.x sometimes 404s on GET /api/tenant/asset/{name}."""
    page = 0
    while True:
        r = session.get(
            f"{TB_URL}/api/tenant/assets",
            params={
                "page": page,
                "pageSize": 100,
                "textSearch": name,
                "sortProperty": "name",
                "sortOrder": "ASC",
            },
            headers=auth_headers(token),
            timeout=60,
        )
        if not r.ok:
            return None
        payload = r.json()
        for a in payload.get("data", []):
            if a.get("name") == name:
                return a
        if not payload.get("hasNext", False):
            break
        page += 1
    return None


def get_asset_by_name(session: requests.Session, token: str, name: str) -> dict[str, Any] | None:
    r = session.get(
        f"{TB_URL}/api/tenant/asset/{quote(name, safe='')}",
        headers=auth_headers(token),
        timeout=60,
    )
    if r.status_code == 200:
        return r.json()
    if r.status_code != 404:
        raise _req_exc(r, f'Get asset "{name}"')
    return _find_asset_via_tenant_list(session, token, name)


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
    r = session.post(
        f"{TB_URL}/api/asset",
        json={"name": name, "type": asset_type, "assetProfileId": asset_profile_id},
        headers=auth_headers(token),
        timeout=60,
    )
    if r.ok:
        return r.json()
    if r.status_code == 400:
        try:
            err = r.json()
            msg = (err.get("message") or "").lower()
            if "already exists" in msg or err.get("errorCode") == 31:
                retry = _find_asset_via_tenant_list(session, token, name)
                if retry:
                    return retry
        except Exception:
            pass
    raise _req_exc(r, f'Create asset "{name}"')


# ---------------------------------------------------------------------------
# Relations
# ---------------------------------------------------------------------------

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
        "to":   {"entityType": to_type,   "id": to_id},
        "type": relation_type,
        "typeGroup": "COMMON",
    }
    r = session.post(
        f"{TB_URL}/api/relation",
        json=body,
        headers=auth_headers(token),
        timeout=60,
    )
    if r.status_code in (200, 201, 204):
        return
    # Idempotent: ignore if relation already exists
    if r.status_code == 400:
        try:
            err = r.json().get("message", "")
        except Exception:
            err = r.text or ""
        if "already exists" in err.lower() or "duplicate" in err.lower():
            return
    raise _req_exc(r, "save_relation")


# ---------------------------------------------------------------------------
# Provisioning logic
# ---------------------------------------------------------------------------

def provision_all_devices(
    session: requests.Session, token: str
) -> dict[str, dict[str, Any]]:
    print("Fetching device profile IDs...")
    mqtt_prof = get_profile_id(session, token, PROFILE_MQTT)
    coap_prof = get_profile_id(session, token, PROFILE_COAP)

    devices: dict[str, dict[str, Any]] = {}
    total = 0
    for floor in range(1, 11):          # Floors 1–10
        for room in range(1, 21):       # Rooms 1–20
            room_num = floor * 100 + room
            node_id  = f"b01-f{floor:02d}-r{room_num:03d}"
            if room <= 10:
                profile_name = PROFILE_MQTT
                prof_id      = mqtt_prof
            else:
                profile_name = PROFILE_COAP
                prof_id      = coap_prof

            dev = create_device(session, token, node_id, profile_name, prof_id)
            devices[node_id] = dev
            total += 1
            print(f"  [OK] [{total:>3}/200] {node_id}  ({profile_name})  id={dev['id']['id']}")

    # Step 12 (floor-summary MQTT topic) — same device names the uplink converter uses
    print("\nCreating floor-summary devices (b01-f01-floor-summary ... b01-f10-floor-summary)...")
    fl_prof = get_profile_id_optional(session, token, PROFILE_FLOOR)
    if fl_prof:
        fl_name = PROFILE_FLOOR
    else:
        fl_prof = mqtt_prof
        fl_name = PROFILE_MQTT
        print(
            f"  [note] No device profile {PROFILE_FLOOR!r} — using {PROFILE_MQTT!r} for floor-summary. "
            f"Optional: create {PROFILE_FLOOR!r} in the UI and re-run --devices-only."
        )
    for floor in range(1, 11):
        node_id = f"b01-f{floor:02d}-floor-summary"
        dev = create_device(session, token, node_id, fl_name, fl_prof)
        devices[node_id] = dev
        print(f"  [OK] [{200 + floor}/210] {node_id}  ({fl_name})  id={dev['id']['id']}")

    return devices


def create_asset_hierarchy(
    session: requests.Session,
    token: str,
    devices: dict[str, dict[str, Any]],
) -> None:
    print("\nFetching default asset profile ID...")
    ap_id = get_default_asset_profile_id(session, token)

    # Campus
    campus = create_asset(session, token, "Campus-B01", "Campus", ap_id)
    print(f"  [OK] Asset: Campus-B01  id={campus['id']['id']}")

    # Building
    building = create_asset(session, token, "Building-01", "Building", ap_id)
    save_relation(session, token, "ASSET", campus["id"]["id"], "ASSET", building["id"]["id"])
    print(f"  [OK] Asset: Building-01  (linked to Campus-B01)")

    # Floors
    floor_assets: dict[int, dict[str, Any]] = {}
    for floor in range(1, 11):
        fl_name = f"Floor-{floor:02d}"
        fl = create_asset(session, token, fl_name, "Floor", ap_id)
        floor_assets[floor] = fl
        save_relation(session, token, "ASSET", building["id"]["id"], "ASSET", fl["id"]["id"])
        print(f"  [OK] Asset: {fl_name}  (linked to Building-01)")

    # Rooms + device links
    print("\nLinking rooms to floors and devices...")
    for floor in range(1, 11):
        fl = floor_assets[floor]
        for room in range(1, 21):
            room_num = floor * 100 + room
            node_id  = f"b01-f{floor:02d}-r{room_num:03d}"

            room_asset = create_asset(session, token, node_id, "Room", ap_id)
            # Floor → Room
            save_relation(session, token, "ASSET", fl["id"]["id"], "ASSET", room_asset["id"]["id"])

            # Room → Device
            dev = devices.get(node_id)
            if not dev:
                raise ThingsBoardError(
                    f'Device "{node_id}" missing from map. Run without --assets-only first.'
                )
            save_relation(session, token, "ASSET", room_asset["id"]["id"], "DEVICE", dev["id"]["id"])
            print(f"    [OK] Floor-{floor:02d} -> {node_id} (room asset + device link)")


# ---------------------------------------------------------------------------
# Purge (delete) — devices first, then assets leaf-to-root
# ---------------------------------------------------------------------------

# Room devices: b01-f01-r101; optional integration devices: b01-f01-floor-summary
_CAMPUS_DEVICE_PAT = re.compile(r"^b01-f\d{2}-(r\d{3}|floor-summary)$")
_CAMPUS_ROOM_ASSET_PAT = re.compile(r"^b01-f\d{2}-r\d{3}$")


def _entity_uuid(tb_obj: dict[str, Any]) -> str:
    eid = tb_obj.get("id")
    if isinstance(eid, dict):
        return str(eid["id"])
    return str(eid)


def _list_all_tenant_devices(session: requests.Session, token: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    page = 0
    while True:
        r = session.get(
            f"{TB_URL}/api/tenant/devices",
            params={
                "page": page,
                "pageSize": 500,
                "sortProperty": "name",
                "sortOrder": "ASC",
            },
            headers=auth_headers(token),
            timeout=120,
        )
        if not r.ok:
            raise _req_exc(r, "List all tenant devices")
        payload = r.json()
        out.extend(payload.get("data", []))
        if not payload.get("hasNext", False):
            break
        page += 1
    return out


def _list_all_tenant_assets(session: requests.Session, token: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    page = 0
    while True:
        r = session.get(
            f"{TB_URL}/api/tenant/assets",
            params={
                "page": page,
                "pageSize": 500,
                "sortProperty": "name",
                "sortOrder": "ASC",
            },
            headers=auth_headers(token),
            timeout=120,
        )
        if not r.ok:
            raise _req_exc(r, "List all tenant assets")
        payload = r.json()
        out.extend(payload.get("data", []))
        if not payload.get("hasNext", False):
            break
        page += 1
    return out


def _delete_device_id(session: requests.Session, token: str, name: str, eid: str) -> None:
    r = session.delete(
        f"{TB_URL}/api/device/{eid}",
        headers=auth_headers(token),
        timeout=60,
    )
    if r.status_code in (200, 204):
        return
    if r.status_code == 404:
        return
    raise _req_exc(r, f'Delete device "{name}"')


def _delete_asset_id(session: requests.Session, token: str, name: str, eid: str) -> None:
    r = session.delete(
        f"{TB_URL}/api/asset/{eid}",
        headers=auth_headers(token),
        timeout=60,
    )
    if r.status_code in (200, 204):
        return
    if r.status_code == 404:
        return
    raise _req_exc(r, f'Delete asset "{name}"')


def purge_campus(session: requests.Session, token: str) -> None:
    """Delete campus room devices, floor-summary devices, then asset hierarchy (TB CE REST)."""
    print("Purge: listing tenant devices...")
    devices = _list_all_tenant_devices(session, token)
    to_remove_dev = [d for d in devices if _CAMPUS_DEVICE_PAT.match((d.get("name") or ""))]
    print(f"  Deleting {len(to_remove_dev)} device(s) (room + floor-summary)...")
    for d in to_remove_dev:
        name = d.get("name") or ""
        _delete_device_id(session, token, name, _entity_uuid(d))
        print(f"    [del] device {name}")

    print("Purge: listing tenant assets...")
    all_assets = _list_all_tenant_assets(session, token)
    by_name = {a.get("name") or "": a for a in all_assets}

    # Room assets (same names as room devices)
    room_assets = [a for a in all_assets if _CAMPUS_ROOM_ASSET_PAT.match((a.get("name") or ""))]
    print(f"  Deleting {len(room_assets)} room asset(s)...")
    for a in room_assets:
        name = a.get("name") or ""
        _delete_asset_id(session, token, name, _entity_uuid(a))
        print(f"    [del] asset {name}")

    # Floor-01 .. Floor-10, Building-01, Campus-B01
    for fl in range(1, 11):
        fn = f"Floor-{fl:02d}"
        a = by_name.get(fn) or get_asset_by_name(session, token, fn)
        if a:
            _delete_asset_id(session, token, fn, _entity_uuid(a))
            print(f"    [del] asset {fn}")
    for fixed in ("Building-01", "Campus-B01"):
        a = by_name.get(fixed) or get_asset_by_name(session, token, fixed)
        if a:
            _delete_asset_id(session, token, fixed, _entity_uuid(a))
            print(f"    [del] asset {fixed}")

    print("[OK] Purge: campus entities removed from ThingsBoard (tenant).")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="ThingsBoard CE campus provisioning")
    parser.add_argument("--devices-only", action="store_true",
                        help="Only create/update 210 devices (200 rooms + 10 floor-summary)")
    parser.add_argument("--assets-only",  action="store_true",
                        help="Only create assets & relations (devices must already exist)")
    parser.add_argument("--purge", action="store_true",
                        help="Delete campus devices and assets, then exit (no re-create)")
    parser.add_argument("--reset", action="store_true",
                        help="Purge all campus entities, then re-provision devices + assets")
    args = parser.parse_args()
    if (args.purge or args.reset) and (args.devices_only or args.assets_only):
        print("[ERROR] Do not combine --purge/--reset with --devices-only or --assets-only.",
              file=sys.stderr)
        return 1

    print(f"Connecting to ThingsBoard at {TB_URL}")
    print(f"Authenticating as: {TB_USERNAME}\n")

    session = requests.Session()
    session.verify = TB_VERIFY_SSL

    try:
        token = get_token(session)
        print("[OK] Login successful\n")
    except ThingsBoardError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        print(
            "\nHint: Make sure TB_USERNAME and TB_PASSWORD match your tenant admin account.\n"
            "      Edit the defaults at the top of this script if needed.",
            file=sys.stderr,
        )
        return 1

    try:
        if args.reset:
            purge_campus(session, token)
            devs = provision_all_devices(session, token)
            create_asset_hierarchy(session, token, devs)
            print("\n[OK] All done! 210 devices (200 rooms + 10 floor-summary) and full asset hierarchy provisioned.")
            return 0

        if args.purge:
            purge_campus(session, token)
            print("\n[OK] Purge finished. Re-run: python scripts/provision_tb.py")
            return 0

        if args.assets_only:
            # Load existing devices from ThingsBoard
            devices: dict[str, dict[str, Any]] = {}
            print("Loading existing devices...")
            for floor in range(1, 11):
                for room in range(1, 21):
                    room_num = floor * 100 + room
                    node_id  = f"b01-f{floor:02d}-r{room_num:03d}"
                    d = get_device_by_name(session, token, node_id)
                    if not d:
                        raise ThingsBoardError(
                            f'Device "{node_id}" not found. Run without --assets-only first.'
                        )
                    devices[node_id] = d
            create_asset_hierarchy(session, token, devices)

        elif args.devices_only:
            provision_all_devices(session, token)

        else:
            devs = provision_all_devices(session, token)
            create_asset_hierarchy(session, token, devs)

    except ThingsBoardError as e:
        print(f"\n[ERROR] {e}", file=sys.stderr)
        return 1
    except requests.RequestException as e:
        print(f"\n[ERROR] HTTP error: {e}", file=sys.stderr)
        return 1

    print("\n[OK] All done! 210 devices (200 rooms + 10 floor-summary) and full asset hierarchy provisioned.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
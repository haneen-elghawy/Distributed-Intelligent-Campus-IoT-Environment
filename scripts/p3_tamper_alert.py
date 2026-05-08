"""Phase 3 — OTA tamper alert monitor.

Subscribes to HiveMQ `campus/+/+/+/ota/report` and:
- If rejected: fires a ThingsBoard CRITICAL alarm (OTA_TAMPER_ALERT)
- If accepted: updates the device CLIENT_SCOPE attribute `current_version`
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import gmqtt
import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | p3_tamper_alert | %(levelname)s | %(message)s",
)
logger = logging.getLogger("p3_tamper_alert")

from dotenv import load_dotenv

load_dotenv(override=True)

TB_URL = os.getenv("TB_URL", "http://localhost:9090").rstrip("/")
TB_USERNAME = os.getenv("TB_USERNAME", "tenant@thingsboard.org")
TB_PASSWORD = os.getenv("TB_PASSWORD", "tenant")

HIVEMQ_HOST = os.getenv("HIVEMQ_HOST", "localhost")
HIVEMQ_PORT = int(os.getenv("HIVEMQ_PORT", "1883"))
HIVEMQ_USER = os.getenv("HIVEMQ_USER", "thingsboard")
HIVEMQ_PASS = os.getenv("HIVEMQ_PASS", "tb_super_pass")

CSV_PATH = Path("thingsboard") / "campus_devices.csv"

SUB_TOPIC = "campus/+/+/+/ota/report"


class ThingsBoardError(RuntimeError):
    pass


@dataclass
class TokenCache:
    token: str | None = None
    issued_at: float = 0.0

    def valid(self) -> bool:
        return bool(self.token) and (time.time() - self.issued_at) < (50 * 60)


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "X-Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _raise_for_resp(resp: httpx.Response, what: str) -> None:
    if resp.status_code < 400:
        return
    detail: Any
    try:
        detail = resp.json()
    except Exception:
        detail = (resp.text or "")[:800]
    raise ThingsBoardError(f"{what} failed: HTTP {resp.status_code} — {detail}")


async def tb_login(client: httpx.AsyncClient) -> str:
    resp = await client.post(
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


async def tb_request(
    client: httpx.AsyncClient,
    token_cache: TokenCache,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: Any | None = None,
    what: str = "Request",
) -> httpx.Response:
    if not token_cache.valid():
        token_cache.token = await tb_login(client)
        token_cache.issued_at = time.time()

    assert token_cache.token is not None
    resp = await client.request(
        method,
        f"{TB_URL}{path}",
        params=params,
        json=json_body,
        headers=_auth_headers(token_cache.token),
    )
    if resp.status_code == 401:
        token_cache.token = await tb_login(client)
        token_cache.issued_at = time.time()
        resp = await client.request(
            method,
            f"{TB_URL}{path}",
            params=params,
            json=json_body,
            headers=_auth_headers(token_cache.token),
        )
    _raise_for_resp(resp, what)
    return resp


def load_rooms_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"missing {path.as_posix()}")
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"name", "protocol"}
        if not required.issubset(reader.fieldnames or []):
            raise ThingsBoardError(f"CSV missing required columns: {required} (got {reader.fieldnames})")
        return list(reader)


async def resolve_device_id(
    tb: httpx.AsyncClient,
    token_cache: TokenCache,
    *,
    device_name: str,
) -> str | None:
    resp = await tb_request(
        tb,
        token_cache,
        "GET",
        "/api/tenant/devices",
        params={"pageSize": 1, "page": 0, "textSearch": device_name},
        what=f"Find device {device_name!r}",
    )
    data = resp.json()
    items = data.get("data") or []
    if not items:
        return None
    return items[0]["id"]["id"]


def _as_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y", "on")
    return False


async def main() -> None:
    rows = load_rooms_csv(CSV_PATH)
    if len(rows) != 200:
        logger.warning("Expected 200 CSV rows; got %d", len(rows))

    token_cache = TokenCache()
    room_key_to_device_id: dict[str, str] = {}

    async with httpx.AsyncClient(timeout=30.0) as tb:
        # Build registry at startup: room_key -> device_id
        for idx, row in enumerate(rows, start=1):
            room_key = (row.get("name") or "").strip()
            protocol = (row.get("protocol") or "").strip().lower()
            if not room_key or not protocol:
                continue
            device_name = f"{room_key}"
            try:
                device_id = await resolve_device_id(tb, token_cache, device_name=device_name)
                if not device_id:
                    logger.warning("Device not found in ThingsBoard: %s", device_name)
                    continue
                room_key_to_device_id[room_key] = device_id
            except Exception as e:
                logger.warning("Failed resolving device_id for %s: %s", device_name, e)

            if idx % 50 == 0:
                logger.info("registry progress: %d/%d (%d resolved)", idx, len(rows), len(room_key_to_device_id))

        if not room_key_to_device_id:
            raise ThingsBoardError("No device_ids resolved from ThingsBoard; cannot start.")

        mqtt = gmqtt.Client(f"p3-tamper-alert-{os.getpid()}")
        mqtt.set_auth_credentials(HIVEMQ_USER, HIVEMQ_PASS)

        def on_connect(_client, _flags, _rc, _props):
            _client.subscribe(SUB_TOPIC, qos=1)
            logger.info("Subscribed to %s", SUB_TOPIC)

        def on_message(_client, topic, payload, qos, properties):
            asyncio.get_running_loop().create_task(handle_report(topic, payload))

        async def handle_report(topic: str, payload: Any) -> None:
            try:
                raw = payload.decode() if isinstance(payload, (bytes, bytearray)) else payload
                msg = json.loads(raw)
            except Exception:
                return

            sensor_id = msg.get("sensor_id")
            if not sensor_id:
                return
            sensor_id = str(sensor_id)
            device_id = room_key_to_device_id.get(sensor_id)
            if not device_id:
                logger.warning("Unknown sensor_id (no device mapping): %s", sensor_id)
                return

            rejected = _as_bool(msg.get("rejected"))
            reason = str(msg.get("reason") or "")
            version = str(msg.get("version") or "")
            ts = msg.get("timestamp") or int(time.time())

            if rejected:
                body = {
                    "name": "OTA_TAMPER_ALERT",
                    "type": "SECURITY",
                    "severity": "CRITICAL",
                    "status": "ACTIVE",
                    "originator": {"id": device_id, "entityType": "DEVICE"},
                    "details": {
                        "reason": reason,
                        "sensor_id": sensor_id,
                        "timestamp": ts,
                        "topic": msg.get("topic", "unknown"),
                    },
                }
                try:
                    await tb_request(tb, token_cache, "POST", "/api/alarm", json_body=body, what="Post alarm")
                    logger.warning("TAMPER ALERT fired for %s: %s", sensor_id, reason)
                except Exception as e:
                    logger.warning("Failed to fire alarm for %s: %s", sensor_id, e)
            else:
                if not version:
                    return
                try:
                    await tb_request(
                        tb,
                        token_cache,
                        "POST",
                        f"/api/plugins/telemetry/DEVICE/{device_id}/attributes/CLIENT_SCOPE",
                        json_body={"current_version": version},
                        what="Post current_version",
                    )
                    logger.info("OTA version updated: %s → v%s", sensor_id, version)
                except Exception as e:
                    logger.warning("Failed to update current_version for %s: %s", sensor_id, e)

        mqtt.on_connect = on_connect
        mqtt.on_message = on_message

        await mqtt.connect(HIVEMQ_HOST, HIVEMQ_PORT, keepalive=15)
        try:
            while True:
                await asyncio.sleep(3600)
        except KeyboardInterrupt:
            logger.info("Stopping (KeyboardInterrupt)")
        finally:
            await mqtt.disconnect()


if __name__ == "__main__":
    asyncio.run(main())


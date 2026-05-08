"""Phase 3 — Shadow State Synchronization (ThingsBoard shared attrs -> HiveMQ cmd -> TB client attrs).

- Loads `thingsboard/campus_devices.csv`
- Resolves device_id + access_token per room via ThingsBoard REST API
- Maintains one ThingsBoard MQTT client per device (auth = access_token)
- Maintains one shared HiveMQ MQTT client for all command publishing
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import gmqtt
import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | p3_shadow_sync | %(levelname)s | %(message)s",
)
logger = logging.getLogger("p3_shadow_sync")

from dotenv import load_dotenv

load_dotenv(override=True)

TB_URL = os.getenv("TB_URL", "http://localhost:9090").rstrip("/")
TB_USERNAME = os.getenv("TB_USERNAME", "tenant@thingsboard.org")
TB_PASSWORD = os.getenv("TB_PASSWORD", "tenant")

TB_HOST = os.getenv("TB_HOST", "localhost")
TB_MQTT_PORT = int(os.getenv("TB_MQTT_PORT", "1884"))

HIVEMQ_HOST = os.getenv("HIVEMQ_HOST", "localhost")
HIVEMQ_PORT = int(os.getenv("HIVEMQ_PORT", "1883"))
HIVEMQ_USER = os.getenv("HIVEMQ_USER", "thingsboard")
HIVEMQ_PASS = os.getenv("HIVEMQ_PASS", "tb_super_pass")

CSV_PATH = Path("thingsboard") / "campus_devices.csv"


class ThingsBoardError(RuntimeError):
    pass


@dataclass(frozen=True)
class DeviceInfo:
    room_key: str
    protocol: str
    floor: int
    room_id: int
    device_id: str
    access_token: str


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
        required = {"name", "protocol", "floor", "room_id"}
        if not required.issubset(reader.fieldnames or []):
            raise ThingsBoardError(f"CSV missing required columns: {required} (got {reader.fieldnames})")
        return list(reader)


async def resolve_device_id(
    tb: httpx.AsyncClient,
    token_cache: TokenCache,
    *,
    device_name: str,
) -> str:
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
        raise ThingsBoardError(f"Device not found: {device_name!r}")
    return items[0]["id"]["id"]


async def resolve_access_token(
    tb: httpx.AsyncClient,
    token_cache: TokenCache,
    *,
    device_id: str,
) -> str:
    resp = await tb_request(
        tb,
        token_cache,
        "GET",
        f"/api/device/{device_id}/credentials",
        what=f"Get credentials for device {device_id}",
    )
    data = resp.json()
    token = data.get("credentialsId")
    if not token:
        raise ThingsBoardError(f"Device credentials missing credentialsId: {data!r}")
    return token


def parse_room_key(room_key: str) -> tuple[str, str, str]:
    # b01-f01-r101 -> building=b01, floor=f01, room=r101
    parts = room_key.split("-")
    if len(parts) != 3:
        raise ValueError(f"invalid room_key {room_key!r}")
    return parts[0], parts[1], parts[2]


class HiveResponseRouter:
    def __init__(self) -> None:
        self._pending_by_cmd: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._pending_by_topic: dict[str, list[asyncio.Future[dict[str, Any]]]] = {}
        self._lock = asyncio.Lock()

    async def register(self, *, cmd_id: str, response_topic: str) -> asyncio.Future[dict[str, Any]]:
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        async with self._lock:
            self._pending_by_cmd[cmd_id] = fut
            self._pending_by_topic.setdefault(response_topic, []).append(fut)
        return fut

    async def resolve_from_message(self, topic: str, payload: Any) -> None:
        try:
            raw = payload.decode() if isinstance(payload, (bytes, bytearray)) else payload
            data = json.loads(raw)
        except Exception:
            return

        cmd_id = data.get("cmd_id")
        async with self._lock:
            if cmd_id and cmd_id in self._pending_by_cmd:
                fut = self._pending_by_cmd.pop(cmd_id)
                if not fut.done():
                    fut.set_result(data)
                return

            # Fallback: resolve the oldest waiter for this topic
            q = self._pending_by_topic.get(topic) or []
            while q:
                fut = q.pop(0)
                if not fut.done():
                    fut.set_result(data)
                    break
            if not q and topic in self._pending_by_topic:
                self._pending_by_topic.pop(topic, None)

    async def cancel(self, *, cmd_id: str, response_topic: str) -> None:
        async with self._lock:
            fut = self._pending_by_cmd.pop(cmd_id, None)
            if fut and not fut.done():
                fut.cancel()
            lst = self._pending_by_topic.get(response_topic)
            if lst:
                self._pending_by_topic[response_topic] = [f for f in lst if f is not fut]
                if not self._pending_by_topic[response_topic]:
                    self._pending_by_topic.pop(response_topic, None)


async def post_device_client_attrs(
    tb: httpx.AsyncClient,
    token_cache: TokenCache,
    *,
    device_id: str,
    attrs: dict[str, Any],
) -> None:
    await tb_request(
        tb,
        token_cache,
        "POST",
        f"/api/plugins/telemetry/DEVICE/{device_id}/attributes/CLIENT_SCOPE",
        json_body=attrs,
        what=f"Post CLIENT_SCOPE attrs to device {device_id}",
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 3 Shadow Sync (TB shared attrs -> HiveMQ cmd -> TB reported attrs)")
    parser.add_argument("--max-devices", type=int, default=200, help="limit number of devices for testing (default 200)")
    args = parser.parse_args()

    rows = load_rooms_csv(CSV_PATH)
    if len(rows) != 200:
        logger.warning("Expected 200 CSV rows; got %d", len(rows))

    max_devices = max(1, min(int(args.max_devices), len(rows)))
    rows = rows[:max_devices]
    logger.info("Starting shadow sync for %d device(s)", len(rows))

    token_cache = TokenCache()
    router = HiveResponseRouter()

    async with httpx.AsyncClient(timeout=30.0) as tb:
        # Resolve device_id + access_token for each CSV row
        devices: list[DeviceInfo] = []
        for i, row in enumerate(rows, start=1):
            room_key = (row.get("name") or "").strip()
            protocol = (row.get("protocol") or "").strip().lower()
            try:
                floor = int(row.get("floor") or "0")
                room_id = int(row.get("room_id") or "0")
            except ValueError:
                logger.warning("Skipping invalid row %d: %r", i, row)
                continue

            device_name = f"{room_key}"
            try:
                device_id = await resolve_device_id(tb, token_cache, device_name=device_name)
                access_token = await resolve_access_token(tb, token_cache, device_id=device_id)
                devices.append(
                    DeviceInfo(
                        room_key=room_key,
                        protocol=protocol,
                        floor=floor,
                        room_id=room_id,
                        device_id=device_id,
                        access_token=access_token,
                    )
                )
            except Exception as e:
                logger.warning("Failed resolving TB device for %s: %s", device_name, e)

        if not devices:
            raise ThingsBoardError("No devices resolved from ThingsBoard; cannot start.")

        # Shared HiveMQ client for all publishing + response listening
        hive = gmqtt.Client(f"p3-shadow-hive-{os.getpid()}")

        def hive_on_connect(_client, _flags, _rc, _props):
            _client.subscribe("campus/+/+/+/response", qos=1)
            logger.info("HiveMQ connected; subscribed to campus/+/+/+/response")

        def hive_on_message(_client, topic, payload, qos, properties):
            asyncio.get_running_loop().create_task(router.resolve_from_message(topic, payload))

        hive.on_connect = hive_on_connect
        hive.on_message = hive_on_message
        await hive.connect(HIVEMQ_HOST, HIVEMQ_PORT, keepalive=15)

        # Per-device TB MQTT clients
        async def start_tb_client(info: DeviceInfo) -> None:
            client = gmqtt.Client(f"p3-shadow-tb-{info.room_key}")
            client.set_auth_credentials(info.access_token, "")

            def on_connect(_client, _flags, _rc, _props):
                _client.subscribe("v1/devices/me/attributes", qos=1)
                logger.info("TB MQTT connected: %s", info.room_key)

            def on_message(_client, topic, payload, qos, properties):
                asyncio.get_running_loop().create_task(handle_shared_update(info, payload))

            client.on_connect = on_connect
            client.on_message = on_message
            await client.connect(TB_HOST, TB_MQTT_PORT, keepalive=20)

        async def handle_shared_update(info: DeviceInfo, payload: Any) -> None:
            try:
                raw = payload.decode() if isinstance(payload, (bytes, bytearray)) else payload
                data = json.loads(raw)
            except Exception:
                return

            desired: dict[str, Any] = {}
            if "hvac_mode" in data:
                desired["hvac_mode"] = data.get("hvac_mode")
            if "lighting_dimmer" in data:
                desired["lighting_dimmer"] = data.get("lighting_dimmer")
            if not desired:
                return

            building, floor_seg, room_seg = parse_room_key(info.room_key)
            cmd_topic = f"campus/{building}/{floor_seg}/{room_seg}/cmd"
            response_topic = f"campus/{building}/{floor_seg}/{room_seg}/response"
            cmd_id = str(uuid4())
            cmd = dict(desired)
            cmd["cmd_id"] = cmd_id

            fut = await router.register(cmd_id=cmd_id, response_topic=response_topic)
            hive.publish(cmd_topic, json.dumps(cmd), qos=1)

            try:
                resp = await asyncio.wait_for(fut, timeout=10.0)
                reported: dict[str, Any] = {}
                if "hvac_mode" in desired:
                    reported["reported_hvac_mode"] = resp.get("hvac_mode")
                if "lighting_dimmer" in desired:
                    reported["reported_lighting_dimmer"] = resp.get("lighting_dimmer")
                reported["sync_status"] = "IN_SYNC"

                await post_device_client_attrs(tb, token_cache, device_id=info.device_id, attrs=reported)
                logger.info("[SYNC] %s: desired=%s reported=%s status=IN_SYNC", info.room_key, desired, reported)
            except asyncio.TimeoutError:
                await router.cancel(cmd_id=cmd_id, response_topic=response_topic)
                await post_device_client_attrs(
                    tb,
                    token_cache,
                    device_id=info.device_id,
                    attrs={"sync_status": "OUT_OF_SYNC"},
                )
                logger.warning("[SYNC] %s: desired=%s status=OUT_OF_SYNC (timeout)", info.room_key, desired)
            except Exception as e:
                logger.warning("[SYNC] %s: error=%s", info.room_key, e)

        # Start TB clients in batches to avoid broker overload
        batch_size = 20
        for i in range(0, len(devices), batch_size):
            batch = devices[i : i + batch_size]
            await asyncio.gather(*(start_tb_client(d) for d in batch))
            await asyncio.sleep(0.1)

        logger.info("All TB MQTT clients started (%d). Waiting for shared attribute updates…", len(devices))
        try:
            while True:
                await asyncio.sleep(3600)
        except KeyboardInterrupt:
            logger.info("Stopping (KeyboardInterrupt)")
        finally:
            await hive.disconnect()


if __name__ == "__main__":
    asyncio.run(main())


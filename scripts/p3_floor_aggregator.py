"""
Phase 3 — Floor Telemetry Aggregator (CLEAN + STABLE VERSION)
Fixes:
- MQTT reconnect storms (0x86)
- duplicate connections
- gmqtt lifecycle bugs
- ThingsBoard asset mapping stability
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from statistics import mean
from typing import Any

import gmqtt
import httpx
from tb_entity_lookup import EntityLookupError, exact_entity_id_from_page

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | p3_floor_aggregator | %(levelname)s | %(message)s",
)

logger = logging.getLogger("p3_floor_aggregator")


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable missing: {name}")
    return value

# -----------------------------
# ENV
# -----------------------------
TB_URL = os.getenv("TB_URL", "http://localhost:9090").rstrip("/")
TB_USERNAME = _required_env("TB_USERNAME")
TB_PASSWORD = _required_env("TB_PASSWORD")

HIVEMQ_HOST = os.getenv("HIVEMQ_HOST", "localhost")
HIVEMQ_PORT = int(os.getenv("HIVEMQ_PORT", "1883"))
HIVEMQ_USER = _required_env("HIVEMQ_USER")
HIVEMQ_PASS = _required_env("HIVEMQ_PASS")

SUB_TOPIC = "campus/+/+/+/telemetry"

WINDOW_SECONDS = 60
POST_EVERY_SECONDS = 30


# -----------------------------
# AUTH CACHE
# -----------------------------
@dataclass
class TokenCache:
    token: str | None = None
    ts: float = 0.0

    def valid(self) -> bool:
        return self.token is not None and (time.time() - self.ts) < 3000


# -----------------------------
# TB AUTH
# -----------------------------
async def tb_login(client: httpx.AsyncClient) -> str:
    r = await client.post(
        f"{TB_URL}/api/auth/login",
        json={"username": TB_USERNAME, "password": TB_PASSWORD},
    )
    r.raise_for_status()
    return r.json()["token"]


async def tb_request(client, cache: TokenCache, method, path, **kwargs):
    if not cache.valid():
        cache.token = await tb_login(client)
        cache.ts = time.time()

    headers = {"X-Authorization": f"Bearer {cache.token}"}

    r = await client.request(method, f"{TB_URL}{path}", headers=headers, **kwargs)

    if r.status_code == 401:
        cache.token = await tb_login(client)
        cache.ts = time.time()
        headers = {"X-Authorization": f"Bearer {cache.token}"}
        r = await client.request(method, f"{TB_URL}{path}", headers=headers, **kwargs)

    r.raise_for_status()
    return r


# -----------------------------
# FLOOR PARSER (b01-f10-r1020)
# -----------------------------
def parse_floor(topic: str) -> int | None:
    try:
        seg = topic.split("/")[2]
        if "f" not in seg:
            return None
        return int(seg.split("-")[1].replace("f", ""))
    except Exception:
        return None


# -----------------------------
# MQTT CLIENT (FIXED)
# -----------------------------
class MQTTManager:
    def __init__(self):
        self.client = gmqtt.Client(f"p3-floor-aggregator-{int(time.time())}")
        self.client.set_auth_credentials(HIVEMQ_USER, HIVEMQ_PASS)
        self.connected = asyncio.Event()
        self.stop = asyncio.Event()

        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message

        self.queue = defaultdict(lambda: deque(maxlen=200))

    # ---- lifecycle ----
    def on_connect(self, client, flags, rc, props):
        logger.info("MQTT connected rc=%s", rc)
        self.connected.set()
        client.subscribe(SUB_TOPIC, qos=1)

    def on_disconnect(self, client, packet, exc=None):
        logger.warning("MQTT disconnected")
        self.connected.clear()

    def on_message(self, client, topic, payload, qos, props):
        floor = parse_floor(topic)
        if floor is None:
            return

        try:
            data = json.loads(payload.decode())
        except Exception:
            return

        self.queue[floor].append((time.time(), data))

    # ---- safe connect loop ----
    async def connect_loop(self):
        while not self.stop.is_set():
            try:
                if not self.connected.is_set():
                    logger.info("Connecting MQTT %s:%s", HIVEMQ_HOST, HIVEMQ_PORT)
                    try:
                        await self.client.connect(HIVEMQ_HOST, HIVEMQ_PORT, keepalive=60)
                        await asyncio.sleep(1)
                    except Exception as e:
                        logger.warning("MQTT connect error: %s", e)
                        await asyncio.sleep(5)
                else:
                    await asyncio.sleep(5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("connect_loop error: %s", e)
                await asyncio.sleep(5)

    async def disconnect(self):
        self.stop.set()
        try:
            await self.client.disconnect()
        except Exception:
            pass


# -----------------------------
# MAIN LOOP
# -----------------------------
async def main():
    cache = TokenCache()

    async with httpx.AsyncClient(timeout=20) as tb:
        mqtt = MQTTManager()

        # start MQTT safely
        mqtt_task = asyncio.create_task(mqtt.connect_loop())

        assets = {}
        for floor_id in range(1, 11):
            name = f"Floor-{floor_id:02d}"
            try:
                resp = await tb_request(
                    tb,
                    cache,
                    "GET",
                    "/api/tenant/assets",
                    params={"pageSize": 100, "page": 0, "textSearch": name},
                )
                asset_id = exact_entity_id_from_page(
                    resp.json(),
                    expected_name=name,
                    entity_label="asset",
                )
                if asset_id:
                    assets[floor_id] = asset_id
                else:
                    logger.warning("Floor asset not found: %s", name)
            except EntityLookupError as e:
                logger.error("Ambiguous floor asset lookup for %s: %s", name, e)
            except Exception as e:
                logger.warning("Error resolving %s: %s", name, e)
        logger.info("Resolved %d floor assets", len(assets))

        try:
            while True:
                await asyncio.sleep(POST_EVERY_SECONDS)

                cutoff = time.time() - WINDOW_SECONDS

                for floor, queue in mqtt.queue.items():
                    values = [x[1].get("temperature") for x in queue if x[0] > cutoff]

                    if not values:
                        continue

                    summary = {
                        "avg_temperature": mean(values),
                        "samples": len(values),
                    }

                    try:
                        asset_id = assets.get(floor)
                        if not asset_id:
                            logger.warning("Skipping floor %s publish: missing exact floor asset mapping", floor)
                            continue
                        await tb_request(
                            tb,
                            cache,
                            "POST",
                            f"/api/plugins/telemetry/ASSET/{asset_id}/timeseries/ANY",
                            json=summary,
                        )
                    except Exception as e:
                        logger.warning("TB error: %s", e)

        except KeyboardInterrupt:
            logger.info("Shutting down...")

        finally:
            await mqtt.disconnect()
            await mqtt_task


if __name__ == "__main__":
    asyncio.run(main())
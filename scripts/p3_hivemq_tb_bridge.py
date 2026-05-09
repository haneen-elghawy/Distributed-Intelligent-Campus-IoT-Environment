"""HiveMQ -> ThingsBoard bridge using HTTP REST API (no per-device MQTT clients)."""
from __future__ import annotations
import asyncio, json, logging, os, time
import httpx, gmqtt
from dotenv import load_dotenv
load_dotenv(override=True)

logging.basicConfig(level="INFO", format="%(asctime)s | p3_bridge | %(levelname)s | %(message)s")
logger = logging.getLogger("p3_bridge")

TB_URL      = os.getenv("TB_URL", "http://localhost:9090").rstrip("/")
TB_USERNAME = os.getenv("TB_USERNAME", "").strip()
TB_PASSWORD = os.getenv("TB_PASSWORD", "").strip()
HIVEMQ_HOST = os.getenv("HIVEMQ_HOST", "localhost")
HIVEMQ_PORT = int(os.getenv("HIVEMQ_PORT", "1883"))
HIVEMQ_USER = os.getenv("HIVEMQ_USER", "").strip()
HIVEMQ_PASS = os.getenv("HIVEMQ_PASS", "").strip()

_tokens: dict[str, str] = {}   # room_key -> TB access token
_tb_token = {"token": "", "ts": 0.0}


def _load_registry():
    logger.info("Loading device tokens...")
    with httpx.Client(timeout=30) as http:
        r = http.post(f"{TB_URL}/api/auth/login",
                      json={"username": TB_USERNAME, "password": TB_PASSWORD})
        r.raise_for_status()
        tok = r.json()["token"]
        h = {"X-Authorization": f"Bearer {tok}"}
        page = 0
        while True:
            data = http.get(f"{TB_URL}/api/tenant/devices",
                            params={"pageSize": 100, "page": page},
                            headers=h).json()
            for dev in data["data"]:
                cred = http.get(f"{TB_URL}/api/device/{dev['id']['id']}/credentials",
                                headers=h).json().get("credentialsId")
                if cred:
                    _tokens[dev["name"]] = cred
            if not data.get("hasNext"):
                break
            page += 1
    logger.info("Loaded %d device tokens", len(_tokens))


async def _post_telemetry(session: httpx.AsyncClient, room_key: str, payload: dict):
    token = _tokens.get(room_key)
    if not token:
        return
    try:
        await session.post(
            f"{TB_URL}/api/v1/{token}/telemetry",
            json=payload,
            timeout=5,
        )
    except Exception as e:
        logger.warning("POST failed %s: %s", room_key, e)


class Bridge:
    def __init__(self):
        self.client = gmqtt.Client(f"p3-bridge-{int(time.time())}")
        self.client.set_auth_credentials(HIVEMQ_USER, HIVEMQ_PASS)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.connected = asyncio.Event()
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=5000)

    def _on_connect(self, client, flags, rc, props):
        logger.info("HiveMQ connected rc=%s", rc)
        self.connected.set()
        client.subscribe("campus/+/+/+/telemetry", qos=0)

    def _on_message(self, client, topic, payload, qos, props):
        parts = topic.split("/")
        if len(parts) != 5:
            return
        room_key = f"{parts[1]}-{parts[2]}-{parts[3]}"
        try:
            data = json.loads(payload)
        except Exception:
            return
        tb = {k: v for k, v in data.items()
              if k in ("temperature","humidity","occupancy","light_level",
                       "lighting_dimmer","hvac_mode","hvac_status","ts")}
        if tb:
            try:
                self._queue.put_nowait((room_key, tb))
            except asyncio.QueueFull:
                pass

    async def run(self):
        await self.client.connect(HIVEMQ_HOST, HIVEMQ_PORT, keepalive=60)
        await self.connected.wait()
        logger.info("Bridge listening — forwarding to ThingsBoard HTTP API")
        async with httpx.AsyncClient() as session:
            batch: dict[str, dict] = {}
            while True:
                deadline = time.time() + 2
                while time.time() < deadline:
                    try:
                        room_key, payload = self._queue.get_nowait()
                        batch[room_key] = payload
                    except asyncio.QueueEmpty:
                        await asyncio.sleep(0.05)
                if batch:
                    tasks = [_post_telemetry(session, k, v) for k, v in batch.items()]
                    await asyncio.gather(*tasks)
                    logger.info("Forwarded %d rooms to ThingsBoard", len(batch))
                    batch.clear()


async def main():
    if not TB_USERNAME or not TB_PASSWORD or not HIVEMQ_USER or not HIVEMQ_PASS:
        raise RuntimeError("Missing required credentials: TB_USERNAME/TB_PASSWORD/HIVEMQ_USER/HIVEMQ_PASS")
    _load_registry()
    bridge = Bridge()
    await bridge.run()

if __name__ == "__main__":
    asyncio.run(main())

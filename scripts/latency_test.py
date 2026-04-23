"""Measure MQTT command → telemetry RTT (ThingsBoard-style path via HiveMQ).

Records time from QoS 2 ``cmd`` publish until the matching ``hvac_mode`` appears on
``telemetry``. Alternates **ECO** / **HEATING** each iteration so each sample reflects a
state change (avoids counting stale telemetry).

**Note:** RTT includes the sim-engine tick interval. For sub-second RTT set a low
``PUBLISH_INTERVAL`` (e.g. ``1``) in ``.env`` before running the full stack.

Usage::
    python scripts/latency_test.py
    python scripts/latency_test.py --save docs/rtt_results.txt

Environment (optional)::
    LATENCY_BROKER, LATENCY_PORT, LATENCY_USER, LATENCY_PASS,
    LATENCY_CMD_TOPIC, LATENCY_TEL_TOPIC,
    LATENCY_ITERATIONS (default 20), LATENCY_GAP_S (default 2),
    RTT_TARGET_MS (default 500), LATENCY_WAIT_S (per-iteration timeout, default 30),
    MQTT_USE_TLS, HIVEMQ_CA_PATH (same as sim-engine when TLS enabled)
    LATENCY_MQTT_VERSION: "311" (default, MQTT 3.1.1) or "50" (MQTT 5.0) — use 311 if
    you see gmqtt log spam ``[TRYING WRITE TO CLOSED SOCKET]`` (broker often drops MQTT 5).
    LATENCY_BROKER: default ``127.0.0.1`` (on Windows prefer this over ``localhost`` if Docker binds IPv4 only).
    This script no longer falls back to ``HIVEMQ_BROKER`` from ``.env`` (that is ``hivemq`` for in-container use only).
    LATENCY_CMD_QOS: 1 (default) for reliable RTT with gmqtt+HiveMQ; 2 to match the course spec
    (QoS-2 command path) but may be less stable in this benchmark.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import ssl
import statistics
import sys
import time
import uuid
from pathlib import Path

from gmqtt import Client
from gmqtt.mqtt.constants import MQTTv311, MQTTv50

# Default to loopback. Do *not* use ``HIVEMQ_BROKER`` from .env here — that value is
# ``hivemq`` for containers only; on the host it does not resolve. Override with
# ``LATENCY_BROKER=127.0.0.1`` if needed (or if you run this script inside a container, use ``hivemq``).
BROKER = os.getenv("LATENCY_BROKER", "127.0.0.1")
PORT = int(os.getenv("LATENCY_PORT", os.getenv("HIVEMQ_PORT_PLAIN", "1883")))
USER = os.getenv("LATENCY_USER", "thingsboard")
PASSWORD = os.getenv("LATENCY_PASS", "tb_super_pass")
CMD_QOS = int(os.getenv("LATENCY_CMD_QOS", "1"))
CMD_TOPIC = os.getenv("LATENCY_CMD_TOPIC", "campus/b01/f01/r101/cmd")
TEL_TOPIC = os.getenv("LATENCY_TEL_TOPIC", "campus/b01/f01/r101/telemetry")
ITERATIONS = int(os.getenv("LATENCY_ITERATIONS", "20"))
GAP_S = float(os.getenv("LATENCY_GAP_S", "2"))
RTT_TARGET_MS = float(os.getenv("RTT_TARGET_MS", "500"))
WAIT_S = float(os.getenv("LATENCY_WAIT_S", "30"))


def _mqtt_version_from_env() -> int:
    """Default MQTT 3.1.1 for HiveMQ CE compatibility; gmqtt's default MQTT 5 can be dropped by broker."""
    v = (os.getenv("LATENCY_MQTT_VERSION", "311") or "311").strip().lower()
    if v in ("5", "50", "mqtt5", "v5", "mqtt_5"):
        return MQTTv50
    return MQTTv311


def _client_ok(client: Client) -> bool:
    """True if gmqtt client reports an active connection (``is_connected`` is a property on Client)."""
    try:
        return bool(client.is_connected)
    except Exception:  # noqa: BLE001
        return True


def _drain_queue(q: asyncio.Queue) -> None:
    while True:
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            return


async def run_latency_test(
    *,
    iterations: int,
    gap_s: float,
    save_path: Path | None,
    rtt_target_ms: float,
) -> list[float]:
    use_tls = os.getenv("MQTT_USE_TLS", "false").lower() == "true"
    if use_tls:
        port = int(os.getenv("LATENCY_PORT", os.getenv("HIVEMQ_PORT", "8883")))
    else:
        port = PORT

    q: asyncio.Queue[tuple[float, dict]] = asyncio.Queue()

    def on_message(cli: Client, topic: str, payload: bytes, qos: int, properties) -> int:
        if topic != TEL_TOPIC:
            return 0
        try:
            data = json.loads(payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return 0
        now = time.time()
        q.put_nowait((now, data))
        return 0

    # Disable gmqtt's infinite reconnect loop (stops "CAN'T RECONNECT" + socket spam on failure).
    client = Client("latency-tester-" + uuid.uuid4().hex[:20], clean_session=True)
    client.reconnect_retries = 0
    client.set_auth_credentials(USER, PASSWORD)
    client.on_message = on_message

    ssl_ctx = None
    if use_tls:
        ssl_ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        ca = os.getenv(
            "HIVEMQ_CA_PATH",
            str(Path(__file__).resolve().parent.parent / "hivemq" / "certs" / "ca.crt"),
        )
        ssl_ctx.load_verify_locations(ca)

    vnum = "5.0" if _mqtt_version_from_env() == MQTTv50 else "3.1.1"
    print(f"MQTT RTT: broker={BROKER}:{port} user={USER!r} version={vnum} cmd_qos={CMD_QOS} topics cmd={CMD_TOPIC!r} tel={TEL_TOPIC!r}", flush=True)

    await client.connect(
        BROKER,
        port,
        ssl=ssl_ctx if use_tls else False,
        keepalive=60,
        version=_mqtt_version_from_env(),
    )
    client.subscribe(TEL_TOPIC, qos=1)
    await asyncio.sleep(0.3)  # allow SUBACK / session to settle
    if not _client_ok(client):
        print(
            "Error: MQTT session closed immediately after connect/subscribe. "
            "Is HiveMQ running? Set LATENCY_MQTT_VERSION=311 if needed. Check: docker ps, docker logs campus-hivemq",
            file=sys.stderr,
        )
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass
        raise ConnectionError("HiveMQ session closed right after connect")

    results: list[float] = []
    lines: list[str] = []

    for i in range(iterations):
        if not _client_ok(client):
            err = (
                f"Error: broker closed the connection before/during iter {i + 1}. "
                f"If you saw gmqtt “[TRYING WRITE TO CLOSED SOCKET]”, set env LATENCY_MQTT_VERSION=311 "
                f"(default is now 311). Run `docker compose up -d` (hivemq + sim-engine). "
                f"Optional: LATENCY_USER=floor01 LATENCY_PASS=floor01pass. "
            )
            print(err, file=sys.stderr)
            lines.append(err.strip())
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass
            raise ConnectionError("MQTT no longer connected (see message above).")
        mode = "ECO" if i % 2 == 0 else "HEATING"
        _drain_queue(q)
        t0 = time.time()
        client.publish(
            CMD_TOPIC,
            json.dumps({"hvac_mode": mode, "target_temp": 22.0}),
            qos=2,
        )
        matched = False
        deadline = t0 + WAIT_S
        while time.time() < deadline:
            try:
                recv_t, data = await asyncio.wait_for(q.get(), timeout=max(0.1, deadline - time.time()))
            except asyncio.TimeoutError:
                break
            if data.get("hvac_mode") == mode:
                rtt_ms = (recv_t - t0) * 1000.0
                results.append(rtt_ms)
                line = f"iter {i + 1}/{iterations}  mode={mode}  RTT: {rtt_ms:.1f} ms"
                print(line)
                lines.append(line)
                matched = True
                break
        if not matched:
            warn = f"iter {i + 1}/{iterations}  mode={mode}  TIMEOUT (no matching telemetry within {WAIT_S}s)"
            print(warn, file=sys.stderr)
            lines.append(warn)

        if i < iterations - 1:
            await asyncio.sleep(gap_s)

    await client.disconnect()

    summary_lines: list[str] = []
    if results:
        summary_lines.extend(
            [
                "",
                f"=== RTT RESULTS ({len(results)}/{iterations} samples) ===",
                f"  Min:    {min(results):.1f} ms",
                f"  Max:    {max(results):.1f} ms",
                f"  Mean:   {statistics.mean(results):.1f} ms",
                f"  Median: {statistics.median(results):.1f} ms",
            ]
        )
        if len(results) > 1:
            summary_lines.append(f"  Stdev:  {statistics.stdev(results):.1f} ms")
        all_under = all(r < rtt_target_ms for r in results)
        summary_lines.append(
            f"  Target: all samples < {rtt_target_ms:.0f} ms — {'PASS' if all_under else 'FAIL'}"
        )
        summary_lines.append(
            f"  Target: max < {rtt_target_ms:.0f} ms — {'PASS' if max(results) < rtt_target_ms else 'FAIL'}"
        )
    else:
        summary_lines.append("No RTT samples collected — check broker, ACL, and sim-engine.")

    for s in summary_lines:
        print(s)
    lines.extend(summary_lines)

    if save_path:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\nWrote {save_path}")

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="MQTT cmd→telemetry RTT benchmark")
    parser.add_argument("--iterations", type=int, default=ITERATIONS)
    parser.add_argument("--gap", type=float, default=GAP_S, help="Seconds between iterations")
    parser.add_argument("--target-ms", type=float, default=RTT_TARGET_MS)
    parser.add_argument(
        "--save",
        type=Path,
        default=None,
        help="Append results to this file (e.g. docs/rtt_results.txt)",
    )
    args = parser.parse_args()

    # Hides gmqtt [TRYING WRITE TO CLOSED SOCKET] warnings unless you need deep MQTT debug.
    for _name in ("gmqtt", "gmqtt.mqtt.protocol", "gmqtt.mqtt.connection"):
        logging.getLogger(_name).setLevel(logging.ERROR)

    try:
        asyncio.run(
            run_latency_test(
                iterations=args.iterations,
                gap_s=args.gap,
                save_path=args.save,
                rtt_target_ms=args.target_ms,
            )
        )
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except (OSError, ConnectionError) as e:
        print(f"Connection error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

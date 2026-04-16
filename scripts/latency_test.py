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
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import ssl
import statistics
import sys
import time
from pathlib import Path

from gmqtt import Client

BROKER = os.getenv("LATENCY_BROKER", os.getenv("HIVEMQ_BROKER", "localhost"))
PORT = int(os.getenv("LATENCY_PORT", os.getenv("HIVEMQ_PORT_PLAIN", "1883")))
USER = os.getenv("LATENCY_USER", "thingsboard")
PASSWORD = os.getenv("LATENCY_PASS", "tb_super_pass")
CMD_TOPIC = os.getenv("LATENCY_CMD_TOPIC", "campus/b01/f01/r101/cmd")
TEL_TOPIC = os.getenv("LATENCY_TEL_TOPIC", "campus/b01/f01/r101/telemetry")
ITERATIONS = int(os.getenv("LATENCY_ITERATIONS", "20"))
GAP_S = float(os.getenv("LATENCY_GAP_S", "2"))
RTT_TARGET_MS = float(os.getenv("RTT_TARGET_MS", "500"))
WAIT_S = float(os.getenv("LATENCY_WAIT_S", "30"))


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

    client = Client("latency-tester-" + str(int(time.time())))
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

    await client.connect(BROKER, port, ssl=ssl_ctx if use_tls else False, keepalive=60)
    client.subscribe(TEL_TOPIC, qos=1)

    results: list[float] = []
    lines: list[str] = []

    for i in range(iterations):
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
    except OSError as e:
        print(f"Connection error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Phase 3.2 — OTA configuration publisher CLI.

Usage examples:
    python scripts/p3_ota_publisher.py --target broadcast --version 1.1 --alpha 0.02 --beta 0.6
    python scripts/p3_ota_publisher.py --target floor:05 --version 2.0 --alpha 0.03
    python scripts/p3_ota_publisher.py --target room:b01-f01-r101 --version 9.9 --alpha 0.99 --corrupt
    python scripts/p3_ota_publisher.py --target broadcast --version 1.1 --alpha 0.02 --alert-test
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import gmqtt
from src.engine.ota import sign_payload

HIVEMQ_HOST = os.getenv("HIVEMQ_HOST", "localhost")
HIVEMQ_PORT = int(os.getenv("HIVEMQ_PORT", "1883"))
BUILDING = "b01"


def topic_for_target(target):
    if target == "broadcast":
        return f"campus/{BUILDING}/ota/config"
    if target.startswith("floor:"):
        floor_part = target.split(":", 1)[1]
        try:
            floor_id = int(floor_part)
        except ValueError:
            sys.exit(f"invalid floor id: {floor_part!r}")
        return f"campus/{BUILDING}/f{floor_id:02d}/ota"
    if target.startswith("room:"):
        room_key = target.split(":", 1)[1]
        parts = room_key.split("-")
        if len(parts) != 3:
            sys.exit(f"invalid room key: {room_key!r}")
        return f"campus/{parts[0]}/{parts[1]}/{parts[2]}/ota"
    sys.exit(f"unknown target: {target!r}")


def build_payload(args):
    params = {}
    for name, value in [
        ("alpha", args.alpha), ("beta", args.beta),
        ("sensor_drift_rate", args.sensor_drift_rate),
        ("frozen_sensor_rate", args.frozen_sensor_rate),
        ("telemetry_delay_rate", args.telemetry_delay_rate),
        ("node_dropout_rate", args.node_dropout_rate),
    ]:
        if value is not None:
            params[name] = value
    if not params:
        sys.exit("no parameters supplied — use --alpha, --beta, etc.")
    return {"version": args.version, "params": params}


async def publish(topic, payload):
    client = gmqtt.Client(f"p3-ota-publisher-{os.getpid()}")
    await client.connect(HIVEMQ_HOST, HIVEMQ_PORT, keepalive=10)
    client.publish(topic, json.dumps(payload), qos=1)
    await asyncio.sleep(0.5)
    await client.disconnect()


def main():
    parser = argparse.ArgumentParser(description="Phase 3 OTA publisher")
    parser.add_argument("--target", required=True, help="broadcast | floor:NN | room:b01-fNN-rRRR")
    parser.add_argument("--version", required=True, help="config version label e.g. 1.1")
    parser.add_argument("--alpha", type=float)
    parser.add_argument("--beta", type=float)
    parser.add_argument("--sensor-drift-rate", type=float)
    parser.add_argument("--frozen-sensor-rate", type=float)
    parser.add_argument("--telemetry-delay-rate", type=float)
    parser.add_argument("--node-dropout-rate", type=float)
    parser.add_argument(
        "--corrupt",
        action="store_true",
        help="tamper with payload after signing (demonstrates hash mismatch)",
    )
    parser.add_argument(
        "--alert-test",
        action="store_true",
        help="[ALERT TEST] same as --corrupt but with clear test labeling",
    )
    args = parser.parse_args()

    topic = topic_for_target(args.target)
    payload = build_payload(args)
    signed = sign_payload(payload)

    if args.alert_test:
        print("[ALERT TEST] Sending tampered payload to trigger security alert pipeline")
        if "alpha" in signed["params"]:
            signed["params"]["alpha"] += 0.01
        else:
            signed["params"]["__alert_test__"] = True
    elif args.corrupt:
        print("[!] payload tampered AFTER signing — receiver should reject")
        if "alpha" in signed["params"]:
            signed["params"]["alpha"] += 0.01
        else:
            signed["params"]["__corrupted__"] = True

    print(f"topic  : {topic}")
    print(f"payload: {json.dumps(signed, indent=2)}")
    asyncio.run(publish(topic, signed))
    print("published.")


if __name__ == "__main__":
    main()


#!/usr/bin/env python3
"""Static verification that Phase 2 repository artifacts exist and import cleanly.

Does **not** start Docker or connect to HiveMQ/ThingsBoard — use after ``docker compose up``
for runtime proof (HiveMQ UI, logs, latency_test, etc.).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ERRORS: list[str] = []


def need(path: Path, label: str) -> None:
    if not path.exists():
        ERRORS.append(f"Missing {label}: {path.relative_to(ROOT)}")


def main() -> int:
    need(ROOT / "docker-compose.yml", "Docker Compose")
    need(ROOT / "hivemq" / "config" / "config.xml", "HiveMQ broker config")
    need(ROOT / "hivemq" / "extensions" / "hivemq-file-rbac-extension" / "conf" / "credentials.xml", "HiveMQ ACL")
    need(ROOT / "src" / "engine" / "runtime.py", "Runtime")
    need(ROOT / "src" / "nodes" / "mqtt_node.py", "MQTT nodes")
    need(ROOT / "src" / "coap" / "server.py", "CoAP servers")
    reg = ROOT / "thingsboard" / "campus_registry_export.json"
    if not reg.exists():
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "generate_campus_registry.py")],
            check=False,
            cwd=str(ROOT),
        )
    need(reg, "Registry export")
    need(ROOT / "thingsboard" / "rule_chain_campus_alarms.json", "Rule chain export (campus alarms)")
    need(ROOT / "thingsboard" / "rule_chain_root.json", "Rule chain export (root name for rubric)")
    need(ROOT / "thingsboard" / "uplink_converter_hivemq.js", "TB uplink converter")
    need(ROOT / "thingsboard" / "dashboard_campus_noc.json", "Campus NOC dashboard (Step 12)")
    need(ROOT / "scripts" / "provision_tb.py", "TB provision script")
    need(ROOT / "scripts" / "latency_test.py", "Latency benchmark")

    for i in range(1, 11):
        need(ROOT / "node-red" / f"gateway-f{i:02d}" / "flows.json", f"Node-RED floor {i:02d}")

    py_files = [
        ROOT / "src" / "engine" / "runtime.py",
        ROOT / "src" / "coap" / "alert_client.py",
        ROOT / "scripts" / "latency_test.py",
    ]
    for p in py_files:
        r = subprocess.run([sys.executable, "-m", "py_compile", str(p)], capture_output=True)
        if r.returncode != 0:
            ERRORS.append(f"py_compile failed: {p.relative_to(ROOT)}")

    if ERRORS:
        print("FAILED:", file=sys.stderr)
        for e in ERRORS:
            print(" ", e, file=sys.stderr)
        return 1

    print("OK - all required Phase 2 paths present.")
    print("  Next: docker compose up -d")
    print("  Then: python scripts/generate_campus_registry.py (if JSON missing)")
    print("  Then: python scripts/latency_test.py --save docs/rtt_results.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

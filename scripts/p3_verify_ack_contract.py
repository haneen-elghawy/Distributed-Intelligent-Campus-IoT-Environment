#!/usr/bin/env python3
"""Verify ACK contract readiness (canonical + legacy migration policy).

Checks:
1) Node-RED generator contains canonical `/response` + legacy `/cmd-response` topics
2) Generator ACK payload includes required canonical fields
3) All generated gateway flows include canonical `/response` references
4) Shadow sync parser accepts/rejects payloads according to policy
"""
from __future__ import annotations

import json
from pathlib import Path

import p3_shadow_sync as shadow_sync

ROOT = Path(__file__).resolve().parent.parent
GENERATOR = ROOT / "node-red" / "generate_gateway_flows.py"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _verify_generator_contract() -> None:
    text = GENERATOR.read_text(encoding="utf-8")
    _require("/response" in text, "Generator missing canonical /response topic")
    _require("/cmd-response" in text, "Generator missing legacy /cmd-response fallback")
    for field in ("cmd_id", "correlation_id", "room_id", "status", "timestamp"):
        _require(field in text, f"Generator missing canonical ACK field: {field}")


def _verify_generated_flows() -> None:
    for i in range(1, 11):
        p = ROOT / "node-red" / f"gateway-f{i:02d}" / "flows.json"
        txt = p.read_text(encoding="utf-8")
        _require("/response" in txt, f"{p} missing canonical /response contract")
        _require("/cmd-response" in txt, f"{p} missing legacy fallback /cmd-response")


def _verify_shadow_sync_parser() -> None:
    # Build a minimal object without running __init__ (avoids env/network coupling).
    client = shadow_sync.ShadowSyncClient.__new__(shadow_sync.ShadowSyncClient)
    client.pending_by_room = {
        "b01-f01-r101": shadow_sync.PendingCommand(
            room_key="b01-f01-r101",
            cmd_id="cmd-1",
            correlation_id="corr-1",
            desired={},
        )
    }

    canonical_ok = {
        "cmd_id": "cmd-1",
        "correlation_id": "corr-1",
        "room_id": "b01-f01-r101",
        "status": "ok",
        "timestamp": 1710000000000,
    }
    parsed = client._parse_canonical_ack(canonical_ok)
    _require(parsed is not None, "Canonical ACK parser rejected valid payload")

    canonical_bad = {
        "correlation_id": "corr-1",
        "room_id": "b01-f01-r101",
        "status": "ok",
        "timestamp": 1710000000000,
    }
    parsed_bad = client._parse_canonical_ack(canonical_bad)
    _require(parsed_bad is None, "Canonical ACK parser accepted invalid payload (missing cmd_id)")

    legacy_ok = {"ok": True, "ts": 1710000000000}
    parsed_legacy = client._parse_legacy_ack(legacy_ok, "campus/b01/f01/r101/cmd-response")
    _require(parsed_legacy is not None, "Legacy fallback parser rejected valid fallback payload")

    legacy_bad = {"ts": 1710000000000}
    parsed_legacy_bad = client._parse_legacy_ack(legacy_bad, "campus/b01/f01/r101/cmd-response")
    _require(parsed_legacy_bad is None, "Legacy fallback parser accepted invalid payload without ok flag")


def main() -> None:
    _verify_generator_contract()
    _verify_generated_flows()
    _verify_shadow_sync_parser()
    print("PASS: ACK contract verification succeeded.")


if __name__ == "__main__":
    main()

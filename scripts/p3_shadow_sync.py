#!/usr/bin/env python3
"""Command shadow/sync client with canonical ACK validation.

Primary contract:
  - subscribe: campus/b01/+/+/response
  - expect strict payload fields:
      cmd_id, correlation_id, room_id, status, timestamp

Legacy transition fallback:
  - subscribe: campus/b01/+/+/cmd-response
  - accept weaker payload shape only as fallback.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gmqtt import Client
from campus_naming import parse_room_key


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _now_ms() -> int:
    return int(time.time() * 1000)


def _cmd_topic(room_key: str) -> str:
    building, floor, room = parse_room_key(room_key)
    return f"campus/{building}/{floor}/{room}/cmd"


def _sync_topic(room_key: str) -> str:
    building, floor, room = parse_room_key(room_key)
    return f"campus/{building}/{floor}/{room}/sync-status"


@dataclass
class PendingCommand:
    room_key: str
    cmd_id: str
    correlation_id: str
    desired: dict[str, Any]
    event: asyncio.Event = field(default_factory=asyncio.Event)
    ack: dict[str, Any] | None = None


class ShadowSyncClient:
    def __init__(self) -> None:
        self.broker = _require_env("HIVEMQ_BROKER")
        self.port = int(_require_env("HIVEMQ_PORT"))
        self.max_retries = int(os.getenv("SYNC_MAX_RETRIES", "2"))
        self.ack_timeout_seconds = float(os.getenv("SYNC_ACK_TIMEOUT_SECONDS", "6"))
        self.state_path = Path(os.getenv("SYNC_STATE_PATH", "data/shadow_sync_state.json"))
        self.publish_sync_status = os.getenv("SYNC_PUBLISH_STATUS", "true").lower() in ("1", "true", "yes")
        self.client_id = os.getenv("SYNC_CLIENT_ID", f"shadow-sync-{uuid.uuid4().hex[:8]}")
        self.username = os.getenv("HIVEMQ_USER", "").strip() or None
        self.password = os.getenv("HIVEMQ_PASS", "").strip() or None
        self.pending_by_cmd: dict[str, PendingCommand] = {}
        self.pending_by_room: dict[str, PendingCommand] = {}
        self.state = self._load_state()
        self.client = Client(self.client_id)
        if self.username:
            self.client.set_auth_credentials(self.username, self.password)
        self.client.on_message = self._on_message

    def _load_state(self) -> dict[str, Any]:
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {"rooms": {}}
        return {"rooms": {}}

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, indent=2) + "\n", encoding="utf-8")

    def _upsert_room_state(self, room_key: str, patch: dict[str, Any]) -> None:
        rooms = self.state.setdefault("rooms", {})
        rec = rooms.setdefault(
            room_key,
            {
                "desired_version": 0,
                "reported_version": 0,
                "sync_status": "UNKNOWN",
                "last_seen": None,
            },
        )
        rec.update(patch)
        self._save_state()

    async def connect(self) -> None:
        await self.client.connect(self.broker, self.port)
        self.client.subscribe("campus/b01/+/+/response", qos=1)
        self.client.subscribe("campus/b01/+/+/cmd-response", qos=1)

    async def disconnect(self) -> None:
        await self.client.disconnect()

    def _on_message(self, client: Client, topic: str, payload: bytes, qos: int, properties: Any) -> int:
        del client, qos, properties
        if isinstance(topic, bytes):
            topic = topic.decode()
        raw_payload = payload.decode() if isinstance(payload, bytes) else str(payload)
        try:
            body = json.loads(raw_payload)
        except json.JSONDecodeError:
            return 0

        is_canonical = topic.endswith("/response")
        ack = self._parse_canonical_ack(body) if is_canonical else self._parse_legacy_ack(body, topic)
        if ack is None:
            return 0

        pending = self.pending_by_cmd.get(str(ack["cmd_id"])) if ack.get("cmd_id") else None
        if pending is None:
            pending = self.pending_by_room.get(str(ack["room_id"]))
        if pending is None:
            return 0

        pending.ack = ack
        pending.event.set()
        return 0

    def _parse_canonical_ack(self, body: dict[str, Any]) -> dict[str, Any] | None:
        required = ("cmd_id", "correlation_id", "room_id", "status", "timestamp")
        if not all(k in body for k in required):
            return None
        if not isinstance(body["cmd_id"], (str, int)):
            return None
        if not isinstance(body["correlation_id"], (str, int)):
            return None
        if not isinstance(body["room_id"], str):
            return None
        if body["status"] not in ("ok", "error", "timeout", "rejected"):
            return None
        if not isinstance(body["timestamp"], (int, float)):
            return None
        ack = {
            "contract": "canonical",
            "cmd_id": str(body["cmd_id"]),
            "correlation_id": str(body["correlation_id"]),
            "room_id": body["room_id"],
            "status": body["status"],
            "timestamp": int(body["timestamp"]),
            "coap_status": body.get("coap_status"),
            "applied_actuators": body.get("applied_actuators", {}),
        }
        return ack

    def _parse_legacy_ack(self, body: dict[str, Any], topic: str) -> dict[str, Any] | None:
        """Legacy fallback parser; weaker schema accepted only in migration window."""
        if not isinstance(body.get("ok"), bool):
            return None

        parts = topic.split("/")
        if len(parts) < 5:
            return None
        room_id = f"b01-{parts[2]}-{parts[3]}"
        pending = self.pending_by_room.get(room_id)
        cmd_id = str(body.get("cmd_id") or (pending.cmd_id if pending else ""))
        correlation_id = str(body.get("correlation_id") or (pending.correlation_id if pending else cmd_id))
        if not cmd_id or not correlation_id:
            return None

        ts = body.get("timestamp", body.get("ts", _now_ms()))
        return {
            "contract": "legacy",
            "cmd_id": cmd_id,
            "correlation_id": correlation_id,
            "room_id": body.get("room_id", room_id),
            "status": "ok" if body["ok"] else "error",
            "timestamp": int(ts),
            "coap_status": body.get("coap_status"),
            "applied_actuators": {},
        }

    async def sync_desired(self, room_key: str, desired: dict[str, Any]) -> dict[str, Any]:
        # Track desired state for dashboards/debugging.
        rec = self.state.setdefault("rooms", {}).setdefault(room_key, {})
        desired_version = int(rec.get("desired_version", 0)) + 1
        desired_patch = {f"desired_{k}": v for k, v in desired.items()}
        self._upsert_room_state(
            room_key,
            {
                **desired_patch,
                "desired_version": desired_version,
                "sync_status": "PENDING",
                "last_seen": _now_ms(),
            },
        )

        cmd_topic = _cmd_topic(room_key)
        sync_topic = _sync_topic(room_key)
        last_ack: dict[str, Any] | None = None
        for attempt in range(1, self.max_retries + 2):
            cmd_id = uuid.uuid4().hex
            correlation_id = uuid.uuid4().hex
            payload = dict(desired)
            payload["cmd_id"] = cmd_id
            payload["correlation_id"] = correlation_id

            pending = PendingCommand(
                room_key=room_key,
                cmd_id=cmd_id,
                correlation_id=correlation_id,
                desired=desired,
            )
            self.pending_by_cmd[pending.cmd_id] = pending
            self.pending_by_room[pending.room_key] = pending

            self.client.publish(cmd_topic, json.dumps(payload), qos=1)

            try:
                await asyncio.wait_for(pending.event.wait(), timeout=self.ack_timeout_seconds)
            except asyncio.TimeoutError:
                self.pending_by_cmd.pop(pending.cmd_id, None)
                if self.pending_by_room.get(room_key) is pending:
                    self.pending_by_room.pop(room_key, None)
                if attempt > self.max_retries:
                    self._upsert_room_state(
                        room_key,
                        {
                            "sync_status": "OUT_OF_SYNC",
                            "last_seen": _now_ms(),
                            "last_error": "ack_timeout",
                        },
                    )
                    return {"ok": False, "error": "ack_timeout", "attempts": attempt}
                continue

            self.pending_by_cmd.pop(pending.cmd_id, None)
            if self.pending_by_room.get(room_key) is pending:
                self.pending_by_room.pop(room_key, None)

            ack = pending.ack or {}
            last_ack = ack
            ok = ack.get("status") == "ok"
            if ok:
                reported_patch: dict[str, Any] = {}
                applied = ack.get("applied_actuators") or {}
                source_reported = applied if applied else desired
                for k, v in source_reported.items():
                    reported_patch[f"reported_{k}"] = v

                latest_rec = self.state.setdefault("rooms", {}).setdefault(room_key, {})
                reported_version = int(latest_rec.get("reported_version", 0)) + 1
                update = {
                    **reported_patch,
                    "reported_version": reported_version,
                    "sync_status": "IN_SYNC",
                    "last_seen": int(ack.get("timestamp", _now_ms())),
                    "last_ack_contract": ack.get("contract"),
                    "last_ack_topic": "response" if ack.get("contract") == "canonical" else "cmd-response",
                }
                self._upsert_room_state(room_key, update)

                if self.publish_sync_status:
                    self.client.publish(sync_topic, json.dumps({"room_id": room_key, **update}), qos=1, retain=True)
                return {"ok": True, "ack": ack, "attempts": attempt}

            if attempt > self.max_retries:
                self._upsert_room_state(
                    room_key,
                    {
                        "sync_status": "OUT_OF_SYNC",
                        "last_seen": int(ack.get("timestamp", _now_ms())),
                        "last_error": "ack_error",
                        "last_ack_contract": ack.get("contract"),
                    },
                )
                return {"ok": False, "error": "ack_error", "ack": ack, "attempts": attempt}

        return {"ok": False, "error": "unexpected", "ack": last_ack}


async def _run_once(args: argparse.Namespace) -> int:
    client = ShadowSyncClient()
    desired: dict[str, Any] = {}
    if args.hvac_mode is not None:
        desired["hvac_mode"] = args.hvac_mode
    if args.target_temp is not None:
        desired["target_temp"] = args.target_temp
    if args.lighting_dimmer is not None:
        desired["lighting_dimmer"] = args.lighting_dimmer
    if not desired:
        raise RuntimeError("No desired actuator values provided.")

    await client.connect()
    try:
        result = await client.sync_desired(args.room, desired)
    finally:
        await client.disconnect()

    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Shadow/sync command dispatcher with ACK validation")
    p.add_argument("--room", required=True, help="Canonical room key: b01-fNN-rRRR")
    p.add_argument("--hvac-mode", help="Desired hvac mode")
    p.add_argument("--target-temp", type=float, help="Desired target temperature")
    p.add_argument("--lighting-dimmer", type=int, help="Desired lighting dimmer [0..100]")
    return p


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    return asyncio.run(_run_once(args))


if __name__ == "__main__":
    raise SystemExit(main())

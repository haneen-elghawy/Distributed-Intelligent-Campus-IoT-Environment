"""Phase 3.2 — OTA configuration application + SHA-256 verification."""

import hmac
import hashlib
import json
import logging
import os
import time
import uuid

logger = logging.getLogger("engine.ota")
SIGNING_KEY = os.getenv("OTA_SIGNING_KEY", "dev-ota-signing-key-change-me").encode("utf-8")
MAX_AGE_SECONDS = int(os.getenv("OTA_MAX_AGE_SECONDS", "600"))

APPLICABLE_PARAMS = {
    "alpha", "beta",
    "sensor_drift_rate", "frozen_sensor_rate",
    "telemetry_delay_rate", "node_dropout_rate",
    "sensor_drift_step_max",
    "telemetry_delay_min_seconds", "telemetry_delay_max_seconds",
}


def canonical_hash(data):
    clean = {k: v for k, v in data.items() if k != "_sig"} if isinstance(data, dict) else data
    blob = json.dumps(clean, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def canonical_hmac(data):
    clean = {k: v for k, v in data.items() if k not in ("_sig", "_hmac")} if isinstance(data, dict) else data
    blob = json.dumps(clean, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(SIGNING_KEY, blob, hashlib.sha256).hexdigest()


def sign_payload(data):
    out = {k: v for k, v in data.items() if k not in ("_sig", "_hmac")}
    out.setdefault("issued_at", int(time.time()))
    out.setdefault("nonce", uuid.uuid4().hex)
    out["_sig"] = canonical_hash(out)
    out["_hmac"] = canonical_hmac(out)
    return out


def verify_payload(data):
    if not isinstance(data, dict):
        return False, "payload not a dict"
    sig = data.get("_sig")
    if not sig:
        return False, "missing _sig"
    expected = canonical_hash(data)
    if sig != expected:
        return False, f"hash mismatch (got {sig[:8]}.., expected {expected[:8]}..)"
    mac = data.get("_hmac")
    if not mac:
        return False, "missing _hmac"
    expected_hmac = canonical_hmac(data)
    if not hmac.compare_digest(str(mac), expected_hmac):
        return False, "hmac mismatch"
    if "version" not in data:
        return False, "missing version"
    if "params" not in data or not isinstance(data["params"], dict):
        return False, "missing or invalid params"
    issued_at = data.get("issued_at")
    if not isinstance(issued_at, (int, float)):
        return False, "missing or invalid issued_at"
    age = time.time() - float(issued_at)
    if age < -60 or age > MAX_AGE_SECONDS:
        return False, f"stale update age={age:.1f}s"
    nonce = data.get("nonce")
    if not isinstance(nonce, str) or not nonce.strip():
        return False, "missing nonce"
    return True, "ok"


def topic_targets_room(topic, room):
    parts = topic.split("/")
    if len(parts) < 3 or parts[0] != "campus":
        return False
    if parts[1] != room.building_id:
        return False
    # broadcast: campus/b01/ota/config
    if len(parts) == 4 and parts[2] == "ota" and parts[3] == "config":
        return True
    # floor: campus/b01/fNN/ota
    if len(parts) == 4 and parts[3] == "ota":
        try:
            return int(parts[2][1:]) == room.floor_id
        except ValueError:
            return False
    # single room: campus/b01/fNN/rRRR/ota
    if len(parts) == 5 and parts[4] == "ota":
        try:
            floor_id = int(parts[2][1:])
            room_number = int(parts[3][1:])
        except ValueError:
            return False
        return floor_id == room.floor_id and room_number == (room.floor_id * 100 + room.room_id)
    return False


def apply_to_room(room, payload, topic="<unknown>"):
    ok, reason = verify_payload(payload)
    if not ok:
        logger.warning("OTA REJECTED on %s topic=%s: %s", room.room_key, topic, reason)
        return {"applied": {}, "rejected": True, "reason": reason}

    params = payload.get("params", {})
    applied = {}
    skipped = []
    for key, value in params.items():
        if key not in APPLICABLE_PARAMS:
            skipped.append(key)
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            skipped.append(key)
            continue
        setattr(room, key, value)
        applied[key] = value

    new_version = str(payload.get("version", "?"))
    setattr(room, "config_version", new_version)
    applied["config_version"] = new_version

    logger.info("OTA APPLIED on %s version=%s applied=%s", room.room_key, new_version, applied)
    return {
        "applied": applied, "skipped": skipped,
        "rejected": False, "version": new_version,
        "applied_at": int(time.time()),
    }


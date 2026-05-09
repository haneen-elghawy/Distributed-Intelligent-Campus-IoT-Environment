"""Repair room asset naming drift for Phase 3 metadata compatibility.

Standard room asset name is: b01-fNN-rRRR
Legacy variant supported by this repair: Room-b01-fNN-rRRR
"""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass

import httpx
from campus_naming import canonicalize_legacy_room_name, is_canonical_room_key
from dotenv import load_dotenv

load_dotenv(override=True)

TB_URL = os.getenv("TB_URL", "http://localhost:9090").rstrip("/")
TB_USERNAME = os.getenv("TB_USERNAME", "").strip()
TB_PASSWORD = os.getenv("TB_PASSWORD", "").strip()

def _headers(token: str) -> dict[str, str]:
    return {"X-Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"}


@dataclass
class RenamePlan:
    asset_id: str
    old_name: str
    new_name: str


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _build_rename_plan(client: httpx.Client, token: str) -> list[RenamePlan]:
    plan: list[RenamePlan] = []
    page = 0
    while True:
        r = client.get(
            f"{TB_URL}/api/tenant/assets",
            params={"pageSize": 100, "page": page, "textSearch": "Room-"},
            headers=_headers(token),
        )
        r.raise_for_status()
        data = r.json()
        for item in data.get("data", []):
            old_name = str(item.get("name", "")).strip()
            canonical = canonicalize_legacy_room_name(old_name)
            if not canonical:
                continue
            if not is_canonical_room_key(canonical):
                continue
            plan.append(
                RenamePlan(
                    asset_id=item["id"]["id"],
                    old_name=old_name,
                    new_name=canonical,
                )
            )
        if not data.get("hasNext"):
            break
        page += 1
    return plan


def _apply_plan(client: httpx.Client, token: str, plan: list[RenamePlan]) -> int:
    renamed = 0
    for step in plan:
        get_resp = client.get(f"{TB_URL}/api/asset/{step.asset_id}", headers=_headers(token))
        get_resp.raise_for_status()
        body = get_resp.json()
        body["name"] = step.new_name
        update_resp = client.post(f"{TB_URL}/api/asset", json=body, headers=_headers(token))
        update_resp.raise_for_status()
        renamed += 1
        print(f"  [renamed] {step.old_name} -> {step.new_name}")
    return renamed


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair legacy Room- prefixed asset names")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview renames only (default)")
    mode.add_argument("--apply", action="store_true", help="Apply renames in ThingsBoard")
    args = parser.parse_args()

    apply_changes = args.apply
    if not TB_USERNAME or not TB_PASSWORD:
        raise RuntimeError("Missing TB_USERNAME/TB_PASSWORD")
    _required_env("TB_USERNAME")
    _required_env("TB_PASSWORD")

    with httpx.Client(timeout=30) as client:
        login = client.post(
            f"{TB_URL}/api/auth/login",
            json={"username": TB_USERNAME, "password": TB_PASSWORD},
        )
        login.raise_for_status()
        token = login.json()["token"]
        plan = _build_rename_plan(client, token)
        print(f"detected {len(plan)} legacy room asset(s)")
        for step in plan:
            print(f"  [plan] {step.old_name} -> {step.new_name}")

        if not apply_changes:
            print("dry-run complete (no changes applied). Use --apply to execute renames.")
            return

        renamed = _apply_plan(client, token, plan)
    print(f"apply complete: renamed {renamed} legacy room assets")


if __name__ == "__main__":
    main()

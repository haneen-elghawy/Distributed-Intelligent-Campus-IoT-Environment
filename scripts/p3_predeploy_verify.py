#!/usr/bin/env python3
"""Run final-mile verifiers and produce one pass/fail signal."""
from __future__ import annotations

import subprocess
import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(script: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script)],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
    )
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    combined = "\n".join(x for x in (out, err) if x).strip()
    return proc.returncode, combined


def _run_metadata_with_fallback() -> tuple[int, str]:
    code, output = _run("p3_verify_metadata.py")
    if code == 0:
        return code, output

    tb_user = os.getenv("TB_USERNAME", "tenant@thingsboard.org")
    tb_pass = os.getenv("TB_PASSWORD", "tenant")
    fallback = subprocess.run(
        [
            "docker",
            "exec",
            "-e",
            "TB_URL=http://thingsboard:9090",
            "-e",
            f"TB_USERNAME={tb_user}",
            "-e",
            f"TB_PASSWORD={tb_pass}",
            "campus-sim-engine",
            "python",
            "scripts/p3_verify_metadata.py",
        ],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
    )
    out = (fallback.stdout or "").strip()
    err = (fallback.stderr or "").strip()
    combined = "\n".join(x for x in (out, err) if x).strip()
    if fallback.returncode == 0:
        note = "Host metadata check failed, Docker-network fallback passed."
        merged = "\n".join(x for x in (note, output, combined) if x).strip()
        return 0, merged
    merged = "\n".join(x for x in (output, combined) if x).strip()
    return fallback.returncode, merged


def main() -> int:
    checks = [
        ("Metadata verifier", "p3_verify_metadata.py"),
        ("ACK contract verifier", "p3_verify_ack_contract.py"),
    ]
    failures: list[str] = []
    print("Pre-deploy readiness verification:")
    for title, script in checks:
        if script == "p3_verify_metadata.py":
            code, output = _run_metadata_with_fallback()
        else:
            code, output = _run(script)
        status = "PASS" if code == 0 else "FAIL"
        print(f"- {title}: {status}")
        if output:
            print(output)
        if code != 0:
            failures.append(f"{title} failed")

    if failures:
        print("FINAL: FAIL")
        for f in failures:
            print(f"- {f}")
        return 1
    print("FINAL: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

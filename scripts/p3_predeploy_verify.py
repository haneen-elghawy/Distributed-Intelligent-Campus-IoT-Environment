#!/usr/bin/env python3
"""Run final-mile verifiers and produce one pass/fail signal."""
from __future__ import annotations

import subprocess
import sys
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


def main() -> int:
    checks = [
        ("Metadata verifier", "p3_verify_metadata.py"),
        ("ACK contract verifier", "p3_verify_ack_contract.py"),
    ]
    failures: list[str] = []
    print("Pre-deploy readiness verification:")
    for title, script in checks:
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

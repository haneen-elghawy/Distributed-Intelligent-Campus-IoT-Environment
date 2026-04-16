"""Generates self-signed CA + server cert for HiveMQ if they don't exist."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CERTS_DIR = _REPO_ROOT / "hivemq" / "certs"


def generate_certs() -> None:
    CERTS_DIR.mkdir(parents=True, exist_ok=True)
    ca_key = CERTS_DIR / "ca.key"
    ca_crt = CERTS_DIR / "ca.crt"
    srv_key = CERTS_DIR / "hivemq.key"
    srv_p12 = CERTS_DIR / "hivemq.p12"

    if srv_p12.exists():
        print("[certs] Already generated — skipping.")
        return

    subprocess.run(
        ["openssl", "genrsa", "-out", str(ca_key), "4096"],
        check=True,
    )
    subprocess.run(
        [
            "openssl",
            "req",
            "-new",
            "-x509",
            "-days",
            "3650",
            "-key",
            str(ca_key),
            "-out",
            str(ca_crt),
            "-subj",
            "/C=EG/ST=Cairo/O=Campus IoT/CN=Campus CA",
        ],
        check=True,
    )
    subprocess.run(
        ["openssl", "genrsa", "-out", str(srv_key), "2048"],
        check=True,
    )
    csr = CERTS_DIR / "hivemq.csr"
    subprocess.run(
        [
            "openssl",
            "req",
            "-new",
            "-key",
            str(srv_key),
            "-out",
            str(csr),
            "-subj",
            "/C=EG/ST=Cairo/O=Campus IoT/CN=hivemq",
        ],
        check=True,
    )
    crt = CERTS_DIR / "hivemq.crt"
    subprocess.run(
        [
            "openssl",
            "x509",
            "-req",
            "-days",
            "825",
            "-in",
            str(csr),
            "-CA",
            str(ca_crt),
            "-CAkey",
            str(ca_key),
            "-CAcreateserial",
            "-out",
            str(crt),
        ],
        check=True,
    )
    subprocess.run(
        [
            "openssl",
            "pkcs12",
            "-export",
            "-in",
            str(crt),
            "-inkey",
            str(srv_key),
            "-CAfile",
            str(ca_crt),
            "-name",
            "hivemq",
            "-out",
            str(srv_p12),
            "-passout",
            "pass:hivemq_keystore_pass",
        ],
        check=True,
    )
    print("[certs] Generated successfully.")


if __name__ == "__main__":
    try:
        generate_certs()
    except FileNotFoundError:
        print("[certs] openssl not found — install OpenSSL and retry.", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"[certs] openssl failed with exit {e.returncode}.", file=sys.stderr)
        sys.exit(e.returncode)

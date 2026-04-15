"""
src/security/cert_gen.py
Self-signed X.509 certificate generation helper.

Generates a CA certificate + a server leaf certificate signed by that CA.
Useful for local HiveMQ TLS testing without an external PKI.

Usage (CLI):
    python -m src.security.cert_gen --out-dir certs/

Usage (Python):
    from src.security.cert_gen import generate_self_signed_bundle
    ca_cert, ca_key, srv_cert, srv_key = generate_self_signed_bundle(out_dir="certs")
"""
from __future__ import annotations

import argparse
import datetime
import ipaddress
import logging
import os
from pathlib import Path
from typing import Tuple

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.x509.oid import NameOID

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------
CertKeyPair = Tuple[x509.Certificate, RSAPrivateKey]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ONE_DAY = datetime.timedelta(days=1)
_VALIDITY = datetime.timedelta(days=365)


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _new_rsa_key(key_size: int = 2048) -> RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=key_size)


def _build_name(cn: str, org: str = "Campus IoT") -> x509.Name:
    return x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, org),
        x509.NameAttribute(NameOID.COMMON_NAME, cn),
    ])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_ca() -> CertKeyPair:
    """Generate a self-signed Root CA certificate + private key."""
    key = _new_rsa_key()
    now = _utcnow()
    name = _build_name("Campus IoT Root CA")
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _ONE_DAY)
        .not_valid_after(now + _VALIDITY)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    return cert, key


def generate_server_cert(
    ca_cert: x509.Certificate,
    ca_key: RSAPrivateKey,
    hostname: str = "hivemq",
) -> CertKeyPair:
    """Generate a server leaf certificate signed by *ca_cert*.

    Parameters
    ----------
    ca_cert:
        The CA certificate returned by :func:`generate_ca`.
    ca_key:
        The CA private key returned by :func:`generate_ca`.
    hostname:
        The DNS hostname (and/or IP SAN) to embed in the certificate.
        Matches the ``HIVEMQ_BROKER`` env var by default.
    """
    key = _new_rsa_key()
    now = _utcnow()
    san_list: list[x509.GeneralName] = [x509.DNSName(hostname)]
    # Also embed 127.0.0.1 so local tests pass
    san_list.append(x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")))

    cert = (
        x509.CertificateBuilder()
        .subject_name(_build_name(hostname))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _ONE_DAY)
        .not_valid_after(now + _VALIDITY)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName(san_list), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )
    return cert, key


def _write_pem(path: Path, obj) -> None:
    if isinstance(obj, x509.Certificate):
        data = obj.public_bytes(serialization.Encoding.PEM)
    else:  # RSAPrivateKey
        data = obj.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    path.write_bytes(data)
    logger.info("Written  %s", path)


def generate_self_signed_bundle(
    out_dir: str | os.PathLike = "certs",
    hostname: str | None = None,
) -> tuple[x509.Certificate, RSAPrivateKey, x509.Certificate, RSAPrivateKey]:
    """Generate and persist a complete CA + server certificate bundle.

    Returns ``(ca_cert, ca_key, server_cert, server_key)``.
    """
    hostname = hostname or os.getenv("HIVEMQ_BROKER", "hivemq")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    ca_cert, ca_key = generate_ca()
    srv_cert, srv_key = generate_server_cert(ca_cert, ca_key, hostname)

    _write_pem(out / "ca.crt", ca_cert)
    _write_pem(out / "ca.key", ca_key)
    _write_pem(out / "server.crt", srv_cert)
    _write_pem(out / "server.key", srv_key)

    return ca_cert, ca_key, srv_cert, srv_key


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _cli() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a self-signed CA + server certificate bundle."
    )
    parser.add_argument(
        "--out-dir",
        default="certs",
        help="Directory to write PEM files (default: certs/)",
    )
    parser.add_argument(
        "--hostname",
        default=None,
        help="Server hostname / SAN (default: $HIVEMQ_BROKER or 'hivemq')",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    generate_self_signed_bundle(out_dir=args.out_dir, hostname=args.hostname)


if __name__ == "__main__":
    _cli()

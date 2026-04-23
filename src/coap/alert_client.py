"""CON (Confirmable) CoAP POST client for sentinel alerts to a floor gateway."""
from __future__ import annotations

import json
import logging
import os
import time

import aiocoap
import aiocoap.credentials as credentials
from aiocoap import Code, Context, Message

logger = logging.getLogger("coap.alert_client")
_COAP_DTLS_CLIENT_TRANSPORT = "tinydtls"


async def send_coap_alert(
    gateway_host: str,
    gateway_coap_port: int,
    floor_id: int,
    room_id: int,
    alert_type: str,
    value: object,
) -> None:
    """Send a Confirmable CoAP POST alert to ``coap://host:port/alerts``.

    aiocoap uses CON by default for client requests. The floor gateway must
    expose a POST handler at ``/alerts`` (e.g. Node-RED **coap in**).
    """
    scheme = os.getenv("COAP_ALERT_SCHEME", "coap").strip().lower() or "coap"
    use_dtls = scheme == "coaps"
    if use_dtls:
        available = list(aiocoap.defaults.get_default_clienttransports())
        if _COAP_DTLS_CLIENT_TRANSPORT not in available:
            raise RuntimeError(
                "COAP_ALERT_SCHEME=coaps but DTLS client backend is unavailable. "
                f"Expected transport '{_COAP_DTLS_CLIENT_TRANSPORT}' in {available}."
            )
        protocol = await Context.create_client_context(
            transports=[_COAP_DTLS_CLIENT_TRANSPORT]
        )
        psk_identity = os.getenv("COAP_DTLS_IDENTITY", "gateway-psk")
        psk = os.getenv("COAP_DTLS_PSK", "change-me-psk")
        protocol.client_credentials.load_from_dict(
            {
                f"coaps://{gateway_host}/*": {
                    "dtls": {
                        "psk": {"ascii": psk},
                        "client-identity": {"ascii": psk_identity},
                    }
                }
            }
        )
    else:
        protocol = await Context.create_client_context()
    try:
        uri = f"{scheme}://{gateway_host}:{gateway_coap_port}/alerts"
        payload = json.dumps(
            {
                "node_id": f"b01-f{floor_id:02d}-r{floor_id * 100 + room_id:03d}",
                "alert": alert_type,
                "value": value,
                "ts": int(time.time()),
            }
        ).encode()
        request = Message(code=Code.POST, payload=payload)
        request.set_request_uri(uri)
        response = await protocol.request(request).response
        logger.info(
            "CoAP CON alert %s → %s ACK=%s",
            alert_type,
            uri,
            response.code,
        )
    finally:
        await protocol.shutdown()

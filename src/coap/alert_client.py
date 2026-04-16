"""CON (Confirmable) CoAP POST client for sentinel alerts to a floor gateway."""
from __future__ import annotations

import json
import logging
import time

from aiocoap import Code, Context, Message

logger = logging.getLogger("coap.alert_client")


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
    protocol = await Context.create_client_context()
    try:
        uri = f"coap://{gateway_host}:{gateway_coap_port}/alerts"
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

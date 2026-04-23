# CoAP DTLS Enablement (Phase 2)

This project now supports **optional DTLS/PSK wiring** for CoAP code paths.

## What was added

- CoAP server DTLS mode in `src/coap/server.py`
- CoAP alert client DTLS mode in `src/coap/alert_client.py`
- Scheme-aware CoAP URI helper in `src/utils/topics.py`
- Gateway flow generator now uses `COAP_SCHEME` (`coap` or `coaps`) in generated URLs:
  - `node-red/generate_gateway_flows.py`
  - regenerated `node-red/gateway-f*/flows.json`

## Environment flags

Set in `.env`:

- `COAP_SCHEME=coap`
- `COAP_ALERT_SCHEME=coap`
- `COAP_USE_DTLS=false`
- `COAP_DTLS_SERVER_HOSTNAME=sim-engine`
- `COAP_DTLS_IDENTITY=gateway-psk`
- `COAP_DTLS_PSK=change-me-psk`

To turn on DTLS:

1. Set:
   - `COAP_SCHEME=coaps`
   - `COAP_ALERT_SCHEME=coaps`
   - `COAP_USE_DTLS=true`
2. Set a strong PSK:
   - `COAP_DTLS_PSK=<long-random-secret>`
3. Recreate containers / restart runtime and gateways.

## Important runtime note

`aiocoap` DTLS requires a DTLS-capable transport backend.  
If unavailable, the code now fails fast with a clear error instead of silently running insecurely.

Expected transport names:

- Server: `tinydtls_server`
- Client: `tinydtls`

If your environment does not provide these backends, keep `COAP_*` scheme as `coap` and document this as a lab limitation, or install an aiocoap/OS runtime variant with DTLS support.

## Report proof suggestions

- Show `.env` with DTLS flags enabled (`coaps`, `COAP_USE_DTLS=true`).
- Show runtime logs indicating CoAP server started with `dtls=True`.
- Capture gateway traffic/logs showing `coaps://...` URIs used.
- Include a short note that MQTT uses TLS (`8883`) and CoAP uses DTLS/PSK with shared identity.

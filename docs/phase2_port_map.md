# Phase 2 — Port & CoAP map (quick reference)

## Services

| Service     | Port   | Protocol | Purpose                    |
|------------|--------|-----------|----------------------------|
| HiveMQ     | 1883   | TCP/MQTT  | Plain broker (dev)         |
| HiveMQ     | 8883   | TCP/MQTTS | TLS broker (production)    |
| HiveMQ     | 8080   | HTTP      | Control Center UI          |
| ThingsBoard| 9090   | HTTP      | Dashboard UI               |
| ThingsBoard| 1884   | TCP/MQTT  | TB internal MQTT (host)    |
| sim-engine | 5683–5782 | UDP/CoAP | 100 CoAP room servers   |
| Node-RED   | 1880   | HTTP      | Gateway UI (if published)  |

## CoAP port mapping

| Floor | Rooms (CoAP) | UDP port range |
|-------|-------------|----------------|
| 01    | r111–r120   | 5683–5692      |
| 02    | r211–r220   | 5693–5702      |
| 03    | r311–r320   | 5703–5712      |
| 04    | r411–r420   | 5713–5722      |
| 05    | r511–r520   | 5723–5732      |
| 06    | r611–r620   | 5733–5742      |
| 07    | r711–r720   | 5743–5752      |
| 08    | r811–r820   | 5753–5762      |
| 09    | r911–r920   | 5763–5772      |
| 10    | r1011–r1020 | 5773–5782      |

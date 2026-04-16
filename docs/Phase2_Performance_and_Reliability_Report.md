# Phase 2 — Performance, Reliability, and Integration Report

**Campus IoT stack:** HiveMQ (MQTT), Node-RED floor gateways (edge thinning + protocol bridging), ThingsBoard (telemetry + alarms), Python world engine (100 MQTT + 100 CoAP endpoints driven by the Phase 1 thermal model).

This document is the **source** for the required ~5-page PDF. Generate the PDF on your machine, for example:

```bash
pandoc docs/Phase2_Performance_and_Reliability_Report.md -o docs/Phase2_Performance_and_Reliability_Report.pdf
```

Embed **screenshots and log excerpts** in the PDF where indicated below (HiveMQ Control Center, ThingsBoard dashboards/alarms, container logs).

---

## 1. Architecture and end-to-end data paths

**World engine (`sim-engine`):** A single `asyncio` process runs 100 `gmqtt` clients and 100 `aiocoap` servers. Room physics from Phase 1 feeds telemetry on both transports. Virtual actuators (`hvac_status`, dimmer, etc.) update from MQTT command topics and CoAP `PUT` actuator resources (see `src/models/room.py`, `src/nodes/mqtt_node.py`, `src/coap/server.py`).

**Gateways:** Ten Node-RED instances (`gateway-f01` … `gateway-f10`) each subscribe to floor-scoped MQTT, observe CoAP resources on `sim-engine`, apply **60-second averaging** before publishing upstream, map MQTT commands to CoAP `PUT`, and expose a CoAP **alert** listener for reliability signaling from the sim (Flow E in generated `flows.json`).

**ThingsBoard:** HiveMQ integration uses `thingsboard/uplink_converter_hivemq.js`. Devices and assets are defined in `thingsboard/campus_registry_export.json` / `thingsboard/campus_devices.csv` (200 devices). Rule chain `thingsboard/rule_chain_campus_alarms.json` saves telemetry and raises `TEMPERATURE_THRESHOLD` alarms.

**Security:** Per-floor MQTT credentials are enforced via HiveMQ File RBAC + topic ACLs (`hivemq/extensions/hivemq-file-rbac-extension/`). TLS for MQTT is configured on port **8883** in `hivemq/config/config.xml` using `hivemq/certs/hivemq.p12` (generate with `python -m src.security.cert_gen` or the project OpenSSL procedure). CoAP in this reference stack uses **UDP without DTLS** on the Docker bridge; for production DTLS/PSK, terminate at a dedicated CoAP proxy or enable DTLS in your chosen CoAP stack and document the PSK map alongside HiveMQ client certs.

---

## 2. Stress test — 100+ active MQTT clients

**Procedure**

1. `docker compose up -d`
2. Open HiveMQ Control Center: `http://localhost:8080` (default CE credentials per HiveMQ docs if enabled).
3. Navigate to **Clients** (or equivalent) and confirm **at least 100 connected MQTT clients** from `sim-engine` plus gateway clients.

**Evidence to capture**

- Screenshot: client count ≥ 100, broker uptime stable.
- Optional: `docker logs campus-sim-engine --tail 200` showing publish loops without repeated connection failures.

---

## 3. Latency — dashboard → device → ack under 500 ms

**Definition of round-trip:** Command issued from the operator path (e.g. ThingsBoard RPC or Node-RED inject → MQTT command topic → `sim-engine` handler → actuator state update) through to acknowledgment (MQTT PUBACK / PUBCOMP at QoS 1/2, or CoAP `2.04 Changed` on `PUT`).

**Tooling:** `scripts/latency_test.py` measures broker RTT and can log samples to a file:

```bash
python scripts/latency_test.py --save docs/rtt_results.txt
```

**Evidence to capture**

- Table or histogram of RTT samples (p50 / p95) with mean &lt; 500 ms under nominal Docker Desktop CPU.
- If local load pushes latency up, document hardware and still show methodology; tune `PUBLISH_INTERVAL` in `.env` if needed for the demo environment.

---

## 4. Reliability validation

### 4.1 MQTT duplicate (DUP) handling

The MQTT command path deduplicates by **hash of topic + raw payload** so retransmissions are not double-applied (`src/nodes/mqtt_node.py`).

**Evidence:** Log lines showing a duplicate delivery followed by a single actuator transition, or debug logging of the dedup cache hit.

### 4.2 QoS 2 delivery guarantees

Gateway Flow E publishes alert forwarding to MQTT at **QoS 2** where configured; use `scripts/stress_mqtt_qos2.sh` (or `mosquitto_sub` / `mosquitto_pub` with `-q 2`) to demonstrate complete four-way handshake and no duplicate application at the subscriber.

**Evidence:** Broker trace or client log showing `PUBLISH` / `PUBREC` / `PUBREL` / `PUBCOMP` sequence; subscriber receives exactly one message.

### 4.3 CoAP confirmable (CON) behavior under instability

The sim’s alert client sends **CON** POSTs to `coap://gateway-f{ff}:5686/alerts` with retry/cooldown (`src/coap/alert_client.py`).

**Evidence:** With `tc netem` on Linux or intermittent `docker network disconnect`, capture logs showing retransmissions or gateway-side handling; in Docker Desktop, document simulated loss via firewall rules or pause/resume of the gateway container and show CoAP stack or Node-RED debug output.

---

## 5. ThingsBoard — dashboard and online/offline indicators

After provisioning (`python scripts/provision_tb.py`) and configuring the HiveMQ integration with `uplink_converter_hivemq.js`:

1. Create a dashboard **“Campus NOC”**.
2. Add **two alias-based entity aliases**: one MQTT room device (`b01-f01-r101`) and one CoAP room device (e.g. `b01-f01-r115` — rooms 11–20 are CoAP in the converter logic).
3. Widgets:
   - **Timeseries line chart:** `temperature`, `humidity` (real-time, aggregation None).
   - **Latest values:** `hvac_status`, `connection_status` / `device_status`.
   - **Alarm widget** filtered by type `TEMPERATURE_THRESHOLD` after attaching `rule_chain_campus_alarms.json` to the integration or root chain.
4. Export the dashboard (**Dashboards → Export**) and store alongside this repo if required for submission.

The converter maps LWT / `…/status` payloads to `connection_status` attributes and telemetry so **online/offline** can be shown as LED or value cards.

---

## 6. Static verification checklist

Run:

```bash
python scripts/verify_phase2_deliverables.py
```

This confirms presence of compose file, HiveMQ config, RBAC extension, ten gateway flow exports, registry JSON, rule chain, and Python syntax for critical modules.

---

## 7. Conclusion

Phase 2 delivers a **fully wired** multi-protocol campus simulation: Python asyncio scale-out, Node-RED edge processing, ThingsBoard mind layer, and broker ACL/TLS hooks. Final **PDF evidence** consists of this narrative plus embedded screenshots (HiveMQ clients, TB dashboard, latency numbers, and reliability logs) captured from your deployment host.

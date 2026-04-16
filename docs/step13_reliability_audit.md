# Step 13 — Reliability audit (QoS 2, CON, DUP)

## 13a — ThingsBoard RPC → MQTT cmd at QoS 2

1. **Dashboard:** edit **Campus NOC** (or a control dashboard) → **Add widget** → **Control widgets** → **RPC** / **Knob** / **Button** (depends on TB version).
2. Set **Target device** to a room device, or use a **Rule chain** that publishes to the integration downlink.
3. For **MQTT integration downlink** (or **External MQTT** rule node): publish to  
   `campus/b01/f{FF}/r{RRR}/cmd` with **QoS 2** (integration advanced settings / rule node **MQTT** publish options).
4. **Verify:** open **HiveMQ Control Center** → inspect **PUBLISH** for the session: QoS **2** and **PUBREC / PUBREL / PUBCOMP** for the command flow.

> TB CE UI labels vary by version; if the widget cannot set QoS 2, use a **Rule chain** **MQTT** node toward HiveMQ with QoS 2.

## 13b — CoAP CON alerts

- Sim-engine sends **CON POST** to `coap://gateway-f{FF}:{COAP_ALERT_GATEWAY_PORT}/alerts` when `COAP_ALERTS_ENABLED=true` and temperature exceeds `TEMP_ALERT_HIGH` (with cooldown).
- The floor **Node-RED** instance must expose **CoAP server** `POST /alerts` and forward to HiveMQ if required for TB.

Env vars: see `.env` **Phase 2** section (`COAP_ALERT_*`).

## 13c — DUP handler

See [dup_flag_handler.md](dup_flag_handler.md).

## 13d — Stress test

From repo root (Linux / Git Bash / WSL):

```bash
bash scripts/stress_mqtt_qos2.sh
```

Manual variant: run `docker compose up`, then `mosquitto_sub` / loop in the script comments.

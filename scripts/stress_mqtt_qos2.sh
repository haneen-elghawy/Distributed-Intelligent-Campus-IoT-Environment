#!/usr/bin/env bash
# Step 13d — Quick QoS 2 + dedup stress (requires mosquitto clients + stack on localhost:1883).
set -euo pipefail

BROKER="${MQTT_HOST:-localhost}"
PORT="${MQTT_PORT:-1883}"
TB_USER="${MQTT_USER_TB:-thingsboard}"
TB_PASS="${MQTT_PASS_TB:-tb_super_pass}"
FLOOR_USER="${MQTT_USER_FLOOR:-floor01}"
FLOOR_PASS="${MQTT_PASS_FLOOR:-floor01pass}"
CMD_TOPIC="${CMD_TOPIC:-campus/b01/f01/r101/cmd}"
PAYLOAD='{"hvac_mode":"ECO","target_temp":24.0}'
LOG="${STRESS_LOG:-stress_test_log.txt}"

echo "Logging all campus traffic to ${LOG} (background subscriber)…"
mosquitto_sub -h "$BROKER" -p "$PORT" -u "$TB_USER" -P "$TB_PASS" \
  -t "campus/#" -v | tee "$LOG" &
SUB_PID=$!
sleep 2

echo "Publishing50 identical QoS 2 commands to ${CMD_TOPIC}…"
for i in $(seq 1 50); do
  mosquitto_pub -h "$BROKER" -p "$PORT" -u "$FLOOR_USER" -P "$FLOOR_PASS" \
    -t "$CMD_TOPIC" -q 2 \
    -m "$PAYLOAD"
done

echo "Subscriber still running (PID ${SUB_PID}). Press Ctrl+C to stop, then:"
echo "  grep -c ALERT \"$LOG\" || true"
echo "  grep cmd \"$LOG\" | wc -l"

wait "$SUB_PID" || true

/** Uplink data converter — HiveMQ MQTT integration (Steps 11d / 12).
 *  Topics:
 *    campus/.../telemetry  — room sensors (+ marks connection_status online)
 *    campus/.../status     — MQTT LWT / gateway mirror (offline | online)
 *    campus/.../floor-summary — per-floor aggregates (optional FloorSummary devices)
 */
var data = decodeToJson(payload);
var topicStr = metadata.topic || metadata.topicName || "";
var parts = topicStr.split("/");

var nodeId = data.node_id;
if (!nodeId && parts.length >= 4) {
  if (parts.length >= 5 && parts[4] === "floor-summary") {
    nodeId = parts[1] + "-" + parts[2] + "-floor-summary";
  } else {
    nodeId = parts[1] + "-" + parts[2] + "-" + parts[3];
  }
}

var devType = "MQTT-ThermalSensor";
if (parts.length >= 5 && parts[4] === "floor-summary") {
  devType = "FloorSummary";
} else if (nodeId) {
  var rm = nodeId.match(/-r(\d{3})$/);
  if (rm) {
    var roomId = parseInt(rm[1], 10) % 100;
    if (roomId >= 11 && roomId <= 20) {
      devType = "CoAP-ThermalSensor";
    }
  }
}
if (data.protocol) {
  devType = data.protocol + "-ThermalSensor";
}

var tsMs = data.ts != null ? (data.ts < 1e12 ? data.ts * 1000 : data.ts) : Date.now();
var tail = parts.length >= 5 ? parts[4] : "";

/* ─── LWT / status topic → attribute + telemetry for NOC grid ─── */
if (tail === "status") {
  var st = data.status != null ? String(data.status) : "unknown";
  var label = st === "offline" ? "Offline" : st === "online" ? "Online" : st;
  return {
    deviceName: nodeId,
    deviceType: devType,
    attributes: {
      connection_status: st,
      connection_status_label: label,
    },
    telemetry: [
      {
        ts: tsMs,
        values: {
          connection_status: st,
          device_status: label,
        },
      },
    ],
  };
}

/* ─── Floor summary ─── */
if (tail === "floor-summary") {
  return {
    deviceName: nodeId,
    deviceType: devType,
    telemetry: [
      {
        ts: tsMs,
        values: {
          avg_temperature: data.avg_temperature != null ? parseFloat(data.avg_temperature) : null,
          avg_humidity: data.avg_humidity != null ? parseFloat(data.avg_humidity) : null,
          occupied_rooms: data.occupied_rooms,
          total_rooms: data.total_rooms,
          floor: data.floor,
        },
      },
    ],
  };
}

/* ─── Normal telemetry ─── */
return {
  deviceName: nodeId,
  deviceType: devType,
  attributes: {
    connection_status: "online",
    connection_status_label: "Online",
  },
  telemetry: [
    {
      ts: tsMs,
      values: {
        temperature: data.temperature,
        humidity: data.humidity,
        occupancy: data.occupancy,
        light_level: data.light_level,
        lighting_dimmer: data.lighting_dimmer,
        hvac_mode: data.hvac_mode,
        connection_status: "online",
        device_status: "Online",
      },
    },
  ],
};

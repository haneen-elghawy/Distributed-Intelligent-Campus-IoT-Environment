/** Uplink data converter — HiveMQ MQTT integration (Steps 11d / 12).
 *  Topics:
 *    campus/.../telemetry  — room sensors (+ marks connection_status online)
 *    campus/.../status     — MQTT LWT / gateway mirror (offline | online)
 *    campus/.../floor-summary — per-floor aggregates (optional FloorSummary devices)
 *    campus/.../sync-status — desired vs reported reconciliation state
 *    campus/.../ota/report  — OTA result / tamper evidence
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
          occupancy_rate: data.occupancy_rate != null ? parseFloat(data.occupancy_rate) : null,
          floor: data.floor,
        },
      },
    ],
  };
}

/* ─── Sync status (desired vs reported shadow state) ─── */
if (tail === "sync-status") {
  return {
    deviceName: nodeId,
    deviceType: devType,
    attributes: {
      last_seen: data.last_seen != null ? data.last_seen : null,
      desired_hvac_mode: data.desired_hvac_mode != null ? data.desired_hvac_mode : null,
      reported_hvac_mode: data.reported_hvac_mode != null ? data.reported_hvac_mode : null,
      desired_lighting_dimmer: data.desired_lighting_dimmer != null ? data.desired_lighting_dimmer : null,
      reported_lighting_dimmer: data.reported_lighting_dimmer != null ? data.reported_lighting_dimmer : null,
      sync_status: data.sync_status != null ? data.sync_status : "UNKNOWN",
      config_version: data.config_version != null ? String(data.config_version) : null,
      current_version: data.current_version != null ? String(data.current_version) : null
    },
    telemetry: [
      {
        ts: tsMs,
        values: {
          sync_status: data.sync_status != null ? data.sync_status : "UNKNOWN"
        }
      }
    ]
  };
}

/* ─── OTA report / tamper forensics ─── */
if (parts.length >= 6 && parts[4] === "ota" && parts[5] === "report") {
  return {
    deviceName: nodeId,
    deviceType: devType,
    attributes: {
      current_version: data.version != null ? String(data.version) : null,
      ota_last_reason: data.reason != null ? String(data.reason) : "",
      ota_last_topic: data.topic != null ? String(data.topic) : "",
      ota_last_rejected: data.rejected === true,
      ota_last_producer_id: data.producer_id != null ? String(data.producer_id) : "",
      ota_last_source_ip: data.source_ip != null ? String(data.source_ip) : ""
    },
    telemetry: [
      {
        ts: tsMs,
        values: {
          ota_rejected: data.rejected === true,
          ota_reason: data.reason != null ? String(data.reason) : "",
          ota_alert: data.rejected === true ? 1 : 0
        }
      }
    ]
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
        hvac_status: data.hvac_status,
        connection_status: "online",
        device_status: "Online",
      },
    },
  ],
};

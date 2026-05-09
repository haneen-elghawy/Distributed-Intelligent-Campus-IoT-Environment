"""Generate node-red/gateway-f01..f10/flows.json from fleet port layout (run after edits)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NUM_FLOORS = 10
MQTT_PER_FLOOR = 10
COAP_PER_FLOOR = 10
COAP_BASE = 5683


def coap_ports_for_floor(floor: int) -> list[tuple[int, int, int]]:
    """(coap_port, floor_id, room_id) for rooms 11..20 on this floor."""
    idx0 = (floor - 1) * COAP_PER_FLOOR  # offset into global CoAP port sequence
    ports = []
    for j, room_id in enumerate(range(MQTT_PER_FLOOR + 1, MQTT_PER_FLOOR + COAP_PER_FLOOR + 1)):
        port = COAP_BASE + idx0 + j
        ports.append((port, floor, room_id))
    return ports


def nid(floor: int, room_id: int) -> str:
    rnum = floor * 100 + room_id
    return f"b01-f{floor:02d}-r{rnum:03d}"


def flows_for_floor(floor: int) -> list[dict]:
    ff = f"{floor:02d}"
    tab_id = f"tab-floor{ff}"
    broker_id = f"broker-{ff}"
    coap_ports = coap_ports_for_floor(floor)

    nodes: list[dict] = [
        {
            "id": tab_id,
            "type": "tab",
            "label": f"Floor {ff} Gateway",
            "disabled": False,
            "info": "Phase 2 — Flows A–E (CoAP alert ingress), edge thinning, cmd routing",
        },
        {
            "id": broker_id,
            "type": "mqtt-broker",
            "name": "HiveMQ",
            "broker": "$(HIVEMQ_HOST)",
            "port": "$(HIVEMQ_PORT)",
            "clientid": "nodered-gw-f$(FLOOR)",
            "autoConnect": True,
            "usetls": False,
            "protocolVersion": "4",
            "keepalive": "60",
            "cleansession": True,
            "birthTopic": "",
            "birthQos": "0",
            "birthRetain": "false",
            "birthPayload": "",
            "birthPayloadType": "str",
            "closeTopic": "",
            "closeQos": "0",
            "closeRetain": "false",
            "closePayload": "",
            "closePayloadType": "str",
            "willTopic": "",
            "willQos": "0",
            "willRetain": "false",
            "willPayload": "",
            "willPayloadType": "str",
            "sessionExpiry": "",
            "credentials": {
                "user": "$(MQTT_USER)",
                "password": "$(MQTT_PASS)",
            },
        },
    ]

    # --- Flow A: MQTT telemetry in → context + status republish ---
    fn_parse_mqtt = f"fn-a-parse-{ff}"
    mq_in_tel = f"mqtt-in-tel-{ff}"
    mq_out_stat = f"mqtt-out-stat-{ff}"
    nodes += [
        {
            "id": mq_in_tel,
            "type": "mqtt in",
            "z": tab_id,
            "name": "A: telemetry",
            "topic": f"campus/b01/f{ff}/+/telemetry",
            "qos": "1",
            "datatype": "json",
            "broker": broker_id,
            "nl": False,
            "rap": False,
            "inputs": 0,
            "x": 140,
            "y": 60,
            "wires": [[fn_parse_mqtt]],
        },
        {
            "id": fn_parse_mqtt,
            "type": "function",
            "z": tab_id,
            "name": "A: store + status topic",
            "func": r"""
let p = msg.payload;
if (typeof p === 'string') { try { p = JSON.parse(p); } catch (e) { return null; } }
if (!p || !p.node_id) return null;
const rooms = flow.get('floor_rooms') || {};
rooms[p.node_id] = {
    temperature: p.temperature,
    humidity: p.humidity,
    occupancy: p.occupancy,
    ts: p.ts,
    source: 'mqtt'
};
flow.set('floor_rooms', rooms);
msg.topic = msg.topic.replace(/\/telemetry$/, '/status');
msg.payload = p;
return msg;
""".strip(),
            "outputs": 1,
            "timeout": 0,
            "noerr": 0,
            "initialize": "",
            "finalize": "",
            "libs": [],
            "x": 380,
            "y": 60,
            "wires": [[mq_out_stat]],
        },
        {
            "id": mq_out_stat,
            "type": "mqtt out",
            "z": tab_id,
            "name": "A: status mirror",
            "topic": "",
            "qos": "1",
            "retain": "false",
            "respTopic": "",
            "contentType": "",
            "userProps": "",
            "correl": "",
            "expiry": "",
            "broker": broker_id,
            "x": 620,
            "y": 60,
            "wires": [],
        },
    ]

    # --- Flow B: CoAP observe × 10 → bridge → MQTT ---
    y0 = 180
    for i, (port, fl, room_id) in enumerate(coap_ports):
        rnum = fl * 100 + room_id
        inj_id = f"inj-coap-{ff}-{i}"
        coap_id = f"coap-obs-{ff}-{i}"
        bridge_id = f"fn-bridge-{ff}-{i}"
        mq_out_t = f"mqtt-out-bridge-{ff}-{i}"
        y = y0 + i * 70
        url = f"$(COAP_SCHEME)://$(SIM_ENGINE_HOST):{port}/f{ff}/r{rnum:03d}/telemetry"
        nodes += [
            {
                "id": inj_id,
                "type": "inject",
                "z": tab_id,
                "name": f"Start observe r{rnum}",
                "props": [{"p": "payload"}, {"p": "topic", "vt": "str"}],
                "repeat": "",
                "crontab": "",
                "once": True,
                "onceDelay": 0.5 + i * 0.05,
                "topic": "",
                "payload": "",
                "payloadType": "date",
                "x": 130,
                "y": y,
                "wires": [[coap_id]],
            },
            {
                "id": coap_id,
                "type": "coap request",
                "z": tab_id,
                "method": "GET",
                "observe": True,
                "url": url,
                "content-format": "application/json",
                "raw-buffer": False,
                "name": f"Observe r{rnum}",
                "x": 360,
                "y": y,
                "wires": [[bridge_id]],
            },
            {
                "id": bridge_id,
                "type": "function",
                "z": tab_id,
                "name": f"B: bridge r{rnum}",
                "func": r"""
let p = msg.payload;
if (typeof p === 'string') { try { p = JSON.parse(p); } catch (e) { return null; } }
if (!p || !p.node_id) return null;
const rooms = flow.get('floor_rooms') || {};
rooms[p.node_id] = {
    temperature: p.temperature,
    humidity: p.humidity,
    occupancy: p.occupancy,
    ts: p.ts,
    source: 'coap'
};
flow.set('floor_rooms', rooms);
const r = p.node_id.split('-r')[1];
const f = process.env.FLOOR;
msg.topic = `campus/b01/f${f}/r${r}/telemetry`;
msg.qos = 1;
msg.payload = p;
return msg;
""".strip(),
                "outputs": 1,
                "timeout": 0,
                "noerr": 0,
                "initialize": "",
                "finalize": "",
                "libs": [],
                "x": 580,
                "y": y,
                "wires": [[mq_out_t]],
            },
            {
                "id": mq_out_t,
                "type": "mqtt out",
                "z": tab_id,
                "name": f"MQTT r{rnum}",
                "topic": "",
                "qos": "1",
                "retain": "false",
                "respTopic": "",
                "contentType": "",
                "userProps": "",
                "correl": "",
                "expiry": "",
                "broker": broker_id,
                "x": 820,
                "y": y,
                "wires": [],
            },
        ]

    # --- Flow C: edge thinning ---
    y_thin = y0 + 10 * 70 + 40
    inj_60 = f"inj-60-{ff}"
    fn_thin = f"fn-thin-{ff}"
    mq_sum = f"mqtt-sum-{ff}"
    nodes += [
        {
            "id": inj_60,
            "type": "inject",
            "z": tab_id,
            "name": "Every 60s",
            "props": [{"p": "payload"}],
            "repeat": "60",
            "crontab": "",
            "once": False,
            "onceDelay": 0.1,
            "topic": "",
            "payload": "",
            "payloadType": "date",
            "x": 140,
            "y": y_thin,
            "wires": [[fn_thin]],
        },
        {
            "id": fn_thin,
            "type": "function",
            "z": tab_id,
            "name": "C: edge-thinning",
            "func": r"""
const floorRooms = flow.get('floor_rooms') || {};
const temps = Object.values(floorRooms).map(r => r.temperature).filter(v => v != null);
const humids = Object.values(floorRooms).map(r => r.humidity).filter(v => v != null);
const occupied = Object.values(floorRooms).filter(r => r.occupancy === true).length;
const summary = {
    floor: process.env.FLOOR,
    ts: Date.now(),
    avg_temperature: temps.length ? (temps.reduce((a,b)=>a+b,0)/temps.length).toFixed(1) : null,
    avg_humidity: humids.length ? (humids.reduce((a,b)=>a+b,0)/humids.length).toFixed(1) : null,
    occupied_rooms: occupied,
    total_rooms: Object.keys(floorRooms).length
};
msg.payload = summary;
msg.topic = `campus/b01/f${process.env.FLOOR}/floor-summary`;
return msg;
""".strip(),
            "outputs": 1,
            "timeout": 0,
            "noerr": 0,
            "initialize": "",
            "finalize": "",
            "libs": [],
            "x": 380,
            "y": y_thin,
            "wires": [[mq_sum]],
        },
        {
            "id": mq_sum,
            "type": "mqtt out",
            "z": tab_id,
            "name": "C: floor-summary",
            "topic": "",
            "qos": "1",
            "retain": "false",
            "respTopic": "",
            "contentType": "",
            "userProps": "",
            "correl": "",
            "expiry": "",
            "broker": broker_id,
            "x": 620,
            "y": y_thin,
            "wires": [],
        },
    ]

    # --- Flow D: command routing ---
    y_cmd = y_thin + 100
    mq_in_cmd = f"mqtt-in-cmd-{ff}"
    fn_route = f"fn-route-{ff}"
    coap_put = f"coap-put-{ff}"
    fn_ack = f"fn-ack-{ff}"
    mq_ack = f"mqtt-ack-{ff}"
    mq_ack_legacy = f"mqtt-ack-legacy-{ff}"
    nodes += [
        {
            "id": mq_in_cmd,
            "type": "mqtt in",
            "z": tab_id,
            "name": "D: commands",
            "topic": f"campus/b01/f{ff}/+/cmd",
            "qos": "2",
            "datatype": "utf8",
            "broker": broker_id,
            "nl": False,
            "rap": False,
            "inputs": 0,
            "x": 140,
            "y": y_cmd,
            "wires": [[fn_route]],
        },
        {
            "id": fn_route,
            "type": "function",
            "z": tab_id,
            "name": "D: cmd-router",
            "func": r"""
const topic = msg.topic;
const parts = topic.split('/');
if (parts.length < 5) return null;
const roomStr = parts[3];
const floorStr = parts[2];
const rfull = parseInt(roomStr.replace(/^r/, ''), 10);
const roomNum = rfull % 100;
const coapStart = parseInt(process.env.COAP_PORT_START || '5683', 10);
const coapPort = coapStart + (roomNum - 11);
let parsedPayload = msg.payload;
if (Buffer.isBuffer(parsedPayload)) {
    parsedPayload = parsedPayload.toString();
}
if (typeof parsedPayload === 'string') {
    try { parsedPayload = JSON.parse(parsedPayload); } catch (e) { parsedPayload = {}; }
}
if (!parsedPayload || typeof parsedPayload !== 'object') {
    parsedPayload = {};
}
const cmdId = parsedPayload.cmd_id || parsedPayload.command_id || null;
const correlationId = parsedPayload.correlation_id || cmdId || null;
const cmdContext = {
    topic,
    floor: floorStr,
    room: roomStr,
    room_id: `b01-${floorStr}-${roomStr}`,
    cmd_id: cmdId,
    correlation_id: correlationId,
    payload: parsedPayload,
    ts: Date.now(),
};
flow.set('last_cmd_context', cmdContext);
if (roomNum >= 11 && roomNum <= 20) {
    const coapScheme = process.env.COAP_SCHEME || 'coap';
    msg.url = `${coapScheme}://${process.env.SIM_ENGINE_HOST}:${coapPort}/${floorStr}/${roomStr}/actuators/hvac`;
    msg.method = 'PUT';
    msg.payload = JSON.stringify(parsedPayload);
    return [msg, null];
}
return [null, null];
""".strip(),
            "outputs": 2,
            "timeout": 0,
            "noerr": 0,
            "initialize": "",
            "finalize": "",
            "libs": [],
            "x": 380,
            "y": y_cmd,
            "wires": [[coap_put], []],
        },
        {
            "id": coap_put,
            "type": "coap request",
            "z": tab_id,
            "method": "PUT",
            "observe": False,
            "url": "",
            "content-format": "application/json",
            "raw-buffer": False,
            "name": "D: CoAP PUT hvac",
            "x": 620,
            "y": y_cmd,
            "wires": [[fn_ack]],
        },
        {
            "id": fn_ack,
            "type": "function",
            "z": tab_id,
            "name": "D: ack-builder",
            "func": r"""
const ctx = flow.get('last_cmd_context');
if (!ctx || !ctx.floor || !ctx.room) return null;
const code = msg.statusCode;
const ok = code == null || String(code).startsWith('2.');
const applied = {};
const p = (ctx.payload && typeof ctx.payload === 'object') ? ctx.payload : {};
if (Object.prototype.hasOwnProperty.call(p, 'hvac_mode')) applied.hvac_mode = p.hvac_mode;
if (Object.prototype.hasOwnProperty.call(p, 'target_temp')) applied.target_temp = p.target_temp;
if (Object.prototype.hasOwnProperty.call(p, 'lighting_dimmer')) applied.lighting_dimmer = p.lighting_dimmer;
const ackPayload = {
    cmd_id: ctx.cmd_id || null,
    correlation_id: ctx.correlation_id || null,
    room_id: ctx.room_id,
    status: ok ? 'ok' : 'error',
    timestamp: Date.now(),
    coap_status: code == null ? null : String(code),
    applied_actuators: applied
};
const canonical = RED.util.cloneMessage(msg);
canonical.topic = `campus/b01/${ctx.floor}/${ctx.room}/response`;
canonical.payload = ackPayload;
const legacy = RED.util.cloneMessage(msg);
legacy.topic = `campus/b01/${ctx.floor}/${ctx.room}/cmd-response`;
legacy.payload = {
    ok,
    coap_status: ackPayload.coap_status,
    ts: ackPayload.timestamp,
    cmd_id: ackPayload.cmd_id,
    correlation_id: ackPayload.correlation_id,
    room_id: ackPayload.room_id
};
return [canonical, legacy];
""".strip(),
            "outputs": 2,
            "timeout": 0,
            "noerr": 0,
            "initialize": "",
            "finalize": "",
            "libs": [],
            "x": 860,
            "y": y_cmd,
            "wires": [[mq_ack], [mq_ack_legacy]],
        },
        {
            "id": mq_ack,
            "type": "mqtt out",
            "z": tab_id,
            "name": "D: response MQTT",
            "topic": "",
            "qos": "1",
            "retain": "false",
            "respTopic": "",
            "contentType": "",
            "userProps": "",
            "correl": "",
            "expiry": "",
            "broker": broker_id,
            "x": 1100,
            "y": y_cmd,
            "wires": [],
        },
        {
            "id": mq_ack_legacy,
            "type": "mqtt out",
            "z": tab_id,
            "name": "D: legacy cmd-response MQTT",
            "topic": "",
            "qos": "1",
            "retain": "false",
            "respTopic": "",
            "contentType": "",
            "userProps": "",
            "correl": "",
            "expiry": "",
            "broker": broker_id,
            "x": 1130,
            "y": y_cmd + 40,
            "wires": [],
        },
    ]

    # --- Offline: broker status → CoAP OFF for unoccupied CoAP rooms ---
    y_off = y_cmd + 120
    st_broker = f"st-broker-{ff}"
    fn_off = f"fn-offline-{ff}"
    coap_off = f"coap-off-{ff}"
    nodes += [
        {
            "id": st_broker,
            "type": "status",
            "z": tab_id,
            "name": "Broker status",
            "scope": [broker_id],
            "x": 140,
            "y": y_off,
            "wires": [[fn_off]],
        },
        {
            "id": fn_off,
            "type": "function",
            "z": tab_id,
            "name": "Offline: unoccupied → HVAC OFF",
            "func": r"""
const text = (msg.status && msg.status.text) ? String(msg.status.text) : '';
if (!text.toLowerCase().includes('disconnect') && !text.toLowerCase().includes('lost')) {
    return null;
}
const F = process.env.FLOOR;
const start = parseInt(process.env.COAP_PORT_START || '5683', 10);
const rooms = flow.get('floor_rooms') || {};
for (let roomId = 11; roomId <= 20; roomId++) {
    const rnum = parseInt(F, 10) * 100 + roomId;
    const rid = `b01-f${F}-r${rnum}`;
    const rec = rooms[rid];
    if (rec && rec.occupancy === false) {
        const port = start + (roomId - 11);
        node.send({
            url: `${process.env.COAP_SCHEME || 'coap'}://${process.env.SIM_ENGINE_HOST}:${port}/f${F}/r${rnum}/actuators/hvac`,
            method: 'PUT',
            payload: JSON.stringify({ hvac_mode: 'OFF' }),
        });
    }
}
return null;
""".strip(),
            "outputs": 1,
            "timeout": 0,
            "noerr": 0,
            "initialize": "",
            "finalize": "",
            "libs": [],
            "x": 400,
            "y": y_off,
            "wires": [[coap_off]],
        },
        {
            "id": coap_off,
            "type": "coap request",
            "z": tab_id,
            "method": "PUT",
            "observe": False,
            "url": "",
            "content-format": "application/json",
            "raw-buffer": False,
            "name": "Offline CoAP PUT",
            "x": 680,
            "y": y_off,
            "wires": [],
        },
    ]

    # --- Flow E: CoAP POST /alerts (CON) from sim-engine → 2.04 ACK + MQTT QoS 2 ---
    y_al = y_off + 140
    srv_al = f"coap-srv-alerts-{ff}"
    coap_in_al = f"coap-in-alerts-{ff}"
    fn_al = f"fn-alerts-{ff}"
    coap_ack = f"coap-ack-alerts-{ff}"
    mq_al = f"mqtt-alerts-{ff}"
    nodes += [
        {
            "id": srv_al,
            "type": "coap-server",
            "name": "Gateway alert listener",
            "port": "$(COAP_LISTEN_PORT)",
        },
        {
            "id": coap_in_al,
            "type": "coap in",
            "z": tab_id,
            "method": "POST",
            "name": "E: POST /alerts",
            "server": srv_al,
            "url": "/alerts",
            "x": 140,
            "y": y_al,
            "wires": [[fn_al]],
        },
        {
            "id": fn_al,
            "type": "function",
            "z": tab_id,
            "name": "E: ACK + MQTT alert",
            "func": r"""
let p = msg.payload;
if (Buffer.isBuffer(p)) { p = p.toString(); }
if (typeof p === 'string') { try { p = JSON.parse(p); } catch (e) { return null; } }
if (!p || !p.node_id) return null;
const m = String(p.node_id).match(/^b01-f(\d{2})-r(\d{3})$/);
if (!m) return null;
const ack = RED.util.cloneMessage(msg);
ack.payload = '';
ack.statusCode = '2.04';
const out = RED.util.cloneMessage(msg);
out.topic = `campus/b01/f${m[1]}/r${m[2]}/alert`;
out.payload = p;
out.qos = 2;
return [ack, out];
""".strip(),
            "outputs": 2,
            "timeout": 0,
            "noerr": 0,
            "initialize": "",
            "finalize": "",
            "libs": [],
            "x": 400,
            "y": y_al,
            "wires": [[coap_ack], [mq_al]],
        },
        {
            "id": coap_ack,
            "type": "coap response",
            "z": tab_id,
            "name": "E: CON ACK",
            "statusCode": "",
            "contentFormat": "application/json",
            "x": 640,
            "y": y_al - 40,
            "wires": [],
        },
        {
            "id": mq_al,
            "type": "mqtt out",
            "z": tab_id,
            "name": "E: HiveMQ alert QoS2",
            "topic": "",
            "qos": "2",
            "retain": "false",
            "respTopic": "",
            "contentType": "",
            "userProps": "",
            "correl": "",
            "expiry": "",
            "broker": broker_id,
            "x": 640,
            "y": y_al + 40,
            "wires": [],
        },
    ]

    return nodes


def main() -> None:
    for floor in range(1, NUM_FLOORS + 1):
        ff = f"{floor:02d}"
        out_dir = ROOT / f"gateway-f{ff}"
        out_dir.mkdir(parents=True, exist_ok=True)
        flows = flows_for_floor(floor)
        path = out_dir / "flows.json"
        path.write_text(json.dumps(flows, indent=2), encoding="utf-8")
        pkg = {
            "name": f"gateway-f{ff}",
            "private": True,
            "description": "Node-RED floor gateway — installs CoAP nodes on container start",
            "dependencies": {"node-red-contrib-coap": "^0.9.0"},
        }
        (out_dir / "package.json").write_text(json.dumps(pkg, indent=2) + "\n", encoding="utf-8")
        print("Wrote", path)


if __name__ == "__main__":
    main()

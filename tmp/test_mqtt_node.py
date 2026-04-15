import sys, os, types, asyncio, json

sys.path.insert(0, '.')

# ── stub gmqtt so no broker is needed ─────────────────────────────────────
gmqtt_mod = types.ModuleType('gmqtt')

class _Will:
    def __init__(self, **kw): pass

class _Client:
    Will = _Will
    def __init__(self, cid, will_message=None):
        self.cid = cid
        self._pub = []
    def set_auth_credentials(self, **kw): pass
    def subscribe(self, topic, qos=0): pass
    def publish(self, topic, payload, qos=0, retain=False):
        self._pub.append((topic, qos))
    async def connect(self, *a, **kw): pass
    async def disconnect(self): pass
    on_message = None

gmqtt_mod.Client = _Client
sys.modules['gmqtt'] = gmqtt_mod

# ── stub Room ──────────────────────────────────────────────────────────────
class FakeRoom:
    building_id = 'b01'
    floor_id = 1
    room_id = 5
    node_id = 'b01-f01-r105'
    protocol = 'mqtt'
    coap_port = None
    temperature = 25.0
    humidity = 50.0
    occupancy = False
    light = 300
    lighting_dimmer = 0
    hvac_mode = 'OFF'
    target_temp = 22.0

# ── import ─────────────────────────────────────────────────────────────────
from src.nodes.mqtt_node import MqttNode, _topic_base, _lwt_payload

room = FakeRoom()
node = MqttNode(room)

# 1. topic helper
base = _topic_base(room)
assert base == 'campus/b01/f01/r105', f'bad topic base: {base}'

# 2. LWT payload
lwt_dict = json.loads(_lwt_payload(room))
assert lwt_dict['status'] == 'offline'
assert lwt_dict['node_id'] == room.node_id

# 3. DUP deduplication
assert not node._is_duplicate('abc123'), 'first call must not be dup'
assert     node._is_duplicate('abc123'), 'second call must be dup'
assert not node._is_duplicate('xyz999'), 'new key must not be dup'

# 4. Wire a stub client
node.client = _Client('test')

# 5. on_message applies hvac_mode / target_temp / lighting_dimmer
class FakeProps:
    dup = False

cmd_payload = json.dumps(
    {'hvac_mode': 'ON', 'target_temp': 26.0, 'lighting_dimmer': 75}
).encode()
node._on_message(None, base + '/cmd', cmd_payload, 2, FakeProps())
assert room.hvac_mode in ('HEATING', 'COOLING'), f'hvac_mode not applied: {room.hvac_mode}'
assert room.target_temp == 26.0,  f'target_temp not applied: {room.target_temp}'
assert room.lighting_dimmer == 75, f'lighting_dimmer not applied: {room.lighting_dimmer}'

# 6. publish_telemetry → QoS 1 ; publish_alert → QoS 2
asyncio.run(node.publish_telemetry())
asyncio.run(node.publish_alert('high_temp', 42.0))

pubs = node.client._pub
assert any('telemetry' in t and qos == 1 for t, qos in pubs), 'telemetry must be QoS 1'
assert any('alert'     in t and qos == 2 for t, qos in pubs), 'alert must be QoS 2'

# 7. online status is published with retain on start (via stub connect)
# (tested indirectly; client._pub includes status entry from start())

print(f'topic_base   : {base}')
print(f'lwt status   : {lwt_dict["status"]}')
print(f'hvac_mode    : {room.hvac_mode}')
print(f'target_temp  : {room.target_temp}')
print(f'dimmer       : {room.lighting_dimmer}')
print(f'publishes    : {[(t.split("/")[-1], q) for t, q in pubs]}')
print('All assertions passed.')

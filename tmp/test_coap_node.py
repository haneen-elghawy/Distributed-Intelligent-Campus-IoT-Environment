"""
Smoke-test for src/coap/server.py + src/nodes/coap_node.py
Stubs out aiocoap so no UDP socket is opened.
"""
import sys, os, types, asyncio, json

sys.path.insert(0, '.')

# ── stub aiocoap ──────────────────────────────────────────────────────────
aiocoap_mod      = types.ModuleType('aiocoap')
resource_mod     = types.ModuleType('aiocoap.resource')
numbers_mod      = types.ModuleType('aiocoap.numbers')
media_types_mod  = types.ModuleType('aiocoap.numbers.media_types')

# Minimal Code enum-alike
class Code:
    CONTENT     = 'CONTENT'
    CHANGED     = 'CHANGED'
    BAD_REQUEST = 'BAD_REQUEST'

# Minimal Message
class Message:
    def __init__(self, code=None, payload=b'', content_format=None):
        self.code    = code
        self.payload = payload if isinstance(payload, bytes) else payload.encode()

# ObservableResource stub
class ObservableResource:
    def __init__(self): self._notified = 0
    def updated_state(self): self._notified += 1

# Resource stub
class Resource: pass

# Site stub
class Site:
    def __init__(self): self._routes = {}
    def add_resource(self, path, res): self._routes[path] = res

# Context stub
class Context:
    _shutdown = False
    @classmethod
    async def create_server_context(cls, site, bind=None):
        inst = cls()
        return inst
    async def shutdown(self):
        self._shutdown = True

aiocoap_mod.Code    = Code
aiocoap_mod.Message = Message
aiocoap_mod.Context = Context
aiocoap_mod.numbers = numbers_mod
numbers_mod.media_types_rev = {"application/json": 50}

resource_mod.ObservableResource = ObservableResource
resource_mod.Resource           = Resource
resource_mod.Site               = Site

sys.modules['aiocoap']          = aiocoap_mod
sys.modules['aiocoap.resource'] = resource_mod
sys.modules['aiocoap.numbers']  = numbers_mod

# ── stub Room ─────────────────────────────────────────────────────────────
class FakeRoom:
    building_id = 'b01'; floor_id = 1; room_id = 11
    node_id = 'b01-f01-r111'; protocol = 'coap'; coap_port = 5683
    temperature = 24.0; humidity = 55.0; occupancy = True
    light = 400; lighting_dimmer = 80; hvac_mode = 'OFF'; target_temp = 22.0

# ── import modules under test ─────────────────────────────────────────────
from src.coap.server import TelemetryResource, HvacActuatorResource, run_coap_server
from src.nodes.coap_node import CoapNode

room = FakeRoom()

# ─────────────────────────────────────────────────────────────────────────
# 1. TelemetryResource – render_get returns valid JSON
# ─────────────────────────────────────────────────────────────────────────
tel = TelemetryResource(room)
resp = asyncio.run(tel.render_get(None))
data = json.loads(resp.payload)
assert data['node_id']     == room.node_id
assert data['temperature'] == round(room.temperature, 1)
assert data['hvac_mode']   == 'OFF'
print('render_get payload OK:', list(data.keys()))

# ─────────────────────────────────────────────────────────────────────────
# 2. notify_watchers – triggers updated_state only on temp change
# ─────────────────────────────────────────────────────────────────────────
assert tel._notified == 0
asyncio.run(tel.notify_watchers())   # temp changed from None → 24.0 → notify
assert tel._notified == 1, f'Expected 1 notification, got {tel._notified}'

asyncio.run(tel.notify_watchers())   # same temp → no notify
assert tel._notified == 1, 'Should not re-notify on same temperature'

room.temperature = 25.5
asyncio.run(tel.notify_watchers())   # temp changed → notify
assert tel._notified == 2, f'Expected 2nd notification, got {tel._notified}'
print(f'notify_watchers: {tel._notified} notifications for 2 distinct temps — OK')

# ─────────────────────────────────────────────────────────────────────────
# 3. HvacActuatorResource – PUT applies hvac_mode and target_temp
# ─────────────────────────────────────────────────────────────────────────
hvac_res = HvacActuatorResource(room)

# 3a. Valid mode + target_temp
cmd = json.dumps({'hvac_mode': 'ECO', 'target_temp': 23.0}).encode()
req = Message(payload=cmd)
resp = asyncio.run(hvac_res.render_put(req))
assert resp.code == Code.CHANGED,    f'Expected CHANGED got {resp.code}'
assert room.hvac_mode == 'ECO',      f'hvac_mode not applied: {room.hvac_mode}'
assert room.target_temp == 23.0,     f'target_temp not applied: {room.target_temp}'

# 3b. ON resolves to COOLING (temp 25.5 > target 23.0)
cmd = json.dumps({'hvac_mode': 'ON'}).encode()
req = Message(payload=cmd)
asyncio.run(hvac_res.render_put(req))
assert room.hvac_mode == 'COOLING',  f'ON should resolve to COOLING, got {room.hvac_mode}'

# 3c. Bad payload → BAD_REQUEST
req_bad = Message(payload=b'not json')
resp_bad = asyncio.run(hvac_res.render_put(req_bad))
assert resp_bad.code == Code.BAD_REQUEST, 'Bad payload should return BAD_REQUEST'
print(f'render_put: hvac_mode={room.hvac_mode}, target_temp={room.target_temp} — OK')

# ─────────────────────────────────────────────────────────────────────────
# 4. run_coap_server – returns a Context (stubbed)
# ─────────────────────────────────────────────────────────────────────────
tel2 = TelemetryResource(room)
ctx = asyncio.run(run_coap_server(room, tel2))
assert isinstance(ctx, Context), 'run_coap_server must return a Context'
print('run_coap_server returned Context — OK')

# ─────────────────────────────────────────────────────────────────────────
# 5. CoapNode – start / notify / stop
# ─────────────────────────────────────────────────────────────────────────
node = CoapNode(room)

async def _test_node():
    await node.start()
    assert node._protocol is not None, 'protocol should be set after start()'
    room.temperature = 27.0
    await node.notify()   # should trigger a push
    assert node.telemetry._notified >= 1, 'notify() should call updated_state at least once'
    await node.stop()
    assert node._protocol is None, 'protocol should be None after stop()'

asyncio.run(_test_node())
print(f'CoapNode start/notify/stop — OK  (notifications={node.telemetry._notified})')

print('\nAll assertions passed.')

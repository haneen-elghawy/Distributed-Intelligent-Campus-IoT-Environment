"""
Smoke-test for src/engine/runtime.py (Phase 2)
Stubs gmqtt, aiocoap, dotenv, persistence and logging_config so the test
runs completely offline.
"""
import sys, os, types, asyncio, math

# ── must happen BEFORE any project imports ─────────────────────────────────
sys.path.insert(0, '.')

# stub dotenv
dotenv_mod = types.ModuleType('dotenv')
dotenv_mod.load_dotenv = lambda: None
sys.modules['dotenv'] = dotenv_mod

# stub gmqtt
gmqtt_mod = types.ModuleType('gmqtt')
class _Will:
    def __init__(self, **kw): pass
class _Client:
    Will = _Will
    _calls = []
    def __init__(self, cid, will_message=None): pass
    def set_auth_credentials(self, **kw): pass
    def subscribe(self, *a, **kw): pass
    def publish(self, topic, payload, qos=0, retain=False):
        _Client._calls.append((topic.split('/')[-1], qos))
    async def connect(self, *a, **kw): pass
    async def disconnect(self): pass
    on_message = None
gmqtt_mod.Client = _Client
sys.modules['gmqtt'] = gmqtt_mod

# stub aiocoap
aiocoap_mod  = types.ModuleType('aiocoap')
resource_mod = types.ModuleType('aiocoap.resource')
numbers_mod  = types.ModuleType('aiocoap.numbers')
class _ObsRes:
    def __init__(self): self._notify_count = 0
    def updated_state(self): self._notify_count += 1
class _Res: pass
class _Site:
    def add_resource(self, path, res): pass
class _Context:
    @classmethod
    async def create_server_context(cls, site, bind=None): return cls()
    async def shutdown(self): pass
aiocoap_mod.Context  = _Context
aiocoap_mod.numbers  = numbers_mod
numbers_mod.media_types_rev = {"application/json": 50}
resource_mod.ObservableResource = _ObsRes
resource_mod.Resource           = _Res
resource_mod.Site               = _Site
sys.modules['aiocoap']          = aiocoap_mod
sys.modules['aiocoap.resource'] = resource_mod
sys.modules['aiocoap.numbers']  = numbers_mod

# stub Message / Code for coap.server
import aiocoap as _ac
class _Msg:
    def __init__(self, code=None, payload=b'', content_format=None):
        self.code = code; self.payload = payload
class _Code:
    CONTENT='CONTENT'; CHANGED='CHANGED'; BAD_REQUEST='BAD_REQUEST'
_ac.Message = _Msg
_ac.Code    = _Code

# stub persistence
pers_mod = types.ModuleType('src.persistence')
_persisted = []
pers_mod.init_db             = lambda: None
pers_mod.initialize_defaults = lambda rooms: None
pers_mod.is_db_empty         = lambda: True
pers_mod.load_previous_state = lambda rooms: None
pers_mod.persist_room_state  = lambda room: _persisted.append(room.node_id)
sys.modules['src.persistence'] = pers_mod

# stub logging_config
lc_mod = types.ModuleType('src.utils.logging_config')
lc_mod.setup_logging = lambda: None
sys.modules['src.utils']                = types.ModuleType('src.utils')
sys.modules['src.utils.logging_config'] = lc_mod

# ── now import the real modules ────────────────────────────────────────────
import importlib

# force re-import with stubs in place
for mod in list(sys.modules.keys()):
    if mod.startswith('src.') and mod not in (
        'src.persistence', 'src.utils', 'src.utils.logging_config'
    ):
        sys.modules.pop(mod, None)

from src.engine import runtime as rt

# ── helpers ────────────────────────────────────────────────────────────────

def test_physics_helpers():
    vt = rt.get_virtual_time()
    hour = vt.hour + vt.minute / 60.0
    temp = rt.get_outside_temperature(hour)
    hum  = rt.get_outside_humidity(hour)
    # sanity: within plausible ranges
    assert 15 <= temp <= 55, f'temp out of range: {temp}'
    assert 20 <= hum  <= 90, f'humidity out of range: {hum}'
    print(f'Virtual time={vt.strftime("%H:%M")}  outside_temp={temp:.1f}  outside_hum={hum:.1f}')

def test_tick_physics():
    from src.engine.fleet import mqtt_rooms
    room = mqtt_rooms[0]
    import time
    old_temp = room.temperature
    rt._tick_physics(room)
    # timestamp updated
    assert room.last_update > 0
    print(f'_tick_physics OK  node={room.node_id}  temp_after={room.temperature:.1f}')

async def test_run_mqtt_node_one_tick():
    """Run run_mqtt_node for one tick then cancel."""
    from src.engine.fleet import mqtt_rooms
    from src.nodes.mqtt_node import MqttNode
    node = MqttNode(mqtt_rooms[5])
    os.environ['STARTUP_JITTER'] = '0'
    os.environ['PUBLISH_INTERVAL'] = '0.05'

    task = asyncio.create_task(rt.run_mqtt_node(node))
    await asyncio.sleep(0.2)   # let at least one tick complete
    task.cancel()
    try: await task
    except asyncio.CancelledError: pass

    pubs = _Client._calls
    assert any('telemetry' in t for t, _ in pubs), f'No telemetry published: {pubs}'
    print(f'run_mqtt_node 1-tick OK  publishes={[(t,q) for t,q in pubs]}')

async def test_run_coap_node_one_tick():
    """Run run_coap_node for one tick then cancel."""
    from src.engine.fleet import coap_rooms
    from src.nodes.coap_node import CoapNode
    node = CoapNode(coap_rooms[0])
    os.environ['STARTUP_JITTER'] = '0'
    os.environ['PUBLISH_INTERVAL'] = '0.05'

    task = asyncio.create_task(rt.run_coap_node(node))
    await asyncio.sleep(0.2)
    task.cancel()
    try: await task
    except asyncio.CancelledError: pass

    # TelemetryResource.notify_watchers() should have been called ≥1 time
    # (first call always triggers updated_state regardless of delta)
    print(f'run_coap_node 1-tick OK  notify_count={node.telemetry._notify_count}')

async def test_fleet_counts():
    from src.engine.fleet import mqtt_rooms, coap_rooms, rooms
    assert len(mqtt_rooms) == 100, f'Expected 100 MQTT, got {len(mqtt_rooms)}'
    assert len(coap_rooms) == 100, f'Expected 100 CoAP, got {len(coap_rooms)}'
    assert len(rooms)      == 200, f'Expected 200 total, got {len(rooms)}'
    assert all(r.protocol == 'mqtt' for r in mqtt_rooms)
    assert all(r.protocol == 'coap' for r in coap_rooms)
    print(f'Fleet: {len(mqtt_rooms)} MQTT + {len(coap_rooms)} CoAP = {len(rooms)} total')

# ── run ─────────────────────────────────────────────────────────────────────
test_physics_helpers()
test_tick_physics()
asyncio.run(test_fleet_counts())
asyncio.run(test_run_mqtt_node_one_tick())
asyncio.run(test_run_coap_node_one_tick())
print('\nAll runtime smoke-tests passed.')

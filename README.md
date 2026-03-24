# Distributed Intelligent Campus IoT Environment

A high-performance **World Engine** that simulates **200+ smart campus rooms** running concurrently, generating realistic IoT sensor data and streaming it via MQTT. Designed as a scalable, config-driven simulation with deterministic physics, fault injection, and bidirectional MQTT communication.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Async Engine                         │
│  ┌─────────┐ ┌─────────┐           ┌─────────┐         │
│  │ Room 1  │ │ Room 2  │    ...    │ Room N  │         │
│  │(asyncio)│ │(asyncio)│           │(asyncio)│         │
│  └────┬────┘ └────┬────┘           └────┬────┘         │
│       │            │                     │               │
│       └────────────┴──────────┬──────────┘               │
│                               │                          │
│  ┌──────────────┐  ┌─────────┴─────────┐  ┌──────────┐ │
│  │   SQLite     │  │   MQTT Broker     │  │  Logging │ │
│  │ Persistence  │  │   (Mosquitto)     │  │          │ │
│  └──────────────┘  │ pub ↑     ↓ sub   │  └──────────┘ │
│                    │ telemetry command  │                │
│                    └───────────────────┘                 │
└─────────────────────────────────────────────────────────┘
```

Each room is an independent async coroutine that per tick:
1. Updates occupancy based on time-of-day patterns
2. Controls HVAC automatically (ON/OFF/ECO with deadband)
3. Simulates temperature using Newton's Law of Cooling with configurable α/β
4. Simulates daylight (sine curve) + artificial lighting with dimmer control
5. Simulates humidity dynamics (leakage, occupancy, HVAC dehumidification)
6. Applies sensor faults (drift, frozen, delay, dropout)
7. Validates state ranges (temp 15-50°C, humidity 0-100%, light 0-1000 lux)
8. Publishes telemetry and heartbeat to MQTT
9. Listens for incoming commands (HVAC mode, target temp, dimmer)
10. Persists state to SQLite every 30 seconds

## Features

- **200+ concurrent rooms** — configurable via `NUM_FLOORS` × `ROOMS_PER_FLOOR`
- **Deterministic thermal physics** — `T_next = T + α(T_outside - T) + β × HVAC_power + occupancy_heat`
- **HVAC actuator logic** — ON/OFF/ECO modes with deadband controller (±0.5°C)
- **ECO mode** — half-power HVAC for energy-efficient operation
- **Occupancy simulation** — time-of-day patterns (70% daytime, 5% nighttime)
- **Light simulation** — sine-curve daylight + artificial lighting when occupied
- **Lighting dimmer** — 0-100% controllable smart lighting
- **Humidity simulation** — leakage, occupancy moisture, HVAC dehumidification
- **Day/night cycle** — outside temperature and humidity vary with virtual clock
- **Time acceleration** — run simulation faster than real-time
- **4 fault types** — sensor drift, frozen sensor, telemetry delay, node dropout
- **Heartbeat system** — per-room alive status monitoring
- **MQTT command subscriber** — receive and apply actuator commands in real-time
- **Startup jitter** — prevents thundering herd on MQTT broker
- **Precision drift compensation** — subtracts processing time from sleep interval
- **State validation** — clamps all values to specification ranges
- **SQLite persistence** — state saved periodically, restored on restart
- **Config-driven** — all parameters via `.env` / environment variables
- **Scalable** — change room count with a single config edit (no code changes)
- **Dockerized** — app + Mosquitto broker via docker-compose
- **Wokwi ESP32** — proof-of-concept with DHT22 + PIR + NTP + JSON validation
- **46 unit tests** — comprehensive coverage of all simulation logic

## Project Structure

```
├── src/
│   ├── __main__.py              # Entry point
│   ├── engine/
│   │   ├── fleet.py             # Creates N Room instances (configurable)
│   │   └── runtime.py           # Async engine: jitter, virtual clock, night cycle
│   ├── models/
│   │   └── room.py              # Room class: physics, HVAC ON/OFF/ECO, faults, validation
│   ├── mqtt/
│   │   └── publisher.py         # MQTT publish + command subscriber
│   ├── persistence/
│   │   └── sqlite_store.py      # SQLite save/load operations
│   └── utils/
│       └── logging_config.py    # Logging setup
├── tests/
│   ├── test_room.py             # Room model tests (41 tests)
│   ├── test_fleet.py            # Fleet creation tests (4 tests)
│   └── test_sqlite.py           # Persistence tests (5 tests)
├── wokwi/
│   ├── diagram.json             # Wokwi circuit: ESP32 + DHT22 + PIR
│   ├── sketch.ino               # Arduino: NTP sync, JSON validation, MQTT pub/sub
│   └── wokwi.toml               # Wokwi config
├── mosquitto/
│   └── config/mosquitto.conf    # Mosquitto broker config
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── config.yaml
├── .env
└── README.md
```

## Prerequisites

- Python 3.12+
- Docker & Docker Compose (for containerized run)
- MQTT broker (Mosquitto included in Docker Compose)

## Setup & Run

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Start an MQTT broker (if not using Docker)
mosquitto -c mosquitto/config/mosquitto.conf

# Run the simulation
python -m src
```

### Docker (Recommended)

```bash
# Build and start app + Mosquitto broker
docker-compose up --build

# Stop
docker-compose down
```

### Run Tests

```bash
python -m unittest discover tests/ -v
```

## MQTT Topics

### Telemetry (Published by Engine)
```
campus/bldg_01/floor_{FF}/room_{RRR}/telemetry
```

Payload:
```json
{
  "sensor_id": "b01-f05-r503",
  "timestamp": 1710000000,
  "temperature": 23.5,
  "humidity": 55.2,
  "occupancy": true,
  "light_level": 620,
  "lighting_dimmer": 80,
  "hvac_mode": "ECO"
}
```

### Heartbeat (Published by Engine)
```
campus/bldg_01/floor_{FF}/room_{RRR}/heartbeat
```

Payload:
```json
{
  "sensor_id": "b01-f05-r503",
  "timestamp": 1710000000,
  "status": "alive"
}
```

### Command (Received by Engine)
```
campus/bldg_01/floor_{FF}/room_{RRR}/command
```

Payload:
```json
{
  "hvac_mode": "ECO",
  "target_temp": 24.0,
  "lighting_dimmer": 60
}
```

## Data Specification

| Field | Type | Range | Description |
|-------|------|-------|-------------|
| sensor_id | String | Slug | Format: `b01-f10-r1001` |
| timestamp | Integer | Unix Epoch | Seconds since Jan 1, 1970 |
| temperature | Float | 15.0 - 50.0 | Celsius (°C) |
| humidity | Float | 0.0 - 100.0 | Relative Humidity (%) |
| occupancy | Boolean | true/false | Presence detection |
| light_level | Integer | 0 - 1000 | Lux |
| lighting_dimmer | Integer | 0 - 100 | Brightness (%) |
| hvac_mode | String | ON/OFF/ECO | Climate control state |

## Thermal Model

Newton's Law of Cooling (simplified):

```
T_next = T_current + α(T_outside - T_current) + β × HVAC_power + occupancy_heat
```

| Parameter | Value | Description |
|-----------|-------|-------------|
| α (alpha) | 0.01 (configurable) | Thermal leakage / insulation constant |
| β (beta) | 0.5 (configurable) | HVAC strength |
| HVAC_power | +1 (heating), -1 (cooling), ±0.5 (ECO), 0 (off) | Direction and intensity |
| occupancy_heat | +0.1°C | Body heat when room is occupied |

**Outside temperature** varies with a day/night sine cycle:
```
T_outside = base_temp + amplitude × sin(π × (hour - 8) / 12)
```

## Configuration

All parameters are configurable via `.env` or environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Logging level |
| `MQTT_BROKER` | `localhost` | MQTT broker hostname |
| `MQTT_PORT` | `1883` | MQTT broker port |
| `PUBLISH_INTERVAL` | `5` | Seconds between telemetry publishes |
| `TIME_ACCELERATION` | `1` | Virtual clock speed multiplier |
| `STARTUP_JITTER` | `5` | Max random startup delay (seconds) |
| `NUM_FLOORS` | `10` | Number of floors in building |
| `ROOMS_PER_FLOOR` | `20` | Rooms per floor |
| `OUTSIDE_TEMP` | `30` | Base outside temperature (°C) |
| `OUTSIDE_TEMP_AMPLITUDE` | `5` | Day/night temperature swing (°C) |
| `OUTSIDE_HUMIDITY` | `60` | Base outside humidity (%) |
| `OUTSIDE_HUMIDITY_AMPLITUDE` | `10` | Day/night humidity swing (%) |
| `THERMAL_ALPHA` | `0.01` | Thermal leakage constant |
| `THERMAL_BETA` | `0.5` | HVAC strength constant |
| `SQLITE_SAVE_INTERVAL_SECONDS` | `30` | State persistence interval |
| `FAULT_RATE` | `0.02` | Base fault probability per tick |
| `SENSOR_DRIFT_RATE` | `0.02` | Sensor drift probability |
| `FROZEN_SENSOR_RATE` | `0.02` | Frozen sensor probability |
| `TELEMETRY_DELAY_RATE` | `0.02` | Telemetry delay probability |
| `NODE_DROPOUT_RATE` | `0.02` | Node dropout probability |

### Scaling to 1000 Rooms

No code changes needed — just update `.env`:

```bash
NUM_FLOORS=20
ROOMS_PER_FLOOR=50
```

## Wokwi ESP32 (Proof of Concept)

The `wokwi/` directory contains the "Reference Room" — a single ESP32 node that:

- **DHT22** on GPIO 4 — reads temperature and humidity
- **PIR** motion sensor on GPIO 13 — detects occupancy
- **LED** on GPIO 2 — MQTT connection status indicator
- **NTP sync** — real Unix timestamps via `pool.ntp.org`
- **JSON validation** — validates all required fields before publishing
- **Command subscriber** — listens on `campus/.../command` topic
- Publishes to the same MQTT topic structure as the Python engine

To use: open `wokwi/diagram.json` in the [Wokwi Simulator](https://wokwi.com/).

## Monitoring

Subscribe to all campus MQTT messages:

```bash
mosquitto_sub -h localhost -t "campus/#" -v
```

Send a command to a room:

```bash
mosquitto_pub -h localhost -t "campus/bldg_01/floor_05/room_503/command" \
  -m '{"hvac_mode":"ECO","target_temp":24.0}'
```

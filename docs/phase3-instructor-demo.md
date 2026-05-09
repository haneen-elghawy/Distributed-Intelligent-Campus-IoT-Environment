# Phase 3 Instructor Demo Guide (Full-Marks Checklist)

This guide is the exact live demo flow to prove Phase 3 requirements end-to-end.

## 0) Prerequisites

- Docker Desktop is running.
- You are in the repository root:
  - `A:/ZC/Year_4_Spring/Internet of Things/Forked Repo/Distributed-Intelligent-Campus-IoT-Environment`
- `.env` contains valid ThingsBoard and HiveMQ credentials.

## 1) Start the Stack

Run:

```powershell
docker compose up -d --build
docker compose ps
```

Expected:
- `campus-hivemq`, `campus-thingsboard`, `campus-sim-engine`, and `campus-gateway-f01..f10` are `Up`.
- All gateway containers become `healthy`.

## 2) Validate Strict Readiness Gate

Run:

```powershell
python scripts/p3_predeploy_verify.py
```

Expected:
- Final line is `FINAL: PASS`.
- Includes:
  - `Metadata verifier: PASS`
  - `ACK contract verifier: PASS`

Note:
- On some Windows hosts, local TB HTTP may intermittently reset. The predeploy script now automatically falls back to the Docker-network metadata check and still enforces pass/fail correctly.

## 3) Validate Canonical ACK Contract (Runtime)

Run:

```powershell
docker exec campus-sim-engine python scripts/p3_shadow_sync.py --room b01-f01-r111 --hvac-mode COOLING --target-temp 22 --lighting-dimmer 35
```

Expected:
- JSON output with `"ok": true`
- ACK includes required correlation fields:
  - `cmd_id`
  - `correlation_id`
  - `room_id`
  - `status`
  - `timestamp`

## 4) Validate Floor Aggregation + occupancy_rate

Run:

```powershell
docker exec campus-gateway-f01 node -e "const mqtt=require('mqtt'); const c=mqtt.connect('mqtt://hivemq:1883',{clientId:'probe-floor-summary-demo'}); c.on('connect',()=>c.subscribe('campus/b01/f01/floor-summary')); c.on('message',(t,m)=>{console.log(m.toString()); c.end(true); process.exit(0);}); setTimeout(()=>{console.log('timeout'); c.end(true); process.exit(2);},80000);"
```

Expected payload contains:
- `avg_temperature`
- `avg_humidity`
- `occupied_rooms`
- `total_rooms`
- `occupancy_rate`

## 5) Validate OTA Security / Tamper Detection Path

Run:

```powershell
docker exec -e HIVEMQ_HOST=hivemq -e HIVEMQ_PORT=1883 -e HIVEMQ_USER=thingsboard -e HIVEMQ_PASS=tb_super_pass campus-sim-engine python scripts/p3_ota_publisher.py --target room:b01-f01-r111 --version 1.2 --alpha 0.03 --alert-test
```

Expected:
- Command prints `[ALERT TEST]` and `published.`
- Tampered payload is intentionally sent (post-signing mutation), which is the required negative-security case.

## 6) Verify Dashboard Artifacts are Regenerated

Run:

```powershell
python scripts/build_campus_noc_dashboard.py
python scripts/generate_floor_polygons.py
```

Expected artifacts:
- `thingsboard/dashboard_campus_noc.json`
- `thingsboard/floor_polygons.json`

These contain:
- Sync-status and desired/reported visibility keys
- Versioning keys (`current_version`, `config_version`)
- Spatial polygon definitions for all floors/rooms

## 7) ThingsBoard UI Demonstration Sequence

1. Log into ThingsBoard tenant.
2. Import `thingsboard/dashboard_campus_noc.json`.
3. Open Campus NOC dashboard.
4. Show:
   - Sync-related table/widget values updating
   - Fleet evolution/version status visibility
   - Floor summary data including `occupancy_rate`
5. Open image map widget setup and load polygon model from `thingsboard/floor_polygons.json` for room hotspots.

## 8) Grading Checklist Mapping (What to Say During Demo)

- Asset hierarchy + metadata: provisioned and metadata verifier-backed.
- Spatial polygons + tooltip fields: generated in `floor_polygons.json`.
- Command override/ACK loop: demonstrated with `p3_shadow_sync.py`.
- Desired vs reported sync visibility: included in converter + dashboard export.
- OTA broadcast/targeting + payload integrity: signed payloads with tamper rejection path.
- Fleet versioning: exposed in dashboard and sync payload fields.
- Objective verification: single readiness command returns PASS/FAIL.

## 9) One-Command Re-Run Pack (Before Instructor Arrives)

```powershell
docker compose up -d --build
python scripts/p3_predeploy_verify.py
docker exec campus-sim-engine python scripts/p3_shadow_sync.py --room b01-f01-r111 --hvac-mode COOLING --target-temp 22 --lighting-dimmer 35
```

If these are green, the phase is demo-ready.

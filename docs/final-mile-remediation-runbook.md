# Final-Mile Remediation Runbook (Comprehensive + AI Prompts)

This runbook is grounded in the current repository state and is designed to move the project from "mostly ready" to a stricter production-readiness posture.

It includes:
- step-by-step instructions,
- exact validation checkpoints,
- and a **copy-paste AI prompt after each step** so you can delegate execution to Cursor (or another AI coding agent).

---

## 0) Baseline and Important Reality Check

Before changing anything, align expectations with what is currently in this repository.

### What this repo currently shows

- `node-red/generate_gateway_flows.py` still emits `.../cmd-response` (not `.../response`).
- All generated flow files in `node-red/gateway-f01..f10/flows.json` still contain `cmd-response`.
- `scripts/p3_shadow_sync.py`, `scripts/p3_provision_metadata.py`, and other `p3_*` scripts referenced in your remediation summary are **not present** in this working tree.
- `src/nodes/mqtt_node.py` currently applies commands but does not publish standardized command ACK payloads with `cmd_id/correlation_id`.
- `docker-compose.yml` still has hardcoded `MQTT_USER/MQTT_PASS` values for floor gateways.

### Why this matters

Your pasted remediation summary appears to describe a different tree/branch/workspace snapshot than this current directory. This runbook assumes **this repository** is your canonical source and gets it to a clean, verifiable state.

### AI prompt for this step

```text
Audit this repository and produce a delta report between current state and expected remediation goals:
1) Confirm whether node-red/generate_gateway_flows.py uses cmd-response vs response.
2) Confirm whether node-red/gateway-f01..f10/flows.json contain cmd-response.
3) Confirm if scripts/p3_shadow_sync.py and other p3_* scripts exist.
4) Confirm whether src/nodes/mqtt_node.py publishes standardized ACK payloads with cmd_id/correlation_id.
5) Confirm if docker-compose.yml still hardcodes MQTT_USER/MQTT_PASS.
Return a concise pass/fail checklist and recommended next actions.
```

---

## 1) Create a Safe Working Branch and Snapshot

Do not start remediation directly on your default branch.

### Actions

1. Create a dedicated branch:
   - Example: `chore/final-mile-remediation`
2. Capture a working snapshot:
   - `git status`
   - `git diff --stat`
3. If there are unrelated local changes, keep them untouched and work carefully around them.
4. Record the current commit SHA in your notes/runbook.

### Validation checkpoint

- New branch is active.
- You have a baseline status snapshot and commit hash recorded.

### AI prompt for this step

```text
Create and switch to a new branch named chore/final-mile-remediation.
Then collect a baseline snapshot:
- git status
- git diff --stat
- git rev-parse --short HEAD
Return the outputs in a compact summary and confirm no files were modified by these commands.
```

---

## 2) Normalize Environment Secrets and Runtime Contract Inputs

You need strict, explicit env-driven configuration before enforcing protocol behavior.

### Actions

1. Add/update `.env.example` with non-secret placeholders for:
   - HiveMQ broker host/port.
   - Per-floor MQTT credentials (`MQTT_USER_FLOOR01` ... `MQTT_PASS_FLOOR10`).
   - Any command sync timeouts/retry configs you plan to enforce.
2. Ensure runtime scripts fail fast if required secrets are absent.
3. In `docker-compose.yml`, stop embedding plaintext defaults for floor credentials when possible; route via env interpolation.
4. Keep existing `.env` file private and out of commits if it contains secrets.

### Validation checkpoint

- Running without required credentials should fail with a clear message.
- `.env.example` is complete and non-sensitive.

### AI prompt for this step

```text
Implement environment hardening:
1) Add/update .env.example with all required non-secret placeholders.
2) Enforce fail-fast required-env checks where needed (especially runtime paths touching broker auth and command handling).
3) Refactor docker-compose.yml to read credentials from env variables instead of hardcoded per-floor secrets where feasible.
4) Keep backward compatibility clear and document required env vars in comments.
After edits, run a quick lint/syntax check and summarize all changed files.
```

---

## 3) Fix Command ACK Contract in Node-RED Flow Generator

This is the critical protocol repair point.

### Target

Update `node-red/generate_gateway_flows.py` so generated flows publish canonical ACKs on:
- topic suffix: `.../response` (canonical)
- payload fields: at minimum `cmd_id`, `correlation_id`, `room_id`, `status`, `timestamp`

### Actions

1. Locate Flow D command path in generator:
   - `D: commands` mqtt in
   - `D: cmd-router`
   - `D: cmd-response`
2. Persist enough command context from incoming command message to build deterministic ACK correlation:
   - topic
   - parsed command payload
   - identifiers from payload
3. Change ACK topic from `cmd-response` to `response`.
4. Emit structured ACK payload schema with strong fields.
5. Keep optional backward compatibility if needed:
   - either dual publish (`response` + legacy `cmd-response`) temporarily
   - or keep consumer compatibility in downstream script until migration is complete

### Validation checkpoint

- Generator source no longer emits only weak `cmd-response`.
- ACK payload includes correlation fields, not just `ok/coap_status/ts`.

### AI prompt for this step

```text
Modify node-red/generate_gateway_flows.py Flow D to implement canonical ACKs:
- Publish ACK topic as .../response.
- Include payload fields: cmd_id, correlation_id, room_id, status, timestamp, and any applied actuator values if present.
- Preserve deterministic correlation by storing original command context before CoAP call.
- Keep temporary backward compatibility strategy (dual topic or documented fallback).
After editing, show the exact function-node logic changes and explain migration behavior.
```

---

## 4) Regenerate and Verify All 10 Gateway Flow Artifacts

Changing the generator is not enough; you must regenerate static `flows.json`.

### Actions

1. Run:
   - `python node-red/generate_gateway_flows.py`
2. Confirm updates across all:
   - `node-red/gateway-f01/flows.json` through `node-red/gateway-f10/flows.json`
3. Verify topic contract in generated files:
   - canonical `.../response` appears,
   - legacy-only `cmd-response` no longer the sole contract.
4. Verify `package.json` in each gateway folder remains valid.

### Validation checkpoint

- All 10 `flows.json` are regenerated in one pass.
- Search-based contract checks pass across all floor files.

### AI prompt for this step

```text
Run the Node-RED flow generator and verify all generated artifacts:
1) Execute python node-red/generate_gateway_flows.py
2) Confirm all gateway-f01..gateway-f10/flows.json changed as expected
3) Search every generated flow for response/cmd-response topic usage and report counts
4) Flag any floor that still has legacy-only behavior
Return a floor-by-floor verification summary.
```

---

## 5) Implement/Align Consumer-Side ACK Validation (Shadow/Sync Layer)

If your ACK consumer still expects old shape/topics, you will keep seeing false out-of-sync behavior.

### Actions

1. Identify the command-sync consumer script/module in this repo (if different naming from `p3_shadow_sync.py`).
2. Enforce strict schema checks for canonical ACK.
3. Add compatibility parser for legacy `cmd-response` only as fallback.
4. Subscribe to both topics during migration window:
   - `.../response` (preferred)
   - `.../cmd-response` (fallback)
5. Add retry policy knobs (env-controlled):
   - max retries
   - ack timeout seconds
6. Persist desired/reported tracking fields needed for dashboard visibility and debugging.

### Validation checkpoint

- Canonical ACK path is primary.
- Legacy path exists only for transition and is clearly marked.

### AI prompt for this step

```text
Find the command-sync/shadow synchronization component in this repository (even if file name differs from p3_shadow_sync.py) and implement:
1) strict canonical ACK schema validation for .../response
2) backward-compatible parser for .../cmd-response
3) dual-topic subscription during migration
4) retry + timeout controls via env vars
5) desired/reported sync state persistence fields
Then provide testable examples of accepted and rejected ACK payloads.
```

---

## 6) Add Deterministic Entity Lookup Utility and Replace Fuzzy Calls

This prevents silent wrong-entity writes in ThingsBoard operations.

### Actions

1. Add a helper module (e.g., `scripts/tb_entity_lookup.py`) that:
   - fetches candidate entities,
   - enforces exact name matching,
   - fails clearly on 0 or >1 exact matches.
2. Replace any text-search-first-result logic in TB-related scripts.
3. Add clear exceptions/logging for ambiguity.

### Validation checkpoint

- No script uses `pageSize=1` + "first result wins" behavior for critical writes.

### AI prompt for this step

```text
Create a deterministic ThingsBoard entity lookup helper and refactor all TB scripts to use it.
Requirements:
- exact-match enforcement by canonical name
- explicit errors for ambiguous or missing entities
- no silent fallback to first search result
After refactor, list every script that was updated and show before/after lookup behavior.
```

---

## 7) Reconcile Asset/Device Naming Conventions and Repair Legacy Names

Name mismatch causes metadata scripts to skip targets or update the wrong entities.

### Actions

1. Define canonical room naming (e.g., `b01-fNN-rRRR`) in one place.
2. Audit scripts that generate, provision, or patch metadata names.
3. Add migration utility to repair legacy prefixes (e.g., `Room-...`).
4. Add a dry-run mode before actual renames.

### Validation checkpoint

- All scripts use one naming contract.
- Repair script can report and fix legacy names predictably.

### AI prompt for this step

```text
Standardize room asset naming across provisioning and metadata scripts to one canonical format.
Then add a repair script with:
- dry-run mode
- apply mode
- clear report of renamed entities
Also remove code paths that introduce divergent naming side effects.
```

---

## 8) Extend Floor Aggregation and Converter Mapping (`occupancy_rate`)

Aggregation consistency should exist from edge computation through TB converter to dashboard.

### Actions

1. Update floor summary computation in Node-RED generation:
   - `occupancy_rate = occupied_rooms / total_rooms` (guard divide-by-zero).
2. Update `thingsboard/uplink_converter_hivemq.js` floor-summary branch to map `occupancy_rate`.
3. Keep numeric typing consistent.

### Validation checkpoint

- Floor summary telemetry contains `occupancy_rate`.
- TB converter forwards it for FloorSummary devices.

### AI prompt for this step

```text
Implement occupancy_rate end-to-end:
1) Add occupancy_rate in floor summary generation (Node-RED flow generator)
2) Map occupancy_rate in thingsboard/uplink_converter_hivemq.js floor-summary conversion
3) Ensure numeric typing and null safety
Then verify generated gateway flows and converter logic are consistent.
```

---

## 9) Regenerate Campus NOC Dashboard Export with Sync-Focused Widgets

Dashboard export should reflect real sync observability needs.

### Actions

1. Update `scripts/build_campus_noc_dashboard.py`:
   - add sync-state keys (desired vs reported fields),
   - add `occupancy_rate` in floor summary table.
2. Regenerate:
   - `python scripts/build_campus_noc_dashboard.py`
3. Verify `thingsboard/dashboard_campus_noc.json` includes new data keys and expected aliases.

### Validation checkpoint

- Exported dashboard JSON contains required telemetry keys.
- Import into TB works without schema errors.

### AI prompt for this step

```text
Enhance scripts/build_campus_noc_dashboard.py to include:
- sync-status visibility keys (desired/reported pairs and sync status fields)
- occupancy_rate in floor summary widgets
Regenerate thingsboard/dashboard_campus_noc.json and verify the new keys exist in the export.
Return a concise list of added data keys and affected widgets.
```

---

## 10) Add Verification Utilities (Metadata and Contract Checks)

You need scriptable proof, not manual confidence.

### Actions

1. Add `scripts/p3_verify_metadata.py` equivalent (or extend existing verifier scripts) to check:
   - required server attributes on room assets/devices,
   - naming conformity,
   - missing telemetry keys where applicable.
2. Add ACK contract verification script/test for:
   - canonical topic and schema,
   - legacy fallback acceptance policy.
3. Integrate checks into a single "pre-deploy verify" command.

### Validation checkpoint

- One command provides pass/fail readiness signal with actionable failures.

### AI prompt for this step

```text
Add automated verification scripts for final-mile readiness:
1) metadata completeness checker for room entities
2) ACK contract checker for canonical and legacy fallback behavior
3) aggregate a single pre-deploy verify command with clear exit codes
Then run the verifiers and provide a pass/fail report with remediation hints.
```

---

## 11) Bring Up Stack and Redeploy Flow-Dependent Services

Changes to flow artifacts and converters require container restart/reload.

### Actions

1. Start/restart stack:
   - `docker compose up -d --build`
2. Restart Node-RED gateway containers if needed after flow regeneration.
3. Confirm container health/status:
   - HiveMQ, sim-engine, ThingsBoard, gateway-f01..f10 are running.

### Validation checkpoint

- All required containers are healthy.
- New flow files are mounted and active in gateways.

### AI prompt for this step

```text
Redeploy services to apply regenerated flows and script changes:
1) run docker compose up -d --build
2) ensure all gateway-f01..f10 containers are running
3) verify Node-RED instances are using updated /data/flows.json
4) report any unhealthy services and likely root causes
Provide a concise service health table in plain text.
```

---

## 12) Execute Runtime Validation Scenarios (E2E)

Run targeted scenarios to verify contract behavior in real traffic.

### Scenario A: Command ACK contract

1. Publish a command with `cmd_id` and `correlation_id`.
2. Observe ACK on `.../response`.
3. Verify fields: `cmd_id`, `correlation_id`, `room_id`, `status`, `timestamp`.
4. Verify sync consumer marks success (not out-of-sync false negatives).

### Scenario B: Legacy fallback (if enabled)

1. Simulate legacy ACK shape/topic.
2. Confirm fallback parsing works and logs deprecation warning.

### Scenario C: Floor summary and occupancy rate

1. Observe `floor-summary` MQTT messages.
2. Confirm `occupancy_rate` present and reasonable.
3. Confirm converter telemetry in TB includes the value.

### Scenario D: Tamper/alerts traceability (if implemented)

1. Trigger representative alert path.
2. Verify alarm details include available forensics metadata.

### Validation checkpoint

- All scenarios produce expected results with no contract ambiguity.

### AI prompt for this step

```text
Run focused E2E runtime checks:
A) command->ACK loop using canonical response contract
B) legacy fallback behavior (if enabled)
C) floor-summary occupancy_rate propagation to ThingsBoard
D) alert/tamper metadata traceability (if implemented)
For each scenario, provide:
- exact test action
- observed output
- pass/fail
- next fix if failed
```

---

## 13) Clean Workspace Topology (Duplicate Tree / Wrong Root Prevention)

Prevent future confusion where changes are made in one tree and run in another.

### Actions

1. Confirm canonical runtime root path for developers and CI.
2. Remove or archive duplicate nested project trees that can mislead tooling.
3. Add a short `docs/WORKSPACE_CONVENTIONS.md` noting:
   - canonical root,
   - forbidden duplicate structure,
   - expected command execution directory.

### Validation checkpoint

- All developers and automation target one root consistently.

### AI prompt for this step

```text
Help me canonicalize workspace layout:
1) detect duplicate project roots or nested mirrors
2) propose safe cleanup plan (no destructive actions without confirmation)
3) add docs/WORKSPACE_CONVENTIONS.md with canonical root and execution rules
Return exact paths flagged and a recommended cleanup sequence.
```

---

## 14) Final Readiness Gate (Strict)

Use objective gates before declaring READY.

### Gate checklist

- [ ] ACK canonical contract active (`.../response`, strong payload schema)
- [ ] Legacy fallback strategy defined and temporary
- [ ] All 10 Node-RED flows regenerated and deployed
- [ ] Env secrets hardening applied, no risky defaults in code paths
- [ ] Entity lookup deterministic (no fuzzy first-result writes)
- [ ] Naming conventions unified + repair path available
- [ ] Dashboard export includes sync and occupancy metrics
- [ ] Verification scripts pass
- [ ] Runtime E2E scenarios pass

### AI prompt for this step

```text
Run a strict final readiness assessment using this checklist:
1) ACK contract and migration status
2) flow regeneration/deployment status for all 10 floors
3) secrets/env hardening status
4) deterministic entity lookup status
5) naming consistency and migration status
6) dashboard/telemetry observability status
7) verification + E2E runtime test status
Return:
- READY / NOT READY verdict
- numeric readiness score
- top 3 remaining blockers (if any)
- exact remediation actions for each blocker.
```

---

## Suggested Execution Order (Fastest Path)

If you want the quickest meaningful path to "strict ready":

1. Step 3 + Step 4 (ACK contract and flow regeneration)
2. Step 5 (consumer-side ACK sync logic)
3. Step 8 + Step 9 (occupancy and dashboard observability)
4. Step 10 + Step 12 (verification and E2E)
5. Step 13 + Step 14 (workspace hygiene and final gate)

---

## Notes on Current Repository Evidence

This runbook is aligned to concrete files currently present:
- `node-red/generate_gateway_flows.py`
- `node-red/gateway-f01..f10/flows.json`
- `src/nodes/mqtt_node.py`
- `thingsboard/uplink_converter_hivemq.js`
- `scripts/build_campus_noc_dashboard.py`
- `docker-compose.yml`
- `scripts/verify_phase2_deliverables.py`

If your newer remediation code exists in another branch or directory, run Step 0 first and then either:
- merge that code into this canonical tree, or
- run this runbook inside the actual remediation tree and keep only one canonical root.

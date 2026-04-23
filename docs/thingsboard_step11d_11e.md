# Step 11d & 11e — Very detailed (ThingsBoard UI)

Use this with your repository **unchanged** — credentials and scripts match:

- **HiveMQ (RBAC in repo):** user `thingsboard`, password `tb_super_pass`  
- **Broker (from the ThingsBoard *container*):** host `hivemq`, port `1883`  
- **Uplink file to paste:** `thingsboard/uplink_converter_hivemq.js`  
- **Rule chain files:** `thingsboard/rule_chain_campus_alarms.json` and/or `thingsboard/rule_chain_root.json` (same logic)

Log in as your **tenant administrator** (e.g. `tenant@campus.io`), not the system admin, for devices and integrations in that tenant.

**Important — edition:** The **Integrations** and **Data converters** flows below match **ThingsBoard Professional Edition (PE)** and some bundles. The public Docker image **`thingsboard/tb-postgres`** is often **Community Edition (CE)**, which **may not** show **Integrations** at all. If you do not see the menus in **11d**, see **§11d — If your ThingsBoard is CE** at the end; ask your course which image to use. **11e (Rule chains)** is available in **CE** and **PE**.

---

# Part 11d — HiveMQ integration + Uplink data converter

## What you are building

ThingsBoard will act as an **MQTT client** to **HiveMQ**, subscribe to **`campus/#`**, and for each message run your **JavaScript uplink converter** to map MQTT payloads into **device names, telemetry, and attributes** so your **200** provisioned devices receive data.

**Network requirement:** The **ThingsBoard** container and **HiveMQ** must be on the **same Docker network** (e.g. `campus-net` in your `docker-compose.yml`) so the hostname **`hivemq`** resolves from **inside** the ThingsBoard container. Your PC browser uses `localhost:9090`; the integration **Host** is **not** `localhost` (that would mean “inside the TB container, connect to the TB container itself”).

## Prerequisites (check before you click)

1. **Docker stack** up: at least `campus-hivemq` and `campus-thingsboard` on the same compose network.  
2. **Devices provisioned** (e.g. `python scripts/provision_tb.py` completed) so **Entities → Devices** lists rooms like `b01-f01-r101`, …  
3. **Device profiles** exist: at least `MQTT-ThermalSensor` and `CoAP-ThermalSensor` (Step 11a).  
4. **File ready:** open `thingsboard/uplink_converter_hivemq.js` in an editor, **Select All** → **Copy** (you will paste the full file, including the `/**` header block).

## Step 11d-A — Create the **Uplink** data converter

1. In the left sidebar, look for one of:  
   - **Advanced features** → **Data converters**  
   - **Integration center** → **Data converters**  
   - or **Data converters** (top level, depending on version)

2. Open **Data converters**.

3. Click the **+** (plus) or **Add data converter** (wording may be **Create**).

4. **Name:** e.g. `HiveMQ campus uplink` (any name; you will pick it in the integration).

5. **Type:** choose **Uplink** (not Downlink-only). If the wizard shows **Uplink and Downlink**, that is fine; the repo only needs the uplink path.

6. In the **JavaScript** / **Decoder** / **Uplink** code area:  
   - Remove any default sample code.  
   - **Paste the entire** contents of `thingsboard/uplink_converter_hivemq.js` (all lines, through the last `};` of the default telemetry return).

7. If the form has a **“Test”** or **“Debug”** / **“Payload”** / **“Topic”** test panel (optional):
   - **Topic:** e.g. `campus/b01/f01/r101/telemetry`  
   - **Payload (example):** a small JSON like  
     `{"node_id":"b01-f01-r101","ts":1700000000,"temperature":22.1,"humidity":45,"occupancy":true,"hvac_mode":"ECO"}`  
   - Run the test. You should see a structured result with `deviceName` and `telemetry` keys. If the editor flags `decodeToJson` as unknown, that is normal—ThingsBoard **provides** that function at runtime; ignore strict IDE checks inside TB.

8. **Save** / **Add** the converter. Confirm the new row appears in the **Data converters** list.

## Step 11d-B — Create the **MQTT** integration

1. In the left sidebar, open **Integrations** (names vary: **Integrations center**, **Integrations**, **Data integrations**).

2. Click **+** to add an integration.

3. Choose the integration type **MQTT** (sometimes **Custom MQTT** or **Remote MQTT**).

4. **General / Basic:**
   - **Name:** e.g. `HiveMQ Campus Integration` (must be unique in the tenant).  
   - **Type:** **MQTT** (confirm it is the consumer/subscriber, not a publishing-only integration if the UI offers both).

5. **Broker connection** (wording may be **Connection** / **MQTT** / **Client**):
   - **Host:** `hivemq`  
   - **Port:** `1883`  
   - **Client ID:** any unique string, e.g. `tb-campus-integr-1` (some UIs require this; if omitted, the server may auto-generate—follow your form).

6. **Subscription / topics:**
   - **Topic filter** or **Filter** or **Topic:** `campus/#`  
   - **QoS:** if offered, use **0** or **1** (either is usually fine for development; the repo does not require QoS 2 for uplink).

7. **Security / authentication:**
   - **Username:** `thingsboard`  
   - **Password:** `tb_super_pass`  
   (These must match `hivemq/extensions/.../credentials.xml` in your repo.)

8. **TLS / SSL:** leave **off** for plain **1883** in development (matches your current HiveMQ setup using the clear-text listener in `docker-compose`).

9. **Processing / converter:**
   - **Uplink data converter:** select **`HiveMQ campus uplink`** (the name you set in 11d-A).  
   - If the UI has **Downlink** converter, you can leave **None** unless your course adds RPC downlink later.

10. **Enable** the integration: toggle **Enabled** / **Active** to **on** (exact label varies).

11. **Save** the integration (button may be **Add**, **Save**, **Apply**).

## Step 11d-C — Connection test and troubleshooting

1. If the **Integration** details page has **Check connection**, **Test connection**, or **Debug**, run it. A **success** means ThingsBoard reached `hivemq:1883` and authenticated.  
2. If it **fails**:
   - Confirm **Host** is exactly `hivemq` (not `localhost`) when ThingsBoard runs in Docker.  
   - `docker ps` and confirm both `campus-thingsboard` and `campus-hivemq` are on the same **network** name as in `docker-compose.yml`.  
   - From the host, run: `docker logs campus-thingsboard` (or your TB container name) and look for MQTT connection, auth, or DNS errors for `hivemq`.  
3. **HiveMQ Control Center** (`http://localhost:8080`, from your **browser** on the **host**): under **Clients**, you should see a new connected client (ThingsBoard) when the integration is active.

## Step 11d-D — End-to-end test (telemetry on a device)

1. Start the full simulation path so HiveMQ has traffic, e.g. `docker compose up -d` including **sim-engine** and **Node-RED** gate ways as in your project.  
2. Wait 30–90 seconds.  
3. In ThingsBoard: **Entities** → **Devices** → open e.g. **`b01-f01-r101`**.  
4. Open the **Latest telemetry** / **Telemetries** tab.  
5. You should see keys such as `temperature`, `humidity`, `hvac_mode`, `occupancy`, and possibly `device_status` / `connection_status` (see your converter). Values should **update** over time, not stay permanently empty.  
6. If **nothing** appears: confirm messages exist on `campus/#` in HiveMQ (Control Center or MQTT sub); then re-check the integration is **Enabled** and the **Uplink** converter is selected; finally check **Data converters** for typos in the pasted script.

## Step 11d — If your ThingsBoard is **CE** (no Integrations / Data converters)

- You will **not** be able to follow 11d-A–B in the UI. Options depend on the course: use a **PE** image, a **course-provided** server, or an alternate design (e.g. devices using ThingsBoard’s **own** MQTT, or a small bridge) — confirm with the instructor. **Do not** block Step **11e** on this: rule chains (below) can still be completed on CE.

---

# Part 11e — Rule engine: import chain + connect to **Root**

## What you are building

- **Save Timeseries** so telemetry is stored.  
- A **Script filter** that is **true** when `temperature` is out of range (`< 16` or `> 35`).  
- A **Create alarm** node with type **`TEMPERATURE_THRESHOLD`**, severity **CRITICAL** (or as in the JSON you import).

The repository exports this as a **standalone** (non-root) rule chain. You **import** it, then you **connect** the **“Post telemetry”** path of the **Root** rule chain to this new chain (or you merge the nodes by hand). Exact labels depend on **ThingsBoard 3.4+ / 4.x**; the goal is: **for each device, after telemetry enters TB,** first **save** it, then **evaluate** the temperature script, then **create alarm** if the filter passes.

## Prerequisites

1. You **already** receive **Post telemetry** (from integration in PE, or from devices using TB MQTT/HTTP/CoAP in other setups).  
2. The files **`thingsboard/rule_chain_campus_alarms.json`** or **`thingsboard/rule_chain_root.json`** are on your PC (for **Import**).

## Step 11e-A — Import the **Campus** rule chain

1. Left menu: **Rule chains** (sometimes under **Rule engine** in older UIs).  
2. Click **+** (Add rule chain) or use the **Import** / **import rule chain** action if shown at list level.  
3. If you use **Import** from a file:  
   - **Choose file:** `thingsboard/rule_chain_campus_alarms.json` (or `rule_chain_root.json` — same three-node graph).  
   - Confirm **name** in the preview, e.g. **Campus Temperature Alarms** (or the name inside the JSON).  
4. **Save** / **Import**. The new chain must **not** be marked as **Root** in the list (in the export, `root: false` — you did not replace the system Root).  
5. Open the **imported** chain in the **Editor** (pencil or **Open**). You should see **three** nodes in this order:  
   - **Save Timeseries**  
   - **Temp out of range** (Script / JS filter)  
   - **Create TEMPERATURE_THRESHOLD** (Create alarm)  
   and connections **Save Timeseries** → **Temp** → **Create alarm** (Success links).

6. (Optional) Click **Test** (if available) on the chain with a fake message containing `msg.temperature` to see if the **filter** and **alarm** path behave as expected.

## Step 11e-B — Open the **Root** rule chain

1. In **Rule chains**, select the **Root** (or **Root Rule Chain**). It is the **default** entry for all device and integration traffic in many setups.  
2. Open the **graph editor** (visual canvas).

3. Find how **incoming** messages are classified. In many versions you will see:  
   - a **“Message type switch”** node (or **Input** with branches), with outputs such as **Post telemetry**, **Post attribute**, **Request**, **RPC request**, etc.

4. Locate the line that carries **“Post telemetry”** (or **Telemetry published** / **Timeseries** — wording varies). This is the branch that must **eventually** reach your **Save timeseries** logic for device telemetry.

5. **Do not delete** unrelated branches (Attributes, RPC, etc.).

## Step 11e-C — Connect **Post telemetry** to the **Campus** chain

**Preferred pattern (sub-rule-chain):**  
1. On the **Post telemetry** output wire, if it currently goes to a **Save timeseries** or similar, you can **insert** a **Rule chain** node (or **Call rule chain** / **Goto** — label varies):  
   - **Target / Rule chain:** select **Campus Temperature Alarms** (the imported one).  
2. The **imported** chain already **starts** with **Save timeseries** → **filter** → **alarm**, so the **input** to **Campus Temperature Alarms** should be the same **msg** the Root chain would have passed for Post telemetry.  
3. If the old Root path also had a **Save timeseries** right after Post telemetry, you must **avoid double-saving** or leave only **one** save path. Simplest: **remove** the duplicate **Save timeseries** on Root **for that branch only** and let the **imported** chain be the only save + alarm path for telemetry; **or** keep Root’s save and **remove** the first node from the campus chain in the **UI** (advanced) — the repo is built so **one** **Save timeseries** at the start of the campus chain is enough.  
4. **Save** / **Apply** the **Root** rule chain. Some systems require a **version** or **Save** and **Activate**.

**If your UI has no “call rule chain” but allows copy-paste:**  
- Open the **imported** chain, **export** the three nodes (if your version supports partial export) or **manually** add the same **three** nodes to **Root** on the **Post telemetry** line in order: **Save timeseries** → **JS filter** (same condition as the JSON) → **Create alarm** (same `TEMPERATURE_THRESHOLD` settings), then connect **Post telemetry** to **Save timeseries**. This duplicates the file logic without a separate chain.

## Step 11e-D — Alarms: optional occupancy filter (guide text)

The Phase 2 guide also mentions a **Script filter** for **occupancy *changes***. The **imported** JSON only implements **temperature** limits. “**Changes**” usually requires **state** (previous value). Practical options:

- Add a **second** branch from the same **Post telemetry** (or after **Save timeseries**) with a **Script** node that only checks **valid** boolean `occupancy` (no “change” detection), or  
- Use **Alarms** / **Rule chain** with **Customer / Device attributes** to store the last value (more setup), or  
- Ask the instructor if **temperature** alarms are sufficient for the rubric.

## Step 11e-E — Test alarms

1. With **sim** running, force a high or low room temperature in the world engine (or temporary script) so **temperature** is **> 35** or **< 16** for a test device.  
2. **Alarms** (left menu) → filter by type **`TEMPERATURE_THRESHOLD`** and device if needed.  
3. A **CRITICAL** (or as configured) alarm should **appear** for that device.  
4. If not: use **Debug** on the **Root** and **Campus** chains, enable **Debug** on individual nodes, and re-send or wait for the next telemetry tick.

## Step 11e-F — Re-export (submission)

If your grader wants an export **from the live** server:  
- **Rule chains** → your **Campus** chain → **⋮** (three dots) → **Export** → save JSON.  
- Keep a copy in `thingsboard/` for Git if required. The repo’s **`rule_chain_campus_alarms.json`** is the **reference** copy.

---

## One-page order of operations (11d + 11e)

1. **(11d-A)** Data converter: paste `uplink_converter_hivemq.js` → **Save**.  
2. **(11d-B)** Integration MQTT: `hivemq`, `1883`, `campus/#`, `thingsboard` / `tb_super_pass`, select uplink converter → **Enabled** → **Save**.  
3. **(11d-D)** **Devices** → one room → **Latest telemetry** updates.  
4. **(11e-A)** **Import** `rule_chain_campus_alarms.json`.  
5. **(11e-B–C)** **Root** → connect **Post telemetry** to **Campus** chain (or merge three nodes) → **Save**.  
6. **(11e-E)** Trigger out-of-range temp → **TEMPERATURE_THRESHOLD** alarm.  

If **11d** is impossible (CE), still do **11e** and document that integration was N/A for your build.

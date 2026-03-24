import network
import time
import json
import machine
import dht
import ntptime

from umqtt.simple import MQTTClient

# --- Pin Definitions ---
DHT_PIN = 4
PIR_PIN = 13
LED_PIN = 2

# --- MQTT Config ---
MQTT_BROKER = "test.mosquitto.org"
MQTT_PORT = 1883
CLIENT_ID = "esp32-campus-room-001"

# --- MQTT Topics ---
TELEMETRY_TOPIC = "campus/bldg_01/floor_01/room_001/telemetry"
HEARTBEAT_TOPIC = "campus/bldg_01/floor_01/room_001/heartbeat"
COMMAND_TOPIC = "campus/bldg_01/floor_01/room_001/command"

# --- Timing ---
TELEMETRY_INTERVAL = 5   # seconds
HEARTBEAT_INTERVAL = 10  # seconds

# --- Required telemetry fields for validation ---
REQUIRED_FIELDS = ["sensor_id", "timestamp", "temperature", "humidity",
                   "occupancy", "light_level", "hvac_mode"]

# --- Hardware Setup ---
dht_sensor = dht.DHT22(machine.Pin(DHT_PIN))
pir_sensor = machine.Pin(PIR_PIN, machine.Pin.IN)
led = machine.Pin(LED_PIN, machine.Pin.OUT)
led.value(0)


def connect_wifi():
    """Connect to WiFi (required in Wokwi before any network call)."""
    print("Connecting to WiFi...", end="")
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect("Wokwi-GUEST", "")
    while not wlan.isconnected():
        print(".", end="")
        time.sleep(0.5)
    print(" Connected!")
    print("IP:", wlan.ifconfig()[0])


def sync_ntp():
    """Synchronize time with NTP server for real Unix timestamps."""
    print("Syncing NTP time...", end="")
    retries = 0
    while retries < 5:
        try:
            ntptime.settime()
            print(" Synced!")
            t = time.localtime()
            print("UTC Time: {}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(*t[:6]))
            return True
        except Exception:
            print(".", end="")
            retries += 1
            time.sleep(1)
    print(" NTP sync failed, using uptime fallback")
    return False


def get_unix_timestamp():
    """Return current Unix timestamp (seconds since 1970-01-01).
    MicroPython epoch starts at 2000-01-01, so we add the offset."""
    EPOCH_OFFSET = 946684800  # seconds between 1970 and 2000
    return time.time() + EPOCH_OFFSET


def validate_telemetry(payload_dict):
    """Validate that the telemetry JSON contains all required fields."""
    for field in REQUIRED_FIELDS:
        if field not in payload_dict:
            print("JSON validation failed: missing field '{}'".format(field))
            return False
    return True


def on_command(topic, msg):
    """Handle incoming MQTT command messages."""
    try:
        payload = msg.decode()
    except Exception:
        print("Command rejected: cannot decode payload")
        return

    if not payload.startswith("{") or not payload.endswith("}"):
        print("Command rejected: malformed JSON:", payload)
        return

    try:
        data = json.loads(payload)
    except ValueError:
        print("Command rejected: invalid JSON:", payload)
        return

    print("Command received:", payload)

    if "hvac_mode" in data:
        mode = data["hvac_mode"]
        if mode in ("ON", "OFF", "ECO", "COOLING", "HEATING"):
            print("Processing HVAC mode command:", mode)
        else:
            print("Command rejected: invalid hvac_mode:", mode)
    elif "target_temp" in data:
        print("Processing target temperature command:", data["target_temp"])
    elif "lighting_dimmer" in data:
        print("Processing lighting dimmer command:", data["lighting_dimmer"])
    else:
        print("Command rejected: no recognized fields")


def connect_mqtt():
    """Connect to MQTT broker and subscribe to command topic."""
    print("Connecting to MQTT broker {}:{}...".format(MQTT_BROKER, MQTT_PORT), end="")
    client = MQTTClient(CLIENT_ID, MQTT_BROKER, port=MQTT_PORT)
    client.set_callback(on_command)
    client.connect()
    print(" Connected!")
    led.value(1)

    client.subscribe(COMMAND_TOPIC)
    print("Subscribed to:", COMMAND_TOPIC)
    return client


def read_sensors():
    """Read DHT22 temperature/humidity and PIR occupancy."""
    try:
        dht_sensor.measure()
        temperature = dht_sensor.temperature()
        humidity = dht_sensor.humidity()
    except OSError:
        print("DHT22 read failed, skipping...")
        return None

    occupancy = pir_sensor.value() == 1
    return {
        "temperature": temperature,
        "humidity": humidity,
        "occupancy": occupancy,
    }


def build_telemetry_payload(sensor_data):
    """Build and validate the telemetry JSON payload."""
    payload = {
        "sensor_id": "b01-f01-r001",
        "timestamp": get_unix_timestamp(),
        "temperature": round(sensor_data["temperature"], 1),
        "humidity": round(sensor_data["humidity"], 1),
        "occupancy": sensor_data["occupancy"],
        "light_level": 0,
        "lighting_dimmer": 0,
        "hvac_mode": "N/A",
    }

    if not validate_telemetry(payload):
        return None
    return payload


def build_heartbeat_payload():
    """Build the heartbeat JSON payload."""
    return {
        "sensor_id": "b01-f01-r001",
        "timestamp": get_unix_timestamp(),
        "status": "alive",
    }


def main():
    """Main loop: connect, read sensors, publish telemetry and heartbeat."""
    connect_wifi()
    sync_ntp()
    client = connect_mqtt()

    last_telemetry = 0
    last_heartbeat = 0

    print("\n--- Simulation Running ---\n")

    while True:
        try:
            client.check_msg()
        except Exception:
            print("MQTT connection lost, reconnecting...")
            led.value(0)
            try:
                client = connect_mqtt()
            except Exception:
                time.sleep(5)
                continue

        now = time.time()

        if now - last_telemetry >= TELEMETRY_INTERVAL:
            last_telemetry = now
            sensor_data = read_sensors()
            if sensor_data is not None:
                payload = build_telemetry_payload(sensor_data)
                if payload is not None:
                    msg = json.dumps(payload)
                    client.publish(TELEMETRY_TOPIC, msg)
                    print("Telemetry:", msg)
                else:
                    print("Telemetry NOT sent: validation failed")

        if now - last_heartbeat >= HEARTBEAT_INTERVAL:
            last_heartbeat = now
            payload = build_heartbeat_payload()
            msg = json.dumps(payload)
            client.publish(HEARTBEAT_TOPIC, msg)
            print("Heartbeat:", msg)

        time.sleep(0.1)


main()

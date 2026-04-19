import logging
import math
import os
import random
import time

logger = logging.getLogger("models.room")


#Functions for the fault ratees if env not configured ytake el default values
def _env_float(name, default):
    value = os.getenv(name)
    if value is None:
        return default

    try:
        return float(value)
    except ValueError:
        return default


def _env_int(name, default):
    value = os.getenv(name)
    if value is None:
        return default

    try:
        return int(value)
    except ValueError:
        return default


class Room:
    def __init__(self, building_id, floor_id, room_id):
        self.building_id = building_id
        self.floor_id = floor_id
        self.room_id = room_id

        # State
        self.temperature = 22.0
        self.humidity = 50.0
        self.occupancy = False
        self.light = 300
        self.lighting_dimmer = 0

        # Actuators (commanded mode + virtual actuator snapshot for telemetry)
        self.hvac_mode = "OFF"
        self.hvac_status = "off"  # virtual actuator: off|eco|cooling|heating|idle
        self.target_temp = 22.0

        self.last_update = time.time()

        # Configurable thermal constants
        self.alpha = _env_float("THERMAL_ALPHA", 0.01)
        self.beta = _env_float("THERMAL_BETA", 0.5)
        self.occupied_light_threshold = _env_int("OCCUPIED_LIGHT_THRESHOLD", 250)
        self.occupancy_heat_gain = _env_float("OCCUPANCY_HEAT_GAIN", 0.1)

        # fault rates can be configured from the env.
        base_fault_rate = _env_float("FAULT_RATE", 0.02)
        self.sensor_drift_rate = _env_float("SENSOR_DRIFT_RATE", base_fault_rate)
        self.frozen_sensor_rate = _env_float("FROZEN_SENSOR_RATE", base_fault_rate)
        self.telemetry_delay_rate = _env_float("TELEMETRY_DELAY_RATE", base_fault_rate)
        self.node_dropout_rate = _env_float("NODE_DROPOUT_RATE", base_fault_rate)

        self.sensor_drift_step_max = _env_float("SENSOR_DRIFT_STEP_MAX", 0.05)
        self.frozen_sensor_duration_seconds = _env_int("FROZEN_SENSOR_DURATION_SECONDS", 30)
        self.telemetry_delay_min_seconds = _env_float("TELEMETRY_DELAY_MIN_SECONDS", 1.0)
        self.telemetry_delay_max_seconds = _env_float("TELEMETRY_DELAY_MAX_SECONDS", 3.0)
        self.node_dropout_duration_seconds = _env_int("NODE_DROPOUT_DURATION_SECONDS", 30)

        self.sensor_drift_bias = 0.0
        self.frozen_until = 0.0
        self.frozen_value = None
        self.dropout_until = 0.0

        # Phase 2 additions
        self.protocol = "mqtt"   # "mqtt" | "coap" — overridden by fleet.py
        self.coap_port = None    # UDP port; set only for CoAP rooms
        self.node_id = None      # unique string e.g. "b01-f02-r011"

    @property
    def room_key(self):
        return f"{self.building_id}-f{self.floor_id:02d}-r{self.floor_id * 100 + self.room_id:03d}"

    def update_occupancy(self, hour):
        # Deterministic occupancy schedule instead of stochastic sampling.
        # Core office hours are occupied; shoulder and night are unoccupied.
        self.occupancy = 8.0 <= hour < 18.0

    def update_light(self, hour):
        if 6.0 <= hour <= 20.0:
            natural_light = 100 + 400 * math.sin(math.pi * (hour - 6.0) / 14.0)
        else:
            natural_light = 20
        if self.occupancy:
            self.lighting_dimmer = 80
            artificial = 300
        else:
            self.lighting_dimmer = 0
            artificial = 0
        self.light = max(0, min(1000, int(natural_light + artificial)))
        if self.occupancy and self.light < self.occupied_light_threshold:
            self.light = self.occupied_light_threshold

    def update_humidity(self, outside_humidity):
        gamma = 0.01
        leakage = gamma * (outside_humidity - self.humidity)
        occ_effect = 0.2 if self.occupancy else 0.0
        if self.hvac_mode in ("COOLING", "ECO"):
            hvac_effect = -0.3 if self.hvac_mode == "COOLING" else -0.15
        elif self.hvac_mode == "HEATING":
            hvac_effect = -0.1
        else:
            hvac_effect = 0.0
        self.humidity += leakage + occ_effect + hvac_effect
        self.humidity = round(max(0.0, min(100.0, self.humidity)), 1)

    def sync_actuator_state(self) -> None:
        """Refresh :attr:`hvac_status` from :attr:`hvac_mode` for dashboards / gateways."""
        mapping = {
            "OFF": "off",
            "ECO": "eco",
            "COOLING": "cooling",
            "HEATING": "heating",
            "ON": "idle",
        }
        self.hvac_status = mapping.get(self.hvac_mode, str(self.hvac_mode).lower())

    def update_hvac(self):
        deadband = 0.5
        if self.hvac_mode == "OFF":
            if self.temperature > self.target_temp + deadband:
                self.hvac_mode = "COOLING"
            elif self.temperature < self.target_temp - deadband:
                self.hvac_mode = "HEATING"
        elif self.hvac_mode == "COOLING":
            if self.temperature <= self.target_temp:
                self.hvac_mode = "OFF"
        elif self.hvac_mode == "HEATING":
            if self.temperature >= self.target_temp:
                self.hvac_mode = "OFF"
        elif self.hvac_mode == "ECO":
            if self.temperature > self.target_temp + deadband:
                pass  # stay in ECO, apply half power cooling
            elif self.temperature < self.target_temp - deadband:
                pass  # stay in ECO, apply half power heating
            # ECO mode stays until explicitly changed via command
        self.sync_actuator_state()

    def update_temperature(self, outside_temp, delta_t=1.0):
        alpha = self.alpha
        if self.hvac_mode == "COOLING":
            hvac_power = -1.0
        elif self.hvac_mode == "HEATING":
            hvac_power = 1.0
        elif self.hvac_mode == "ECO":
            if self.temperature > self.target_temp:
                hvac_power = -0.5
            elif self.temperature < self.target_temp:
                hvac_power = 0.5
            else:
                hvac_power = 0.0
        else:
            hvac_power = 0.0

        leakage = alpha * (outside_temp - self.temperature) * delta_t
        change = self.beta * hvac_power * delta_t

        if self.occupancy:
            self.temperature += self.occupancy_heat_gain * delta_t
        self.temperature += leakage + change

    def validate_state(self):
        self.temperature = max(15.0, min(50.0, self.temperature))
        self.humidity = max(0.0, min(100.0, self.humidity))
        self.light = max(0, min(1000, self.light))
        self.lighting_dimmer = max(0, min(100, self.lighting_dimmer))

    def apply_sensor_faults(self, now=None):
        if now is None:
            now = time.time()

        # Sensor drift: gradual bias accumulation on temperature readings.
        if random.random() < self.sensor_drift_rate:
            self.sensor_drift_bias += random.uniform( -self.sensor_drift_step_max, self.sensor_drift_step_max )
            logger.warning("Sensor drift on %s, bias=%.3f", self.room_key, self.sensor_drift_bias)
        self.temperature += self.sensor_drift_bias

        # Frozen sensor: temperature reading gets stuck for a duration.
        if now < self.frozen_until and self.frozen_value is not None:
            self.temperature = self.frozen_value
        else:
            self.frozen_value = None
            if random.random() < self.frozen_sensor_rate:
                self.frozen_value = self.temperature
                self.frozen_until = now + self.frozen_sensor_duration_seconds
                logger.warning("Sensor frozen on %s until %.0f", self.room_key, self.frozen_until)

    def get_telemetry_faults(self, now=None):
        if now is None:
            now = time.time()

        is_dropout = False
        if now < self.dropout_until:
            is_dropout = True
        elif random.random() < self.node_dropout_rate:
            self.dropout_until = now + self.node_dropout_duration_seconds
            is_dropout = True
            logger.warning("Node dropout on %s until %.0f", self.room_key, self.dropout_until)

        delay_seconds = 0.0
        min_delay = min(self.telemetry_delay_min_seconds, self.telemetry_delay_max_seconds)
        max_delay = max(self.telemetry_delay_min_seconds, self.telemetry_delay_max_seconds)
        if random.random() < self.telemetry_delay_rate:
            delay_seconds = random.uniform(min_delay, max_delay)
            logger.info("Telemetry delay %.1fs on %s", delay_seconds, self.room_key)

        return {"dropout": is_dropout, "delay_seconds": delay_seconds}

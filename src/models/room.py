import os
import random
import time

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

        # Actuators
        self.hvac_mode = "OFF"
        self.target_temp = 22.0

        self.last_update = time.time()

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

    def update_temperature(self, outside_temp):
        alpha = 0.01  # leakage
        beta = 0.5 if self.hvac_mode == "ON" else 0.0

        leakage = alpha * (outside_temp - self.temperature)
        change = beta

        if self.occupancy:
            self.light = max(self.light, 300)
            self.temperature += 0.1
        self.temperature += leakage + change

    def apply_sensor_faults(self, now=None):
        if now is None:
            now = time.time()

        # Sensor drift: gradual bias accumulation on temperature readings.
        if random.random() < self.sensor_drift_rate:
            self.sensor_drift_bias += random.uniform( -self.sensor_drift_step_max, self.sensor_drift_step_max )
        self.temperature += self.sensor_drift_bias

        # Frozen sensor: temperature reading gets stuck for a duration.
        if now < self.frozen_until and self.frozen_value is not None:
            self.temperature = self.frozen_value
        else:
            self.frozen_value = None
            if random.random() < self.frozen_sensor_rate:
                self.frozen_value = self.temperature
                self.frozen_until = now + self.frozen_sensor_duration_seconds

    def get_telemetry_faults(self, now=None):
        if now is None:
            now = time.time()

        is_dropout = False
        if now < self.dropout_until:
            is_dropout = True
        elif random.random() < self.node_dropout_rate:
            self.dropout_until = now + self.node_dropout_duration_seconds
            is_dropout = True

        delay_seconds = 0.0
        min_delay = min(self.telemetry_delay_min_seconds, self.telemetry_delay_max_seconds)
        max_delay = max(self.telemetry_delay_min_seconds, self.telemetry_delay_max_seconds)
        if random.random() < self.telemetry_delay_rate:
            delay_seconds = random.uniform(min_delay, max_delay)

        return {"dropout": is_dropout, "delay_seconds": delay_seconds}

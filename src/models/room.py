import time


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

    def update_temperature(self, outside_temp):
        alpha = 0.01  # leake
        beta = 0.5 if self.hvac_mode == "ON" else 0.0

        leakage = alpha * (outside_temp - self.temperature)
        change = beta

        if self.occupancy:
            self.light = max(self.light, 300)
            self.temperature += 0.1
        self.temperature += leakage + change

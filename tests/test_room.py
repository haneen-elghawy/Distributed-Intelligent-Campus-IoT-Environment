import unittest

from src.models.room import Room


class TestRoomInit(unittest.TestCase):
    def test_default_values(self):
        room = Room("b01", 1, 1)
        self.assertEqual(room.temperature, 22.0)
        self.assertEqual(room.humidity, 50.0)
        self.assertFalse(room.occupancy)
        self.assertEqual(room.light, 300)
        self.assertEqual(room.lighting_dimmer, 0)
        self.assertEqual(room.hvac_mode, "OFF")
        self.assertEqual(room.target_temp, 22.0)

    def test_identifiers(self):
        room = Room("b01", 3, 15)
        self.assertEqual(room.building_id, "b01")
        self.assertEqual(room.floor_id, 3)
        self.assertEqual(room.room_id, 15)

    def test_room_key(self):
        room = Room("b01", 5, 3)
        self.assertEqual(room.room_key, "b01-f05-r503")

    def test_configurable_alpha_beta(self):
        room = Room("b01", 1, 1)
        self.assertEqual(room.alpha, 0.01)
        self.assertEqual(room.beta, 0.5)


class TestTemperatureUpdate(unittest.TestCase):
    def test_leakage_toward_outside(self):
        room = Room("b01", 1, 1)
        room.temperature = 22.0
        room.hvac_mode = "OFF"
        room.occupancy = False
        room.update_temperature(outside_temp=30)
        self.assertGreater(room.temperature, 22.0)

    def test_cooling_reduces_temp(self):
        room = Room("b01", 1, 1)
        room.temperature = 25.0
        room.hvac_mode = "COOLING"
        room.occupancy = False
        room.update_temperature(outside_temp=25)
        self.assertLess(room.temperature, 25.0)

    def test_heating_increases_temp(self):
        room = Room("b01", 1, 1)
        room.temperature = 18.0
        room.hvac_mode = "HEATING"
        room.occupancy = False
        room.update_temperature(outside_temp=18)
        self.assertGreater(room.temperature, 18.0)

    def test_occupancy_adds_heat(self):
        room = Room("b01", 1, 1)
        room.temperature = 22.0
        room.hvac_mode = "OFF"
        room.occupancy = True
        room.update_temperature(outside_temp=22)
        self.assertGreater(room.temperature, 22.0)

    def test_eco_mode_cools_when_above_target(self):
        room = Room("b01", 1, 1)
        room.temperature = 25.0
        room.target_temp = 22.0
        room.hvac_mode = "ECO"
        room.occupancy = False
        room.update_temperature(outside_temp=25)
        # ECO uses half power: hvac_power = -0.5, change = beta * -0.5 = 0.5 * -0.5 = -0.25
        self.assertLess(room.temperature, 25.0)

    def test_eco_mode_heats_when_below_target(self):
        room = Room("b01", 1, 1)
        room.temperature = 18.0
        room.target_temp = 22.0
        room.hvac_mode = "ECO"
        room.occupancy = False
        room.update_temperature(outside_temp=18)
        self.assertGreater(room.temperature, 18.0)

    def test_eco_half_power_vs_full(self):
        room_eco = Room("b01", 1, 1)
        room_eco.temperature = 25.0
        room_eco.target_temp = 22.0
        room_eco.hvac_mode = "ECO"
        room_eco.occupancy = False
        room_eco.update_temperature(outside_temp=25)

        room_full = Room("b01", 1, 1)
        room_full.temperature = 25.0
        room_full.target_temp = 22.0
        room_full.hvac_mode = "COOLING"
        room_full.occupancy = False
        room_full.update_temperature(outside_temp=25)

        # ECO should cool less aggressively than COOLING
        self.assertGreater(room_eco.temperature, room_full.temperature)

    def test_delta_t_scales_temperature_change(self):
        room_fast = Room("b01", 1, 1)
        room_fast.temperature = 22.0
        room_fast.hvac_mode = "OFF"
        room_fast.occupancy = False
        room_fast.update_temperature(outside_temp=30, delta_t=5.0)

        room_slow = Room("b01", 1, 1)
        room_slow.temperature = 22.0
        room_slow.hvac_mode = "OFF"
        room_slow.occupancy = False
        room_slow.update_temperature(outside_temp=30, delta_t=1.0)

        self.assertGreater(room_fast.temperature - 22.0, room_slow.temperature - 22.0)


class TestHVAC(unittest.TestCase):
    def test_cooling_activates(self):
        room = Room("b01", 1, 1)
        room.target_temp = 22.0
        room.temperature = 23.0
        room.update_hvac()
        self.assertEqual(room.hvac_mode, "COOLING")

    def test_heating_activates(self):
        room = Room("b01", 1, 1)
        room.target_temp = 22.0
        room.temperature = 21.0
        room.update_hvac()
        self.assertEqual(room.hvac_mode, "HEATING")

    def test_no_change_in_deadband(self):
        room = Room("b01", 1, 1)
        room.target_temp = 22.0
        room.temperature = 22.3
        room.update_hvac()
        self.assertEqual(room.hvac_mode, "OFF")

    def test_cooling_turns_off_at_target(self):
        room = Room("b01", 1, 1)
        room.target_temp = 22.0
        room.hvac_mode = "COOLING"
        room.temperature = 22.0
        room.update_hvac()
        self.assertEqual(room.hvac_mode, "OFF")

    def test_heating_turns_off_at_target(self):
        room = Room("b01", 1, 1)
        room.target_temp = 22.0
        room.hvac_mode = "HEATING"
        room.temperature = 22.0
        room.update_hvac()
        self.assertEqual(room.hvac_mode, "OFF")

    def test_eco_mode_stays(self):
        room = Room("b01", 1, 1)
        room.target_temp = 22.0
        room.hvac_mode = "ECO"
        room.temperature = 25.0
        room.update_hvac()
        self.assertEqual(room.hvac_mode, "ECO")


class TestOccupancy(unittest.TestCase):
    def test_work_hours_occupied(self):
        room = Room("b01", 1, 1)
        room.update_occupancy(12.0)
        self.assertTrue(room.occupancy)

    def test_night_unoccupied(self):
        room = Room("b01", 1, 1)
        room.update_occupancy(3.0)
        self.assertFalse(room.occupancy)


class TestLight(unittest.TestCase):
    def test_daytime_light(self):
        room = Room("b01", 1, 1)
        room.occupancy = False
        room.update_light(12.0)
        self.assertGreater(room.light, 300)

    def test_nighttime_light(self):
        room = Room("b01", 1, 1)
        room.occupancy = False
        room.update_light(2.0)
        self.assertEqual(room.light, 20)

    def test_occupied_adds_artificial(self):
        room = Room("b01", 1, 1)
        room.occupancy = True
        room.update_light(2.0)
        self.assertEqual(room.light, 320)

    def test_lighting_dimmer_set_on_occupancy(self):
        room = Room("b01", 1, 1)
        room.occupancy = True
        room.update_light(12.0)
        self.assertEqual(room.lighting_dimmer, 80)

    def test_lighting_dimmer_off_when_unoccupied(self):
        room = Room("b01", 1, 1)
        room.occupancy = False
        room.update_light(12.0)
        self.assertEqual(room.lighting_dimmer, 0)

    def test_light_clamped_to_1000(self):
        room = Room("b01", 1, 1)
        room.occupancy = True
        room.update_light(13.0)  # peak natural light + artificial
        self.assertLessEqual(room.light, 1000)

    def test_occupied_light_respects_threshold(self):
        room = Room("b01", 1, 1)
        room.occupancy = True
        room.occupied_light_threshold = 350
        room.update_light(2.0)
        self.assertGreaterEqual(room.light, 350)


class TestHumidity(unittest.TestCase):
    def test_humidity_clamped_low(self):
        room = Room("b01", 1, 1)
        room.humidity = 1.0
        room.occupancy = False
        room.hvac_mode = "OFF"
        room.update_humidity(outside_humidity=0)
        self.assertGreaterEqual(room.humidity, 0.0)

    def test_humidity_clamped_high(self):
        room = Room("b01", 1, 1)
        room.humidity = 99.0
        room.occupancy = True
        room.hvac_mode = "OFF"
        room.update_humidity(outside_humidity=100)
        self.assertLessEqual(room.humidity, 100.0)

    def test_cooling_dehumidifies(self):
        room = Room("b01", 1, 1)
        room.humidity = 60.0
        room.hvac_mode = "COOLING"
        room.occupancy = False
        room.update_humidity(outside_humidity=60.0)
        self.assertLess(room.humidity, 60.0)

    def test_eco_dehumidifies_less_than_cooling(self):
        room_eco = Room("b01", 1, 1)
        room_eco.humidity = 60.0
        room_eco.hvac_mode = "ECO"
        room_eco.occupancy = False
        room_eco.update_humidity(outside_humidity=60.0)

        room_cool = Room("b01", 1, 1)
        room_cool.humidity = 60.0
        room_cool.hvac_mode = "COOLING"
        room_cool.occupancy = False
        room_cool.update_humidity(outside_humidity=60.0)

        self.assertGreater(room_eco.humidity, room_cool.humidity)


class TestStateValidation(unittest.TestCase):
    def test_temp_clamped_low(self):
        room = Room("b01", 1, 1)
        room.temperature = 10.0
        room.validate_state()
        self.assertEqual(room.temperature, 15.0)

    def test_temp_clamped_high(self):
        room = Room("b01", 1, 1)
        room.temperature = 55.0
        room.validate_state()
        self.assertEqual(room.temperature, 50.0)

    def test_humidity_clamped(self):
        room = Room("b01", 1, 1)
        room.humidity = -5.0
        room.validate_state()
        self.assertEqual(room.humidity, 0.0)

    def test_light_clamped(self):
        room = Room("b01", 1, 1)
        room.light = 1500
        room.validate_state()
        self.assertEqual(room.light, 1000)

    def test_dimmer_clamped(self):
        room = Room("b01", 1, 1)
        room.lighting_dimmer = 120
        room.validate_state()
        self.assertEqual(room.lighting_dimmer, 100)


class TestFaultSimulation(unittest.TestCase):
    def test_sensor_drift_accumulates(self):
        room = Room("b01", 1, 1)
        room.sensor_drift_rate = 1.0
        initial_bias = room.sensor_drift_bias
        room.apply_sensor_faults()
        self.assertNotEqual(room.sensor_drift_bias, initial_bias)

    def test_dropout_returns_dict(self):
        room = Room("b01", 1, 1)
        result = room.get_telemetry_faults()
        self.assertIn("dropout", result)
        self.assertIn("delay_seconds", result)

    def test_frozen_sensor(self):
        room = Room("b01", 1, 1)
        room.frozen_sensor_rate = 1.0
        room.sensor_drift_rate = 0.0
        room.apply_sensor_faults()
        frozen_val = room.frozen_value
        self.assertIsNotNone(frozen_val)
        room.temperature = 99.0
        room.apply_sensor_faults()
        self.assertEqual(room.temperature, frozen_val)


if __name__ == "__main__":
    unittest.main()

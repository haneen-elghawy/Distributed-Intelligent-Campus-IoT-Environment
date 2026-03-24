import unittest

from src.models.room import Room


class TestFleet(unittest.TestCase):
    def _create_fleet(self):
        rooms = []
        for floor in range(1, 11):
            for room in range(1, 21):
                rooms.append(Room("b01", floor, room))
        return rooms

    def test_fleet_size(self):
        fleet = self._create_fleet()
        self.assertEqual(len(fleet), 200)

    def test_all_building_b01(self):
        fleet = self._create_fleet()
        for room in fleet:
            self.assertEqual(room.building_id, "b01")

    def test_floor_range(self):
        fleet = self._create_fleet()
        floors = {room.floor_id for room in fleet}
        self.assertEqual(floors, set(range(1, 11)))

    def test_rooms_per_floor(self):
        fleet = self._create_fleet()
        for floor in range(1, 11):
            count = sum(1 for r in fleet if r.floor_id == floor)
            self.assertEqual(count, 20)


if __name__ == "__main__":
    unittest.main()

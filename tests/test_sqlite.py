import os
import tempfile
import unittest

from src.models.room import Room
from src.persistence.sqlite_store import (
    init_db,
    initialize_defaults,
    is_db_empty,
    load_previous_state,
    persist_room_state,
)


class TestSQLite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".db")

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.unlink(self.tmp)

    def test_init_creates_db(self):
        init_db(self.tmp)
        self.assertTrue(os.path.exists(self.tmp))

    def test_empty_after_init(self):
        init_db(self.tmp)
        self.assertTrue(is_db_empty(self.tmp))

    def test_not_empty_after_defaults(self):
        init_db(self.tmp)
        rooms = [Room("b01", 1, 1)]
        initialize_defaults(rooms, self.tmp)
        self.assertFalse(is_db_empty(self.tmp))

    def test_save_and_load(self):
        init_db(self.tmp)
        rooms = [Room("b01", 1, 1)]
        rooms[0].temperature = 25.5
        rooms[0].humidity = 65.0
        initialize_defaults(rooms, self.tmp)

        rooms2 = [Room("b01", 1, 1)]
        load_previous_state(rooms2, self.tmp)
        self.assertAlmostEqual(rooms2[0].temperature, 25.5)
        self.assertAlmostEqual(rooms2[0].humidity, 65.0)

    def test_persist_updates(self):
        init_db(self.tmp)
        room = Room("b01", 1, 1)
        initialize_defaults([room], self.tmp)
        room.temperature = 30.0
        persist_room_state(room, self.tmp)

        room2 = Room("b01", 1, 1)
        load_previous_state([room2], self.tmp)
        self.assertAlmostEqual(room2.temperature, 30.0)


if __name__ == "__main__":
    unittest.main()

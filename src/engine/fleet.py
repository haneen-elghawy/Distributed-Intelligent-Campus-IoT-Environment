import os

from ..models import Room


def create_room_fleet():
    num_floors = int(os.getenv("NUM_FLOORS", "10"))
    rooms_per_floor = int(os.getenv("ROOMS_PER_FLOOR", "20"))
    rooms = []

    for floor in range(1, num_floors + 1):
        for room in range(1, rooms_per_floor + 1):
            rooms.append(Room("b01", floor, room))

    return rooms


rooms = create_room_fleet()

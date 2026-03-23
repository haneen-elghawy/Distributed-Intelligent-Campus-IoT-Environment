from ..models import Room


def create_room_fleet():
    rooms = []

    for floor in range(1, 11):
        for room in range(1, 21):
            rooms.append(Room("b01", floor, room))

    return rooms


rooms = create_room_fleet()

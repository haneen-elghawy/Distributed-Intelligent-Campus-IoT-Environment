import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger("persistence.sqlite")


def _get_db_path(db_path=None):
    if db_path is not None:
        return db_path

    return os.getenv("SQLITE_DB_PATH", "data/campus_iot.db")


def _ensure_parent_dir(db_path):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)


def _room_key(room):
    room_number = room.floor_id * 100 + room.room_id
    return f"{room.building_id}-f{room.floor_id:02d}-r{room_number:03d}"


def init_db(db_path=None):
    path = _get_db_path(db_path)
    _ensure_parent_dir(path)

    with sqlite3.connect(path, timeout=30) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rooms (
                room_id TEXT PRIMARY KEY,
                last_temp REAL,
                last_humidity REAL,
                hvac_mode TEXT,
                target_temp REAL,
                last_update INTEGER
            );
            """
        )
        conn.commit()
    logger.info("Database initialized at %s", path)


def is_db_empty(db_path=None):
    path = _get_db_path(db_path)
    _ensure_parent_dir(path)

    with sqlite3.connect(path, timeout=30) as conn:
        row = conn.execute("SELECT COUNT(*) FROM rooms").fetchone()
        return (row[0] if row else 0) == 0


def initialize_defaults(rooms, db_path=None):
    path = _get_db_path(db_path)
    _ensure_parent_dir(path)

    with sqlite3.connect(path, timeout=30) as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO rooms (
                room_id,
                last_temp,
                last_humidity,
                hvac_mode,
                target_temp,
                last_update
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    _room_key(room),
                    room.temperature,
                    room.humidity,
                    room.hvac_mode,
                    room.target_temp,
                    int(room.last_update),
                )
                for room in rooms
            ],
        )
        conn.commit()


def load_previous_state(rooms, db_path=None):
    path = _get_db_path(db_path)
    _ensure_parent_dir(path)

    with sqlite3.connect(path, timeout=30) as conn:
        rows = conn.execute(
            """
            SELECT room_id, last_temp, last_humidity, hvac_mode, target_temp, last_update
            FROM rooms
            """
        ).fetchall()

    logger.info("Loaded state for %d rooms", len(rows))

    room_rows = {
        row[0]: {
            "last_temp": row[1],
            "last_humidity": row[2],
            "hvac_mode": row[3],
            "target_temp": row[4],
            "last_update": row[5],
        }
        for row in rows
    }

    for room in rooms:
        key = _room_key(room)
        state = room_rows.get(key)
        if state is None:
            continue

        room.temperature = state["last_temp"]
        room.humidity = state["last_humidity"]
        room.hvac_mode = state["hvac_mode"]
        room.target_temp = state["target_temp"]
        room.last_update = state["last_update"]


def persist_room_state(room, db_path=None):
    path = _get_db_path(db_path)
    _ensure_parent_dir(path)

    with sqlite3.connect(path, timeout=30) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO rooms (
                room_id,
                last_temp,
                last_humidity,
                hvac_mode,
                target_temp,
                last_update
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                _room_key(room),
                room.temperature,
                room.humidity,
                room.hvac_mode,
                room.target_temp,
                int(room.last_update),
            ),
        )
        conn.commit()

import sqlite3
from contextlib import contextmanager

import config
from config import SQL_TIMEOUT_SECONDS

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS parking_lot_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    name TEXT NOT NULL DEFAULT 'Demo停车场',
    total_spots INTEGER NOT NULL DEFAULT 800,
    floors INTEGER NOT NULL DEFAULT 4,
    spots_per_floor INTEGER NOT NULL DEFAULT 200,
    hourly_rate REAL NOT NULL DEFAULT 6.0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS vehicle_record (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plate TEXT NOT NULL,
    vehicle_type TEXT NOT NULL
        CHECK(vehicle_type IN ('ICE', 'BEV', 'PHEV', 'HEV')),
    entry_time DATETIME NOT NULL,
    exit_time DATETIME,
    entry_floor INTEGER CHECK(entry_floor BETWEEN 1 AND 10),
    entry_spot INTEGER
);

CREATE INDEX IF NOT EXISTS idx_entry_time ON vehicle_record(entry_time);
CREATE INDEX IF NOT EXISTS idx_exit_time ON vehicle_record(exit_time);
CREATE INDEX IF NOT EXISTS idx_vehicle_type ON vehicle_record(vehicle_type);
CREATE INDEX IF NOT EXISTS idx_plate ON vehicle_record(plate);
CREATE INDEX IF NOT EXISTS idx_active ON vehicle_record(entry_time)
    WHERE exit_time IS NULL;
"""


@contextmanager
def get_db(read_only: bool = False) -> sqlite3.Connection:
    """Get a SQLite connection with proper settings."""
    uri = f"file:{config.DATABASE_PATH}?mode=ro" if read_only else config.DATABASE_PATH
    conn = sqlite3.connect(uri, uri=True if read_only else False, timeout=SQL_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON" if read_only else "PRAGMA query_only = OFF")
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    """Initialize database schema and seed config if empty."""
    conn = sqlite3.connect(config.DATABASE_PATH)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


def seed_config(
    name: str = "Demo停车场",
    total_spots: int = 800,
    floors: int = 4,
    spots_per_floor: int = 200,
    hourly_rate: float = 6.0,
) -> None:
    """Insert default parking lot config if not exists."""
    conn = sqlite3.connect(config.DATABASE_PATH)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO parking_lot_config (id, name, total_spots, floors, spots_per_floor, hourly_rate) "
            "VALUES (1, ?, ?, ?, ?, ?)",
            (name, total_spots, floors, spots_per_floor, hourly_rate),
        )
        conn.commit()
    finally:
        conn.close()

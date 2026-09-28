import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "nexus.db"


def get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_database():
    connection = get_connection()

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS electrical_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            voltage REAL NOT NULL,
            current REAL NOT NULL,
            frequency REAL NOT NULL,
            power_factor REAL NOT NULL,
            active_power REAL NOT NULL,
            temperature REAL NOT NULL,
            status TEXT NOT NULL
        )
        """
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS monitoring_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            message TEXT NOT NULL,
            recommendation TEXT NOT NULL
        )
        """
    )

    connection.commit()
    connection.close()


def save_reading(reading: dict):
    connection = get_connection()

    connection.execute(
        """
        INSERT INTO electrical_readings (
            timestamp,
            voltage,
            current,
            frequency,
            power_factor,
            active_power,
            temperature,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            reading["timestamp"].isoformat(),
            reading["voltage"],
            reading["current"],
            reading["frequency"],
            reading["power_factor"],
            reading["active_power"],
            reading["temperature"],
            reading["status"],
        ),
    )

    connection.commit()
    connection.close()


def get_recent_readings(limit: int = 50):
    connection = get_connection()

    rows = connection.execute(
        """
        SELECT
            id,
            timestamp,
            voltage,
            current,
            frequency,
            power_factor,
            active_power,
            temperature,
            status
        FROM electrical_readings
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    connection.close()

    return [dict(row) for row in reversed(rows)]


def save_event(event: dict):
    connection = get_connection()

    connection.execute(
        """
        INSERT INTO monitoring_events (
            timestamp,
            event_type,
            severity,
            message,
            recommendation
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            event["timestamp"].isoformat(),
            event["event_type"],
            event["severity"],
            event["message"],
            event["recommendation"],
        ),
    )

    connection.commit()
    connection.close()


def get_recent_events(limit: int = 20):
    connection = get_connection()

    rows = connection.execute(
        """
        SELECT
            id,
            timestamp,
            event_type,
            severity,
            message,
            recommendation
        FROM monitoring_events
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    connection.close()

    return [dict(row) for row in rows]
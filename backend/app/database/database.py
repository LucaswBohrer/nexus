import sqlite3
from datetime import datetime

from app.config import settings

DB_PATH = settings.database_path


def get_connection():
    connection = sqlite3.connect(DB_PATH, timeout=10.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 5000;")
    return connection


def init_database():
    connection = get_connection()
    connection.execute("PRAGMA journal_mode = WAL;")
    connection.execute("PRAGMA synchronous = NORMAL;")

    connection.execute("""
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
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS monitoring_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            message TEXT NOT NULL,
            recommendation TEXT NOT NULL
        )
    """)

    connection.commit()
    connection.close()


def get_latest_reading_from_db() -> dict | None:
    connection = get_connection()
    row = connection.execute(
        """
        SELECT id, timestamp, voltage, current, frequency,
               power_factor, active_power, temperature, status
        FROM electrical_readings
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    connection.close()

    if row:
        data = dict(row)
        if isinstance(data["timestamp"], str):
            try:
                data["timestamp"] = datetime.fromisoformat(data["timestamp"])
            except ValueError:
                pass
        return data
    return None



def save_reading(reading: dict):
    connection = get_connection()

    connection.execute(
        """
        INSERT INTO electrical_readings (
            timestamp, voltage, current, frequency,
            power_factor, active_power, temperature, status
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
        SELECT id, timestamp, voltage, current, frequency,
               power_factor, active_power, temperature, status
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
            timestamp, event_type, severity, message, recommendation
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
        SELECT id, timestamp, event_type, severity, message, recommendation
        FROM monitoring_events
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    connection.close()
    return [dict(row) for row in rows]


import sqlite3
from pathlib import Path

<<<<<<< HEAD

=======
>>>>>>> 02fde370763d1c188b8feb2264e406ee5aafbdac
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "nexus.db"


def get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_database():
    connection = get_connection()

<<<<<<< HEAD
    connection.execute(
        """
=======
    connection.execute("""
>>>>>>> 02fde370763d1c188b8feb2264e406ee5aafbdac
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
<<<<<<< HEAD
        """
    )

    connection.execute(
        """
=======
    """)

    connection.execute("""
>>>>>>> 02fde370763d1c188b8feb2264e406ee5aafbdac
        CREATE TABLE IF NOT EXISTS monitoring_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            message TEXT NOT NULL,
            recommendation TEXT NOT NULL
        )
<<<<<<< HEAD
        """
    )
=======
    """)
>>>>>>> 02fde370763d1c188b8feb2264e406ee5aafbdac

    connection.commit()
    connection.close()


def save_reading(reading: dict):
    connection = get_connection()

    connection.execute(
        """
        INSERT INTO electrical_readings (
<<<<<<< HEAD
            timestamp,
            voltage,
            current,
            frequency,
            power_factor,
            active_power,
            temperature,
            status
=======
            timestamp, voltage, current, frequency,
            power_factor, active_power, temperature, status
>>>>>>> 02fde370763d1c188b8feb2264e406ee5aafbdac
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
<<<<<<< HEAD
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
=======
        SELECT id, timestamp, voltage, current, frequency,
               power_factor, active_power, temperature, status
>>>>>>> 02fde370763d1c188b8feb2264e406ee5aafbdac
        FROM electrical_readings
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    connection.close()
<<<<<<< HEAD

=======
>>>>>>> 02fde370763d1c188b8feb2264e406ee5aafbdac
    return [dict(row) for row in reversed(rows)]


def save_event(event: dict):
    connection = get_connection()

    connection.execute(
        """
        INSERT INTO monitoring_events (
<<<<<<< HEAD
            timestamp,
            event_type,
            severity,
            message,
            recommendation
=======
            timestamp, event_type, severity, message, recommendation
>>>>>>> 02fde370763d1c188b8feb2264e406ee5aafbdac
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
<<<<<<< HEAD
        SELECT
            id,
            timestamp,
            event_type,
            severity,
            message,
            recommendation
=======
        SELECT id, timestamp, event_type, severity, message, recommendation
>>>>>>> 02fde370763d1c188b8feb2264e406ee5aafbdac
        FROM monitoring_events
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    connection.close()
<<<<<<< HEAD

    return [dict(row) for row in rows]
=======
    return [dict(row) for row in rows]
>>>>>>> 02fde370763d1c188b8feb2264e406ee5aafbdac

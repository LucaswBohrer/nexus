import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

DB_PATH = settings.database_path

# Retention policy: telemetry writes ~1 reading/sec (+ events) forever, so
# tables must not grow without bound. Rows older than this are pruned.
DATA_RETENTION_DAYS = 30

# Hard ceiling for paginated reads. The API layer validates `limit` with
# FastAPI Query constraints; this is a defense-in-depth guard so a missed
# validation can never turn into a full-table dump.
MAX_HISTORY_LIMIT = 1000
MAX_EVENTS_LIMIT = 500


def get_connection():
    connection = sqlite3.connect(DB_PATH, timeout=10.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 5000;")
    return connection


def init_database():
    try:
        _init_database()
    except sqlite3.DatabaseError as exc:
        # A corrupt database file must not be a permanent outage: quarantine
        # it and start fresh. Only *definitive* corruption is recoverable —
        # OperationalError (permissions, missing directory, disk full) means
        # the environment is at fault, and renaming the file would hide the
        # real problem while risking abandonment of a healthy database.
        if not _should_quarantine(exc) or not DB_PATH.exists():
            raise
        target = _quarantine_corrupt_database()
        logger.warning(
            "Database file %s is corrupt (%s); quarantined as %s and starting fresh.",
            DB_PATH,
            exc,
            target,
        )
        _init_database()


def _should_quarantine(exc: BaseException) -> bool:
    """True only for definitive corruption, never for environmental errors."""
    return isinstance(exc, sqlite3.DatabaseError) and not isinstance(
        exc, sqlite3.OperationalError
    )


def _quarantine_corrupt_database() -> Path:
    """Move the corrupt database (plus WAL/journal sidecars) aside.

    Never deletes user data: the original bytes are preserved under a
    timestamped name for forensics.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = DB_PATH.with_name(f"{DB_PATH.stem}.corrupt-{stamp}{DB_PATH.suffix}")
    DB_PATH.replace(target)
    for sidecar in ("-wal", "-shm", "-journal"):
        sidecar_path = Path(str(DB_PATH) + sidecar)
        if sidecar_path.exists():
            sidecar_path.replace(Path(str(target) + sidecar))
    return target


def _init_database():
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

    pruned = prune_old_data()
    if pruned["readings_deleted"] or pruned["events_deleted"]:
        logger.info(
            "Pruned old telemetry data on startup: %d readings, %d events removed "
            "(retention: %d days)",
            pruned["readings_deleted"],
            pruned["events_deleted"],
            DATA_RETENTION_DAYS,
        )


def prune_old_data(retention_days: int = DATA_RETENTION_DAYS) -> dict[str, int]:
    """Delete readings/events older than `retention_days`.

    Returns the number of deleted rows per table. Never raises: pruning is
    best-effort maintenance and must not break startup or the telemetry loop.
    """
    cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat()
    try:
        connection = get_connection()
        readings_cursor = connection.execute(
            "DELETE FROM electrical_readings WHERE timestamp < ?",
            (cutoff,),
        )
        events_cursor = connection.execute(
            "DELETE FROM monitoring_events WHERE timestamp < ?",
            (cutoff,),
        )
        connection.commit()
        readings_deleted = readings_cursor.rowcount
        events_deleted = events_cursor.rowcount
        connection.close()
        return {
            "readings_deleted": readings_deleted,
            "events_deleted": events_deleted,
        }
    except Exception:
        logger.exception("Failed to prune old telemetry data")
        return {"readings_deleted": 0, "events_deleted": 0}


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
    # Defense in depth: never allow an unbounded read even if the caller
    # skipped validation (the API layer rejects out-of-range values with 422).
    limit = max(1, min(limit, MAX_HISTORY_LIMIT))
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
    # Defense in depth: see get_recent_readings.
    limit = max(1, min(limit, MAX_EVENTS_LIMIT))
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


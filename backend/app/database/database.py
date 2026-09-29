import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import settings
from app.database.migrations import run_migrations

logger = logging.getLogger(__name__)

DB_PATH = settings.database_path

# Per-table retention policy (NEXUS 2.1): telemetry writes ~1 reading/sec
# forever, so tables must not grow without bound. These are the seed
# defaults; at runtime they are overridable via the settings service
# (retention.<table>_days keys). `settings` itself is never pruned.
RETENTION_DEFAULTS: dict[str, int] = {
    "readings": 30,
    "events": 90,
    "diagnostic_episodes": 90,
    "simulation_sessions": 180,
}

# Backwards-compatible alias: the legacy retention knob always referred to
# the readings table.
DATA_RETENTION_DAYS = RETENTION_DEFAULTS["readings"]

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

    # Bring the schema up to date (idempotent; no-op when already current).
    run_migrations(connection)
    connection.close()

    pruned = prune_all()
    total = sum(pruned.values())
    if total:
        logger.info(
            "Pruned old telemetry data on startup: %s (retention: %s)",
            ", ".join(f"{count} {table}" for table, count in pruned.items() if count),
            RETENTION_DEFAULTS,
        )


def _utc_cutoff(days: int) -> str:
    # Cutoffs are UTC ISO-8601 strings. Every post-migration timestamp is
    # UTC in the same fixed-width format, so lexicographic comparison is
    # chronological.
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def prune_old_data(
    readings_days: int = RETENTION_DEFAULTS["readings"],
    events_days: int = RETENTION_DEFAULTS["events"],
) -> dict[str, int]:
    """Delete readings/events older than their per-table retention windows.

    Contract preserved for existing callers: returns exactly
    {"readings_deleted", "events_deleted"}. Never raises: pruning is
    best-effort maintenance and must not break startup or the telemetry loop.
    """
    try:
        connection = get_connection()
        readings_cursor = connection.execute(
            "DELETE FROM electrical_readings WHERE timestamp < ?",
            (_utc_cutoff(readings_days),),
        )
        # Events may predate the lifecycle columns; fall back to the legacy
        # timestamp column for those rows.
        events_cursor = connection.execute(
            "DELETE FROM monitoring_events WHERE COALESCE(opened_at, timestamp) < ?",
            (_utc_cutoff(events_days),),
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


def prune_auxiliary_data(
    episodes_days: int = RETENTION_DEFAULTS["diagnostic_episodes"],
    sessions_days: int = RETENTION_DEFAULTS["simulation_sessions"],
) -> dict[str, int]:
    """Delete old diagnostic episodes and simulation sessions.

    The settings table is permanent and is never pruned. Never raises.
    """
    try:
        connection = get_connection()
        episodes_cursor = connection.execute(
            "DELETE FROM diagnostic_episodes WHERE started_at < ?",
            (_utc_cutoff(episodes_days),),
        )
        sessions_cursor = connection.execute(
            "DELETE FROM simulation_sessions WHERE started_at < ?",
            (_utc_cutoff(sessions_days),),
        )
        connection.commit()
        episodes_deleted = episodes_cursor.rowcount
        sessions_deleted = sessions_cursor.rowcount
        connection.close()
        return {
            "episodes_deleted": episodes_deleted,
            "sessions_deleted": sessions_deleted,
        }
    except Exception:
        logger.exception("Failed to prune auxiliary telemetry data")
        return {"episodes_deleted": 0, "sessions_deleted": 0}


def prune_all(retention: dict[str, int] | None = None) -> dict[str, int]:
    """Prune every telemetry table using per-table retention windows.

    `retention` overrides RETENTION_DEFAULTS; keys are "readings", "events",
    "diagnostic_episodes" and "simulation_sessions". Called by startup and
    by the hourly telemetry maintenance.
    """
    retention = {**RETENTION_DEFAULTS, **(retention or {})}
    counts = prune_old_data(
        readings_days=retention["readings"],
        events_days=retention["events"],
    )
    counts.update(
        prune_auxiliary_data(
            episodes_days=retention["diagnostic_episodes"],
            sessions_days=retention["simulation_sessions"],
        )
    )
    return counts


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


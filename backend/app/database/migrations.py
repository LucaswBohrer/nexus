"""Idempotent schema migrations for the NEXUS SQLite database.

The migration state lives in ``PRAGMA user_version``. Each migration is
written to be safely re-runnable:

- DDL uses ``IF NOT EXISTS`` / guarded ``ALTER TABLE`` (SQLite has no
  ``ADD COLUMN IF NOT EXISTS``, so new columns are added only when absent
  from ``PRAGMA table_info``);
- the legacy timestamp conversion only touches rows whose timestamp is
  still naive, so a second run is a no-op;
- ``run_migrations()`` checks the stored version first and applies only
  the migrations that have not run yet.

Convention: migrations are numbered v1, v2, ... and applied in order.
"""

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Bump this when a new migration is added to _MIGRATIONS.
CURRENT_SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# Timestamp policy (NEXUS 2.1)
# ---------------------------------------------------------------------------
# Every timestamp written before NEXUS 2.1 was a *naive* ``datetime.now()``
# value produced in the server's local timezone, America/Sao_Paulo.
# Migration v1 reinterprets those naive values as America/Sao_Paulo and
# converts them to UTC. All new code must write timezone-aware UTC
# datetimes (``datetime.now(timezone.utc)``); the database therefore only
# ever contains UTC ISO-8601 strings after migration. Presentation in the
# user's local timezone is a frontend concern (Intl).
LEGACY_TIMEZONE = ZoneInfo("America/Sao_Paulo")

# New lifecycle columns for monitoring_events (NEXUS 2.1 event model).
# equipment_id is nullable on purpose: the event identity is
# (event_type, equipment_id) so per-equipment deduplication can be added
# later without another schema change.
NEW_EVENT_COLUMNS: dict[str, str] = {
    "status": "TEXT",
    "opened_at": "TEXT",
    "closed_at": "TEXT",
    "last_seen": "TEXT",
    "occurrences": "INTEGER DEFAULT 1",
    "last_value": "REAL",
    "threshold": "REAL",
    "acknowledged_at": "TEXT",
    "acknowledged_by": "TEXT",
    "equipment_id": "TEXT",
}


def get_schema_version(connection) -> int:
    row = connection.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row else 0


def run_migrations(connection) -> int:
    """Apply every pending migration. Returns the resulting schema version.

    Safe to call on every startup: already-applied migrations are skipped
    via PRAGMA user_version, and each migration is itself re-runnable.
    """
    version = get_schema_version(connection)
    while version < CURRENT_SCHEMA_VERSION:
        target = version + 1
        migrate = _MIGRATIONS.get(target)
        if migrate is None:
            raise RuntimeError(f"No migration registered for schema v{target}")
        logger.info("Applying database migration v%d", target)
        migrate(connection)
        connection.execute(f"PRAGMA user_version = {target}")
        connection.commit()
        version = target
        logger.info("Database migration v%d applied", target)
    return version


def _existing_columns(connection, table: str) -> set[str]:
    return {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _migrate_v1(connection) -> None:
    # 1. Time-range index for history/aggregation queries.
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_readings_ts "
        "ON electrical_readings(timestamp)"
    )

    # 2. Event lifecycle columns.
    existing = _existing_columns(connection, "monitoring_events")
    for column, ddl in NEW_EVENT_COLUMNS.items():
        if column not in existing:
            connection.execute(
                f"ALTER TABLE monitoring_events ADD COLUMN {column} {ddl}"
            )

    # 3. Diagnostic episodes: one row per abnormal period (opened when the
    #    system enters an abnormal state, closed after K normal ticks).
    connection.execute("""
        CREATE TABLE IF NOT EXISTS diagnostic_episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            status TEXT NOT NULL,
            severity TEXT NOT NULL,
            rules TEXT,
            peak_values TEXT,
            recommendations TEXT
        )
    """)

    # 4. Simulation sessions: audit trail of simulation runs.
    connection.execute("""
        CREATE TABLE IF NOT EXISTS simulation_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mode TEXT NOT NULL,
            parameters TEXT,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            peak_values TEXT
        )
    """)

    # 5. System settings: operational configuration (thresholds, retention,
    #    tariff, simulation defaults). Visual/user preferences live in
    #    frontend localStorage, never here.
    connection.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    # 6. Convert legacy naive timestamps (America/Sao_Paulo) to UTC.
    _convert_legacy_timestamps(connection, "electrical_readings", ["timestamp"])
    _convert_legacy_timestamps(connection, "monitoring_events", ["timestamp"])

    # 7. Backfill the lifecycle model for pre-2.1 events: each legacy row
    #    was an independent observation, so it becomes a resolved event
    #    whose whole life is that single timestamp.
    connection.execute("""
        UPDATE monitoring_events
        SET status = 'resolved',
            opened_at = timestamp,
            closed_at = timestamp,
            last_seen = timestamp,
            occurrences = 1
        WHERE status IS NULL
    """)
    connection.commit()


def _convert_legacy_timestamps(connection, table: str, columns: list[str]) -> None:
    """Reinterpret naive timestamps as America/Sao_Paulo and store UTC.

    Rows that already carry timezone info are normalized to UTC instead,
    which makes the conversion idempotent: running it twice changes
    nothing the second time. Unparseable values are left untouched and
    logged so one bad row can never abort the migration.
    """
    select_cols = ", ".join(["id"] + columns)
    rows = connection.execute(f"SELECT {select_cols} FROM {table}").fetchall()
    converted = 0
    for row in rows:
        updates = {}
        for column in columns:
            raw = row[column]
            if not raw:
                continue
            try:
                parsed = datetime.fromisoformat(raw)
            except ValueError:
                logger.warning(
                    "Migration v1: skipping unparseable timestamp %r in %s.%s",
                    raw,
                    table,
                    column,
                )
                continue
            if parsed.tzinfo is None:
                # Legacy naive value: it was produced in America/Sao_Paulo.
                parsed = parsed.replace(tzinfo=LEGACY_TIMEZONE)
            utc = parsed.astimezone(timezone.utc).isoformat()
            if utc != raw:
                updates[column] = utc
        if updates:
            assignments = ", ".join(f"{col} = ?" for col in updates)
            connection.execute(
                f"UPDATE {table} SET {assignments} WHERE id = ?",
                (*updates.values(), row["id"]),
            )
            converted += 1
    if converted:
        logger.info(
            "Migration v1: converted %d rows to UTC in %s", converted, table
        )


_MIGRATIONS = {
    1: _migrate_v1,
}

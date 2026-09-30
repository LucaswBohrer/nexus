"""Reports: JSON summaries and streaming CSV exports (NEXUS 2.3).

Single source of truth: the JSON summary is built directly on
get_analytics_overview() -- reports and analytics share the exact same
formulas, there is no separate "reports math". CSV exports stream
row-by-row (fetchmany batches) and never build the whole dataset in
memory.
"""

import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from app.database.database import get_connection
from app.services.aggregation import (
    AggregationError,
    _equipment_filter,
    get_analytics_overview,
    parse_bound,
    validate_range,
)
from app.services.events import list_events

# Defensive caps for report payloads.
MAX_REPORT_EVENTS = 200  # list_events() enforces the same cap internally
MAX_REPORT_EPISODES = 200

READINGS_CSV_COLUMNS = (
    "timestamp",
    "voltage",
    "current",
    "frequency",
    "power_factor",
    "active_power",
    "temperature",
    "status",
)

EVENTS_CSV_COLUMNS = (
    "timestamp",
    "event_type",
    "severity",
    "status",
    "message",
    "recommendation",
    "occurrences",
    "opened_at",
    "closed_at",
    "last_value",
    "threshold",
)


def parse_date_param(value: str, name: str) -> datetime:
    """Strict YYYY-MM-DD -> midnight UTC. 422-style error on misuse."""
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except (ValueError, TypeError):
        raise AggregationError(
            f"Query parameter '{name}' must be YYYY-MM-DD, got {value!r}"
        )
    return parsed.replace(tzinfo=timezone.utc)


def parse_week_param(value: str) -> tuple[datetime, datetime]:
    """ISO week 'YYYY-Www' -> (week start Monday 00:00 UTC, next Monday)."""
    try:
        monday = datetime.strptime(value + "-1", "%G-W%V-%u")
    except (ValueError, TypeError):
        raise AggregationError(
            f"Query parameter 'week' must be ISO week 'YYYY-Www', "
            f"got {value!r}"
        )
    monday = monday.replace(tzinfo=timezone.utc)
    return monday, monday + timedelta(days=7)


def get_report_summary(
    from_dt: datetime, to_dt: datetime, equipment_id: int | None = None
) -> dict[str, Any]:
    """Full JSON report for a period.

    The numeric summary comes straight from get_analytics_overview() --
    the same function behind /api/v1/analytics/overview -- so reports
    and analytics can never disagree. NEXUS 2.4: optionally scoped to
    one equipment.
    """
    validate_range(from_dt, to_dt)
    overview = get_analytics_overview(
        from_dt, to_dt, equipment_id=equipment_id
    )
    per_metric = overview["per_metric"]
    equipment_sql, equipment_params = _equipment_filter(equipment_id)

    connection = get_connection()
    try:
        status_rows = connection.execute(
            f"""SELECT status, COUNT(*) FROM electrical_readings
               WHERE timestamp >= ? AND timestamp < ?{equipment_sql}
               GROUP BY status""",
            (overview["from"], overview["to"], *equipment_params),
        ).fetchall()
        episode_rows = connection.execute(
            f"""SELECT id, started_at, ended_at, status, severity,
                      rules, peak_values, recommendations, equipment_id
               FROM diagnostic_episodes
               WHERE started_at >= ? AND started_at < ?{equipment_sql}
               ORDER BY id DESC LIMIT ?""",
            (overview["from"], overview["to"], *equipment_params,
             MAX_REPORT_EPISODES),
        ).fetchall()
    finally:
        connection.close()

    status_counts = {"normal": 0, "warning": 0, "critical": 0}
    for status, count in status_rows:
        if status in status_counts:
            status_counts[status] = count

    events, _ = list_events(
        from_dt=from_dt,
        to_dt=to_dt,
        limit=MAX_REPORT_EVENTS,
        equipment_id=equipment_id,
    )
    episodes = [dict(row) for row in episode_rows]

    active_power = per_metric["active_power"]
    voltage = per_metric["voltage"]
    return {
        "period": {"from": overview["from"], "to": overview["to"]},
        "summary": {
            "readings_count": overview["readings_count"],
            "energy_kwh": overview["energy_kwh"],
            "power_avg": active_power["avg"],
            "power_max": active_power["max"],
            "voltage_avg": voltage["avg"],
            "voltage_min": voltage["min"],
            "voltage_max": voltage["max"],
            "power_factor_avg": per_metric["power_factor"]["avg"],
            "temperature_max": per_metric["temperature"]["max"],
        },
        "status": status_counts,
        "events": events,
        "events_truncated": len(events) >= MAX_REPORT_EVENTS,
        "diagnostic_episodes": episodes,
    }


def _csv_chunk(rows: list[tuple]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def iter_readings_csv(
    from_dt: datetime,
    to_dt: datetime,
    batch: int = 1000,
    equipment_id: int | None = None,
) -> Iterator[bytes]:
    """Stream readings as CSV. Only one batch is ever held in memory.
    NEXUS 2.4: optionally scoped to one equipment."""
    validate_range(from_dt, to_dt)
    yield _csv_chunk([READINGS_CSV_COLUMNS])
    equipment_sql, equipment_params = _equipment_filter(equipment_id)
    connection = get_connection()
    try:
        cursor = connection.execute(
            f"""SELECT timestamp, voltage, current, frequency,
                      power_factor, active_power, temperature, status
               FROM electrical_readings
               WHERE timestamp >= ? AND timestamp < ?{equipment_sql}
               ORDER BY timestamp ASC""",
            (from_dt.isoformat(), to_dt.isoformat(), *equipment_params),
        )
        while True:
            rows = cursor.fetchmany(batch)
            if not rows:
                break
            yield _csv_chunk([tuple(row) for row in rows])
    finally:
        connection.close()


def iter_events_csv(
    from_dt: datetime,
    to_dt: datetime,
    batch: int = 1000,
    equipment_id: int | None = None,
) -> Iterator[bytes]:
    """Stream events as CSV. Only one batch is ever held in memory.
    NEXUS 2.4: optionally scoped to one equipment."""
    validate_range(from_dt, to_dt)
    yield _csv_chunk([EVENTS_CSV_COLUMNS])
    equipment_sql, equipment_params = _equipment_filter(equipment_id)
    connection = get_connection()
    try:
        cursor = connection.execute(
            f"""SELECT timestamp, event_type, severity, status, message,
                      recommendation, occurrences, opened_at, closed_at,
                      last_value, threshold
               FROM monitoring_events
               WHERE opened_at >= ? AND opened_at < ?{equipment_sql}
               ORDER BY opened_at ASC""",
            (from_dt.isoformat(), to_dt.isoformat(), *equipment_params),
        )
        while True:
            rows = cursor.fetchmany(batch)
            if not rows:
                break
            yield _csv_chunk([tuple(row) for row in rows])
    finally:
        connection.close()


def resolve_format(value: str | None) -> str:
    """'json' (default) or 'csv'; anything else is a 422-style error."""
    fmt = (value or "json").lower()
    if fmt not in ("json", "csv"):
        raise AggregationError(
            f"Query parameter 'format' must be 'json' or 'csv', got {value!r}"
        )
    return fmt

"""Aggregation layer (NEXUS 2.1).

All heavy computation happens here, in SQL — the frontend receives ready
aggregations, never thousands of raw rows. Buckets, statistics and energy
are computed from the real stored readings.

Energy is computed with REAL timestamp deltas
(energy_kwh += power_kw * delta_seconds / 3600), never assuming exactly
one reading per second, so tick drift or slow disks cannot skew it. Deltas
are capped at MAX_ENERGY_DELTA_S: after a long gap (restart, outage) the
interval is not representative of continuous consumption.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.database.database import get_connection, get_latest_reading_from_db

logger = logging.getLogger(__name__)

# metric -> SQL expression over electrical_readings. apparent_power is a
# derived metric (S = V * I / 1000, kVA); there is no such sensor.
METRICS: dict[str, str] = {
    "voltage": "voltage",
    "current": "current",
    "active_power": "active_power",
    "power_factor": "power_factor",
    "temperature": "temperature",
    "frequency": "frequency",
    "apparent_power": "voltage * current / 1000.0",
}

# bucket name -> seconds.
BUCKETS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "1d": 86400,
}

# Hard limits so no request can build a giant response.
MAX_HISTORY_RANGE_DAYS = 31
MAX_BUCKETS = 2000

# Intervals longer than this are not representative (gap/outage); they are
# excluded from the energy integral instead of inflating it.
MAX_ENERGY_DELTA_S = 300.0

# Metrics summarized in the dashboard stats payload.
SUMMARY_METRICS = (
    "voltage",
    "current",
    "active_power",
    "power_factor",
    "temperature",
    "frequency",
)


class AggregationError(ValueError):
    """Invalid aggregation parameters (surfaced as HTTP 422)."""


def parse_bound(value: str, name: str) -> datetime:
    """Parse an ISO-8601 bound. Naive values are interpreted as UTC.

    All stored timestamps are UTC; interpreting naive query bounds as UTC
    keeps the comparison consistent. The frontend converts local time to
    UTC (or appends an offset) before calling.
    """
    try:
        parsed = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        raise AggregationError(
            f"Query parameter '{name}' must be ISO-8601, got {value!r}"
        )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def get_history_buckets(
    metric: str,
    from_dt: datetime,
    to_dt: datetime,
    bucket: str,
) -> list[dict[str, Any]]:
    """Aggregate one metric into time buckets.

    Returns [{"t", "min", "max", "avg", "count"}] ordered by time. Raises
    AggregationError for invalid parameters.
    """
    if metric not in METRICS:
        raise AggregationError(
            f"Unknown metric '{metric}'. Valid: {sorted(METRICS)}"
        )
    if bucket not in BUCKETS:
        raise AggregationError(
            f"Unknown bucket '{bucket}'. Valid: {sorted(BUCKETS)}"
        )
    if from_dt >= to_dt:
        raise AggregationError("'from' must be before 'to'")

    range_days = (to_dt - from_dt).total_seconds() / 86400
    if range_days > MAX_HISTORY_RANGE_DAYS:
        raise AggregationError(
            f"Range exceeds the {MAX_HISTORY_RANGE_DAYS}-day maximum"
        )

    bucket_s = BUCKETS[bucket]
    bucket_count = (to_dt - from_dt).total_seconds() / bucket_s
    if bucket_count > MAX_BUCKETS:
        raise AggregationError(
            f"Range/bucket combination would produce {bucket_count:.0f} "
            f"buckets (max {MAX_BUCKETS}); use a larger bucket"
        )

    expression = METRICS[metric]
    connection = get_connection()
    try:
        rows = connection.execute(
            f"""
            SELECT
                CAST(strftime('%s', timestamp) / ? AS INTEGER) AS bucket_id,
                MIN({expression}) AS min_v,
                MAX({expression}) AS max_v,
                AVG({expression}) AS avg_v,
                COUNT(*) AS n
            FROM electrical_readings
            WHERE timestamp >= ? AND timestamp < ?
            GROUP BY bucket_id
            ORDER BY bucket_id ASC
            """,
            (bucket_s, from_dt.isoformat(), to_dt.isoformat()),
        ).fetchall()
    finally:
        connection.close()

    return [
        {
            # Bucket start as UTC ISO. SQLite's unixepoch rendering is
            # naive; re-attach UTC explicitly.
            "t": datetime.fromtimestamp(
                row["bucket_id"] * bucket_s, tz=timezone.utc
            ).isoformat(),
            "min": row["min_v"],
            "max": row["max_v"],
            "avg": row["avg_v"],
            "count": row["n"],
        }
        for row in rows
    ]


def _parse_ts(raw: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def compute_energy_kwh(rows: list[tuple[str, float]]) -> float:
    """Integrate power over real timestamp deltas.

    `rows` are (timestamp_iso, active_power_kw) in ascending time order.
    Each interval contributes prev_power * delta / 3600; intervals longer
    than MAX_ENERGY_DELTA_S are skipped (gap, not consumption).
    """
    energy = 0.0
    prev_ts: datetime | None = None
    prev_power = 0.0
    for raw_ts, power in rows:
        ts = _parse_ts(raw_ts)
        if ts is None:
            continue
        if prev_ts is not None:
            delta = (ts - prev_ts).total_seconds()
            if 0 < delta <= MAX_ENERGY_DELTA_S:
                energy += prev_power * delta / 3600.0
        prev_ts, prev_power = ts, power
    return energy


def get_stats_summary(now: datetime | None = None) -> dict[str, Any]:
    """Consolidated dashboard payload, computed from real stored data."""
    now = now or datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_ago = now - timedelta(hours=24)

    connection = get_connection()
    try:
        readings_count = connection.execute(
            "SELECT COUNT(*) FROM electrical_readings"
        ).fetchone()[0]

        energy_rows = connection.execute(
            """SELECT timestamp, active_power FROM electrical_readings
               WHERE timestamp >= ? ORDER BY timestamp ASC""",
            (day_start.isoformat(),),
        ).fetchall()

        last_24h: dict[str, dict[str, float | None]] = {}
        for metric in SUMMARY_METRICS:
            row = connection.execute(
                f"""SELECT MIN({METRICS[metric]}), MAX({METRICS[metric]}),
                           AVG({METRICS[metric]})
                    FROM electrical_readings WHERE timestamp >= ?""",
                (day_ago.isoformat(),),
            ).fetchone()
            last_24h[metric] = {"min": row[0], "max": row[1], "avg": row[2]}

        status_rows = connection.execute(
            """SELECT status, COUNT(*) FROM electrical_readings
               WHERE timestamp >= ? GROUP BY status""",
            (day_ago.isoformat(),),
        ).fetchall()
    finally:
        connection.close()

    energy_today_kwh = compute_energy_kwh(
        [(r["timestamp"], r["active_power"]) for r in energy_rows]
    )

    latest = get_latest_reading_from_db()
    if latest and isinstance(latest.get("timestamp"), datetime):
        latest["timestamp"] = latest["timestamp"].isoformat()

    # Lazy import: monitoring imports the event pipeline; aggregation must
    # not create an import cycle at module load.
    from app.services.monitoring import telemetry_service

    return {
        "energy_today_kwh": energy_today_kwh,
        "readings_count": readings_count,
        "uptime_s": telemetry_service.get_uptime_seconds(),
        "current": latest,
        "last_24h": last_24h,
        "status_counts_24h": {row[0]: row[1] for row in status_rows},
    }

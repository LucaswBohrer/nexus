"""Diagnostic episode tracking (NEXUS 2.1 §14).

An *episode* is the whole-system view of an abnormal period, complementing
the per-condition event lifecycle in ``events.py``:

- the system enters an abnormal state (diagnosis status != "normal") with
  no open episode -> open a new episode (status='open', started_at=now);
- while abnormal -> the open episode is updated: severity is the worst seen,
  rules/recommendations are unioned, peak_values track per-metric min/max
  observed during the episode, normal_streak reset to 0;
- K consecutive normal ticks -> the episode closes (status='resolved',
  ended_at set). K = NORMAL_TICKS_TO_RESOLVE = 5, same as events.

JSON columns (rules, peak_values, recommendations) store real observed data,
never placeholders.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.database.database import get_connection

logger = logging.getLogger(__name__)

# Consecutive normal ticks required before an open episode closes.
NORMAL_TICKS_TO_RESOLVE = 5

# Metrics whose extremes are tracked inside an episode.
TRACKED_METRICS = (
    "voltage",
    "current",
    "active_power",
    "power_factor",
    "temperature",
    "frequency",
)

_SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}


def _worst_severity(first: str, second: str) -> str:
    if _SEVERITY_RANK.get(second, 0) > _SEVERITY_RANK.get(first, 0):
        return second
    return first


def _episode_peak_values(reading: dict[str, Any]) -> dict[str, dict[str, float]]:
    peaks: dict[str, dict[str, float]] = {}
    for metric in TRACKED_METRICS:
        value = reading.get(metric)
        if isinstance(value, (int, float)):
            peaks[metric] = {"min": float(value), "max": float(value)}
    return peaks


def _merge_peaks(
    existing: dict[str, Any], reading: dict[str, Any]
) -> dict[str, dict[str, float]]:
    merged: dict[str, dict[str, float]] = {}
    for metric in TRACKED_METRICS:
        value = reading.get(metric)
        if not isinstance(value, (int, float)):
            continue
        value = float(value)
        previous = existing.get(metric) or {}
        merged[metric] = {
            "min": min(value, previous.get("min", value)),
            "max": max(value, previous.get("max", value)),
        }
    return merged


def process_tick_episode(
    diagnosis: dict[str, Any],
    reading: dict[str, Any],
    now: datetime | None = None,
    equipment_id: int | None = None,
) -> None:
    """Apply the episode rules for one telemetry tick.

    `now` is injectable for deterministic tests; defaults to UTC now.

    NEXUS 2.4: episodes are isolated per equipment — an abnormal period
    on equipment A opens/updates/closes only A's episode. When
    ``equipment_id`` is omitted it falls back to the reading's stamp.
    """
    if equipment_id is None:
        raw = reading.get("equipment_id")
        equipment_id = int(raw) if raw is not None else None
    now_iso = (now or datetime.now(timezone.utc)).isoformat()
    abnormal = diagnosis.get("status") != "normal"

    connection = get_connection()
    try:
        open_query = (
            """SELECT id, severity, rules, peak_values, recommendations, normal_streak
               FROM diagnostic_episodes
               WHERE status = 'open' AND ended_at IS NULL"""
            + (" AND equipment_id = ?" if equipment_id is not None else "")
            + " ORDER BY id DESC LIMIT 1"
        )
        open_params = (equipment_id,) if equipment_id is not None else ()
        row = connection.execute(open_query, open_params).fetchone()

        if abnormal:
            anomalies = list(diagnosis.get("anomalies") or [])
            recommendations = list(diagnosis.get("recommendations") or [])
            severity = diagnosis.get("severity") or "info"
            if row is None:
                connection.execute(
                    """INSERT INTO diagnostic_episodes (
                           started_at, status, severity, rules, peak_values,
                           recommendations, normal_streak, equipment_id
                       ) VALUES (?, 'open', ?, ?, ?, ?, 0, ?)""",
                    (
                        now_iso,
                        severity,
                        json.dumps(anomalies),
                        json.dumps(_episode_peak_values(reading)),
                        json.dumps(recommendations),
                        equipment_id,
                    ),
                )
                logger.debug("Opened diagnostic episode: %s", anomalies)
            else:
                rules = set(json.loads(row["rules"] or "[]")) | set(anomalies)
                recs = set(json.loads(row["recommendations"] or "[]")) | set(
                    recommendations
                )
                peaks = _merge_peaks(json.loads(row["peak_values"] or "{}"), reading)
                connection.execute(
                    """UPDATE diagnostic_episodes
                       SET severity = ?, rules = ?, peak_values = ?,
                           recommendations = ?, normal_streak = 0
                       WHERE id = ?""",
                    (
                        _worst_severity(row["severity"], severity),
                        json.dumps(sorted(rules)),
                        json.dumps(peaks),
                        json.dumps(sorted(recs)),
                        row["id"],
                    ),
                )
        elif row is not None:
            streak = (row["normal_streak"] or 0) + 1
            if streak >= NORMAL_TICKS_TO_RESOLVE:
                connection.execute(
                    """UPDATE diagnostic_episodes
                       SET status = 'resolved', ended_at = ?, normal_streak = ?
                       WHERE id = ?""",
                    (now_iso, streak, row["id"]),
                )
                logger.debug("Closed diagnostic episode %d", row["id"])
            else:
                connection.execute(
                    "UPDATE diagnostic_episodes SET normal_streak = ? WHERE id = ?",
                    (streak, row["id"]),
                )
        connection.commit()
    finally:
        connection.close()


def list_episodes(
    limit: int = 50, equipment_id: int | None = None
) -> list[dict[str, Any]]:
    """Latest episodes first, with JSON columns parsed; optionally
    scoped to one equipment."""
    connection = get_connection()
    try:
        query = """SELECT id, started_at, ended_at, status, severity,
                      rules, peak_values, recommendations, equipment_id
               FROM diagnostic_episodes"""
        params: tuple = ()
        if equipment_id is not None:
            query += " WHERE equipment_id = ?"
            params = (equipment_id,)
        query += " ORDER BY id DESC LIMIT ?"
        rows = connection.execute(query, params + (limit,)).fetchall()
    finally:
        connection.close()

    episodes = []
    for row in rows:
        episodes.append(
            {
                "id": row["id"],
                "started_at": row["started_at"],
                "ended_at": row["ended_at"],
                "status": row["status"],
                "severity": row["severity"],
                "rules": json.loads(row["rules"] or "[]"),
                "peak_values": json.loads(row["peak_values"] or "{}"),
                "recommendations": json.loads(row["recommendations"] or "[]"),
                "equipment_id": row["equipment_id"],
            }
        )
    return episodes

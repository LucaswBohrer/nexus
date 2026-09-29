"""Event lifecycle service (NEXUS 2.1).

Replaces the old "one row per anomalous tick" behavior. Each distinct
condition has at most one non-resolved event, identified by
``(event_type, equipment_id)`` (see ``event_identity()``; ``equipment_id``
is None today and reserved for future per-equipment deduplication):

- condition appears, no open/acknowledged event -> create
  (status='open', occurrences=1, opened_at=now);
- condition persists -> occurrences += 1, last_value/last_seen updated,
  normal_streak reset;
- condition absent for K consecutive ticks -> status='resolved',
  closed_at set (K = NORMAL_TICKS_TO_RESOLVE = 5).

A resolved event is NEVER reopened: a later occurrence of the same
condition creates a NEW event row.

Severity is stored normalized (info/warning/critical); the legacy API
maps it back for old clients.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from app.database.database import get_connection

logger = logging.getLogger(__name__)

# Consecutive normal ticks required before an absent condition is resolved.
NORMAL_TICKS_TO_RESOLVE = 5

# Lifecycle states an event can be in while its condition may still recur.
ACTIVE_STATES = ("open", "acknowledged")


def event_identity(event: dict[str, Any]) -> tuple[str, Any]:
    """Deduplication key for a condition: (event_type, equipment_id)."""
    return (event["event_type"], event.get("equipment_id"))


def process_tick_events(
    diagnosis_events: list[dict[str, Any]],
    now: datetime | None = None,
) -> None:
    """Apply the lifecycle rules for one telemetry tick.

    `diagnosis_events` are the firing conditions from analyze_reading().
    `now` is injectable for deterministic tests; defaults to UTC now.
    """
    now_iso = (now or datetime.now(timezone.utc)).isoformat()
    firing = {event_identity(event) for event in diagnosis_events}

    connection = get_connection()
    try:
        for event in diagnosis_events:
            _upsert_firing_event(connection, event, now_iso)
        _age_absent_events(connection, firing, now_iso)
        connection.commit()
    finally:
        connection.close()


def _find_active_event(
    connection, event_type: str, equipment_id: Any
) -> Any | None:
    # equipment_id is NULL today; COALESCE makes NULL = NULL comparisons work
    # and keeps the query correct once per-equipment ids exist.
    return connection.execute(
        """SELECT id FROM monitoring_events
           WHERE event_type = ?
             AND COALESCE(equipment_id, '') = COALESCE(?, '')
             AND status IN ('open', 'acknowledged')
           LIMIT 1""",
        (event_type, equipment_id),
    ).fetchone()


def _upsert_firing_event(connection, event: dict[str, Any], now_iso: str) -> None:
    event_type, equipment_id = event_identity(event)
    row = _find_active_event(connection, event_type, equipment_id)
    if row is None:
        connection.execute(
            """INSERT INTO monitoring_events (
                   timestamp, event_type, severity, message, recommendation,
                   status, opened_at, last_seen, occurrences,
                   last_value, threshold, equipment_id, normal_streak
               ) VALUES (?, ?, ?, ?, ?, 'open', ?, ?, 1, ?, ?, ?, 0)""",
            (
                now_iso,
                event_type,
                event["severity"],
                event["message"],
                event["recommendation"],
                now_iso,
                now_iso,
                event.get("value"),
                event.get("threshold"),
                equipment_id,
            ),
        )
        logger.debug("Opened event for condition %s", event_type)
    else:
        connection.execute(
            """UPDATE monitoring_events
               SET occurrences = occurrences + 1,
                   last_seen = ?,
                   last_value = ?,
                   message = ?,
                   recommendation = ?,
                   normal_streak = 0
               WHERE id = ?""",
            (
                now_iso,
                event.get("value"),
                event["message"],
                event["recommendation"],
                row["id"],
            ),
        )


def _age_absent_events(
    connection, firing: set[tuple[str, Any]], now_iso: str
) -> None:
    rows = connection.execute(
        """SELECT id, event_type, equipment_id, normal_streak
           FROM monitoring_events
           WHERE status IN ('open', 'acknowledged')"""
    ).fetchall()
    for row in rows:
        identity = (row["event_type"], row["equipment_id"])
        if identity in firing:
            continue
        streak = (row["normal_streak"] or 0) + 1
        if streak >= NORMAL_TICKS_TO_RESOLVE:
            connection.execute(
                """UPDATE monitoring_events
                   SET status = 'resolved', closed_at = ?, normal_streak = ?
                   WHERE id = ?""",
                (now_iso, streak, row["id"]),
            )
            logger.debug(
                "Resolved event %d (%s) after %d normal ticks",
                row["id"],
                row["event_type"],
                streak,
            )
        else:
            connection.execute(
                "UPDATE monitoring_events SET normal_streak = ? WHERE id = ?",
                (streak, row["id"]),
            )

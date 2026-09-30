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

# Valid status filter values for the API.
STATUSES = ("open", "acknowledged", "resolved")

# Valid severities stored in the database.
SEVERITIES = ("info", "warning", "critical")


def _normalize_equipment_id(value: Any) -> int | None:
    """Normalize an equipment reference to an int id.

    Needed because ``monitoring_events.equipment_id`` is a TEXT column
    (since v1) while the rest of NEXUS 2.4 passes integer ids. Returns
    None for missing/unparseable values (legacy rows).
    """
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def event_identity(event: dict[str, Any]) -> tuple[str, int | None]:
    """Deduplication key for a condition: (event_type, equipment_id).

    NEXUS 2.4: the same condition can fire on several equipments and
    each one is an independent event row.
    """
    return (
        event["event_type"],
        _normalize_equipment_id(event.get("equipment_id")),
    )


def process_tick_events(
    diagnosis_events: list[dict[str, Any]],
    now: datetime | None = None,
    equipment_id: int | None = None,
) -> None:
    """Apply the lifecycle rules for one telemetry tick.

    `diagnosis_events` are the firing conditions from analyze_reading().
    `now` is injectable for deterministic tests; defaults to UTC now.

    NEXUS 2.4: the caller stamps every event with the tick's
    equipment_id (``equipment_id`` is a fallback for legacy callers).
    Event aging is scoped to that equipment: a tick for equipment A
    never ages or resolves events belonging to equipment B.
    """
    now_iso = (now or datetime.now(timezone.utc)).isoformat()
    tick_equipment = _normalize_equipment_id(equipment_id)
    for event in diagnosis_events:
        stamped = _normalize_equipment_id(event.get("equipment_id"))
        event["equipment_id"] = (
            stamped if stamped is not None else tick_equipment
        )
    firing = {event_identity(event) for event in diagnosis_events}

    connection = get_connection()
    try:
        for event in diagnosis_events:
            _upsert_firing_event(connection, event, now_iso)
        _age_absent_events(connection, firing, now_iso, tick_equipment)
        connection.commit()
    finally:
        connection.close()


def _find_active_event(
    connection, event_type: str, equipment_id: int | None
) -> Any | None:
    # equipment_id is a TEXT column (v1) holding integer ids; CAST makes
    # the comparison type-safe. NULL equipment (legacy rows) matches
    # only NULL, via the -1 sentinel.
    return connection.execute(
        """SELECT id FROM monitoring_events
           WHERE event_type = ?
             AND CAST(COALESCE(equipment_id, -1) AS INTEGER)
                 = CAST(COALESCE(?, -1) AS INTEGER)
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
    connection,
    firing: set[tuple[str, int | None]],
    now_iso: str,
    tick_equipment_id: int | None,
) -> None:
    # NEXUS 2.4: aging is scoped to the tick's equipment. A tick for
    # equipment A must not touch events of equipment B. When the tick
    # carries no equipment (legacy callers), only legacy NULL-equipment
    # rows are aged, preserving the pre-2.4 behaviour.
    if tick_equipment_id is None:
        query = (
            "SELECT id, event_type, equipment_id, normal_streak"
            " FROM monitoring_events"
            " WHERE status IN ('open', 'acknowledged')"
            " AND equipment_id IS NULL"
        )
        rows = connection.execute(query).fetchall()
    else:
        rows = connection.execute(
            """SELECT id, event_type, equipment_id, normal_streak
               FROM monitoring_events
               WHERE status IN ('open', 'acknowledged')
                 AND CAST(equipment_id AS INTEGER) = ?""",
            (tick_equipment_id,),
        ).fetchall()
    for row in rows:
        identity = (
            row["event_type"],
            _normalize_equipment_id(row["equipment_id"]),
        )
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


# ---------------------------------------------------------------------------
# Query API (used by GET /api/v1/events)
# ---------------------------------------------------------------------------

_EVENT_COLUMNS = (
    "id, timestamp, event_type, severity, message, recommendation, status, "
    "opened_at, closed_at, last_seen, occurrences, last_value, threshold, "
    "acknowledged_at, acknowledged_by, equipment_id"
)


class EventError(ValueError):
    """Invalid event query or transition (surfaced as HTTP 422)."""


class EventNotFound(Exception):
    """Event id does not exist (surfaced as HTTP 404)."""


def get_event(event_id: int) -> dict[str, Any] | None:
    connection = get_connection()
    try:
        row = connection.execute(
            f"SELECT {_EVENT_COLUMNS} FROM monitoring_events WHERE id = ?",
            (event_id,),
        ).fetchone()
    finally:
        connection.close()
    return dict(row) if row else None


def list_events(
    status: str | None = None,
    severity: str | None = None,
    event_type: str | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    q: str | None = None,
    limit: int = 50,
    cursor: int | None = None,
    equipment_id: int | None = None,
) -> tuple[list[dict[str, Any]], int | None]:
    """List events, latest first, with optional filters and id-cursor paging.

    Returns (items, next_cursor); next_cursor is None when there are no
    more pages. Raises EventError on invalid filter values.
    """
    if status is not None and status not in STATUSES:
        raise EventError(f"Invalid status '{status}'. Valid: {list(STATUSES)}")
    if severity is not None and severity not in SEVERITIES:
        raise EventError(
            f"Invalid severity '{severity}'. Valid: {list(SEVERITIES)}"
        )
    limit = max(1, min(limit, 200))

    conditions = []
    params: list[Any] = []
    if status is not None:
        conditions.append("status = ?")
        params.append(status)
    if severity is not None:
        conditions.append("severity = ?")
        params.append(severity)
    if event_type is not None:
        conditions.append("event_type = ?")
        params.append(event_type)
    if from_dt is not None:
        conditions.append("timestamp >= ?")
        params.append(from_dt.isoformat())
    if to_dt is not None:
        conditions.append("timestamp < ?")
        params.append(to_dt.isoformat())
    if q:
        conditions.append("message LIKE ?")
        params.append(f"%{q}%")
    if cursor is not None:
        conditions.append("id < ?")
        params.append(cursor)
    if equipment_id is not None:
        # equipment_id is a TEXT column holding integer ids; CAST makes
        # the comparison type-safe.
        conditions.append("CAST(equipment_id AS INTEGER) = ?")
        params.append(equipment_id)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    connection = get_connection()
    try:
        # Fetch one extra row to know whether another page exists.
        rows = connection.execute(
            f"""SELECT {_EVENT_COLUMNS} FROM monitoring_events
                {where}
                ORDER BY id DESC
                LIMIT ?""",
            (*params, limit + 1),
        ).fetchall()
    finally:
        connection.close()

    items = []
    for row in rows[:limit]:
        item = dict(row)
        # NEXUS 2.4: the column has TEXT affinity, but the public
        # contract is an integer equipment id (None only for legacy
        # rows that predate equipment stamping).
        item["equipment_id"] = _normalize_equipment_id(
            item.get("equipment_id")
        )
        items.append(item)
    next_cursor = items[-1]["id"] if len(rows) > limit else None
    return items, next_cursor


# ---------------------------------------------------------------------------
# Transitions (used by PATCH /api/v1/events/{id})
# ---------------------------------------------------------------------------

# action -> (allowed from-states, resulting state)
_TRANSITIONS = {
    "acknowledge": (("open",), "acknowledged"),
    "resolve": (("open", "acknowledged"), "resolved"),
}


def transition_event(
    event_id: int, action: str, actor: str | None = None
) -> dict[str, Any]:
    """Apply a lifecycle transition. Raises EventNotFound / EventError."""
    if action not in _TRANSITIONS:
        raise EventError(
            f"Invalid action '{action}'. Valid: {sorted(_TRANSITIONS)}"
        )
    allowed_from, to_state = _TRANSITIONS[action]

    now_iso = datetime.now(timezone.utc).isoformat()
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT id, status FROM monitoring_events WHERE id = ?",
            (event_id,),
        ).fetchone()
        if row is None:
            raise EventNotFound(f"No event with id {event_id}")
        if row["status"] not in allowed_from:
            raise EventError(
                f"Cannot '{action}' an event with status '{row['status']}'"
            )

        if to_state == "acknowledged":
            connection.execute(
                """UPDATE monitoring_events
                   SET status = 'acknowledged',
                       acknowledged_at = ?, acknowledged_by = ?
                   WHERE id = ?""",
                (now_iso, actor, event_id),
            )
        else:  # resolved
            connection.execute(
                """UPDATE monitoring_events
                   SET status = 'resolved', closed_at = ?
                   WHERE id = ?""",
                (now_iso, event_id),
            )
        connection.commit()
        updated = connection.execute(
            f"SELECT {_EVENT_COLUMNS} FROM monitoring_events WHERE id = ?",
            (event_id,),
        ).fetchone()
    finally:
        connection.close()

    logger.info("Event %d: %s -> %s", event_id, row["status"], to_state)
    return dict(updated)

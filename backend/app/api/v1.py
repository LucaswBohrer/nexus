"""NEXUS API v1 (NEXUS 2.1).

New functionality lives here. The legacy /api/* endpoints keep their exact
contracts and are implemented in app.api.routes.
"""

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import require_api_key
from app.services import settings as settings_service
from app.services.aggregation import (
    AggregationError,
    get_history_buckets,
    get_stats_summary,
    parse_bound,
)
from app.services.episodes import list_episodes
from app.services.errors import get_errors
from app.services.events import (
    EventError,
    EventNotFound,
    list_events,
    transition_event,
)

router = APIRouter(prefix="/api/v1")


class SettingUpdate(BaseModel):
    value: Any


class EventTransition(BaseModel):
    action: str


@router.get("/settings")
def list_settings():
    """Return every known setting with its effective value."""
    return {"settings": settings_service.get_all_settings()}


@router.get("/settings/{key}")
def get_setting(key: str):
    """Return a single setting. 404 for unknown keys."""
    try:
        value = settings_service.get_setting(key)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown setting: {key}")
    return {"key": key, "value": value}


@router.put("/settings/{key}", dependencies=[Depends(require_api_key)])
def update_setting(key: str, body: SettingUpdate):
    """Update a setting. 404 for unknown keys, 422 for invalid values."""
    try:
        value = settings_service.set_setting(key, body.value)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown setting: {key}")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"key": key, "value": value}


# ---------------------------------------------------------------------------
# History / aggregation
# ---------------------------------------------------------------------------


@router.get("/history")
def get_history(
    metric: str = Query(..., description="Metric name, e.g. voltage"),
    from_: str = Query(
        ..., alias="from", description="ISO-8601 start (naive = UTC)"
    ),
    to: str = Query(..., description="ISO-8601 end (naive = UTC)"),
    bucket: str = Query("5m", description="Bucket size: 1m, 5m, 15m, 1h, 1d"),
):
    """Aggregate one metric into time buckets.

    Naive `from`/`to` values are interpreted as UTC (all stored timestamps
    are UTC). Maximum range is 31 days and 2000 buckets; violations
    return 422.
    """
    try:
        from_dt = parse_bound(from_, "from")
        to_dt = parse_bound(to, "to")
        buckets = get_history_buckets(metric, from_dt, to_dt, bucket)
    except AggregationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"buckets": buckets}


@router.get("/stats/summary")
def get_summary():
    """Consolidated dashboard statistics, computed from real stored data."""
    return get_stats_summary()


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


@router.get("/events")
def get_events_v1(
    status: str | None = Query(None, description="open, acknowledged, resolved"),
    severity: str | None = Query(None, description="info, warning, critical"),
    type: str | None = Query(None, alias="type", description="Event type"),
    from_: str | None = Query(None, alias="from", description="ISO-8601 (naive = UTC)"),
    to: str | None = Query(None, description="ISO-8601 (naive = UTC)"),
    q: str | None = Query(None, description="Substring search in message"),
    limit: int = Query(50, ge=1, le=200),
    cursor: int | None = Query(None, description="Paging cursor (event id)"),
):
    """List events, latest first, with filters and id-cursor pagination."""
    try:
        from_dt = parse_bound(from_, "from") if from_ else None
        to_dt = parse_bound(to, "to") if to else None
        items, next_cursor = list_events(
            status=status,
            severity=severity,
            event_type=type,
            from_dt=from_dt,
            to_dt=to_dt,
            q=q,
            limit=limit,
            cursor=cursor,
        )
    except EventError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"events": items, "next_cursor": next_cursor}


@router.patch("/events/{event_id}", dependencies=[Depends(require_api_key)])
def patch_event(event_id: int, body: EventTransition):
    """Acknowledge or resolve an event.

    Valid transitions: open -> acknowledged, open -> resolved,
    acknowledged -> resolved. Anything else returns 422; a resolved
    event is never reopened.
    """
    try:
        event = transition_event(event_id, body.action)
    except EventNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except EventError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"event": event}


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


@router.get("/diagnostics/episodes")
def get_diagnostic_episodes(
    limit: int = Query(default=20, ge=1, le=200),
):
    """Diagnostic episodes: whole-system abnormal periods, latest first."""
    return {"episodes": list_episodes(limit)}


# ---------------------------------------------------------------------------
# System / observability
# ---------------------------------------------------------------------------


@router.get("/system/errors")
def system_errors():
    """Last 100 process errors, latest first (in-memory ring buffer)."""
    return {"errors": get_errors()}


@router.get("/system/database")
def system_database():
    """SQLite database introspection: path, size, tables, schema version."""
    from app.database import database as database_module
    from app.database.database import get_connection
    from app.database.migrations import get_schema_version

    db_path = str(database_module.DB_PATH)
    connection = get_connection()
    try:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' ORDER BY name"
            ).fetchall()
        ]
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        user_version = get_schema_version(connection)
    finally:
        connection.close()

    return {
        "path": db_path,
        "size_bytes": (
            os.path.getsize(db_path) if os.path.exists(db_path) else 0
        ),
        "tables": tables,
        "user_version": user_version,
        "journal_mode": journal_mode,
    }

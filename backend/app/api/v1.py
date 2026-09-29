"""NEXUS API v1 (NEXUS 2.1).

New functionality lives here. The legacy /api/* endpoints keep their exact
contracts and are implemented in app.api.routes.
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.deps import require_api_key
from app.services import settings as settings_service
from app.services.aggregation import (
    AggregationError,
    get_analytics_overview,
    get_history_buckets,
    get_history_extremes,
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
from app.services.monitoring import telemetry_service

logger = logging.getLogger(__name__)

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
# Real-time stream (SSE)
# ---------------------------------------------------------------------------

# Seconds between `: heartbeat` comments so buffering proxies (nginx,
# tunnels) do not stall the stream.
SSE_HEARTBEAT_S = 15.0

# Target event cadence (~1 Hz, matching the telemetry tick).
SSE_INTERVAL_S = 1.0


def _serialize_reading(reading: dict[str, Any]) -> dict[str, Any]:
    serialized = dict(reading)
    timestamp = serialized.get("timestamp")
    if isinstance(timestamp, datetime):
        serialized["timestamp"] = timestamp.isoformat()
    return serialized


def _latest_stream_payload() -> dict[str, Any] | None:
    """Sample the shared telemetry state. Returns None before any tick."""
    try:
        latest = telemetry_service.get_latest_diagnosis()
    except RuntimeError:
        return None
    diagnosis = latest["diagnosis"]
    return {
        "reading": _serialize_reading(latest["reading"]),
        "diagnosis_status": diagnosis["status"],
        "severity": diagnosis["severity"],
        "server_ts": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/stream/readings")
def stream_readings():
    """Server-Sent Events stream of live readings (~1 Hz).

    Each `data:` event is JSON
    {"reading", "diagnosis_status", "severity", "server_ts"}. A
    `: heartbeat` comment is sent every 15 s so proxies do not buffer
    the connection. The generator samples the shared telemetry state —
    no per-client buffers, so many clients cannot leak memory. Public
    like every other GET (NEXUS_API_KEY only guards writes).
    """

    def event_generator():
        last_heartbeat = time.monotonic()
        try:
            while True:
                payload = _latest_stream_payload()
                if payload is not None:
                    yield f"data: {json.dumps(payload)}\n\n"
                now = time.monotonic()
                if now - last_heartbeat >= SSE_HEARTBEAT_S:
                    yield ": heartbeat\n\n"
                    last_heartbeat = now
                time.sleep(SSE_INTERVAL_S)
        except (GeneratorExit, asyncio.CancelledError):
            # Client disconnected; the generator is torn down silently.
            return
        except Exception:
            logger.exception("SSE stream generator failed")
            return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


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


@router.get("/history/extremes")
def get_extremes(
    metric: str = Query(..., description="Metric name, e.g. voltage"),
    from_: str = Query(
        ..., alias="from", description="ISO-8601 start (naive = UTC)"
    ),
    to: str = Query(..., description="ISO-8601 end (naive = UTC)"),
):
    """Min/max/avg of one metric over a range, with extreme timestamps.

    Naive `from`/`to` are interpreted as UTC. Maximum range is 31 days;
    violations return 422.
    """
    try:
        from_dt = parse_bound(from_, "from")
        to_dt = parse_bound(to, "to")
        return get_history_extremes(metric, from_dt, to_dt)
    except AggregationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/stats/summary")
def get_summary():
    """Consolidated dashboard statistics, computed from real stored data."""
    return get_stats_summary()


@router.get("/analytics/overview")
def get_analytics(
    from_: str = Query(
        ..., alias="from", description="ISO-8601 start (naive = UTC)"
    ),
    to: str = Query(..., description="ISO-8601 end (naive = UTC)"),
):
    """Period analytics: readings, energy, per-metric stats, event and
    episode counts. All values come from the real stored tables.

    Naive `from`/`to` are interpreted as UTC. Maximum range is 31 days;
    violations return 422.
    """
    try:
        from_dt = parse_bound(from_, "from")
        to_dt = parse_bound(to, "to")
        return get_analytics_overview(from_dt, to_dt)
    except AggregationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


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

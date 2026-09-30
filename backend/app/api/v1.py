"""NEXUS API v1 (NEXUS 2.1).

New functionality lives here. The legacy /api/* endpoints keep their exact
contracts and are implemented in app.api.routes.
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.deps import require_api_key
from app.engine.simulator import SimulationError
from app.services import settings as settings_service
from app.services import simulation as simulation_service
from app.services.simulation import SimulationConflict
from app.services import reports as reports_service
from app.services import equipment as equipment_service
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


class EquipmentCreate(BaseModel):
    """Payload to register a new equipment.

    `name` and `code` are required; `code` is unique across the
    registry. `status` must be active | inactive | maintenance.
    `enabled=False` registers the equipment deactivated (writes are
    refused, history stays readable).
    """

    name: str
    code: str
    description: str | None = None
    equipment_type: str | None = None
    location: str | None = None
    status: str = "active"
    enabled: bool = True


class EquipmentUpdate(BaseModel):
    """Partial equipment update; every field is optional."""

    name: str | None = None
    code: str | None = None
    description: str | None = None
    equipment_type: str | None = None
    location: str | None = None
    status: str | None = None
    enabled: bool | None = None


def _equipment_error(exc: Exception) -> HTTPException:
    """Map equipment service errors to HTTP status codes."""
    if isinstance(exc, equipment_service.EquipmentNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, equipment_service.EquipmentConflict):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


def _resolve_equipment(equipment_id: str | None) -> int:
    """Resolve the `equipment_id` query/body param to an integer id.

    Omitted -> the DEFAULT equipment (all pre-2.4 data); accepts ids
    and codes. Unknown references raise 404.
    """
    try:
        return equipment_service.resolve_equipment_id(equipment_id)
    except equipment_service.EquipmentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


EQUIPMENT_ID_PARAM = Query(
    None,
    description=(
        "Equipment id or code. Omitted = DEFAULT equipment, which owns"
        " all pre-2.4 data (backward compatible)."
    ),
)


class EventTransition(BaseModel):
    action: str


# ---------------------------------------------------------------------------
# Simulation control center (NEXUS 2.3)
# ---------------------------------------------------------------------------


class SimulationStart(BaseModel):
    mode: str
    intensity: Any = 100.0
    duration_minutes: Any = None
    anomalies: Any = None
    equipment_id: Any = None  # NEXUS 2.4: id or code; None = DEFAULT


@router.post("/simulation/start", dependencies=[Depends(require_api_key)])
def simulation_start(body: SimulationStart):
    """Start a simulation scenario.

    - intensity: 0-200 (percent of the mode's nominal deviation)
    - duration_minutes: null = indefinite, otherwise a positive number
      of minutes (fractional values allowed, e.g. 0.05 ~= 3 s)
    - anomalies: optional composer list of extra anomaly names
    - equipment_id: id or code of the equipment being simulated;
      omitted = DEFAULT equipment (backward compatible)
    Invalid payloads return 422; unknown equipment returns 404;
    disabled equipment returns 409.
    """
    try:
        return simulation_service.start_simulation(
            mode=body.mode,
            intensity=body.intensity,
            duration_minutes=body.duration_minutes,
            anomalies=body.anomalies,
            equipment_id=body.equipment_id,
        )
    except SimulationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except (
        equipment_service.EquipmentNotFound,
        equipment_service.EquipmentConflict,
    ) as exc:
        raise _equipment_error(exc) from exc


@router.get("/simulation/status")
def simulation_status(equipment_id: str | None = EQUIPMENT_ID_PARAM):
    """Current simulation status. Cheap and safe for polling; the backend
    is the source of truth (remaining_seconds is computed server-side).

    With equipment_id the view is per-equipment: when the active
    session belongs to another equipment, this one is reported idle.
    """
    eid = _resolve_equipment(equipment_id)
    return simulation_service.get_status(equipment_id=eid)


@router.post("/simulation/stop", dependencies=[Depends(require_api_key)])
def simulation_stop(equipment_id: str | None = EQUIPMENT_ID_PARAM):
    """Stop the active simulation and revert to normal. Idempotent: when
    nothing is running it reports stopped=false instead of erroring.

    NEXUS 2.4: ``equipment_id`` scopes the stop — the active session must
    belong to that equipment (409 on mismatch). Omitted keeps the legacy
    global stop.
    """
    try:
        eid = (
            _resolve_equipment(equipment_id)
            if equipment_id is not None
            else None
        )
        return simulation_service.stop_simulation(equipment_id=eid)
    except SimulationConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/simulation/reset", dependencies=[Depends(require_api_key)])
def simulation_reset(equipment_id: str | None = EQUIPMENT_ID_PARAM):
    """Reset to baseline: end any active session, clear the timer and any
    composer anomalies, restore intensity 100%.

    NEXUS 2.4: same scoping contract as stop (409 on equipment mismatch).
    """
    try:
        eid = (
            _resolve_equipment(equipment_id)
            if equipment_id is not None
            else None
        )
        return simulation_service.reset_simulation(equipment_id=eid)
    except SimulationConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/simulation/sessions")
def simulation_sessions(
    limit: int = Query(50, ge=1, le=200),
    cursor: int | None = Query(None, description="Paging cursor (session id)"),
    equipment_id: str | None = EQUIPMENT_ID_PARAM,
):
    """Simulation session history, newest first, with id-cursor paging.
    Optionally scoped to one equipment."""
    try:
        eid = _resolve_equipment(equipment_id)
        return simulation_service.list_sessions(
            limit=limit, cursor=cursor, equipment_id=eid
        )
    except SimulationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ---------------------------------------------------------------------------
# Equipment registry (NEXUS 2.4)
# ---------------------------------------------------------------------------


@router.get("/equipment")
def list_equipment_api():
    """List every registered equipment, oldest first. The DEFAULT
    equipment owns all pre-2.4 data."""
    return {"equipment": equipment_service.list_equipment()}


@router.get("/equipment/{equipment_id}")
def get_equipment_api(equipment_id: int):
    """One equipment by id. 404 for unknown ids."""
    equipment = equipment_service.get_equipment(equipment_id)
    if equipment is None:
        raise HTTPException(
            status_code=404, detail=f"equipment not found: {equipment_id!r}"
        )
    return {"equipment": equipment}


@router.post("/equipment", dependencies=[Depends(require_api_key)])
def create_equipment_api(body: EquipmentCreate):
    """Register a new equipment. 422 for validation errors (missing
    name, duplicate code, invalid status)."""
    try:
        equipment = equipment_service.create_equipment(
            name=body.name,
            code=body.code,
            description=body.description,
            equipment_type=body.equipment_type,
            location=body.location,
            status=body.status,
            enabled=body.enabled,
        )
    except Exception as exc:
        raise _equipment_error(exc) from exc
    return {"equipment": equipment}


@router.patch("/equipment/{equipment_id}", dependencies=[Depends(require_api_key)])
def update_equipment_api(equipment_id: int, body: EquipmentUpdate):
    """Partial equipment update (including enabled=false deactivation).
    404 for unknown ids, 422 for validation errors."""
    try:
        equipment = equipment_service.update_equipment(
            equipment_id,
            **{
                key: value
                for key, value in body.model_dump().items()
                if value is not None
            },
        )
    except Exception as exc:
        raise _equipment_error(exc) from exc
    return {"equipment": equipment}


@router.delete("/equipment/{equipment_id}", dependencies=[Depends(require_api_key)])
def delete_equipment_api(equipment_id: int):
    """Physical delete, only for equipment without historical data.

    404 for unknown ids; 409 for the DEFAULT equipment and for
    equipment that still has data. Prefer PATCH enabled=false
    (logical deactivation) for anything real.
    """
    try:
        equipment_service.delete_equipment(equipment_id)
    except Exception as exc:
        raise _equipment_error(exc) from exc
    return {"deleted": True, "equipment_id": equipment_id}


@router.get("/equipment/{equipment_id}/summary")
def get_equipment_summary(equipment_id: int):
    """Equipment summary from real stored data only: identity, status,
    last reading + timestamp, current diagnosis state, active events,
    open episodes and the readings count. Empty states are honest
    (nulls/zeros) for equipment without data. 404 for unknown ids."""
    equipment = equipment_service.get_equipment(equipment_id)
    if equipment is None:
        raise HTTPException(
            status_code=404, detail=f"equipment not found: {equipment_id!r}"
        )
    from app.database.database import get_connection
    from app.engine.diagnostics import analyze_reading

    connection = get_connection()
    try:
        last_reading = connection.execute(
            "SELECT * FROM electrical_readings"
            " WHERE equipment_id = ?"
            " ORDER BY id DESC LIMIT 1",
            (equipment_id,),
        ).fetchone()
        readings_count = connection.execute(
            "SELECT COUNT(*) FROM electrical_readings"
            " WHERE equipment_id = ?",
            (equipment_id,),
        ).fetchone()[0]
        # monitoring_events.equipment_id is TEXT: CAST for a type-safe
        # comparison (an int = comparison against TEXT never matches).
        active_events = connection.execute(
            "SELECT COUNT(*) FROM monitoring_events"
            " WHERE CAST(equipment_id AS INTEGER) = ?"
            " AND status IN ('open', 'acknowledged')",
            (equipment_id,),
        ).fetchone()[0]
        open_episodes = connection.execute(
            "SELECT COUNT(*) FROM diagnostic_episodes"
            " WHERE equipment_id = ? AND status = 'open'",
            (equipment_id,),
        ).fetchone()[0]
    finally:
        connection.close()

    last_reading_dict = dict(last_reading) if last_reading else None
    # NEXUS 2.4: the current diagnosis is recomputed from the last real
    # stored reading with the diagnosis engine (current thresholds) —
    # never invented state.
    diagnosis = None
    if last_reading_dict is not None:
        evaluated = analyze_reading(dict(last_reading_dict))
        diagnosis = {
            "status": evaluated["status"],
            "severity": evaluated.get("severity"),
            "anomalies": evaluated.get("anomalies", []),
            "recommendations": evaluated.get("recommendations", []),
        }
    return {
        "equipment": equipment,
        "last_reading": last_reading_dict,
        "last_reading_at": (
            last_reading_dict["timestamp"] if last_reading_dict else None
        ),
        "diagnosis": diagnosis,
        "active_events": active_events,
        "open_episodes": open_episodes,
        "readings_count": readings_count,
    }


# ---------------------------------------------------------------------------
# Reports (NEXUS 2.3)
# ---------------------------------------------------------------------------


def _csv_response(
    generator, filename: str
) -> StreamingResponse:
    return StreamingResponse(
        generator,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reports/daily")
def report_daily(
    date: str | None = Query(
        None, description="Day as YYYY-MM-DD (default: today, UTC)"
    ),
    format: str | None = Query(
        None, description="'json' (default) or 'csv'"
    ),
    equipment_id: str | None = EQUIPMENT_ID_PARAM,
):
    """Daily report for one UTC day. JSON is the full summary (same
    numbers as /analytics/overview); CSV streams the day's readings.
    Optionally scoped to one equipment."""
    try:
        fmt = reports_service.resolve_format(format)
        day = (
            reports_service.parse_date_param(date, "date")
            if date
            else datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        )
        from_dt, to_dt = day, day + timedelta(days=1)
        eid = _resolve_equipment(equipment_id)
        if fmt == "csv":
            return _csv_response(
                reports_service.iter_readings_csv(
                    from_dt, to_dt, equipment_id=eid
                ),
                f"nexus-readings-{day.strftime('%Y-%m-%d')}.csv",
            )
        return reports_service.get_report_summary(
            from_dt, to_dt, equipment_id=eid
        )
    except AggregationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/reports/weekly")
def report_weekly(
    week: str | None = Query(
        None, description="ISO week as YYYY-Www (default: current week)"
    ),
    format: str | None = Query(
        None, description="'json' (default) or 'csv'"
    ),
    equipment_id: str | None = EQUIPMENT_ID_PARAM,
):
    """Weekly report for one ISO week (Monday 00:00 UTC to next Monday).
    JSON is the full summary; CSV streams the week's readings.
    Optionally scoped to one equipment."""
    try:
        fmt = reports_service.resolve_format(format)
        if week:
            from_dt, to_dt = reports_service.parse_week_param(week)
            label = week
        else:
            today = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            from_dt = today - timedelta(days=today.weekday())
            to_dt = from_dt + timedelta(days=7)
            label = from_dt.strftime("%G-W%V")
        eid = _resolve_equipment(equipment_id)
        if fmt == "csv":
            return _csv_response(
                reports_service.iter_readings_csv(
                    from_dt, to_dt, equipment_id=eid
                ),
                f"nexus-readings-{label}.csv",
            )
        return reports_service.get_report_summary(
            from_dt, to_dt, equipment_id=eid
        )
    except AggregationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/reports/events")
def report_events(
    from_: str = Query(
        ..., alias="from", description="ISO-8601 start (naive = UTC)"
    ),
    to: str = Query(..., description="ISO-8601 end (naive = UTC)"),
    format: str | None = Query(
        None, description="'json' (default) or 'csv'"
    ),
    equipment_id: str | None = EQUIPMENT_ID_PARAM,
):
    """Events in a period. JSON returns the event list; CSV streams it
    with timestamp, type, severity, status, message, recommendation,
    occurrences, opened/closed times, last value and threshold.
    Optionally scoped to one equipment."""
    try:
        fmt = reports_service.resolve_format(format)
        from_dt = parse_bound(from_, "from")
        to_dt = parse_bound(to, "to")
        eid = _resolve_equipment(equipment_id)
        if fmt == "csv":
            return _csv_response(
                reports_service.iter_events_csv(
                    from_dt, to_dt, equipment_id=eid
                ),
                "nexus-events.csv",
            )
        events, _ = reports_service.list_events(
            from_dt=from_dt,
            to_dt=to_dt,
            limit=reports_service.MAX_REPORT_EVENTS,
            equipment_id=eid,
        )
        return {
            "period": {
                "from": from_dt.isoformat(),
                "to": to_dt.isoformat(),
            },
            "equipment_id": eid,
            "events": events,
        }
    except AggregationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/reports/summary")
def report_summary(
    from_: str = Query(
        ..., alias="from", description="ISO-8601 start (naive = UTC)"
    ),
    to: str = Query(..., description="ISO-8601 end (naive = UTC)"),
    format: str | None = Query(
        None, description="'json' (default) or 'csv'"
    ),
    equipment_id: str | None = EQUIPMENT_ID_PARAM,
):
    """Summary report for a custom period (max 31 days). JSON is the full
    summary; CSV streams the period's readings. Optionally scoped to
    one equipment."""
    try:
        fmt = reports_service.resolve_format(format)
        from_dt = parse_bound(from_, "from")
        to_dt = parse_bound(to, "to")
        eid = _resolve_equipment(equipment_id)
        if fmt == "csv":
            return _csv_response(
                reports_service.iter_readings_csv(
                    from_dt, to_dt, equipment_id=eid
                ),
                "nexus-readings.csv",
            )
        return reports_service.get_report_summary(
            from_dt, to_dt, equipment_id=eid
        )
    except AggregationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


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
def stream_readings(equipment_id: str | None = EQUIPMENT_ID_PARAM):
    """Server-Sent Events stream of live readings (~1 Hz).

    Each `data:` event is JSON
    {"reading", "diagnosis_status", "severity", "server_ts"}; the
    reading carries its "equipment_id". A `: heartbeat` comment is
    sent every 15 s so proxies do not buffer the connection.

    NEXUS 2.4: the stream is scoped to one equipment (omitted =
    DEFAULT). Only that equipment's readings are delivered; ticks for
    other equipment are skipped, heartbeats keep flowing. The
    generator samples the shared telemetry state — no per-client
    buffers, so many clients cannot leak memory. Public like every
    other GET (NEXUS_API_KEY only guards writes).
    """

    requested_equipment_id = _resolve_equipment(equipment_id)

    def event_generator():
        last_heartbeat = time.monotonic()
        try:
            while True:
                payload = _latest_stream_payload()
                if (
                    payload is not None
                    and payload["reading"].get("equipment_id")
                    == requested_equipment_id
                ):
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
    equipment_id: str | None = EQUIPMENT_ID_PARAM,
):
    """Aggregate one metric into time buckets.

    Naive `from`/`to` values are interpreted as UTC (all stored timestamps
    are UTC). Maximum range is 31 days and 2000 buckets; violations
    return 422. Optionally scoped to one equipment (omitted = DEFAULT).
    """
    try:
        from_dt = parse_bound(from_, "from")
        to_dt = parse_bound(to, "to")
        eid = _resolve_equipment(equipment_id)
        buckets = get_history_buckets(
            metric, from_dt, to_dt, bucket, equipment_id=eid
        )
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
    equipment_id: str | None = EQUIPMENT_ID_PARAM,
):
    """Min/max/avg of one metric over a range, with extreme timestamps.

    Naive `from`/`to` are interpreted as UTC. Maximum range is 31 days;
    violations return 422. Optionally scoped to one equipment
    (omitted = DEFAULT).
    """
    try:
        from_dt = parse_bound(from_, "from")
        to_dt = parse_bound(to, "to")
        eid = _resolve_equipment(equipment_id)
        return get_history_extremes(
            metric, from_dt, to_dt, equipment_id=eid
        )
    except AggregationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/stats/summary")
def get_summary(equipment_id: str | None = EQUIPMENT_ID_PARAM):
    """Consolidated dashboard statistics, computed from real stored
    data. Optionally scoped to one equipment (omitted = DEFAULT);
    uptime is process-global and stays unscoped."""
    eid = _resolve_equipment(equipment_id)
    return get_stats_summary(equipment_id=eid)


@router.get("/analytics/overview")
def get_analytics(
    from_: str = Query(
        ..., alias="from", description="ISO-8601 start (naive = UTC)"
    ),
    to: str = Query(..., description="ISO-8601 end (naive = UTC)"),
    equipment_id: str | None = EQUIPMENT_ID_PARAM,
):
    """Period analytics: readings, energy, per-metric stats, event and
    episode counts. All values come from the real stored tables.

    Naive `from`/`to` are interpreted as UTC. Maximum range is 31 days;
    violations return 422. Optionally scoped to one equipment
    (omitted = DEFAULT).
    """
    try:
        from_dt = parse_bound(from_, "from")
        to_dt = parse_bound(to, "to")
        eid = _resolve_equipment(equipment_id)
        return get_analytics_overview(
            from_dt, to_dt, equipment_id=eid
        )
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
    equipment_id: str | None = EQUIPMENT_ID_PARAM,
):
    """List events, latest first, with filters and id-cursor pagination.
    Optionally scoped to one equipment (omitted = DEFAULT)."""
    try:
        from_dt = parse_bound(from_, "from") if from_ else None
        to_dt = parse_bound(to, "to") if to else None
        eid = _resolve_equipment(equipment_id)
        items, next_cursor = list_events(
            status=status,
            severity=severity,
            event_type=type,
            from_dt=from_dt,
            to_dt=to_dt,
            q=q,
            limit=limit,
            cursor=cursor,
            equipment_id=eid,
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
    equipment_id: str | None = EQUIPMENT_ID_PARAM,
):
    """Diagnostic episodes: abnormal periods, latest first. Optionally
    scoped to one equipment (omitted = DEFAULT)."""
    eid = _resolve_equipment(equipment_id)
    return {"episodes": list_episodes(limit, equipment_id=eid)}


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

"""NEXUS API v1 (NEXUS 2.1).

New functionality lives here. The legacy /api/* endpoints keep their exact
contracts and are implemented in app.api.routes.
"""

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

router = APIRouter(prefix="/api/v1")


class SettingUpdate(BaseModel):
    value: Any


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

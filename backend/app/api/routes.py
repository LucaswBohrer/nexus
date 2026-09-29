from fastapi import APIRouter, HTTPException, Query

from app.database.database import (
    MAX_EVENTS_LIMIT,
    MAX_HISTORY_LIMIT,
    get_recent_events,
    get_recent_readings,
)
from app.engine.simulator import simulator
from app.models.schemas import ElectricalReading
from app.services.monitoring import telemetry_service

router = APIRouter(prefix="/api")

# NEXUS 2.1 severity normalization map for legacy clients: the database
# stores info/warning/critical, the legacy contract used low/medium/high.
# Unknown values pass through untouched.
_LEGACY_SEVERITY = {
    "info": "low",
    "warning": "medium",
    "critical": "high",
}


@router.get("/monitoring/current", response_model=ElectricalReading)
def get_current_reading():
    return telemetry_service.get_latest_reading()


@router.get("/monitoring/diagnostics")
def get_diagnostics():
    return telemetry_service.get_latest_diagnosis()



@router.get("/monitoring/history")
def get_history(
    limit: int = Query(default=50, ge=1, le=MAX_HISTORY_LIMIT),
):
    return {
        "readings": get_recent_readings(limit),
    }


@router.get("/monitoring/events")
def get_events(
    limit: int = Query(default=20, ge=1, le=MAX_EVENTS_LIMIT),
):
    events = get_recent_events(limit)
    # NEXUS 2.1 stores severity normalized (info/warning/critical); legacy
    # clients expect the old low/medium/high vocabulary.
    for event in events:
        event["severity"] = _LEGACY_SEVERITY.get(event["severity"], event["severity"])
    return {
        "events": events,
    }


@router.get("/simulation/mode")
def get_simulation_mode():
    return {
        "mode": simulator.mode,
    }


@router.post("/simulation/mode/{mode}")
def set_simulation_mode(mode: str):
    try:
        simulator.set_mode(mode)
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        )

    return {
        "mode": simulator.mode,
        "status": "simulation mode updated",
    }


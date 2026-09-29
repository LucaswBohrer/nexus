from fastapi import APIRouter, HTTPException

from app.database.database import (
    get_recent_events,
    get_recent_readings,
)
from app.engine.simulator import simulator
from app.models.schemas import ElectricalReading
from app.services.monitoring import telemetry_service

router = APIRouter(prefix="/api")


@router.get("/monitoring/current", response_model=ElectricalReading)
def get_current_reading():
    return telemetry_service.get_latest_reading()


@router.get("/monitoring/diagnostics")
def get_diagnostics():
    return telemetry_service.get_latest_diagnosis()



@router.get("/monitoring/history")
def get_history(limit: int = 50):
    return {
        "readings": get_recent_readings(limit),
    }


@router.get("/monitoring/events")
def get_events(limit: int = 20):
    return {
        "events": get_recent_events(limit),
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


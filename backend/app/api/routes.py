<<<<<<< HEAD
from fastapi import APIRouter
=======
from fastapi import APIRouter, HTTPException
>>>>>>> 02fde370763d1c188b8feb2264e406ee5aafbdac

from app.database.database import (
    get_recent_events,
    get_recent_readings,
    save_event,
    save_reading,
)
<<<<<<< HEAD

from fastapi import APIRouter, HTTPException
=======
>>>>>>> 02fde370763d1c188b8feb2264e406ee5aafbdac
from app.engine.diagnostics import analyze_reading
from app.engine.simulator import simulator
from app.models.schemas import ElectricalReading

<<<<<<< HEAD

=======
>>>>>>> 02fde370763d1c188b8feb2264e406ee5aafbdac
router = APIRouter(prefix="/api")


def process_reading():
    reading = simulator.generate_reading()
<<<<<<< HEAD

    diagnosis = analyze_reading(reading)

=======
    diagnosis = analyze_reading(reading)
>>>>>>> 02fde370763d1c188b8feb2264e406ee5aafbdac
    reading["status"] = diagnosis["status"]

    save_reading(reading)

    for event in diagnosis["events"]:
        save_event(event)

    return reading, diagnosis


@router.get("/monitoring/current", response_model=ElectricalReading)
def get_current_reading():
    reading, _ = process_reading()
<<<<<<< HEAD

=======
>>>>>>> 02fde370763d1c188b8feb2264e406ee5aafbdac
    return reading


@router.get("/monitoring/diagnostics")
def get_diagnostics():
    reading, diagnosis = process_reading()
<<<<<<< HEAD

=======
>>>>>>> 02fde370763d1c188b8feb2264e406ee5aafbdac
    return {
        "reading": reading,
        "diagnosis": diagnosis,
    }


@router.get("/monitoring/history")
def get_history(limit: int = 50):
    return {
<<<<<<< HEAD
        "readings": get_recent_readings(limit)
=======
        "readings": get_recent_readings(limit),
>>>>>>> 02fde370763d1c188b8feb2264e406ee5aafbdac
    }


@router.get("/monitoring/events")
def get_events(limit: int = 20):
    return {
<<<<<<< HEAD
        "events": get_recent_events(limit)
    }

=======
        "events": get_recent_events(limit),
    }


>>>>>>> 02fde370763d1c188b8feb2264e406ee5aafbdac
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
<<<<<<< HEAD
    }
=======
    }
>>>>>>> 02fde370763d1c188b8feb2264e406ee5aafbdac

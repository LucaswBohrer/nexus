"""Simulation session control (NEXUS 2.3).

Owns the simulation lifecycle: start/stop/reset, duration expiry
(auto-revert), session audit rows in `simulation_sessions` and in-memory
peak tracking. The telemetry loop calls check_expiry() on every tick, so
the *backend* owns the timer -- expiry works with no frontend connected,
even if the browser tab is closed or the phone screen is locked.

Session status is derived, never stored: a row with ended_at set is
"finished"; the currently active row is "running"; a row with no
ended_at that is not active (e.g. the process died mid-session) is
"interrupted". This keeps the 2.1 table untouched -- no migration needed.

Thread-safety: the telemetry tick runs in a worker thread while API
handlers run in the event loop thread. All state mutations and reads go
through _LOCK.
"""

import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from app.database.database import get_connection
from app.engine.simulator import (
    SimulationError,
    VALID_MODES,
    simulator,
)

logger = logging.getLogger(__name__)

# Metrics tracked for peak_values during a session.
PEAK_METRICS = (
    "voltage",
    "current",
    "active_power",
    "frequency",
    "power_factor",
    "temperature",
)

# Defensive cap for GET /api/v1/simulation/sessions.
MAX_SESSIONS_LIMIT = 200
DEFAULT_SESSIONS_LIMIT = 50

_LOCK = threading.Lock()

# Active session or None. Keys: session_id, mode, intensity, anomalies,
# started_at (datetime), ends_at (datetime | None), peaks
# ({metric: {"min": v, "max": v}}).
_active: dict[str, Any] | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_duration(duration_minutes: Any) -> float | None:
    """None = indefinite. Otherwise a positive finite number of minutes.

    Fractional values are accepted (e.g. 0.05 ~= 3 s); the contract is
    "a positive duration in minutes", which keeps real end-to-end
    auto-revert tests honest without a test-only backdoor.
    """
    if duration_minutes is None:
        return None
    try:
        value = float(duration_minutes)
    except (TypeError, ValueError):
        raise SimulationError(
            "duration_minutes must be null or a positive number of minutes, "
            f"got {duration_minutes!r}"
        )
    if isinstance(duration_minutes, bool) or value <= 0 or value != value:
        # value != value catches NaN without importing math explicitly.
        raise SimulationError(
            "duration_minutes must be null or a positive number of minutes, "
            f"got {duration_minutes!r}"
        )
    if value == float("inf"):
        raise SimulationError("duration_minutes must be finite")
    return value


def _session_info(session: dict[str, Any]) -> dict[str, Any]:
    """Public shape of the active session (also used by /status)."""
    ends_at = session["ends_at"]
    remaining = None
    if ends_at is not None:
        remaining = max(
            0, int((ends_at - _now()).total_seconds())
        )
    return {
        "running": True,
        "session_id": session["session_id"],
        "mode": session["mode"],
        "intensity": session["intensity"],
        "anomalies": list(session["anomalies"]),
        "started_at": session["started_at"].isoformat(),
        "ends_at": ends_at.isoformat() if ends_at else None,
        "remaining_seconds": remaining,
    }


def _insert_session_row(
    mode: str,
    intensity: float,
    duration_minutes: float | None,
    anomalies: list[str],
    started_at: datetime,
) -> int:
    parameters = json.dumps(
        {
            "mode": mode,
            "intensity": intensity,
            "duration_minutes": duration_minutes,
            "anomalies": anomalies,
        }
    )
    connection = get_connection()
    try:
        cursor = connection.execute(
            """INSERT INTO simulation_sessions (mode, parameters, started_at)
               VALUES (?, ?, ?)""",
            (mode, parameters, started_at.isoformat()),
        )
        connection.commit()
        return cursor.lastrowid
    finally:
        connection.close()


def _finish_session_locked(now: datetime) -> dict[str, Any] | None:
    """Single internal path that ends the active session. No duplicates."""
    global _active
    session = _active
    if session is None:
        return None
    peak_values = json.dumps(session["peaks"])
    connection = get_connection()
    try:
        connection.execute(
            """UPDATE simulation_sessions
               SET ended_at = ?, peak_values = ?
               WHERE id = ?""",
            (now.isoformat(), peak_values, session["session_id"]),
        )
        connection.commit()
    finally:
        connection.close()
    finished = {
        "session_id": session["session_id"],
        "mode": session["mode"],
        "intensity": session["intensity"],
        "anomalies": list(session["anomalies"]),
        "started_at": session["started_at"].isoformat(),
        "ended_at": now.isoformat(),
        "peak_values": session["peaks"],
    }
    _active = None
    simulator.reset_scenario()
    logger.info(
        "Simulation session %s finished (mode=%s)",
        finished["session_id"],
        finished["mode"],
    )
    return finished


def start_simulation(
    mode: str,
    intensity: float = 100.0,
    duration_minutes: float | None = None,
    anomalies: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Start a simulation scenario. Validates everything; raises
    SimulationError on invalid input.

    Starting mode="normal" with no anomalies stops any active session and
    restores the baseline without creating an audit row (there is nothing
    anomalous to audit). Any other start supersedes a running session:
    the old one is finished first so states can never overlap.
    """
    if mode not in VALID_MODES:
        raise SimulationError(
            f"Invalid simulation mode: {mode!r}. Valid: {sorted(VALID_MODES)}"
        )
    duration = _validate_duration(duration_minutes)
    # apply_scenario validates intensity and the anomaly list/combination.
    simulator.apply_scenario(mode, intensity=intensity, anomalies=anomalies)
    scenario = simulator.get_scenario()

    now = _now()
    with _LOCK:
        _finish_session_locked(now)
        if not scenario["effective_anomalies"]:
            return idle_status()
        ends_at = (
            now + timedelta(minutes=duration) if duration is not None else None
        )
        session_id = _insert_session_row(
            mode,
            scenario["intensity"],
            duration,
            scenario["anomalies"],
            now,
        )
        global _active
        _active = {
            "session_id": session_id,
            "mode": mode,
            "intensity": scenario["intensity"],
            "anomalies": scenario["anomalies"],
            "started_at": now,
            "ends_at": ends_at,
            "peaks": {},
        }
        info = _session_info(_active)
    logger.info(
        "Simulation session %s started (mode=%s intensity=%s duration=%s)",
        session_id,
        mode,
        scenario["intensity"],
        duration,
    )
    return info


def idle_status() -> dict[str, Any]:
    return {
        "running": False,
        "session_id": None,
        "mode": "normal",
        "intensity": 100.0,
        "anomalies": [],
        "started_at": None,
        "ends_at": None,
        "remaining_seconds": 0,
    }


def get_status() -> dict[str, Any]:
    """Cheap status snapshot for polling. Never raises."""
    with _LOCK:
        if _active is None:
            return idle_status()
        return _session_info(_active)


def current_mode() -> str:
    """Effective simulation mode (legacy GET /api/simulation/mode)."""
    with _LOCK:
        return _active["mode"] if _active else "normal"


def stop_simulation() -> dict[str, Any]:
    """Stop the active session, idempotent when nothing is running."""
    now = _now()
    with _LOCK:
        finished = _finish_session_locked(now)
    if finished is None:
        return {"stopped": False, **idle_status()}
    return {"stopped": True, **finished}


def reset_simulation() -> dict[str, Any]:
    """Back to baseline: end any session, clear timer and composer state."""
    now = _now()
    with _LOCK:
        finished = _finish_session_locked(now)
        simulator.reset_scenario()
    result: dict[str, Any] = {"reset": True, **idle_status()}
    if finished is not None:
        result["finished_session"] = finished
    return result


def check_expiry() -> None:
    """Auto-revert: called on every telemetry tick. Ends the session and
    restores normal as soon as ends_at passes. Best-effort: never raises,
    so a broken clock can never break telemetry."""
    try:
        now = _now()
        with _LOCK:
            session = _active
            if session is None or session["ends_at"] is None:
                return
            if now < session["ends_at"]:
                return
            _finish_session_locked(now)
    except Exception:
        logger.exception("Simulation auto-revert check failed")


def track_peak(reading: dict[str, Any]) -> None:
    """Update in-memory min/max for the active session. Cheap: a few
    comparisons per tick; persistence happens once at session end."""
    with _LOCK:
        session = _active
        if session is None:
            return
        peaks = session["peaks"]
        for metric in PEAK_METRICS:
            value = reading.get(metric)
            if not isinstance(value, (int, float)):
                continue
            entry = peaks.get(metric)
            if entry is None:
                peaks[metric] = {"min": value, "max": value}
            else:
                if value < entry["min"]:
                    entry["min"] = value
                if value > entry["max"]:
                    entry["max"] = value


def list_sessions(
    limit: int = DEFAULT_SESSIONS_LIMIT, cursor: int | None = None
) -> dict[str, Any]:
    """Newest-first session history with a defensive limit and id cursor."""
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise SimulationError("limit must be an integer")
    if limit < 1 or limit > MAX_SESSIONS_LIMIT:
        raise SimulationError(
            f"limit must be between 1 and {MAX_SESSIONS_LIMIT}"
        )
    if cursor is not None and (
        not isinstance(cursor, int) or isinstance(cursor, bool) or cursor < 1
    ):
        raise SimulationError("cursor must be a positive session id")

    with _LOCK:
        active_id = _active["session_id"] if _active else None

    connection = get_connection()
    try:
        if cursor is None:
            rows = connection.execute(
                """SELECT id, mode, parameters, started_at, ended_at, peak_values
                   FROM simulation_sessions
                   ORDER BY id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        else:
            rows = connection.execute(
                """SELECT id, mode, parameters, started_at, ended_at, peak_values
                   FROM simulation_sessions
                   WHERE id < ?
                   ORDER BY id DESC LIMIT ?""",
                (cursor, limit),
            ).fetchall()
    finally:
        connection.close()

    now = _now()
    sessions = []
    for row in rows:
        sid, mode, parameters, started_at, ended_at, peak_values = row
        if ended_at:
            status = "finished"
            duration_s = (
                datetime.fromisoformat(ended_at)
                - datetime.fromisoformat(started_at)
            ).total_seconds()
        elif sid == active_id:
            status = "running"
            duration_s = (now - datetime.fromisoformat(started_at)).total_seconds()
        else:
            status = "interrupted"
            duration_s = None
        sessions.append(
            {
                "id": sid,
                "mode": mode,
                "parameters": json.loads(parameters) if parameters else None,
                "started_at": started_at,
                "ended_at": ended_at,
                "duration_s": duration_s,
                "peak_values": json.loads(peak_values) if peak_values else None,
                "status": status,
            }
        )

    next_cursor = sessions[-1]["id"] if len(sessions) == limit else None
    return {"sessions": sessions, "next_cursor": next_cursor}

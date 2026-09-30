import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from app.database.database import (
    get_latest_reading_from_db,
    prune_all,
    save_reading,
)
from app.engine.diagnostics import analyze_reading
from app.engine.simulator import simulator
from app.services import simulation as simulation_service
from app.services import equipment as equipment_service
from app.services.errors import record_error
from app.services.events import process_tick_events
from app.services.episodes import process_tick_episode
from app.services.settings import get_setting

logger = logging.getLogger(__name__)

# How often the telemetry loop prunes rows older than the retention policy.
# Startup already prunes once; this covers long-running processes.
PRUNE_INTERVAL_SECONDS = 3600.0


def _retention_from_settings() -> dict[str, int] | None:
    """Build the per-table retention map from settings.

    Returns None when settings are unavailable (very early startup); the
    pruner then falls back to the compiled-in defaults. Never raises: the
    telemetry tick must not break because of maintenance.
    """
    try:
        return {
            "readings": int(get_setting("retention.readings_days")),
            "events": int(get_setting("retention.events_days")),
            "diagnostic_episodes": int(
                get_setting("retention.diagnostic_episodes_days")
            ),
            "simulation_sessions": int(
                get_setting("retention.simulation_sessions_days")
            ),
        }
    except Exception:
        logger.exception("Failed to read retention settings; using defaults")
        return None


class TelemetryService:
    def __init__(self):
        self._is_running: bool = False
        self._task: asyncio.Task | None = None
        self._latest_reading: dict[str, Any] | None = None
        self._latest_diagnosis: dict[str, Any] | None = None
        self._last_prune_ts: float = 0.0
        self._started_at: datetime | None = None
        # Tick metrics for /api/health and /api/v1/system/* (NEXUS 2.1).
        self._tick_count: int = 0
        self._tick_total_s: float = 0.0
        self._last_tick_at: datetime | None = None

    def _execute_tick(self) -> tuple[dict[str, Any], dict[str, Any]]:
        tick_start = time.monotonic()

        # NEXUS 2.3: the backend owns simulation timers. Checking expiry
        # on every tick (including the cold-start tick below) makes
        # auto-revert work with no frontend connected.
        simulation_service.check_expiry()

        # NEXUS 2.4: the tick owns exactly one equipment — the active
        # simulation's equipment, or DEFAULT when idle. Every row this
        # tick writes (reading, events, episode) is stamped with it.
        equipment_id = simulation_service.get_active_equipment_id()
        if equipment_id is None:
            equipment_id = equipment_service.get_default_equipment()["id"]

        reading = simulator.generate_reading()
        diagnosis = analyze_reading(reading)
        reading["status"] = diagnosis["status"]
        reading["equipment_id"] = equipment_id

        save_reading(reading)

        # NEXUS 2.3: track in-memory peak values while a session is active.
        simulation_service.track_peak(reading)

        # NEXUS 2.1: events have a lifecycle (open -> resolved) with
        # deduplication per condition. A sustained anomaly produces ONE
        # event row, not one row per tick.
        for event in diagnosis["events"]:
            event["equipment_id"] = equipment_id
        process_tick_events(diagnosis["events"], equipment_id=equipment_id)

        # NEXUS 2.1 §14: track the whole-system diagnostic episode for
        # this abnormal period (open/update/close).
        process_tick_episode(diagnosis, reading, equipment_id=equipment_id)

        self._latest_reading = reading
        self._latest_diagnosis = {
            "reading": reading,
            "diagnosis": diagnosis,
        }
        self._maybe_prune_old_data()

        self._tick_count += 1
        self._tick_total_s += time.monotonic() - tick_start
        self._last_tick_at = datetime.now(timezone.utc)
        return reading, diagnosis

    def _maybe_prune_old_data(self) -> None:
        """Prune rows older than the retention policy, at most once per hour.

        Telemetry writes ~1 reading/sec forever; without pruning the SQLite
        tables grow without bound. prune_all() is best-effort and never
        raises, so the tick is unaffected.
        """
        now = time.monotonic()
        if now - self._last_prune_ts < PRUNE_INTERVAL_SECONDS:
            return
        self._last_prune_ts = now
        pruned = prune_all(_retention_from_settings())
        if any(pruned.values()):
            logger.info(
                "Pruned old telemetry data: %s",
                ", ".join(
                    f"{count} {table}"
                    for table, count in pruned.items()
                    if count
                ),
            )

    async def _run_loop(self):
        logger.info("Telemetry background loop started (1 Hz)")
        interval = 1.0

        while self._is_running:
            start_time = time.monotonic()
            try:
                # The tick does synchronous SQLite I/O. Running it in a
                # worker thread keeps the event loop responsive to API
                # requests even under disk pressure. This is thread-safe:
                # every DB helper opens its own connection, `random` is
                # thread-safe, and `_latest_*` updates are atomic stores.
                await asyncio.to_thread(self._execute_tick)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Error executing telemetry cycle: %s", e)
                record_error(f"Telemetry tick failed: {e}", context="telemetry")
                try:
                    await asyncio.sleep(interval)
                except asyncio.CancelledError:
                    break
                continue

            elapsed = time.monotonic() - start_time
            sleep_time = max(0.0, interval - elapsed)

            try:
                await asyncio.sleep(sleep_time)
            except asyncio.CancelledError:
                break

        logger.info("Telemetry background loop stopped")

    async def start(self):
        if self._is_running or (self._task is not None and not self._task.done()):
            logger.warning("TelemetryService is already running.")
            return

        # Cold start: ensure initial reading and diagnosis exist immediately
        try:
            self._execute_tick()
        except Exception as e:
            logger.exception("Failed to execute initial telemetry tick, checking database fallback: %s", e)
            fallback = get_latest_reading_from_db()
            if fallback:
                self._latest_reading = fallback
                self._latest_diagnosis = {
                    "reading": fallback,
                    "diagnosis": analyze_reading(fallback),
                }

        self._is_running = True
        self._started_at = datetime.now(timezone.utc)
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self):
        if not self._is_running and self._task is None:
            return

        self._is_running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.exception("Error during telemetry worker shutdown: %s", e)
            finally:
                self._task = None

    def get_uptime_seconds(self) -> float | None:
        """Seconds since the telemetry service started (None if never)."""
        if self._started_at is None:
            return None
        return (datetime.now(timezone.utc) - self._started_at).total_seconds()

    def get_tick_metrics(self) -> dict[str, Any]:
        """Internal telemetry metrics for health/system endpoints."""
        return {
            "tick_count": self._tick_count,
            "avg_tick_duration_s": (
                self._tick_total_s / self._tick_count
                if self._tick_count
                else None
            ),
            "last_tick_at": (
                self._last_tick_at.isoformat() if self._last_tick_at else None
            ),
        }

    def get_latest_reading(self) -> dict[str, Any]:
        if self._latest_reading is not None:
            return self._latest_reading

        fallback = get_latest_reading_from_db()
        if fallback:
            self._latest_reading = fallback
            return self._latest_reading

        raise RuntimeError("No telemetry reading is available.")

    def get_latest_diagnosis(self) -> dict[str, Any]:
        if self._latest_diagnosis is not None:
            return self._latest_diagnosis

        reading = self.get_latest_reading()
        diagnosis = analyze_reading(reading)
        self._latest_diagnosis = {
            "reading": reading,
            "diagnosis": diagnosis,
        }
        return self._latest_diagnosis


telemetry_service = TelemetryService()

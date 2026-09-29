import asyncio
import logging
import time
from typing import Any

from app.database.database import (
    get_latest_reading_from_db,
    save_event,
    save_reading,
)
from app.engine.diagnostics import analyze_reading
from app.engine.simulator import simulator

logger = logging.getLogger(__name__)


class TelemetryService:
    def __init__(self):
        self._is_running: bool = False
        self._task: asyncio.Task | None = None
        self._latest_reading: dict[str, Any] | None = None
        self._latest_diagnosis: dict[str, Any] | None = None

    def _execute_tick(self) -> tuple[dict[str, Any], dict[str, Any]]:
        reading = simulator.generate_reading()
        diagnosis = analyze_reading(reading)
        reading["status"] = diagnosis["status"]

        save_reading(reading)

        for event in diagnosis["events"]:
            save_event(event)

        self._latest_reading = reading
        self._latest_diagnosis = {
            "reading": reading,
            "diagnosis": diagnosis,
        }
        return reading, diagnosis

    async def _run_loop(self):
        logger.info("Telemetry background loop started (1 Hz)")
        interval = 1.0

        while self._is_running:
            start_time = time.monotonic()
            try:
                self._execute_tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Error executing telemetry cycle: %s", e)
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

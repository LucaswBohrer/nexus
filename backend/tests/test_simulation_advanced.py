"""Tests for the NEXUS 2.3 simulation control API.

HTTP tests run against a live uvicorn server on port 8150 with a temp
database; the simulator's deterministic properties (intensity scaling,
oscillation phase, frozen sensor) are additionally covered by fast
in-process unit tests with a fixed random seed.

Covered: valid start, invalid payloads (422), intensity 0/50/100/200,
status countdown, manual stop, auto-revert end-to-end, session
creation/listing/paging, peak_values persistence, the three new modes,
multi-anomaly composer, legacy endpoints, and diagnostics continuity.

Run:  python -m unittest discover -s tests -v   (from backend/)
"""
import json
import os
import random
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)
BASE_URL = "http://127.0.0.1:8150"

from app.database import database  # noqa: E402
from app.engine.simulator import (  # noqa: E402
    SimulationError,
    simulator,
)


def _http_get(path: str):
    try:
        with urllib.request.urlopen(BASE_URL + path, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, None


def _http_post(path: str, payload=None):
    data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(
        BASE_URL + path, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, None


def _wait_for(predicate, timeout_s: float, interval: float = 0.5):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


class SimulationApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmpdir.name, "simulation_test.db")
        old_path = database.DB_PATH
        database.DB_PATH = cls.db_path
        try:
            database.init_database()
        finally:
            database.DB_PATH = old_path

        env = dict(os.environ, NEXUS_DATABASE_URL=cls.db_path)
        venv_python = os.path.join(BACKEND_DIR, ".venv", "bin", "python")
        cls.server = subprocess.Popen(
            [venv_python, "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", "8150"],
            cwd=BACKEND_DIR,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 25
        while time.time() < deadline:
            try:
                status, _ = _http_get("/api/monitoring/current")
                if status == 200:
                    break
            except OSError:
                pass
            time.sleep(0.5)
        else:
            cls.server.terminate()
            raise RuntimeError("test server did not start in time")

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        try:
            cls.server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.server.kill()
        cls.tmpdir.cleanup()

    def tearDown(self):
        # Leave no session running for the next test.
        try:
            _http_post("/api/v1/simulation/reset")
        except OSError:
            pass

    # -- start -----------------------------------------------------------

    def test_start_valid(self):
        status, body = _http_post(
            "/api/v1/simulation/start",
            {"mode": "high_voltage", "intensity": 100,
             "duration_minutes": None, "anomalies": []},
        )
        self.assertEqual(status, 200)
        self.assertIn("session_id", body)
        self.assertEqual(body["mode"], "high_voltage")
        self.assertEqual(body["intensity"], 100)
        self.assertIsNone(body["ends_at"])
        self.assertIsNotNone(body["started_at"])

    def test_start_invalid_payloads(self):
        bad = [
            {"mode": "nope", "intensity": 100},
            {"mode": "high_voltage", "intensity": 300},
            {"mode": "high_voltage", "intensity": -5},
            {"mode": "high_voltage", "intensity": "abc"},
            {"mode": "high_voltage", "duration_minutes": 0},
            {"mode": "high_voltage", "duration_minutes": -2},
            {"mode": "high_voltage", "anomalies": ["bogus"]},
            {"mode": "high_voltage", "anomalies": "high_voltage"},
            # sensor_failure dominates: combining it is impossible.
            {"mode": "sensor_failure", "anomalies": ["high_voltage"]},
            {"mode": "normal", "anomalies": ["sensor_failure", "overload"]},
        ]
        for payload in bad:
            with self.subTest(payload=payload):
                status, _ = _http_post("/api/v1/simulation/start", payload)
                self.assertEqual(status, 422, payload)

    def test_start_with_duration_reports_ends_at(self):
        status, body = _http_post(
            "/api/v1/simulation/start",
            {"mode": "low_voltage", "duration_minutes": 5},
        )
        self.assertEqual(status, 200)
        self.assertIsNotNone(body["ends_at"])
        self.assertGreater(body["remaining_seconds"], 0)
        self.assertLessEqual(body["remaining_seconds"], 300)

    # -- status / countdown ----------------------------------------------

    def test_status_countdown_decreases(self):
        _http_post(
            "/api/v1/simulation/start",
            {"mode": "high_temperature", "duration_minutes": 0.2},
        )
        _, first = _http_get("/api/v1/simulation/status")
        self.assertTrue(first["running"])
        self.assertEqual(first["mode"], "high_temperature")
        r1 = first["remaining_seconds"]
        time.sleep(2.5)
        _, second = _http_get("/api/v1/simulation/status")
        r2 = second["remaining_seconds"]
        self.assertLess(r2, r1)

    def test_status_idle_shape(self):
        status, body = _http_get("/api/v1/simulation/status")
        self.assertEqual(status, 200)
        self.assertFalse(body["running"])
        self.assertEqual(body["mode"], "normal")
        self.assertEqual(body["intensity"], 100)
        self.assertEqual(body["anomalies"], [])
        self.assertEqual(body["remaining_seconds"], 0)
        self.assertIsNone(body["session_id"])

    # -- stop / reset -----------------------------------------------------

    def test_stop_manual(self):
        _http_post("/api/v1/simulation/start", {"mode": "overload"})
        status, body = _http_post("/api/v1/simulation/stop")
        self.assertEqual(status, 200)
        self.assertTrue(body["stopped"])
        self.assertIsNotNone(body["ended_at"])
        _, idle = _http_get("/api/v1/simulation/status")
        self.assertFalse(idle["running"])
        self.assertEqual(idle["mode"], "normal")

    def test_stop_idempotent_when_idle(self):
        status, body = _http_post("/api/v1/simulation/stop")
        self.assertEqual(status, 200)
        self.assertFalse(body["stopped"])
        self.assertFalse(body["running"])

    def test_reset_clears_everything(self):
        _http_post(
            "/api/v1/simulation/start",
            {"mode": "high_voltage", "intensity": 150,
             "duration_minutes": 10, "anomalies": ["high_temperature"]},
        )
        status, body = _http_post("/api/v1/simulation/reset")
        self.assertEqual(status, 200)
        self.assertTrue(body["reset"])
        self.assertFalse(body["running"])
        self.assertEqual(body["mode"], "normal")
        self.assertEqual(body["intensity"], 100)
        self.assertEqual(body["anomalies"], [])

    # -- auto-revert (real end-to-end path) --------------------------------

    def test_auto_revert(self):
        # 0.05 minutes ~= 3 s: the backend's own tick loop must expire the
        # session with no frontend involvement.
        _http_post(
            "/api/v1/simulation/start",
            {"mode": "high_voltage", "duration_minutes": 0.05},
        )
        reverted = _wait_for(
            lambda: _http_get("/api/v1/simulation/status")[1]["running"]
            is False,
            timeout_s=15,
        )
        self.assertTrue(reverted, "session did not auto-revert in time")
        _, status = _http_get("/api/v1/simulation/status")
        self.assertEqual(status["mode"], "normal")
        _, sessions = _http_get("/api/v1/simulation/sessions?limit=5")
        latest = sessions["sessions"][0]
        self.assertEqual(latest["status"], "finished")
        self.assertIsNotNone(latest["ended_at"])

    # -- sessions ----------------------------------------------------------

    def test_session_created_and_listed(self):
        _, started = _http_post(
            "/api/v1/simulation/start",
            {"mode": "low_power_factor", "intensity": 75,
             "anomalies": ["high_temperature"]},
        )
        _, body = _http_get("/api/v1/simulation/sessions?limit=5")
        latest = body["sessions"][0]
        self.assertEqual(latest["id"], started["session_id"])
        self.assertEqual(latest["status"], "running")
        self.assertEqual(latest["mode"], "low_power_factor")
        params = latest["parameters"]
        self.assertEqual(params["intensity"], 75)
        self.assertEqual(params["anomalies"], ["high_temperature"])

    def test_start_supersedes_active_session(self):
        _http_post("/api/v1/simulation/start", {"mode": "high_voltage"})
        _http_post("/api/v1/simulation/start", {"mode": "low_voltage"})
        _, body = _http_get("/api/v1/simulation/sessions?limit=5")
        by_id = {s["id"]: s for s in body["sessions"][:2]}
        newest = max(by_id)
        self.assertEqual(by_id[newest]["status"], "running")
        self.assertEqual(by_id[newest]["mode"], "low_voltage")
        oldest = min(by_id)
        self.assertEqual(by_id[oldest]["status"], "finished")
        self.assertIsNotNone(by_id[oldest]["ended_at"])

    def test_peak_values_persisted(self):
        _http_post("/api/v1/simulation/start", {"mode": "overload"})
        time.sleep(4)  # let a few 1 Hz ticks accumulate peaks
        _http_post("/api/v1/simulation/stop")
        _, body = _http_get("/api/v1/simulation/sessions?limit=1")
        peaks = body["sessions"][0]["peak_values"]
        for metric in ("voltage", "current", "active_power", "frequency",
                       "power_factor", "temperature"):
            self.assertIn(metric, peaks)
            self.assertLessEqual(peaks[metric]["min"], peaks[metric]["max"])
        # Overload must actually show elevated current in the peaks.
        self.assertGreater(peaks["current"]["max"], 20)

    def test_sessions_pagination(self):
        _, before = _http_get("/api/v1/simulation/sessions?limit=200")
        n0 = len(before["sessions"])
        for _ in range(3):
            _http_post("/api/v1/simulation/start", {"mode": "high_voltage"})
            _http_post("/api/v1/simulation/stop")
        _, page1 = _http_get("/api/v1/simulation/sessions?limit=2")
        self.assertEqual(len(page1["sessions"]), 2)
        self.assertIsNotNone(page1["next_cursor"])
        cursor = page1["next_cursor"]
        _, page2 = _http_get(f"/api/v1/simulation/sessions?limit=200&cursor={cursor}")
        self.assertEqual(len(page2["sessions"]), n0 + 3 - 2)
        ids1 = {s["id"] for s in page1["sessions"]}
        ids2 = {s["id"] for s in page2["sessions"]}
        self.assertTrue(ids1.isdisjoint(ids2))

    def test_sessions_limit_validated(self):
        status, _ = _http_get("/api/v1/simulation/sessions?limit=0")
        self.assertEqual(status, 422)

    # -- new modes ----------------------------------------------------------

    def test_sensor_failure_freezes_values(self):
        _http_post("/api/v1/simulation/start", {"mode": "sensor_failure"})
        time.sleep(2.5)
        _, first = _http_get("/api/monitoring/current")
        time.sleep(1.5)
        _, second = _http_get("/api/monitoring/current")
        for metric in ("voltage", "current", "frequency", "power_factor",
                       "active_power", "temperature"):
            self.assertEqual(first[metric], second[metric],
                             f"{metric} changed under sensor_failure")
        # Diagnostics must flag the stale sensor as its own condition.
        found = _wait_for(
            lambda: any(
                e["event_type"] == "SENSOR_STALE" and e["status"] == "open"
                for e in _http_get("/api/v1/events?type=SENSOR_STALE")[1]["events"]
            ),
            timeout_s=10,
        )
        self.assertTrue(found, "SENSOR_STALE event never opened")

    def test_overload_elevates_current(self):
        _http_post("/api/v1/simulation/start", {"mode": "overload"})
        time.sleep(3)
        _, reading = _http_get("/api/monitoring/current")
        self.assertGreater(reading["current"], 20)
        # active_power stays consistent with the V*I*PF chain.
        expected = round(
            reading["voltage"] * reading["current"]
            * reading["power_factor"] / 1000, 3
        )
        self.assertAlmostEqual(reading["active_power"], expected, places=2)

    def test_multi_anomaly_composer_detected(self):
        _http_post(
            "/api/v1/simulation/start",
            {"mode": "normal",
             "anomalies": ["high_voltage", "high_temperature"]},
        )
        _, status = _http_get("/api/v1/simulation/status")
        self.assertEqual(
            sorted(status["anomalies"]), ["high_temperature", "high_voltage"]
        )
        found = _wait_for(
            lambda: {
                e["event_type"]
                for e in _http_get("/api/v1/events")[1]["events"]
                if e["status"] == "open"
            } >= {"HIGH_VOLTAGE", "HIGH_TEMPERATURE"},
            timeout_s=12,
        )
        self.assertTrue(
            found, "composer anomalies were not detected by diagnostics"
        )

    # -- legacy compatibility ------------------------------------------------

    def test_legacy_endpoints_still_work(self):
        status, body = _http_post("/api/simulation/mode/high_voltage")
        self.assertEqual(status, 200)
        self.assertEqual(body["mode"], "high_voltage")
        status, body = _http_get("/api/simulation/mode")
        self.assertEqual(status, 200)
        self.assertEqual(body["mode"], "high_voltage")
        # Legacy keeps its 400 contract for unknown modes.
        status, _ = _http_post("/api/simulation/mode/bogus_mode")
        self.assertEqual(status, 400)
        # Legacy "normal" stops the session like before.
        _http_post("/api/simulation/mode/normal")
        _, status_body = _http_get("/api/v1/simulation/status")
        self.assertFalse(status_body["running"])


class SimulatorUnitTest(unittest.TestCase):
    """Deterministic simulator properties, in-process with fixed seeds."""

    def setUp(self):
        simulator.reset_scenario()

    def tearDown(self):
        simulator.reset_scenario()

    def _mean_voltage(self, mode, intensity, n=300, seed=42):
        random.seed(seed)
        simulator.apply_scenario(mode, intensity=intensity)
        return sum(
            simulator.generate_reading()["voltage"] for _ in range(n)
        ) / n

    def test_intensity_scales_deviation(self):
        m0 = self._mean_voltage("high_voltage", 0)
        m50 = self._mean_voltage("high_voltage", 50)
        m100 = self._mean_voltage("high_voltage", 100)
        m200 = self._mean_voltage("high_voltage", 200)
        self.assertAlmostEqual(m0, 220.0, delta=2.0)
        self.assertAlmostEqual(m50, 235.0, delta=2.0)
        self.assertAlmostEqual(m100, 250.0, delta=2.0)
        self.assertAlmostEqual(m200, 280.0, delta=2.0)
        self.assertLess(m0, m50)
        self.assertLess(m50, m100)
        self.assertLess(m100, m200)

    def test_intensity_invalid_rejected(self):
        for bad in (300, -1, float("nan"), float("inf"), "high", None, True):
            with self.subTest(bad=bad):
                with self.assertRaises(SimulationError):
                    simulator.apply_scenario("high_voltage", intensity=bad)

    def test_unknown_mode_and_anomaly_rejected(self):
        with self.assertRaises(SimulationError):
            simulator.apply_scenario("meltdown")
        with self.assertRaises(SimulationError):
            simulator.apply_scenario("normal", anomalies=["meltdown"])

    def test_oscillation_is_deterministic_sine(self):
        simulator.apply_scenario("oscillation", intensity=100)
        voltages = [
            simulator.generate_reading()["voltage"] for _ in range(24)
        ]
        # Phase starts at tick 1: v = 220 + 15*sin(2*pi*n/24).
        import math
        for n, v in enumerate(voltages, start=1):
            expected = round(220.0 + 15.0 * math.sin(2 * math.pi * n / 24), 2)
            self.assertAlmostEqual(v, expected, places=1)
        # One full period returns to (almost) the start value.
        self.assertAlmostEqual(voltages[0], voltages[-1], delta=4.0)

    def test_overload_signature(self):
        random.seed(7)
        simulator.apply_scenario("overload", intensity=100)
        readings = [simulator.generate_reading() for _ in range(200)]
        mean_current = sum(r["current"] for r in readings) / 200
        mean_power = sum(r["active_power"] for r in readings) / 200
        self.assertAlmostEqual(mean_current, 28.0, delta=1.5)
        self.assertGreater(mean_power, 5.0)
        for r in readings:
            expected = round(
                r["voltage"] * r["current"] * r["power_factor"] / 1000, 3
            )
            self.assertEqual(r["active_power"], expected)

    def test_sensor_failure_freezes_in_process(self):
        simulator.apply_scenario("sensor_failure")
        first = simulator.generate_reading()
        second = simulator.generate_reading()
        self.assertTrue(first["stale"])
        self.assertTrue(second["stale"])
        for metric in ("voltage", "current", "frequency", "power_factor",
                       "active_power", "temperature"):
            self.assertEqual(first[metric], second[metric])
        # Leaving the mode unfreezes the sensor again.
        simulator.apply_scenario("normal")
        third = simulator.generate_reading()
        self.assertNotIn("stale", third)

    def test_physical_clamps_hold_at_extreme_intensity(self):
        random.seed(11)
        simulator.apply_scenario("low_power_factor", intensity=200)
        for _ in range(200):
            r = simulator.generate_reading()
            self.assertGreaterEqual(r["power_factor"], 0.5)
            self.assertLessEqual(r["power_factor"], 1.0)
            self.assertGreaterEqual(r["current"], 0.1)
            self.assertGreaterEqual(r["temperature"], 15.0)
            for v in r.values():
                if isinstance(v, float):
                    self.assertTrue(
                        v == v and abs(v) != float("inf"),
                        "NaN/inf leaked into a reading",
                    )


if __name__ == "__main__":
    unittest.main()

"""Integration + unit tests for the NEXUS 2.1 settings service.

Covers:
  - GET /api/v1/settings returns the seeded defaults;
  - GET /api/v1/settings/{key} round-trip; 404 for unknown keys;
  - PUT /api/v1/settings/{key}: valid update persists, invalid values
    return 422, unknown keys return 404;
  - a threshold change affects analyze_reading() without a restart
    (unit-style, local temp DB).

Run:  python -m unittest discover -s tests -v   (from backend/)
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

BASE_URL = "http://127.0.0.1:8136"

from app.database import database  # noqa: E402
from app.engine.diagnostics import analyze_reading  # noqa: E402
from app.services import settings as settings_module  # noqa: E402


def _http_get(path: str):
    try:
        with urllib.request.urlopen(BASE_URL + path, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, None


def _http_put(path: str, payload: dict):
    req = urllib.request.Request(
        BASE_URL + path,
        data=json.dumps(payload).encode(),
        method="PUT",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, None


class SettingsApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmpdir.name, "settings_test.db")

        env = dict(os.environ, NEXUS_DATABASE_URL=cls.db_path)
        venv_python = os.path.join(BACKEND_DIR, ".venv", "bin", "python")
        cls.server = subprocess.Popen(
            [venv_python, "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", "8136"],
            cwd=BACKEND_DIR,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        deadline = time.time() + 25
        while time.time() < deadline:
            try:
                status, _ = _http_get("/api/v1/settings")
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

    def test_defaults_are_seeded(self):
        status, body = _http_get("/api/v1/settings")
        self.assertEqual(status, 200)
        expected = {
            "thresholds.voltage_min": 198.0,
            "thresholds.voltage_max": 242.0,
            "thresholds.frequency_min": 59.5,
            "thresholds.frequency_max": 60.5,
            "thresholds.power_factor_min": 0.8,
            "thresholds.temperature_max": 70.0,
            "retention.readings_days": 30,
            "retention.events_days": 90,
            "retention.diagnostic_episodes_days": 90,
            "retention.simulation_sessions_days": 180,
            "energy_tariff": None,
            "simulation.default_intensity": 100,
            "simulation.default_duration_minutes": None,
        }
        for key, value in expected.items():
            self.assertIn(key, body["settings"])
            self.assertEqual(body["settings"][key], value)

    def test_get_single_setting(self):
        status, body = _http_get("/api/v1/settings/thresholds.voltage_max")
        self.assertEqual(status, 200)
        self.assertEqual(body["key"], "thresholds.voltage_max")
        self.assertEqual(body["value"], 242.0)

    def test_get_unknown_setting_returns_404(self):
        status, _ = _http_get("/api/v1/settings/nope.not_real")
        self.assertEqual(status, 404)

    def test_put_valid_setting_round_trips(self):
        status, body = _http_put(
            "/api/v1/settings/thresholds.temperature_max", {"value": 75}
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["value"], 75.0)

        status, body = _http_get("/api/v1/settings/thresholds.temperature_max")
        self.assertEqual(status, 200)
        self.assertEqual(body["value"], 75.0)

        # Restore the default so other tests see a pristine server.
        _http_put("/api/v1/settings/thresholds.temperature_max", {"value": 70})

    def test_put_unknown_setting_returns_404(self):
        status, _ = _http_put("/api/v1/settings/nope.not_real", {"value": 1})
        self.assertEqual(status, 404)

    def test_put_rejects_min_above_max(self):
        # voltage_min=250 would exceed voltage_max=242.
        status, _ = _http_put(
            "/api/v1/settings/thresholds.voltage_min", {"value": 250}
        )
        self.assertEqual(status, 422)

    def test_put_rejects_out_of_range_retention(self):
        status, _ = _http_put(
            "/api/v1/settings/retention.readings_days", {"value": 0}
        )
        self.assertEqual(status, 422)
        status, _ = _http_put(
            "/api/v1/settings/retention.readings_days", {"value": 366}
        )
        self.assertEqual(status, 422)

    def test_put_rejects_out_of_range_intensity(self):
        status, _ = _http_put(
            "/api/v1/settings/simulation.default_intensity", {"value": 201}
        )
        self.assertEqual(status, 422)

    def test_put_rejects_wrong_type(self):
        status, _ = _http_put(
            "/api/v1/settings/thresholds.voltage_max", {"value": "hot"}
        )
        self.assertEqual(status, 422)


class ThresholdDynamicsTest(unittest.TestCase):
    """Threshold changes take effect in diagnostics without a restart."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self._old_db_path = database.DB_PATH
        database.DB_PATH = os.path.join(self.tmpdir.name, "unit.db")
        settings_module._cache.clear()
        database.init_database()
        settings_module.seed_settings()

    def tearDown(self):
        database.DB_PATH = self._old_db_path
        settings_module._cache.clear()
        self.tmpdir.cleanup()

    def _reading(self, voltage: float):
        from datetime import datetime, timezone

        return {
            "timestamp": datetime.now(timezone.utc),
            "voltage": voltage,
            "current": 12.0,
            "frequency": 60.0,
            "power_factor": 0.93,
            "active_power": 2.5,
            "temperature": 45.0,
        }

    def test_threshold_change_affects_diagnosis(self):
        self.assertEqual(analyze_reading(self._reading(210.0))["anomalies"], [])

        settings_module.set_setting("thresholds.voltage_max", 200.0)

        diagnosis = analyze_reading(self._reading(210.0))
        self.assertIn("HIGH_VOLTAGE", diagnosis["anomalies"])
        self.assertEqual(diagnosis["severity"], "warning")


if __name__ == "__main__":
    unittest.main()

"""Integration tests for the simulation-mode endpoints.

Spins up a real uvicorn server (subprocess) against a temporary SQLite
database and asserts the HTTP contract with stdlib urllib:

  - GET /api/simulation/mode returns the active mode (default "normal");
  - POST /api/simulation/mode/{mode} accepts every documented mode and
    the GET endpoint reflects the change;
  - POST with an unknown mode returns 400;
  - switching to an anomaly mode actually changes the telemetry stream
    (temperature rises past the 70 C threshold) and produces a
    HIGH_TEMPERATURE monitoring event.

Run:  python -m unittest discover -s tests -v   (from backend/)
"""
import json
import os
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_URL = "http://127.0.0.1:8134"

VALID_MODES = [
    "normal",
    "high_voltage",
    "low_voltage",
    "low_power_factor",
    "high_temperature",
    "multiple_anomalies",
]


def _http_get(path: str):
    """Return (status_code, parsed_json_or_None)."""
    try:
        with urllib.request.urlopen(BASE_URL + path, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, None


def _http_post(path: str):
    """Return (status_code, parsed_json_or_None) for an empty-body POST."""
    req = urllib.request.Request(BASE_URL + path, data=b"", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, None


class SimulationModeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        db_path = os.path.join(cls.tmpdir.name, "simulation_test.db")

        env = dict(os.environ, NEXUS_DATABASE_URL=db_path)
        venv_python = os.path.join(BACKEND_DIR, ".venv", "bin", "python")
        cls.server = subprocess.Popen(
            [venv_python, "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", "8134"],
            cwd=BACKEND_DIR,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Wait for readiness.
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

    def test_get_mode_defaults_to_normal(self):
        _http_post("/api/simulation/mode/normal")
        status, body = _http_get("/api/simulation/mode")
        self.assertEqual(status, 200)
        self.assertEqual(body["mode"], "normal")

    def test_set_each_valid_mode(self):
        for mode in VALID_MODES:
            with self.subTest(mode=mode):
                status, body = _http_post(f"/api/simulation/mode/{mode}")
                self.assertEqual(status, 200)
                self.assertEqual(body["mode"], mode)

                status, body = _http_get("/api/simulation/mode")
                self.assertEqual(status, 200)
                self.assertEqual(body["mode"], mode)

        # Leave the simulator in its default state.
        _http_post("/api/simulation/mode/normal")

    def test_set_invalid_mode_returns_400(self):
        status, _ = _http_post("/api/simulation/mode/mega_overdrive")
        self.assertEqual(status, 400)

    def test_anomaly_mode_changes_telemetry(self):
        _http_post("/api/simulation/mode/high_temperature")

        # The telemetry loop ticks at 1 Hz with mean 78 C (std 3 C);
        # the first anomalous reading should appear within seconds.
        deadline = time.time() + 15
        hot_reading = None
        while time.time() < deadline:
            status, body = _http_get("/api/monitoring/current")
            self.assertEqual(status, 200)
            if body["temperature"] > 70:
                hot_reading = body
                break
            time.sleep(0.5)

        self.assertIsNotNone(
            hot_reading, "no reading above 70 C within 15 s of enabling "
            "high_temperature mode")
        self.assertNotEqual(hot_reading["status"], "normal")

        _http_post("/api/simulation/mode/normal")

    def test_anomaly_mode_generates_events(self):
        _http_post("/api/simulation/mode/high_temperature")

        deadline = time.time() + 15
        found = False
        while time.time() < deadline:
            status, body = _http_get("/api/monitoring/events?limit=50")
            self.assertEqual(status, 200)
            if any(e["event_type"] == "HIGH_TEMPERATURE"
                   for e in body["events"]):
                found = True
                break
            time.sleep(0.5)

        self.assertTrue(
            found, "no HIGH_TEMPERATURE event within 15 s of enabling "
            "high_temperature mode")

        _http_post("/api/simulation/mode/normal")


if __name__ == "__main__":
    unittest.main()

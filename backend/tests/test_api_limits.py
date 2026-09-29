"""Integration tests for `limit` validation on the monitoring API.

Spins up a real uvicorn server (subprocess) against a temporary SQLite database
and asserts the HTTP contract with stdlib urllib:

  - out-of-range `limit` values -> 422 (huge, -1, 0, non-integer);
  - in-range values and defaults -> 200 with the expected payload shape.

Before the fix, `?limit=-1` and `?limit=999999999` returned HTTP 200 with the
entire table (LIMIT -1 == unlimited in SQLite).

Run:  python -m unittest discover -s tests -v   (from backend/)
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_URL = "http://127.0.0.1:8131"


def _http_get(path: str):
    """Return (status_code, parsed_json_or_None)."""
    try:
        with urllib.request.urlopen(BASE_URL + path, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, None


class ApiLimitValidationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        db_path = os.path.join(cls.tmpdir.name, "api_test.db")

        # Seed a few rows so 200-responses carry data.
        conn = sqlite3.connect(db_path)
        conn.execute(
            """CREATE TABLE electrical_readings (
                   id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
                   voltage REAL NOT NULL, current REAL NOT NULL,
                   frequency REAL NOT NULL, power_factor REAL NOT NULL,
                   active_power REAL NOT NULL, temperature REAL NOT NULL,
                   status TEXT NOT NULL)"""
        )
        conn.execute(
            """CREATE TABLE monitoring_events (
                   id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
                   event_type TEXT NOT NULL, severity TEXT NOT NULL,
                   message TEXT NOT NULL, recommendation TEXT NOT NULL)"""
        )
        conn.executemany(
            "INSERT INTO electrical_readings (timestamp, voltage, current, frequency,"
            " power_factor, active_power, temperature, status)"
            " VALUES ('2026-09-29T17:00:00', 220.0, 12.0, 60.0, 0.93, 2.45, 45.0, 'normal')",
            [() for _ in range(30)],
        )
        conn.executemany(
            "INSERT INTO monitoring_events (timestamp, event_type, severity, message,"
            " recommendation) VALUES ('2026-09-29T17:00:00', 'EVT', 'low', 'm', 'r')",
            [() for _ in range(10)],
        )
        conn.commit()
        conn.close()

        env = dict(os.environ, NEXUS_DATABASE_URL=db_path)
        venv_python = os.path.join(BACKEND_DIR, ".venv", "bin", "python")
        cls.server = subprocess.Popen(
            [venv_python, "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", "8131"],
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

    # --- /api/monitoring/history ---

    def test_history_default_limit_ok(self):
        status, body = _http_get("/api/monitoring/history")
        self.assertEqual(status, 200)
        self.assertIn("readings", body)
        self.assertLessEqual(len(body["readings"]), 50)

    def test_history_limit_1000_ok(self):
        status, body = _http_get("/api/monitoring/history?limit=1000")
        self.assertEqual(status, 200)
        self.assertLessEqual(len(body["readings"]), 1000)

    def test_history_limit_above_max_rejected(self):
        status, _ = _http_get("/api/monitoring/history?limit=1001")
        self.assertEqual(status, 422)

    def test_history_huge_limit_rejected(self):
        status, _ = _http_get("/api/monitoring/history?limit=999999999")
        self.assertEqual(status, 422)

    def test_history_negative_limit_rejected(self):
        # Regression: LIMIT -1 == unlimited in SQLite; used to dump the table.
        status, _ = _http_get("/api/monitoring/history?limit=-1")
        self.assertEqual(status, 422)

    def test_history_zero_limit_rejected(self):
        status, _ = _http_get("/api/monitoring/history?limit=0")
        self.assertEqual(status, 422)

    def test_history_non_integer_limit_rejected(self):
        status, _ = _http_get("/api/monitoring/history?limit=abc")
        self.assertEqual(status, 422)

    # --- /api/monitoring/events ---

    def test_events_default_limit_ok(self):
        status, body = _http_get("/api/monitoring/events")
        self.assertEqual(status, 200)
        self.assertIn("events", body)
        self.assertLessEqual(len(body["events"]), 20)

    def test_events_limit_500_ok(self):
        status, _ = _http_get("/api/monitoring/events?limit=500")
        self.assertEqual(status, 200)

    def test_events_limit_above_max_rejected(self):
        status, _ = _http_get("/api/monitoring/events?limit=501")
        self.assertEqual(status, 422)

    def test_events_huge_limit_rejected(self):
        status, _ = _http_get("/api/monitoring/events?limit=999999999")
        self.assertEqual(status, 422)

    def test_events_negative_limit_rejected(self):
        status, _ = _http_get("/api/monitoring/events?limit=-1")
        self.assertEqual(status, 422)


if __name__ == "__main__":
    unittest.main()

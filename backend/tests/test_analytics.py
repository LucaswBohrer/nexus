"""Tests for GET /api/v1/analytics/overview (NEXUS 2.2).

A synthetic dataset with hand-computed expectations is inserted into a
temp database before the server starts; the overview endpoint must match
exactly: readings_count, energy (real 60 s deltas), per-metric
min/max/avg, event counts by severity/status and episode counts. Range
violations (>31 d) must return 422.

Run:  python -m unittest discover -s tests -v   (from backend/)
"""
import json
import os
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)
BASE_URL = "http://127.0.0.1:8148"

from app.database import database  # noqa: E402


def _http_get(path: str):
    try:
        with urllib.request.urlopen(BASE_URL + path, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, None


def _iso(dt: datetime) -> str:
    return dt.isoformat()


class AnalyticsOverviewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmpdir.name, "analytics_test.db")

        # Build the synthetic dataset before the server starts.
        cls.t0 = datetime.now(timezone.utc) - timedelta(hours=2)
        cls.powers = [2.5 + 0.1 * i for i in range(10)]
        cls.voltages = [220.0 + i for i in range(10)]
        cls.temps = [40.0 + i for i in range(10)]

        old_path = database.DB_PATH
        database.DB_PATH = cls.db_path
        try:
            database.init_database()
            conn = sqlite3.connect(cls.db_path)
            try:
                for i in range(10):
                    ts = _iso(cls.t0 + timedelta(seconds=60 * i))
                    conn.execute(
                        """INSERT INTO electrical_readings
                           (timestamp, voltage, current, frequency,
                            power_factor, active_power, temperature, status)
                           VALUES (?, ?, 12.0, 60.0, 0.93, ?, ?, 'normal')""",
                        (ts, cls.voltages[i], cls.powers[i], cls.temps[i]),
                    )
                events = [
                    ("warning", "open"),
                    ("warning", "open"),
                    ("critical", "resolved"),
                    ("info", "acknowledged"),
                ]
                for j, (severity, status) in enumerate(events):
                    ts = _iso(cls.t0 + timedelta(seconds=60 * j))
                    conn.execute(
                        """INSERT INTO monitoring_events
                           (timestamp, event_type, severity, message,
                            recommendation, status, opened_at, occurrences)
                           VALUES (?, 'SYNTH', ?, 'm', 'r', ?, ?, 1)""",
                        (ts, severity, status, ts),
                    )
                for k, status in enumerate(("open", "resolved")):
                    ts = _iso(cls.t0 + timedelta(seconds=60 * k))
                    conn.execute(
                        """INSERT INTO diagnostic_episodes
                           (started_at, status, severity, rules,
                            peak_values, recommendations)
                           VALUES (?, ?, 'warning', '[]', '{}', '[]')""",
                        (ts, status),
                    )
                conn.commit()
            finally:
                conn.close()
        finally:
            database.DB_PATH = old_path

        cls.from_iso = _iso(cls.t0 - timedelta(seconds=60))
        cls.to_iso = _iso(cls.t0 + timedelta(seconds=11 * 60))

        env = dict(os.environ, NEXUS_DATABASE_URL=cls.db_path)
        venv_python = os.path.join(BACKEND_DIR, ".venv", "bin", "python")
        cls.server = subprocess.Popen(
            [venv_python, "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", "8148"],
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

    def _overview(self):
        qs = urllib.parse.urlencode(
            {"from": self.from_iso, "to": self.to_iso}
        )
        status, body = _http_get(f"/api/v1/analytics/overview?{qs}")
        self.assertEqual(status, 200)
        return body

    def test_readings_count(self):
        self.assertEqual(self._overview()["readings_count"], 10)

    def test_energy_uses_real_deltas(self):
        # Hand-computed: sum of prev_power * 60s / 3600 over the 9 intervals.
        expected = sum(p * 60.0 / 3600.0 for p in self.powers[:-1])
        self.assertAlmostEqual(
            self._overview()["energy_kwh"], expected, places=9
        )

    def test_per_metric_min_max_avg(self):
        per_metric = self._overview()["per_metric"]
        self.assertAlmostEqual(per_metric["voltage"]["min"], 220.0)
        self.assertAlmostEqual(per_metric["voltage"]["max"], 229.0)
        self.assertAlmostEqual(
            per_metric["voltage"]["avg"], statistics.mean(self.voltages)
        )
        self.assertAlmostEqual(per_metric["temperature"]["min"], 40.0)
        self.assertAlmostEqual(per_metric["temperature"]["max"], 49.0)
        self.assertAlmostEqual(
            per_metric["active_power"]["avg"], statistics.mean(self.powers)
        )

    def test_events_by_severity(self):
        self.assertEqual(
            self._overview()["events_by_severity"],
            {"info": 1, "warning": 2, "critical": 1},
        )

    def test_events_by_status(self):
        self.assertEqual(
            self._overview()["events_by_status"],
            {"open": 2, "acknowledged": 1, "resolved": 1},
        )

    def test_episodes(self):
        self.assertEqual(
            self._overview()["episodes"], {"total": 2, "open": 1}
        )

    def test_range_over_31_days_rejected(self):
        status, _ = _http_get(
            "/api/v1/analytics/overview"
            "?from=2020-01-01T00:00:00&to=2026-01-01T00:00:00"
        )
        self.assertEqual(status, 422)

    def test_from_after_to_rejected(self):
        qs = urllib.parse.urlencode(
            {"from": self.to_iso, "to": self.from_iso}
        )
        status, _ = _http_get(f"/api/v1/analytics/overview?{qs}")
        self.assertEqual(status, 422)


if __name__ == "__main__":
    unittest.main()

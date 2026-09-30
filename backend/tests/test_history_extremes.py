"""Tests for GET /api/v1/history/extremes (NEXUS 2.2).

A known dataset is inserted into a temp database; the endpoint must
return the correct min/max values with their timestamps, avg and count.
The derived apparent_power metric (V*I/1000) is covered too. Invalid
metric and >31 d ranges must return 422.

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
BASE_URL = "http://127.0.0.1:8149"

from app.database import database  # noqa: E402
from app.services import equipment as equipment_service  # noqa: E402


def _http_get(path: str):
    try:
        with urllib.request.urlopen(BASE_URL + path, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, None


class HistoryExtremesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmpdir.name, "extremes_test.db")

        cls.t0 = datetime.now(timezone.utc) - timedelta(hours=3)
        # (voltage, current) pairs; apparent = V*I/1000.
        cls.samples = [
            (220.0, 12.0),
            (225.0, 11.0),
            (215.0, 13.0),  # min voltage
            (230.0, 10.0),  # max voltage
            (222.0, 12.5),
        ]
        cls.timestamps = [
            (cls.t0 + timedelta(seconds=60 * i)).isoformat()
            for i in range(len(cls.samples))
        ]

        old_path = database.DB_PATH
        database.DB_PATH = cls.db_path
        try:
            database.init_database()
            # NEXUS 2.4: fixture rows are stamped with the DEFAULT
            # equipment, like real pre-2.4 data after the v4 backfill.
            default_id = equipment_service.get_default_equipment()["id"]
            conn = sqlite3.connect(cls.db_path)
            try:
                for (voltage, current), ts in zip(cls.samples, cls.timestamps):
                    conn.execute(
                        """INSERT INTO electrical_readings
                           (timestamp, voltage, current, frequency,
                            power_factor, active_power, temperature, status,
                            equipment_id)
                           VALUES (?, ?, ?, 60.0, 0.93, 2.5, 42.0, 'normal',
                                   ?)""",
                        (ts, voltage, current, default_id),
                    )
                conn.commit()
            finally:
                conn.close()
        finally:
            database.DB_PATH = old_path

        cls.from_iso = (cls.t0 - timedelta(seconds=60)).isoformat()
        cls.to_iso = (cls.t0 + timedelta(seconds=360)).isoformat()

        env = dict(os.environ, NEXUS_DATABASE_URL=cls.db_path)
        venv_python = os.path.join(BACKEND_DIR, ".venv", "bin", "python")
        cls.server = subprocess.Popen(
            [venv_python, "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", "8149"],
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

    def _extremes(self, metric):
        qs = urllib.parse.urlencode(
            {"metric": metric, "from": self.from_iso, "to": self.to_iso}
        )
        status, body = _http_get(f"/api/v1/history/extremes?{qs}")
        self.assertEqual(status, 200)
        return body

    def test_voltage_extremes_with_timestamps(self):
        body = self._extremes("voltage")
        self.assertEqual(body["metric"], "voltage")
        self.assertEqual(body["count"], 5)
        self.assertEqual(body["min"]["value"], 215.0)
        self.assertEqual(body["min"]["timestamp"], self.timestamps[2])
        self.assertEqual(body["max"]["value"], 230.0)
        self.assertEqual(body["max"]["timestamp"], self.timestamps[3])
        self.assertAlmostEqual(
            body["avg"], statistics.mean(v for v, _ in self.samples)
        )

    def test_apparent_power_derived(self):
        body = self._extremes("apparent_power")
        apparent = [v * i / 1000.0 for v, i in self.samples]
        self.assertEqual(body["count"], 5)
        self.assertAlmostEqual(body["min"]["value"], min(apparent))
        self.assertAlmostEqual(body["max"]["value"], max(apparent))
        self.assertAlmostEqual(body["avg"], statistics.mean(apparent))

    def test_unknown_metric_rejected(self):
        qs = urllib.parse.urlencode(
            {"metric": "bogus", "from": self.from_iso, "to": self.to_iso}
        )
        status, _ = _http_get(f"/api/v1/history/extremes?{qs}")
        self.assertEqual(status, 422)

    def test_range_over_31_days_rejected(self):
        status, _ = _http_get(
            "/api/v1/history/extremes?metric=voltage"
            "&from=2020-01-01T00:00:00&to=2026-01-01T00:00:00"
        )
        self.assertEqual(status, 422)


if __name__ == "__main__":
    unittest.main()

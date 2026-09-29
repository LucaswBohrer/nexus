"""Tests for the NEXUS 2.1 stats summary endpoint.

compute_energy_kwh() is tested deterministically (real timestamp deltas,
gap cap); GET /api/v1/stats/summary is exercised through a live server.

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
from datetime import datetime, timedelta, timezone

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

BASE_URL = "http://127.0.0.1:8139"

from app.services.aggregation import compute_energy_kwh  # noqa: E402


def _http_get(path: str):
    try:
        with urllib.request.urlopen(BASE_URL + path, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, None


class EnergyComputationTest(unittest.TestCase):
    def test_energy_uses_real_deltas(self):
        t0 = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
        rows = [
            (t0.isoformat(), 2.0),
            ((t0 + timedelta(seconds=60)).isoformat(), 2.0),
            ((t0 + timedelta(seconds=120)).isoformat(), 2.0),
        ]
        # 2 kW for 120 s -> 2*120/3600 = 0.0667 kWh.
        self.assertAlmostEqual(
            compute_energy_kwh(rows), 2.0 * 120 / 3600, places=6
        )

    def test_energy_weights_each_interval_by_its_power(self):
        t0 = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
        rows = [
            (t0.isoformat(), 1.0),  # 1 kW during [t0, t0+60]
            ((t0 + timedelta(seconds=60)).isoformat(), 3.0),  # 3 kW [t0+60, t0+120]
            ((t0 + timedelta(seconds=120)).isoformat(), 0.0),
        ]
        expected = (1.0 * 60 + 3.0 * 60) / 3600
        self.assertAlmostEqual(compute_energy_kwh(rows), expected, places=6)

    def test_long_gap_is_capped_not_inflated(self):
        t0 = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
        rows = [
            (t0.isoformat(), 5.0),
            ((t0 + timedelta(seconds=60)).isoformat(), 5.0),
            # 940 s gap (restart/outage): excluded, not counted as 5 kW.
            ((t0 + timedelta(seconds=1000)).isoformat(), 5.0),
        ]
        self.assertAlmostEqual(
            compute_energy_kwh(rows), 5.0 * 60 / 3600, places=6
        )

    def test_single_reading_yields_zero_energy(self):
        t0 = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(compute_energy_kwh([(t0.isoformat(), 9.9)]), 0.0)


class StatsSummaryIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmpdir.name, "stats_test.db")

        env = dict(os.environ, NEXUS_DATABASE_URL=cls.db_path)
        venv_python = os.path.join(BACKEND_DIR, ".venv", "bin", "python")
        cls.server = subprocess.Popen(
            [venv_python, "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", "8139"],
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

    def test_summary_shape_and_real_counts(self):
        time.sleep(5)  # let a few ticks accumulate
        status, body = _http_get("/api/v1/stats/summary")
        self.assertEqual(status, 200)

        for key in (
            "energy_today_kwh",
            "readings_count",
            "uptime_s",
            "current",
            "last_24h",
            "status_counts_24h",
        ):
            self.assertIn(key, body)

        # Real counts, not placeholders.
        self.assertGreaterEqual(body["readings_count"], 3)
        self.assertGreater(body["uptime_s"], 0)
        self.assertGreaterEqual(body["energy_today_kwh"], 0)

        current = body["current"]
        self.assertIsNotNone(current)
        self.assertIn("voltage", current)

        day = body["last_24h"]["voltage"]
        self.assertLessEqual(day["min"], day["avg"])
        self.assertLessEqual(day["avg"], day["max"])

        total_status = sum(body["status_counts_24h"].values())
        self.assertGreater(total_status, 0)


if __name__ == "__main__":
    unittest.main()

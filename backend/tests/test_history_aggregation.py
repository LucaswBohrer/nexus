"""Tests for the NEXUS 2.1 history aggregation endpoint.

Unit tests insert synthetic readings with known timestamps/values and
call get_history_buckets() directly; integration tests exercise
GET /api/v1/history through a live server (validation -> 422s).

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
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

BASE_URL = "http://127.0.0.1:8138"

from app.database import database  # noqa: E402
from app.database.database import save_reading  # noqa: E402
from app.services.aggregation import (  # noqa: E402
    AggregationError,
    get_history_buckets,
    parse_bound,
)


def _http_get(path: str):
    try:
        with urllib.request.urlopen(BASE_URL + path, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
        except Exception:
            body = None
        return e.code, body


def _reading(ts: datetime, voltage: float = 220.0) -> dict:
    return {
        "timestamp": ts,
        "voltage": voltage,
        "current": 10.0,
        "frequency": 60.0,
        "power_factor": 0.92,
        "active_power": 2.0,
        "temperature": 45.0,
        "status": "normal",
    }


class HistoryAggregationTest(unittest.TestCase):
    """Deterministic aggregation tests against a local temp database."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self._old_db_path = database.DB_PATH
        database.DB_PATH = os.path.join(self.tmpdir.name, "unit.db")
        database.init_database()
        # 10 readings, one per minute, voltage 200..209 V.
        self.t0 = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
        for i in range(10):
            save_reading(_reading(self.t0 + timedelta(minutes=i), 200.0 + i))

    def tearDown(self):
        database.DB_PATH = self._old_db_path
        self.tmpdir.cleanup()

    def test_bucket_aggregation_values(self):
        buckets = get_history_buckets(
            "voltage",
            self.t0,
            self.t0 + timedelta(minutes=10),
            "5m",
        )
        self.assertEqual(len(buckets), 2)
        first, second = buckets
        self.assertEqual(first["count"], 5)
        self.assertEqual(first["min"], 200.0)
        self.assertEqual(first["max"], 204.0)
        self.assertAlmostEqual(first["avg"], 202.0)
        self.assertEqual(second["count"], 5)
        self.assertEqual(second["min"], 205.0)
        self.assertEqual(second["max"], 209.0)
        # Buckets are ordered by time and start on bucket boundaries.
        self.assertLess(first["t"], second["t"])
        self.assertTrue(first["t"].endswith("+00:00"))

    def test_derived_metric_apparent_power(self):
        # apparent_power = voltage * current / 1000 = 220 * 10 / 1000 = 2.2
        buckets = get_history_buckets(
            "apparent_power",
            self.t0,
            self.t0 + timedelta(minutes=10),
            "1h",
        )
        self.assertEqual(len(buckets), 1)
        self.assertAlmostEqual(buckets[0]["avg"], 2.045, places=3)

    def test_empty_range_returns_no_buckets(self):
        buckets = get_history_buckets(
            "voltage",
            self.t0 + timedelta(days=1),
            self.t0 + timedelta(days=1, minutes=10),
            "5m",
        )
        self.assertEqual(buckets, [])

    def test_invalid_metric_raises(self):
        with self.assertRaises(AggregationError):
            get_history_buckets(
                "nope", self.t0, self.t0 + timedelta(minutes=10), "5m"
            )

    def test_invalid_bucket_raises(self):
        with self.assertRaises(AggregationError):
            get_history_buckets(
                "voltage", self.t0, self.t0 + timedelta(minutes=10), "2m"
            )

    def test_from_after_to_raises(self):
        with self.assertRaises(AggregationError):
            get_history_buckets(
                "voltage", self.t0 + timedelta(minutes=10), self.t0, "5m"
            )

    def test_range_over_31_days_raises(self):
        with self.assertRaises(AggregationError):
            get_history_buckets(
                "voltage", self.t0, self.t0 + timedelta(days=32), "1d"
            )

    def test_too_many_buckets_raises(self):
        # 3 days at 1m = 4320 buckets > 2000.
        with self.assertRaises(AggregationError):
            get_history_buckets(
                "voltage", self.t0, self.t0 + timedelta(days=3), "1m"
            )

    def test_naive_bounds_interpreted_as_utc(self):
        parsed = parse_bound("2026-09-29T12:00:00", "from")
        self.assertEqual(parsed.tzinfo, timezone.utc)
        self.assertEqual(parsed, self.t0)


class HistoryApiIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmpdir.name, "history_test.db")

        env = dict(os.environ, NEXUS_DATABASE_URL=cls.db_path)
        venv_python = os.path.join(BACKEND_DIR, ".venv", "bin", "python")
        cls.server = subprocess.Popen(
            [venv_python, "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", "8138"],
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

    def _history(self, **params):
        qs = urllib.parse.urlencode(params)
        return _http_get(f"/api/v1/history?{qs}")

    def test_history_endpoint_aggregates_live_data(self):
        time.sleep(4)  # let a few ticks accumulate
        now = datetime.now(timezone.utc)
        status, body = self._history(
            metric="voltage",
            **{"from": (now - timedelta(minutes=5)).isoformat()},
            to=now.isoformat(),
            bucket="1m",
        )
        self.assertEqual(status, 200)
        self.assertIn("buckets", body)
        self.assertGreater(len(body["buckets"]), 0)
        bucket = body["buckets"][0]
        for key in ("t", "min", "max", "avg", "count"):
            self.assertIn(key, bucket)
        self.assertGreaterEqual(bucket["count"], 1)

    def test_history_invalid_metric_is_422(self):
        now = datetime.now(timezone.utc)
        status, _ = self._history(
            metric="nope",
            **{"from": (now - timedelta(minutes=5)).isoformat()},
            to=now.isoformat(),
            bucket="1m",
        )
        self.assertEqual(status, 422)

    def test_history_range_over_31_days_is_422(self):
        now = datetime.now(timezone.utc)
        status, _ = self._history(
            metric="voltage",
            **{"from": (now - timedelta(days=40)).isoformat()},
            to=now.isoformat(),
            bucket="1d",
        )
        self.assertEqual(status, 422)

    def test_history_too_many_buckets_is_422(self):
        now = datetime.now(timezone.utc)
        status, _ = self._history(
            metric="voltage",
            **{"from": (now - timedelta(days=3)).isoformat()},
            to=now.isoformat(),
            bucket="1m",
        )
        self.assertEqual(status, 422)


if __name__ == "__main__":
    unittest.main()

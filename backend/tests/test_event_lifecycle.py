"""Tests for the NEXUS 2.1 event lifecycle (deduplication).

Unit tests drive process_tick_events() directly with synthetic diagnosis
events for determinism; one integration test proves the live telemetry
loop no longer spams one row per tick.

Lifecycle rules under test:
  - 10 sustained ticks of one condition -> exactly 1 row, occurrences=10;
  - 5 consecutive normal ticks -> status='resolved', closed_at set;
  - a later occurrence of the same condition -> a NEW row (resolved rows
    are never reopened);
  - deduplication is per (event_type, equipment_id) identity.

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
from datetime import datetime, timedelta, timezone

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

BASE_URL = "http://127.0.0.1:8137"

from app.database import database  # noqa: E402
from app.services.events import process_tick_events  # noqa: E402


def _http_get(path: str):
    try:
        with urllib.request.urlopen(BASE_URL + path, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, None


def _http_post(path: str):
    req = urllib.request.Request(BASE_URL + path, data=b"", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, None


def _make_event(event_type: str, severity: str = "warning") -> dict:
    return {
        "timestamp": datetime.now(timezone.utc),
        "event_type": event_type,
        "severity": severity,
        "message": f"{event_type} happened",
        "recommendation": "do something",
        "threshold": 242.0,
        "value": 250.0,
    }


class EventLifecycleTest(unittest.TestCase):
    """Deterministic lifecycle tests against a local temp database."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self._old_db_path = database.DB_PATH
        database.DB_PATH = os.path.join(self.tmpdir.name, "unit.db")
        database.init_database()
        self.t0 = datetime.now(timezone.utc)

    def tearDown(self):
        database.DB_PATH = self._old_db_path
        self.tmpdir.cleanup()

    def _rows(self):
        conn = sqlite3.connect(database.DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM monitoring_events ORDER BY id"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def _tick(self, events, seconds: int):
        process_tick_events(events, now=self.t0 + timedelta(seconds=seconds))

    def test_sustained_condition_creates_single_event(self):
        for i in range(10):
            self._tick([_make_event("HIGH_VOLTAGE")], i)

        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event_type"], "HIGH_VOLTAGE")
        self.assertEqual(rows[0]["status"], "open")
        self.assertEqual(rows[0]["occurrences"], 10)
        self.assertEqual(rows[0]["severity"], "warning")
        self.assertIsNotNone(rows[0]["opened_at"])
        self.assertIsNone(rows[0]["closed_at"])
        self.assertEqual(rows[0]["last_value"], 250.0)

    def test_five_normal_ticks_resolve_the_event(self):
        for i in range(3):
            self._tick([_make_event("HIGH_VOLTAGE")], i)
        for i in range(3, 8):
            self._tick([], i)

        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "resolved")
        self.assertIsNotNone(rows[0]["closed_at"])
        self.assertEqual(rows[0]["occurrences"], 3)

    def test_fewer_than_five_normal_ticks_keep_event_open(self):
        for i in range(3):
            self._tick([_make_event("HIGH_VOLTAGE")], i)
        for i in range(3, 7):
            self._tick([], i)

        rows = self._rows()
        self.assertEqual(rows[0]["status"], "open")

    def test_new_occurrence_after_resolve_creates_new_event(self):
        for i in range(3):
            self._tick([_make_event("HIGH_VOLTAGE")], i)
        for i in range(3, 8):
            self._tick([], i)
        # Condition fires again after resolution.
        for i in range(8, 10):
            self._tick([_make_event("HIGH_VOLTAGE")], i)

        rows = self._rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["status"], "resolved")
        self.assertEqual(rows[1]["status"], "open")
        self.assertEqual(rows[1]["occurrences"], 2)

    def test_dedup_is_per_condition_identity(self):
        for i in range(4):
            self._tick(
                [_make_event("HIGH_VOLTAGE"), _make_event("HIGH_TEMPERATURE")],
                i,
            )

        rows = self._rows()
        self.assertEqual(len(rows), 2)
        by_type = {r["event_type"]: r for r in rows}
        self.assertEqual(by_type["HIGH_VOLTAGE"]["occurrences"], 4)
        self.assertEqual(by_type["HIGH_TEMPERATURE"]["occurrences"], 4)

    def test_absent_condition_does_not_touch_other_events(self):
        for i in range(6):
            self._tick([_make_event("HIGH_VOLTAGE")], i)
        # HIGH_VOLTAGE keeps firing; LOW_VOLTAGE never did.
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "open")


class EventSpamIntegrationTest(unittest.TestCase):
    """The live telemetry loop must not write one row per tick."""

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmpdir.name, "lifecycle_test.db")

        env = dict(os.environ, NEXUS_DATABASE_URL=cls.db_path)
        venv_python = os.path.join(BACKEND_DIR, ".venv", "bin", "python")
        cls.server = subprocess.Popen(
            [venv_python, "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", "8137"],
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
        try:
            _http_post("/api/simulation/mode/normal")
        except OSError:
            pass
        cls.server.terminate()
        try:
            cls.server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.server.kill()
        cls.tmpdir.cleanup()

    def test_sustained_anomaly_yields_one_legacy_event(self):
        status, _ = _http_post("/api/simulation/mode/high_voltage")
        self.assertEqual(status, 200)
        time.sleep(7)  # ~7 ticks of sustained HIGH_VOLTAGE

        status, body = _http_get("/api/monitoring/events?limit=50")
        self.assertEqual(status, 200)
        hv = [e for e in body["events"] if e["event_type"] == "HIGH_VOLTAGE"]
        # One logical event, not seven rows...
        self.assertEqual(len(hv), 1)
        # ...and the legacy severity vocabulary is preserved.
        self.assertEqual(hv[0]["severity"], "medium")
        self.assertIn("recommendation", hv[0])

        _http_post("/api/simulation/mode/normal")


if __name__ == "__main__":
    unittest.main()

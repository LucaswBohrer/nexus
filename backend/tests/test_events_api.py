"""Tests for the NEXUS 2.1 events API.

Events are seeded deterministically by calling process_tick_events()
against the same SQLite file the test server uses (separate process,
separate connections — plain SQLite file sharing).

Covers: listing (latest first), filters (status/severity/type/from/to/q),
id-cursor pagination, PATCH transitions (valid and invalid), 404s.

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
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

BASE_URL = "http://127.0.0.1:8140"

from app.database import database  # noqa: E402
from app.services.events import process_tick_events  # noqa: E402


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


def _http_patch(path: str, payload: dict):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        BASE_URL + path, data=data, method="PATCH",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
        except Exception:
            body = None
        return e.code, body


def _event(event_type: str, severity: str, message: str) -> dict:
    return {
        "timestamp": datetime.now(timezone.utc),
        "event_type": event_type,
        "severity": severity,
        "message": message,
        "recommendation": "check it",
        "threshold": 1.0,
        "value": 2.0,
    }


class EventsApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmpdir.name, "events_test.db")

        env = dict(os.environ, NEXUS_DATABASE_URL=cls.db_path)
        venv_python = os.path.join(BACKEND_DIR, ".venv", "bin", "python")
        cls.server = subprocess.Popen(
            [venv_python, "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", "8140"],
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

        # Seed three known events directly into the server's database file.
        database.DB_PATH = cls.db_path
        database.init_database()
        t0 = datetime.now(timezone.utc)
        process_tick_events(
            [_event("HIGH_VOLTAGE", "warning", "voltage spike on phase A")],
            now=t0,
        )
        process_tick_events(
            [_event("HIGH_TEMPERATURE", "critical", "motor overheating")],
            now=t0 + timedelta(seconds=1),
        )
        # Resolve the first event so we have every status present.
        for i in range(2, 8):
            process_tick_events(
                [_event("HIGH_TEMPERATURE", "critical", "motor overheating")],
                now=t0 + timedelta(seconds=i),
            )
        conn = sqlite3.connect(cls.db_path)
        cls.ids = {
            row[1]: row[0]
            for row in conn.execute(
                "SELECT id, event_type FROM monitoring_events ORDER BY id"
            ).fetchall()
        }
        conn.close()

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        try:
            cls.server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.server.kill()
        cls.tmpdir.cleanup()

    def setUp(self):
        # The live telemetry loop resolves events whose condition has been
        # absent for 5 ticks. Re-fire the open seeded condition before each
        # test so its status is deterministic regardless of timing.
        # (HIGH_VOLTAGE stays resolved: re-firing it would open a new one.)
        database.DB_PATH = self.db_path
        process_tick_events(
            [_event("HIGH_TEMPERATURE", "critical", "motor overheating")]
        )

    def test_list_latest_first_with_cursor(self):
        status, body = _http_get("/api/v1/events?limit=1")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["events"]), 1)
        first = body["events"][0]
        self.assertEqual(first["event_type"], "HIGH_TEMPERATURE")
        self.assertIsNotNone(body["next_cursor"])

        status, body2 = _http_get(
            f"/api/v1/events?limit=1&cursor={body['next_cursor']}"
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(body2["events"]), 1)
        self.assertEqual(body2["events"][0]["event_type"], "HIGH_VOLTAGE")
        self.assertIsNone(body2["next_cursor"])

    def test_filter_by_status(self):
        status, body = _http_get("/api/v1/events?status=open")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["events"]), 1)
        self.assertEqual(body["events"][0]["event_type"], "HIGH_TEMPERATURE")

        status, body = _http_get("/api/v1/events?status=resolved")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["events"]), 1)
        self.assertEqual(body["events"][0]["event_type"], "HIGH_VOLTAGE")

    def test_filter_by_severity_and_type(self):
        status, body = _http_get("/api/v1/events?severity=critical")
        self.assertEqual(status, 200)
        self.assertTrue(all(e["severity"] == "critical" for e in body["events"]))

        status, body = _http_get("/api/v1/events?type=HIGH_VOLTAGE")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["events"]), 1)

    def test_search_query(self):
        status, body = _http_get("/api/v1/events?q=" + urllib.parse.quote("phase A"))
        self.assertEqual(status, 200)
        self.assertEqual(len(body["events"]), 1)
        self.assertEqual(body["events"][0]["event_type"], "HIGH_VOLTAGE")

    def test_invalid_status_is_422(self):
        status, _ = _http_get("/api/v1/events?status=bogus")
        self.assertEqual(status, 422)

    def test_patch_transitions(self):
        temp_id = self.ids["HIGH_TEMPERATURE"]  # open

        status, body = _http_patch(
            f"/api/v1/events/{temp_id}", {"action": "acknowledge"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["event"]["status"], "acknowledged")
        self.assertIsNotNone(body["event"]["acknowledged_at"])

        status, body = _http_patch(
            f"/api/v1/events/{temp_id}", {"action": "resolve"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["event"]["status"], "resolved")
        self.assertIsNotNone(body["event"]["closed_at"])

    def test_patch_invalid_transitions(self):
        hv_id = self.ids["HIGH_VOLTAGE"]  # resolved
        temp_id = self.ids["HIGH_TEMPERATURE"]  # open (fresh seed order)

        # Resolved can never be reopened or re-acknowledged.
        status, _ = _http_patch(f"/api/v1/events/{hv_id}", {"action": "acknowledge"})
        self.assertEqual(status, 422)
        status, _ = _http_patch(f"/api/v1/events/{hv_id}", {"action": "resolve"})
        self.assertEqual(status, 422)

        # Unknown action.
        status, _ = _http_patch(f"/api/v1/events/{temp_id}", {"action": "snooze"})
        self.assertEqual(status, 422)

        # Unknown id.
        status, _ = _http_patch("/api/v1/events/999999", {"action": "resolve"})
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()

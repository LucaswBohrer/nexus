"""Tests for NEXUS 2.1 diagnostic episode tracking (§14).

Unit tests drive process_tick_episode() directly with synthetic
diagnosis/reading dicts for determinism; one integration test proves the
live telemetry loop opens/updates/closes episodes and that
GET /api/v1/diagnostics/episodes serves them.

Rules under test:
  - sustained abnormal ticks -> exactly 1 open episode;
  - 5 consecutive normal ticks -> status='resolved', ended_at set;
  - a later abnormal period -> a NEW episode;
  - severity is the worst seen; peak_values track real per-metric min/max;
  - the v1 endpoint lists episodes, latest first.

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

BASE_URL = "http://127.0.0.1:8140"

from app.database import database  # noqa: E402
from app.services.episodes import list_episodes, process_tick_episode  # noqa: E402


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


def _abnormal_diagnosis():
    return {
        "status": "warning",
        "severity": "warning",
        "anomalies": ["HIGH_VOLTAGE"],
        "recommendations": ["Inspect voltage regulation."],
        "events": [],
    }


def _normal_diagnosis():
    return {
        "status": "normal",
        "severity": "info",
        "anomalies": [],
        "recommendations": [],
        "events": [],
    }


def _reading(voltage: float = 250.0):
    return {
        "timestamp": datetime.now(timezone.utc),
        "voltage": voltage,
        "current": 12.0,
        "frequency": 60.0,
        "power_factor": 0.93,
        "active_power": 2.8,
        "temperature": 42.0,
        "status": "warning",
    }


class EpisodeLifecycleTest(unittest.TestCase):
    """Deterministic episode tests against a local temp database."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self._old_db_path = database.DB_PATH
        database.DB_PATH = os.path.join(self.tmpdir.name, "unit.db")
        database.init_database()
        self.t0 = datetime.now(timezone.utc)

    def tearDown(self):
        database.DB_PATH = self._old_db_path
        self.tmpdir.cleanup()

    def _tick(self, diagnosis, reading, seconds: int):
        process_tick_episode(
            diagnosis, reading, now=self.t0 + timedelta(seconds=seconds)
        )

    def test_sustained_abnormal_opens_single_episode(self):
        for i in range(10):
            self._tick(_abnormal_diagnosis(), _reading(voltage=248.0 + i), i)
        episodes = list_episodes()
        self.assertEqual(len(episodes), 1)
        episode = episodes[0]
        self.assertEqual(episode["status"], "open")
        self.assertIsNone(episode["ended_at"])
        self.assertEqual(episode["rules"], ["HIGH_VOLTAGE"])
        # peak_values reflect the real observed extremes (248..257).
        peaks = episode["peak_values"]["voltage"]
        self.assertAlmostEqual(peaks["min"], 248.0, places=1)
        self.assertAlmostEqual(peaks["max"], 257.0, places=1)

    def test_five_normal_ticks_close_episode(self):
        for i in range(3):
            self._tick(_abnormal_diagnosis(), _reading(), i)
        for i in range(5):
            self._tick(_normal_diagnosis(), _reading(voltage=220.0), 100 + i)
        episodes = list_episodes()
        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0]["status"], "resolved")
        self.assertIsNotNone(episodes[0]["ended_at"])

    def test_later_abnormal_period_opens_new_episode(self):
        for i in range(3):
            self._tick(_abnormal_diagnosis(), _reading(), i)
        for i in range(5):
            self._tick(_normal_diagnosis(), _reading(voltage=220.0), 100 + i)
        for i in range(3):
            self._tick(_abnormal_diagnosis(), _reading(), 200 + i)
        episodes = list_episodes()
        self.assertEqual(len(episodes), 2)
        # Latest first: the new one is open, the old one resolved.
        self.assertEqual(episodes[0]["status"], "open")
        self.assertEqual(episodes[1]["status"], "resolved")

    def test_severity_tracks_worst_seen(self):
        diag = _abnormal_diagnosis()
        self._tick(diag, _reading(), 0)
        critical = _abnormal_diagnosis()
        critical["severity"] = "critical"
        critical["status"] = "critical"
        self._tick(critical, _reading(), 1)
        episodes = list_episodes()
        self.assertEqual(episodes[0]["severity"], "critical")

    def test_normal_ticks_without_episode_are_noop(self):
        for i in range(10):
            self._tick(_normal_diagnosis(), _reading(voltage=220.0), i)
        self.assertEqual(list_episodes(), [])


class EpisodeIntegrationTest(unittest.TestCase):
    """Live-server proof: the tick hook feeds episodes to the v1 endpoint."""

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmpdir.name, "episodes_test.db")
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

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        try:
            cls.server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.server.kill()
        cls.tmpdir.cleanup()

    def _episodes(self):
        status, body = _http_get("/api/v1/diagnostics/episodes")
        self.assertEqual(status, 200)
        return body["episodes"]

    def test_tick_opens_and_closes_episode(self):
        status, _ = _http_post("/api/simulation/mode/high_voltage")
        self.assertEqual(status, 200)
        time.sleep(7)  # ~7 sustained abnormal ticks
        episodes = self._episodes()
        self.assertGreaterEqual(len(episodes), 1)
        self.assertEqual(episodes[0]["status"], "open")
        self.assertIn("HIGH_VOLTAGE", episodes[0]["rules"])

        status, _ = _http_post("/api/simulation/mode/normal")
        self.assertEqual(status, 200)
        time.sleep(7)  # 5+ normal ticks close it
        episodes = self._episodes()
        self.assertEqual(episodes[0]["status"], "resolved")
        self.assertIsNotNone(episodes[0]["ended_at"])


if __name__ == "__main__":
    unittest.main()

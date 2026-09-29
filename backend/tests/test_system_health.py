"""Tests for NEXUS 2.1 health, system endpoints and API key protection.

Server A (no NEXUS_API_KEY): health contract, system/database, system/errors,
writes open. Server B (NEXUS_API_KEY set): writes require X-API-Key (401),
GETs stay public.

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

BASE_A = "http://127.0.0.1:8141"
BASE_B = "http://127.0.0.1:8142"


def _request(base, method, path, payload=None, headers=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        base + path, data=data, method=method,
        headers=headers or {},
    )
    if payload is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
        except Exception:
            body = None
        return e.code, body


def _spawn(port: int, db_path: str, extra_env: dict | None = None):
    env = dict(os.environ, NEXUS_DATABASE_URL=db_path)
    if extra_env:
        env.update(extra_env)
    venv_python = os.path.join(BACKEND_DIR, ".venv", "bin", "python")
    proc = subprocess.Popen(
        [venv_python, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=BACKEND_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 25
    while time.time() < deadline:
        try:
            status, _ = _request(base, "GET", "/api/monitoring/current")
            if status == 200:
                return proc
        except OSError:
            pass
        time.sleep(0.5)
    proc.terminate()
    raise RuntimeError(f"test server on {port} did not start in time")


def _stop(proc, tmpdir):
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    tmpdir.cleanup()


class SystemHealthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmpdir.name, "health_test.db")
        cls.server = _spawn(8141, cls.db_path)
        time.sleep(3)  # let ticks and uptime accumulate

    @classmethod
    def tearDownClass(cls):
        _stop(cls.server, cls.tmpdir)

    def test_health_preserves_legacy_contract(self):
        status, body = _request(BASE_A, "GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "healthy")
        self.assertEqual(body["service"], "nexus-api")
        self.assertEqual(body["database"], "ok")

    def test_health_adds_observability_fields(self):
        status, body = _request(BASE_A, "GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["version"], "2.1.0")
        self.assertGreater(body["uptime_s"], 0)
        self.assertGreater(body["db_size_bytes"], 0)
        self.assertGreaterEqual(body["readings_count"], 1)
        self.assertGreaterEqual(body["last_tick_age_ms"], 0)
        # A healthy 1 Hz loop ticks recently.
        self.assertLess(body["last_tick_age_ms"], 5000)

    def test_system_database(self):
        status, body = _request(BASE_A, "GET", "/api/v1/system/database")
        self.assertEqual(status, 200)
        self.assertTrue(body["path"].endswith("health_test.db"))
        self.assertGreater(body["size_bytes"], 0)
        for table in (
            "electrical_readings",
            "monitoring_events",
            "settings",
            "diagnostic_episodes",
            "simulation_sessions",
        ):
            self.assertIn(table, body["tables"])
        self.assertEqual(body["user_version"], 2)
        self.assertIn("journal_mode", body)

    def test_system_errors_shape(self):
        status, body = _request(BASE_A, "GET", "/api/v1/system/errors")
        self.assertEqual(status, 200)
        self.assertIn("errors", body)
        self.assertIsInstance(body["errors"], list)

    def test_writes_open_without_api_key(self):
        status, body = _request(BASE_A, "POST", "/api/simulation/mode/normal")
        self.assertEqual(status, 200)
        self.assertEqual(body["mode"], "normal")


class ApiKeyProtectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmpdir.name, "apikey_test.db")
        cls.server = _spawn(8142, cls.db_path, {"NEXUS_API_KEY": "testkey123"})

    @classmethod
    def tearDownClass(cls):
        _stop(cls.server, cls.tmpdir)

    def _key(self):
        return {"X-API-Key": "testkey123"}

    def test_legacy_simulation_post_requires_key(self):
        status, _ = _request(BASE_B, "POST", "/api/simulation/mode/normal")
        self.assertEqual(status, 401)

        status, body = _request(
            BASE_B, "POST", "/api/simulation/mode/normal", headers=self._key()
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["mode"], "normal")

    def test_wrong_key_is_rejected(self):
        status, _ = _request(
            BASE_B, "POST", "/api/simulation/mode/normal",
            headers={"X-API-Key": "wrong"},
        )
        self.assertEqual(status, 401)

    def test_settings_put_requires_key(self):
        path = "/api/v1/settings/simulation.default_intensity"
        status, _ = _request(BASE_B, "PUT", path, {"value": 150})
        self.assertEqual(status, 401)

        status, body = _request(
            BASE_B, "PUT", path, {"value": 150}, headers=self._key()
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["value"], 150)

        # Restore the default so no state leaks.
        _request(BASE_B, "PUT", path, {"value": 100}, headers=self._key())

    def test_event_patch_requires_key(self):
        status, _ = _request(BASE_B, "PATCH", "/api/v1/events/1",
                             {"action": "resolve"})
        self.assertEqual(status, 401)

    def test_reads_stay_public(self):
        for path in ("/api/v1/settings", "/api/v1/stats/summary",
                     "/api/v1/events", "/api/health"):
            status, _ = _request(BASE_B, "GET", path)
            self.assertEqual(status, 200, path)


if __name__ == "__main__":
    unittest.main()

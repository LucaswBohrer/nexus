"""Integration tests for the `/api/health` endpoint.

Spins up a real uvicorn server (subprocess) against a temporary SQLite database
and asserts the HTTP contract with stdlib urllib:

  - healthy database -> 200 with status/service/database fields;
  - unreachable database -> 503 (so orchestrators stop routing traffic
    instead of seeing a false "healthy").

The 503 case is simulated by overwriting the live database file with garbage
bytes: every health check opens a fresh connection, so the next probe fails
deterministically with "file is not a database".

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
BASE_URL = "http://127.0.0.1:8132"


def _http_get(path: str):
    """Return (status_code, parsed_json_or_None)."""
    try:
        with urllib.request.urlopen(BASE_URL + path, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, None


class HealthCheckTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmpdir.name, "health_test.db")

        env = dict(os.environ, NEXUS_DATABASE_URL=cls.db_path)
        venv_python = os.path.join(BACKEND_DIR, ".venv", "bin", "python")
        cls.server = subprocess.Popen(
            [venv_python, "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", "8132"],
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

    def test_health_ok(self):
        status, body = _http_get("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "healthy")
        self.assertEqual(body["service"], "nexus-api")
        self.assertEqual(body["database"], "ok")

    def test_health_unreachable_db_returns_503(self):
        # Corrupt the live database file: the next probe must fail.
        with open(self.db_path, "wb") as f:
            f.write(b"this is not a sqlite database")

        status = None
        deadline = time.time() + 10
        while time.time() < deadline:
            status, _ = _http_get("/api/health")
            if status == 503:
                break
            time.sleep(0.2)
        self.assertEqual(status, 503)


if __name__ == "__main__":
    unittest.main()

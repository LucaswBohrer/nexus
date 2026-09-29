"""Regression tests for corrupt-database recovery at startup.

Before the fix, a corrupt `nexus.db` made `init_database()` raise
`sqlite3.DatabaseError: file is not a database` out of the lifespan handler,
so uvicorn logged "Application startup failed. Exiting." and the whole
monitoring system stayed down until manual intervention.

Now `init_database()` quarantines a *definitively* corrupt file
(`DatabaseError` that is not `OperationalError`) under a timestamped
`*.corrupt-*.db` name and boots fresh — while environmental failures
(permissions, missing directory, disk full) still fail fast without touching
user data.

Run:  python -m unittest discover -s tests -v   (from backend/)
"""
import glob
import json
import os
import sqlite3
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_URL = "http://127.0.0.1:8133"
GARBAGE = b"this is not a sqlite database \x00\x01\x02"


def _http_get(path: str):
    """Return (status_code, parsed_json_or_None)."""
    try:
        with urllib.request.urlopen(BASE_URL + path, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, None


def _spawn_server(db_path: str):
    env = dict(os.environ, NEXUS_DATABASE_URL=db_path)
    venv_python = os.path.join(BACKEND_DIR, ".venv", "bin", "python")
    return subprocess.Popen(
        [venv_python, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", "8133"],
        cwd=BACKEND_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_ready(deadline_s: float) -> bool:
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        try:
            status, _ = _http_get("/api/monitoring/current")
            if status == 200:
                return True
        except OSError:
            pass
        time.sleep(0.3)
    return False


class CorruptDatabaseRecoveryTest(unittest.TestCase):
    def _stop(self, server):
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()

    def test_corrupt_db_is_quarantined_and_server_boots(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        db_path = os.path.join(tmpdir.name, "nexus.db")
        with open(db_path, "wb") as f:
            f.write(GARBAGE)

        server = _spawn_server(db_path)
        self.addCleanup(self._stop, server)

        # Before the fix the server never became ready (startup crashed).
        self.assertTrue(_wait_ready(25), "server did not boot with corrupt DB")

        # Original bytes preserved under a timestamped quarantine name...
        quarantined = glob.glob(os.path.join(tmpdir.name, "nexus.corrupt-*.db"))
        self.assertEqual(len(quarantined), 1)
        with open(quarantined[0], "rb") as f:
            self.assertEqual(f.read(), GARBAGE)

        # ...and the live path is a fresh, healthy database.
        status, body = _http_get("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["database"], "ok")
        conn = sqlite3.connect(db_path)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        self.assertIn("electrical_readings", tables)
        self.assertIn("monitoring_events", tables)

    def test_healthy_db_is_never_quarantined(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        db_path = os.path.join(tmpdir.name, "nexus.db")
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
            "INSERT INTO electrical_readings (timestamp, voltage, current, frequency,"
            " power_factor, active_power, temperature, status)"
            " VALUES ('2026-09-29T17:00:00', 999.0, 12.0, 60.0, 0.93, 2.45, 45.0, 'normal')"
        )
        conn.commit()
        conn.close()

        server = _spawn_server(db_path)
        self.addCleanup(self._stop, server)
        self.assertTrue(_wait_ready(25), "server did not boot with healthy DB")

        # No quarantine files created...
        self.assertEqual(
            glob.glob(os.path.join(tmpdir.name, "*.corrupt-*.db")), [])

        # ...and the sentinel row survived.
        status, body = _http_get("/api/monitoring/history?limit=1000")
        self.assertEqual(status, 200)
        self.assertTrue(
            any(r["voltage"] == 999.0 for r in body["readings"]),
            "sentinel row missing after boot")

    def test_unopenable_db_still_fails_fast_without_quarantine(self):
        # OperationalError (missing directory) is environmental: the server
        # must keep failing fast and must NOT rename anything.
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        db_path = os.path.join(tmpdir.name, "no-such-dir", "nexus.db")

        server = _spawn_server(db_path)
        self.addCleanup(self._stop, server)

        self.assertFalse(
            _wait_ready(8),
            "server should NOT boot when the database cannot be opened")
        self.assertEqual(
            glob.glob(os.path.join(tmpdir.name, "**", "*.corrupt-*.db"),
                      recursive=True), [])


if __name__ == "__main__":
    unittest.main()

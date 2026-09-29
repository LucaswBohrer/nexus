"""Tests for the NEXUS 2.2 SSE readings stream.

Live-server tests against GET /api/v1/stream/readings:

  - the response is text/event-stream with no-cache headers;
  - >=3 data events arrive within ~6 s, each parsing as JSON with the
    expected keys (reading.*, diagnosis_status, severity, server_ts);
  - a `: heartbeat` comment arrives within ~25 s (15 s interval);
  - closing the client does not kill the server (health still 200).

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
BASE_URL = "http://127.0.0.1:8147"


def _http_get(path: str):
    try:
        with urllib.request.urlopen(BASE_URL + path, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, None


class SSEStreamTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmpdir.name, "sse_test.db")
        env = dict(os.environ, NEXUS_DATABASE_URL=cls.db_path)
        venv_python = os.path.join(BACKEND_DIR, ".venv", "bin", "python")
        cls.server = subprocess.Popen(
            [venv_python, "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", "8147"],
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

    def _open_stream(self):
        req = urllib.request.Request(
            BASE_URL + "/api/v1/stream/readings",
            headers={"Accept": "text/event-stream"},
        )
        return urllib.request.urlopen(req, timeout=30)

    def _read_sse(self, resp, want_data=3, want_heartbeat=True,
                  timeout_s=25):
        """Read lines until enough data events (and a heartbeat) arrive."""
        data_events = []
        heartbeat_seen = False
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            line = resp.readline().decode("utf-8", errors="replace")
            if not line:
                break  # stream closed
            line = line.rstrip("\n")
            if line.startswith("data:"):
                data_events.append(json.loads(line[len("data:"):].strip()))
            elif line.startswith(":"):
                if "heartbeat" in line:
                    heartbeat_seen = True
            if len(data_events) >= want_data and (
                heartbeat_seen or not want_heartbeat
            ):
                break
        return data_events, heartbeat_seen

    def test_stream_headers(self):
        resp = self._open_stream()
        try:
            content_type = resp.headers.get("Content-Type", "")
            self.assertIn("text/event-stream", content_type)
            self.assertEqual(
                resp.headers.get("Cache-Control"), "no-cache"
            )
            self.assertEqual(
                resp.headers.get("X-Accel-Buffering"), "no"
            )
        finally:
            resp.close()

    def test_data_events_parse(self):
        resp = self._open_stream()
        try:
            events, _ = self._read_sse(
                resp, want_data=3, want_heartbeat=False, timeout_s=10
            )
        finally:
            resp.close()
        self.assertGreaterEqual(len(events), 3)
        for event in events:
            self.assertIn("reading", event)
            self.assertIn("diagnosis_status", event)
            self.assertIn("severity", event)
            self.assertIn("server_ts", event)
            reading = event["reading"]
            for key in (
                "voltage", "current", "frequency", "power_factor",
                "active_power", "temperature", "timestamp",
            ):
                self.assertIn(key, reading)
            self.assertIn(event["diagnosis_status"],
                          ("normal", "warning", "critical"))
            self.assertIn(event["severity"], ("info", "warning", "critical"))

    def test_heartbeat_comment(self):
        resp = self._open_stream()
        try:
            _, heartbeat_seen = self._read_sse(
                resp, want_data=1, want_heartbeat=True, timeout_s=25
            )
        finally:
            resp.close()
        self.assertTrue(heartbeat_seen, "no : heartbeat comment within 25 s")

    def test_client_disconnect_does_not_kill_server(self):
        resp = self._open_stream()
        try:
            events, _ = self._read_sse(
                resp, want_data=1, want_heartbeat=False, timeout_s=10
            )
            self.assertGreaterEqual(len(events), 1)
        finally:
            resp.close()  # abrupt client disconnect
        time.sleep(2)  # let the server notice the disconnect
        status, body = _http_get("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "healthy")


if __name__ == "__main__":
    unittest.main()

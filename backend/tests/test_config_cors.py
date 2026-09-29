"""Tests for backend configuration and CORS behavior.

  - Settings defaults and NEXUS_* environment overrides are asserted by
    reloading app.config under a patched environment (no server needed).
  - The CORS allowlist is asserted against a live uvicorn server started
    with a LAN-style origin configured: a matching Origin is echoed back,
    a non-listed Origin gets no CORS headers (never a wildcard).

Run:  python -m unittest discover -s tests -v   (from backend/)
"""
import importlib
import json
import os
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_URL = "http://127.0.0.1:8135"

LAN_ORIGIN = "http://192.168.99.99:8135"
EVIL_ORIGIN = "http://evil.example"


def _http_get_with_origin(path: str, origin: str):
    """Return (status_code, response_headers)."""
    req = urllib.request.Request(BASE_URL + path, headers={"Origin": origin})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.headers
    except urllib.error.HTTPError as e:
        return e.code, e.headers


class SettingsTest(unittest.TestCase):
    def _reload_settings(self, env_overrides):
        old_env = dict(os.environ)
        try:
            for key in [k for k in os.environ if k.startswith("NEXUS_")]:
                del os.environ[key]
            os.environ.update(env_overrides)
            import app.config
            importlib.reload(app.config)
            return app.config.settings
        finally:
            os.environ.clear()
            os.environ.update(old_env)
            import app.config
            importlib.reload(app.config)

    def test_defaults(self):
        settings = self._reload_settings({})
        self.assertEqual(settings.host, "127.0.0.1")
        self.assertEqual(settings.port, 8000)
        self.assertEqual(settings.database_url, "nexus.db")
        self.assertEqual(
            settings.cors_origins_list, ["http://localhost:3000"])

    def test_env_overrides(self):
        settings = self._reload_settings({
            "NEXUS_HOST": "0.0.0.0",
            "NEXUS_PORT": "9000",
            "NEXUS_CORS_ORIGINS":
                "http://localhost:3000, http://192.168.1.42:3000",
            "NEXUS_DATABASE_URL": "/tmp/custom.db",
        })
        self.assertEqual(settings.host, "0.0.0.0")
        self.assertEqual(settings.port, 9000)
        self.assertEqual(settings.database_url, "/tmp/custom.db")
        # Whitespace around entries is stripped.
        self.assertEqual(
            settings.cors_origins_list,
            ["http://localhost:3000", "http://192.168.1.42:3000"])


class CorsAllowlistTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        db_path = os.path.join(cls.tmpdir.name, "cors_test.db")

        env = dict(
            os.environ,
            NEXUS_DATABASE_URL=db_path,
            NEXUS_CORS_ORIGINS=f"http://localhost:8135,{LAN_ORIGIN}",
        )
        venv_python = os.path.join(BACKEND_DIR, ".venv", "bin", "python")
        cls.server = subprocess.Popen(
            [venv_python, "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", "8135"],
            cwd=BACKEND_DIR,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        deadline = time.time() + 25
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                        BASE_URL + "/api/health", timeout=15) as resp:
                    if resp.status == 200:
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

    def test_listed_lan_origin_is_allowed(self):
        status, headers = _http_get_with_origin("/api/health", LAN_ORIGIN)
        self.assertEqual(status, 200)
        self.assertEqual(
            headers.get("Access-Control-Allow-Origin"), LAN_ORIGIN)

    def test_unlisted_origin_gets_no_cors_headers(self):
        status, headers = _http_get_with_origin("/api/health", EVIL_ORIGIN)
        self.assertEqual(status, 200)
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))

    def test_no_wildcard_origin(self):
        # The allowlist must be explicit: "*" is never an acceptable
        # production answer for credentialed CORS.
        for origin in (f"http://localhost:8135", LAN_ORIGIN):
            _, headers = _http_get_with_origin("/api/health", origin)
            self.assertNotEqual(
                headers.get("Access-Control-Allow-Origin"), "*")


if __name__ == "__main__":
    unittest.main()

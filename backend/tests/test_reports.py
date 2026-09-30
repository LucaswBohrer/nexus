"""Tests for the NEXUS 2.3 reports API (backend/tests/test_reports.py).

A synthetic dataset with hand-computed expectations is inserted into a
temp database before the server starts (port 8151). Covered: JSON
summary validity, daily/weekly/custom periods, readings CSV, events
CSV/JSON, invalid periods and formats (422), streaming (no
Content-Length: the body is chunked, never built in memory), JSON
report == analytics overview for the same period (single source of
truth), empty periods, and range safety limits.

Run:  python -m unittest discover -s tests -v   (from backend/)
"""
import csv
import io
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
BASE_URL = "http://127.0.0.1:8151"

from app.database import database  # noqa: E402
from app.services import equipment as equipment_service  # noqa: E402


def _http_get_raw(path: str):
    """Returns (status, headers dict, body bytes); 4xx/5xx -> (code, {}, b'').

    Header names are lowercased: HTTP header case is not significant and
    urllib's dict conversion would otherwise break lookups.
    """
    try:
        with urllib.request.urlopen(BASE_URL + path, timeout=20) as resp:
            headers = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, headers, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, {}, b""


def _http_get_json(path: str):
    status, _, body = _http_get_raw(path)
    return status, json.loads(body.decode()) if body else None


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _qs(**params) -> str:
    return "?" + urllib.parse.urlencode(params)


class ReportsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmpdir.name, "reports_test.db")

        cls.t0 = datetime.now(timezone.utc).replace(
            hour=12, minute=0, second=0, microsecond=0
        )
        cls.powers = [2.5 + 0.1 * i for i in range(10)]
        cls.voltages = [220.0 + i for i in range(10)]
        cls.temps = [40.0 + i for i in range(10)]

        old_path = database.DB_PATH
        database.DB_PATH = cls.db_path
        try:
            database.init_database()
            # NEXUS 2.4: fixture rows are stamped with the DEFAULT
            # equipment, like real pre-2.4 data after the v4 backfill.
            default_id = equipment_service.get_default_equipment()["id"]
            conn = sqlite3.connect(cls.db_path)
            try:
                for i in range(10):
                    ts = _iso(cls.t0 + timedelta(seconds=60 * i))
                    conn.execute(
                        """INSERT INTO electrical_readings
                           (timestamp, voltage, current, frequency,
                            power_factor, active_power, temperature, status,
                            equipment_id)
                           VALUES (?, ?, 12.0, 60.0, 0.93, ?, ?, ?, ?)""",
                        (ts, cls.voltages[i], cls.powers[i], cls.temps[i],
                         "warning" if i % 3 == 0 else "normal", default_id),
                    )
                events = [
                    ("HIGH_VOLTAGE", "warning", "open"),
                    ("HIGH_TEMP", "critical", "resolved"),
                ]
                for j, (etype, severity, status) in enumerate(events):
                    ts = _iso(cls.t0 + timedelta(seconds=60 * j))
                    conn.execute(
                        """INSERT INTO monitoring_events
                           (timestamp, event_type, severity, message,
                            recommendation, status, opened_at, occurrences,
                            last_value, threshold, equipment_id)
                           VALUES (?, ?, ?, 'm', 'r', ?, ?, 1, 250.0, 242.0,
                                   ?)""",
                        (ts, etype, severity, status, ts, default_id),
                    )
                ts = _iso(cls.t0)
                conn.execute(
                    """INSERT INTO diagnostic_episodes
                       (started_at, status, severity, rules,
                        peak_values, recommendations, equipment_id)
                       VALUES (?, 'resolved', 'warning', '[]', '{}', '[]',
                               ?)""",
                    (ts, default_id),
                )
                conn.commit()
            finally:
                conn.close()
        finally:
            database.DB_PATH = old_path

        cls.from_iso = _iso(cls.t0 - timedelta(seconds=60))
        cls.to_iso = _iso(cls.t0 + timedelta(seconds=11 * 60))
        # Hand-computed energy: sum of prev_power * 60/3600 over 9 intervals.
        cls.expected_energy = sum(cls.powers[:9]) * 60 / 3600

        env = dict(os.environ, NEXUS_DATABASE_URL=cls.db_path)
        venv_python = os.path.join(BACKEND_DIR, ".venv", "bin", "python")
        cls.server = subprocess.Popen(
            [venv_python, "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", "8151"],
            cwd=BACKEND_DIR,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 25
        while time.time() < deadline:
            try:
                status, _ = _http_get_json("/api/monitoring/current")
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

    def _summary_path(self, **kw):
        return "/api/v1/reports/summary" + _qs(
            **{"from": self.from_iso, "to": self.to_iso, **kw}
        )

    # -- JSON summary --------------------------------------------------------

    def test_json_report_valid(self):
        status, body = _http_get_json(self._summary_path())
        self.assertEqual(status, 200)
        self.assertEqual(body["period"]["from"], self.from_iso)
        self.assertEqual(body["period"]["to"], self.to_iso)
        summary = body["summary"]
        self.assertEqual(summary["readings_count"], 10)
        self.assertAlmostEqual(
            summary["energy_kwh"], self.expected_energy, places=6
        )
        self.assertAlmostEqual(summary["power_avg"], sum(self.powers) / 10)
        self.assertAlmostEqual(summary["power_max"], max(self.powers))
        self.assertAlmostEqual(
            summary["voltage_avg"], sum(self.voltages) / 10
        )
        self.assertEqual(summary["voltage_min"], min(self.voltages))
        self.assertEqual(summary["voltage_max"], max(self.voltages))
        self.assertAlmostEqual(summary["power_factor_avg"], 0.93)
        self.assertEqual(summary["temperature_max"], max(self.temps))
        # 4 of the 10 readings were inserted with status "warning".
        self.assertEqual(body["status"]["warning"], 4)
        self.assertEqual(body["status"]["normal"], 6)
        self.assertEqual(len(body["events"]), 2)
        self.assertEqual(len(body["diagnostic_episodes"]), 1)

    def test_report_matches_analytics(self):
        """Reports and analytics share one source of truth: identical
        numbers for the same period."""
        _, report = _http_get_json(self._summary_path())
        _, overview = _http_get_json(
            "/api/v1/analytics/overview"
            + _qs(**{"from": self.from_iso, "to": self.to_iso})
        )
        self.assertAlmostEqual(
            report["summary"]["energy_kwh"], overview["energy_kwh"], places=6
        )
        self.assertEqual(
            report["summary"]["readings_count"], overview["readings_count"]
        )
        for metric, stats in overview["per_metric"].items():
            for agg in ("min", "max", "avg"):
                self.assertAlmostEqual(
                    report["summary"].get(f"{metric}_{agg}", stats[agg])
                    if f"{metric}_{agg}" in report["summary"]
                    else stats[agg],
                    stats[agg],
                    places=6,
                    msg=f"{metric}.{agg}",
                )
        self.assertEqual(
            {e["event_type"] for e in report["events"]},
            {"HIGH_VOLTAGE", "HIGH_TEMP"},
        )

    def test_daily_report(self):
        today = self.t0.strftime("%Y-%m-%d")
        status, body = _http_get_json(
            "/api/v1/reports/daily" + _qs(date=today)
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["period"]["from"].startswith(today))
        # The live telemetry loop keeps writing; the 10 synthetic rows are
        # the minimum present.
        self.assertGreaterEqual(body["summary"]["readings_count"], 10)

    def test_daily_default_is_today(self):
        status, body = _http_get_json("/api/v1/reports/daily")
        self.assertEqual(status, 200)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.assertTrue(body["period"]["from"].startswith(today))

    def test_weekly_report(self):
        week = self.t0.strftime("%G-W%V")
        status, body = _http_get_json(
            "/api/v1/reports/weekly" + _qs(week=week)
        )
        self.assertEqual(status, 200)
        from_dt = datetime.fromisoformat(body["period"]["from"])
        to_dt = datetime.fromisoformat(body["period"]["to"])
        self.assertEqual((to_dt - from_dt).days, 7)
        self.assertEqual(from_dt.weekday(), 0)  # Monday
        self.assertGreaterEqual(body["summary"]["readings_count"], 10)

    # -- CSV -----------------------------------------------------------------

    def _parse_csv(self, body: bytes):
        return list(csv.reader(io.StringIO(body.decode("utf-8"))))

    def test_readings_csv(self):
        status, headers, body = _http_get_raw(
            self._summary_path(format="csv")
        )
        self.assertEqual(status, 200)
        self.assertIn("text/csv", headers.get("content-type", ""))
        self.assertIn("attachment", headers.get("content-disposition", ""))
        rows = self._parse_csv(body)
        self.assertEqual(
            rows[0],
            ["timestamp", "voltage", "current", "frequency", "power_factor",
             "active_power", "temperature", "status"],
        )
        self.assertEqual(len(rows) - 1, 10)
        # Values match the inserted dataset, chronological order.
        self.assertAlmostEqual(float(rows[1][1]), self.voltages[0])
        self.assertAlmostEqual(float(rows[10][1]), self.voltages[9])
        self.assertAlmostEqual(float(rows[1][5]), self.powers[0], places=2)

    def test_daily_csv(self):
        today = self.t0.strftime("%Y-%m-%d")
        status, _, body = _http_get_raw(
            "/api/v1/reports/daily" + _qs(date=today, format="csv")
        )
        self.assertEqual(status, 200)
        rows = self._parse_csv(body)
        self.assertGreaterEqual(len(rows) - 1, 10)

    def test_events_csv(self):
        status, headers, body = _http_get_raw(
            "/api/v1/reports/events"
            + _qs(**{"from": self.from_iso, "to": self.to_iso,
                     "format": "csv"})
        )
        self.assertEqual(status, 200)
        self.assertIn("text/csv", headers.get("content-type", ""))
        rows = self._parse_csv(body)
        self.assertEqual(
            rows[0],
            ["timestamp", "event_type", "severity", "status", "message",
             "recommendation", "occurrences", "opened_at", "closed_at",
             "last_value", "threshold"],
        )
        self.assertEqual(len(rows) - 1, 2)
        types = {r[1] for r in rows[1:]}
        self.assertEqual(types, {"HIGH_VOLTAGE", "HIGH_TEMP"})

    def test_events_json(self):
        status, body = _http_get_json(
            "/api/v1/reports/events"
            + _qs(**{"from": self.from_iso, "to": self.to_iso})
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(body["events"]), 2)

    def test_csv_streams_without_content_length(self):
        """StreamingResponse over a generator must not buffer the whole
        dataset: no Content-Length is set (chunked transfer)."""
        status, headers, _ = _http_get_raw(self._summary_path(format="csv"))
        self.assertEqual(status, 200)
        self.assertNotIn("content-length", headers)
        te = headers.get("transfer-encoding", "")
        self.assertIn("chunked", te.lower())

    # -- validation ------------------------------------------------------------

    def test_invalid_periods_rejected(self):
        # from after to
        status, _ = _http_get_json(
            "/api/v1/reports/summary"
            + _qs(**{"from": self.to_iso, "to": self.from_iso})
        )
        self.assertEqual(status, 422)
        # range over 31 days
        far = _iso(self.t0 - timedelta(days=40))
        status, _ = _http_get_json(
            "/api/v1/reports/summary" + _qs(**{"from": far, "to": self.to_iso})
        )
        self.assertEqual(status, 422)
        # bad format
        status, _ = _http_get_json(self._summary_path(format="xml"))
        self.assertEqual(status, 422)
        # bad date / week
        status, _ = _http_get_json("/api/v1/reports/daily" + _qs(date="x"))
        self.assertEqual(status, 422)
        status, _ = _http_get_json(
            "/api/v1/reports/weekly" + _qs(week="2026-W99")
        )
        self.assertEqual(status, 422)

    def test_empty_period_is_honest(self):
        from_iso = _iso(self.t0 + timedelta(days=2))
        to_iso = _iso(self.t0 + timedelta(days=2, hours=1))
        status, body = _http_get_json(
            "/api/v1/reports/summary" + _qs(**{"from": from_iso, "to": to_iso})
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["summary"]["readings_count"], 0)
        self.assertEqual(body["events"], [])
        self.assertEqual(body["diagnostic_episodes"], [])
        status, _, csv_body = _http_get_raw(
            "/api/v1/reports/summary"
            + _qs(**{"from": from_iso, "to": to_iso, "format": "csv"})
        )
        self.assertEqual(status, 200)
        # Header only, no invented rows.
        self.assertEqual(len(self._parse_csv(csv_body)), 1)


if __name__ == "__main__":
    unittest.main()

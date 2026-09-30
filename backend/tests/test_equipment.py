"""Tests for the NEXUS 2.4 equipment registry (multi-equipment backend).

Covers, in order of the 2.4 backend phases:
  - migration v4: empty DB, a 2.3-era DB with data (backfill to DEFAULT),
    already-migrated DB, and repeated runs (idempotency);
  - the equipment service: CRUD, validation, soft-delete/deactivation,
    physical-delete guards, resolve_equipment_id semantics;
  - the Equipment API: the six endpoints + summary, status codes
    (200/404/409/422) and real-data-only summaries;
  - per-equipment isolation: telemetry reads, events (dedup, aging,
    listing), episodes, analytics, history, extremes, stats, reports
    (JSON + streaming CSV) and the simulation lifecycle;
  - SSE scoped by ?equipment_id= (only that equipment's data events).

HTTP tests run against a live uvicorn server on port 8155 with a temp
database; in-process tests use temp databases directly. Ports 3000,
8000, 8100 and the 813x-8154 test ports are never touched.

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
from urllib.parse import quote

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)
BASE_URL = "http://127.0.0.1:8155"

from app.database import database  # noqa: E402
from app.database import migrations  # noqa: E402
from app.services import equipment as equipment_service  # noqa: E402
from app.services.episodes import list_episodes, process_tick_episode  # noqa: E402
from app.services.events import list_events, process_tick_events  # noqa: E402


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

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


def _http_write(method: str, path: str, payload=None):
    data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(
        BASE_URL + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
        except Exception:
            body = None
        return e.code, body


def _wait_for(predicate, timeout_s: float, interval: float = 0.25):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _make_event(event_type, severity="warning", message="m"):
    return {
        "event_type": event_type,
        "severity": severity,
        "message": message,
        "recommendation": "r",
        "value": 250.0,
        "threshold": 242.0,
    }


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _qp(value: str) -> str:
    """URL-quote a query-param value (ISO-8601 offsets contain '+')."""
    return quote(value, safe="")


# ---------------------------------------------------------------------------
# Migration v4
# ---------------------------------------------------------------------------

class EquipmentMigrationTest(unittest.TestCase):
    """The four migration scenarios: empty DB, 2.3 DB with data,
    already-migrated DB, repeated runs."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "mig24_test.db")
        self._old_db_path = database.DB_PATH
        database.DB_PATH = self.db_path

    def tearDown(self):
        database.DB_PATH = self._old_db_path
        self.tmpdir.cleanup()

    def _make_v3_database(self):
        """A NEXUS 2.3-era database: v3 schema with data in all four
        scoped tables, no equipment table, user_version = 3."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE electrical_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                voltage REAL NOT NULL,
                current REAL NOT NULL,
                frequency REAL NOT NULL,
                power_factor REAL NOT NULL,
                active_power REAL NOT NULL,
                temperature REAL NOT NULL,
                status TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE monitoring_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                recommendation TEXT NOT NULL
            )
        """)
        for version in (1, 2, 3):
            migrations._MIGRATIONS[version](conn)
        conn.execute("PRAGMA user_version = 3")

        t0 = datetime.now(timezone.utc) - timedelta(hours=1)
        for i in range(5):
            ts = _iso(t0 + timedelta(seconds=60 * i))
            conn.execute(
                """INSERT INTO electrical_readings
                   (timestamp, voltage, current, frequency, power_factor,
                    active_power, temperature, status)
                   VALUES (?, 220.0, 12.0, 60.0, 0.93, 2.5, 42.0, 'normal')""",
                (ts,),
            )
        ts = _iso(t0)
        # A 2.3-style open event row (equipment_id NULL: the column
        # existed since v1 but nothing wrote it).
        conn.execute(
            """INSERT INTO monitoring_events
               (timestamp, event_type, severity, message, recommendation,
                status, opened_at, last_seen, occurrences, equipment_id)
               VALUES (?, 'HIGH_VOLTAGE', 'warning', 'm', 'r',
                       'open', ?, ?, 3, NULL)""",
            (ts, ts, ts),
        )
        conn.execute(
            """INSERT INTO diagnostic_episodes
               (started_at, status, severity, rules, peak_values,
                recommendations, normal_streak)
               VALUES (?, 'open', 'warning', '[]', '{}', '[]', 0)""",
            (ts,),
        )
        conn.execute(
            """INSERT INTO simulation_sessions
               (mode, parameters, started_at)
               VALUES ('overload', '{}', ?)""",
            (ts,),
        )
        conn.commit()
        conn.close()

    def _default_id(self) -> int:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT id FROM equipment WHERE code = 'DEFAULT'"
        ).fetchone()
        conn.close()
        return row[0]

    def test_empty_database_migrates_to_v4_with_default(self):
        database.init_database()

        conn = sqlite3.connect(self.db_path)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        indexes = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
        conn.row_factory = sqlite3.Row
        default = conn.execute(
            "SELECT * FROM equipment WHERE code = 'DEFAULT'"
        ).fetchone()
        for table in (
            "electrical_readings",
            "monitoring_events",
            "diagnostic_episodes",
            "simulation_sessions",
        ):
            cols = {
                r[1] for r in conn.execute(f"PRAGMA table_info({table})")
            }
            self.assertIn("equipment_id", cols, table)
        conn.close()

        self.assertEqual(version, 4)
        self.assertIn("equipment", tables)
        self.assertIsNotNone(default)
        self.assertEqual(default["name"], "Main Electrical System")
        self.assertEqual(default["status"], "active")
        self.assertEqual(default["enabled"], 1)
        for index in (
            "idx_readings_equipment_ts",
            "idx_events_equipment",
            "idx_episodes_equipment",
            "idx_sessions_equipment",
        ):
            self.assertIn(index, indexes)

    def test_v3_database_data_preserved_and_backfilled(self):
        self._make_v3_database()
        database.init_database()

        conn = sqlite3.connect(self.db_path)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        default_id = self._default_id()
        readings = conn.execute(
            "SELECT COUNT(*), MIN(voltage) FROM electrical_readings"
        ).fetchone()
        nulls = 0
        for table in (
            "electrical_readings",
            "monitoring_events",
            "diagnostic_episodes",
            "simulation_sessions",
        ):
            nulls += conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE equipment_id IS NULL"
            ).fetchone()[0]
            wrong = conn.execute(
                f"SELECT COUNT(*) FROM {table}"
                " WHERE equipment_id != ?",
                (default_id,),
            ).fetchone()[0]
            self.assertEqual(wrong, 0, table)
        event_status = conn.execute(
            "SELECT status, occurrences FROM monitoring_events"
        ).fetchone()
        conn.close()

        self.assertEqual(version, 4)
        self.assertEqual(readings[0], 5)  # all rows preserved
        self.assertEqual(readings[1], 220.0)
        self.assertEqual(nulls, 0)  # every row backfilled to DEFAULT
        # The 2.3 open event keeps its lifecycle state.
        self.assertEqual(event_status[0], "open")
        self.assertEqual(event_status[1], 3)

    def test_migration_idempotent_on_already_migrated(self):
        database.init_database()
        first_default = self._default_id()
        database.init_database()  # second run must be a no-op
        database.init_database()  # and a third

        conn = sqlite3.connect(self.db_path)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        count = conn.execute(
            "SELECT COUNT(*) FROM equipment WHERE code = 'DEFAULT'"
        ).fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM equipment").fetchone()[0]
        conn.close()

        self.assertEqual(version, 4)
        self.assertEqual(count, 1)
        self.assertEqual(total, 1)
        self.assertEqual(self._default_id(), first_default)

    def test_migrate_v4_direct_rerun_is_safe(self):
        database.init_database()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        migrations._migrate_v4(conn)  # direct re-run must not raise
        migrations._migrate_v4(conn)
        count = conn.execute(
            "SELECT COUNT(*) FROM equipment WHERE code = 'DEFAULT'"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)


# ---------------------------------------------------------------------------
# Equipment service (in-process)
# ---------------------------------------------------------------------------

class EquipmentServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "svc_test.db")
        self._old_db_path = database.DB_PATH
        database.DB_PATH = self.db_path
        database.init_database()
        self.default_id = equipment_service.get_default_equipment()["id"]

    def tearDown(self):
        database.DB_PATH = self._old_db_path
        self.tmpdir.cleanup()

    def test_create_and_get_equipment(self):
        created = equipment_service.create_equipment(
            name="Panel B",
            code="PANEL_B",
            description="Second panel",
            equipment_type="electrical_panel",
            location="Building 2",
            status="active",
        )
        self.assertEqual(created["code"], "PANEL_B")
        self.assertEqual(created["name"], "Panel B")
        self.assertEqual(created["location"], "Building 2")
        self.assertTrue(created["enabled"])
        self.assertIsNotNone(created["created_at"])

        fetched = equipment_service.get_equipment(created["id"])
        self.assertEqual(fetched, created)
        by_code = equipment_service.get_equipment_by_code("PANEL_B")
        self.assertEqual(by_code["id"], created["id"])

    def test_create_duplicate_code_rejected(self):
        equipment_service.create_equipment(name="A", code="DUP")
        with self.assertRaises(equipment_service.EquipmentError):
            equipment_service.create_equipment(name="B", code="DUP")

    def test_create_missing_name_rejected(self):
        with self.assertRaises(equipment_service.EquipmentError):
            equipment_service.create_equipment(name="  ", code="NONAME")

    def test_create_invalid_status_rejected(self):
        with self.assertRaises(equipment_service.EquipmentError):
            equipment_service.create_equipment(
                name="X", code="BADSTATUS", status="exploded"
            )

    def test_get_unknown_returns_none(self):
        self.assertIsNone(equipment_service.get_equipment(99999))
        self.assertIsNone(equipment_service.get_equipment_by_code("NOPE"))

    def test_update_equipment(self):
        created = equipment_service.create_equipment(
            name="Old", code="UPD", status="active"
        )
        updated = equipment_service.update_equipment(
            created["id"], name="New", status="maintenance", location="Lab"
        )
        self.assertEqual(updated["name"], "New")
        self.assertEqual(updated["status"], "maintenance")
        self.assertEqual(updated["location"], "Lab")
        self.assertEqual(updated["code"], "UPD")  # unchanged

    def test_update_unknown_raises_not_found(self):
        with self.assertRaises(equipment_service.EquipmentNotFound):
            equipment_service.update_equipment(99999, name="x")

    def test_update_duplicate_code_rejected(self):
        equipment_service.create_equipment(name="A", code="CODE_A")
        other = equipment_service.create_equipment(name="B", code="CODE_B")
        with self.assertRaises(equipment_service.EquipmentError):
            equipment_service.update_equipment(other["id"], code="CODE_A")

    def test_deactivate_and_reactivate(self):
        created = equipment_service.create_equipment(name="D", code="DEACT")
        deactivated = equipment_service.deactivate_equipment(created["id"])
        self.assertFalse(deactivated["enabled"])
        # Historical data stays readable; only writes are refused.
        reactivated = equipment_service.activate_equipment(created["id"])
        self.assertTrue(reactivated["enabled"])

    def test_delete_equipment_without_data(self):
        created = equipment_service.create_equipment(name="Tmp", code="TMP")
        equipment_service.delete_equipment(created["id"])
        self.assertIsNone(equipment_service.get_equipment(created["id"]))
        with self.assertRaises(equipment_service.EquipmentNotFound):
            equipment_service.delete_equipment(created["id"])

    def test_delete_default_refused(self):
        with self.assertRaises(equipment_service.EquipmentConflict):
            equipment_service.delete_equipment(self.default_id)

    def test_delete_equipment_with_data_refused(self):
        created = equipment_service.create_equipment(name="Data", code="DATA")
        reading = {
            "timestamp": datetime.now(timezone.utc),
            "voltage": 220.0,
            "current": 12.0,
            "frequency": 60.0,
            "power_factor": 0.93,
            "active_power": 2.5,
            "temperature": 42.0,
            "status": "normal",
            "equipment_id": created["id"],
        }
        database.save_reading(reading)
        with self.assertRaises(equipment_service.EquipmentConflict):
            equipment_service.delete_equipment(created["id"])
        # Still there, and deactivation (the preferred path) works.
        self.assertIsNotNone(equipment_service.get_equipment(created["id"]))
        self.assertFalse(
            equipment_service.deactivate_equipment(created["id"])["enabled"]
        )

    def test_resolve_none_returns_default(self):
        self.assertEqual(
            equipment_service.resolve_equipment_id(None), self.default_id
        )

    def test_resolve_unknown_raises_not_found(self):
        with self.assertRaises(equipment_service.EquipmentNotFound):
            equipment_service.resolve_equipment_id(99999)
        with self.assertRaises(equipment_service.EquipmentNotFound):
            equipment_service.resolve_equipment_id("UNKNOWN_CODE")

    def test_resolve_accepts_id_and_code(self):
        created = equipment_service.create_equipment(name="R", code="RESOLVE_ME")
        self.assertEqual(
            equipment_service.resolve_equipment_id(created["id"]),
            created["id"],
        )
        self.assertEqual(
            equipment_service.resolve_equipment_id("RESOLVE_ME"),
            created["id"],
        )
        self.assertEqual(
            equipment_service.resolve_equipment_id(str(created["id"])),
            created["id"],
        )

    def test_require_writable_equipment(self):
        created = equipment_service.create_equipment(name="W", code="WRITE_ME")
        self.assertEqual(
            equipment_service.require_writable_equipment("WRITE_ME"),
            created["id"],
        )
        equipment_service.deactivate_equipment(created["id"])
        with self.assertRaises(equipment_service.EquipmentConflict):
            equipment_service.require_writable_equipment(created["id"])
        with self.assertRaises(equipment_service.EquipmentNotFound):
            equipment_service.require_writable_equipment(99999)

    def test_list_equipment(self):
        equipment_service.create_equipment(name="L1", code="LIST_A")
        equipment_service.create_equipment(name="L2", code="LIST_B")
        items = equipment_service.list_equipment()
        codes = [item["code"] for item in items]
        self.assertEqual(codes[0], "DEFAULT")
        self.assertIn("LIST_A", codes)
        self.assertIn("LIST_B", codes)

# ---------------------------------------------------------------------------
# HTTP tests: Equipment API, isolation, simulation, SSE (port 8155)
# ---------------------------------------------------------------------------

class EquipmentHttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmpdir.name, "equipment_test.db")
        old_path = database.DB_PATH
        database.DB_PATH = cls.db_path
        try:
            database.init_database()
        finally:
            database.DB_PATH = old_path

        env = dict(os.environ, NEXUS_DATABASE_URL=cls.db_path)
        venv_python = os.path.join(BACKEND_DIR, ".venv", "bin", "python")
        cls.server = subprocess.Popen(
            [venv_python, "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", "8155"],
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

        status, body = _http_get("/api/v1/equipment")
        assert status == 200, body
        cls.default_id = next(
            item["id"] for item in body["equipment"]
            if item["code"] == "DEFAULT"
        )

    @classmethod
    def tearDownClass(cls):
        try:
            _http_write("POST", "/api/v1/simulation/stop")
        except OSError:
            pass
        cls.server.terminate()
        try:
            cls.server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.server.kill()
        cls.tmpdir.cleanup()

    def _use_server_db(self):
        database.DB_PATH = self.db_path

    # -- Equipment API --------------------------------------------------

    def test_list_contains_default(self):
        status, body = _http_get("/api/v1/equipment")
        self.assertEqual(status, 200)
        codes = [item["code"] for item in body["equipment"]]
        self.assertIn("DEFAULT", codes)
        default = next(
            item for item in body["equipment"] if item["code"] == "DEFAULT"
        )
        self.assertEqual(default["name"], "Main Electrical System")
        self.assertTrue(default["enabled"])

    def test_crud_flow(self):
        status, created = _http_write(
            "POST", "/api/v1/equipment",
            {"name": "CRUD Panel", "code": "CRUD_T1",
             "location": "Lab", "equipment_type": "electrical_panel"},
        )
        self.assertEqual(status, 200, created)
        eid = created["equipment"]["id"]
        self.assertEqual(created["equipment"]["code"], "CRUD_T1")

        status, body = _http_get(f"/api/v1/equipment/{eid}")
        self.assertEqual(status, 200)
        self.assertEqual(body["equipment"]["location"], "Lab")

        status, body = _http_write(
            "PATCH", f"/api/v1/equipment/{eid}",
            {"name": "CRUD Panel Renamed", "status": "maintenance"},
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["equipment"]["name"], "CRUD Panel Renamed")
        self.assertEqual(body["equipment"]["status"], "maintenance")

        status, body = _http_write("DELETE", f"/api/v1/equipment/{eid}")
        self.assertEqual(status, 200, body)
        self.assertTrue(body["deleted"])

        status, _ = _http_get(f"/api/v1/equipment/{eid}")
        self.assertEqual(status, 404)

    def test_create_validation_errors(self):
        # Duplicate code.
        status, _ = _http_write(
            "POST", "/api/v1/equipment",
            {"name": "Dup One", "code": "CRUD_DUP"},
        )
        self.assertEqual(status, 200)
        status, _ = _http_write(
            "POST", "/api/v1/equipment",
            {"name": "Dup Two", "code": "CRUD_DUP"},
        )
        self.assertEqual(status, 422)
        # Invalid status.
        status, _ = _http_write(
            "POST", "/api/v1/equipment",
            {"name": "Bad", "code": "CRUD_BAD", "status": "exploded"},
        )
        self.assertEqual(status, 422)
        # Missing name -> pydantic 422.
        status, _ = _http_write(
            "POST", "/api/v1/equipment", {"code": "CRUD_NONAME"}
        )
        self.assertEqual(status, 422)

    def test_unknown_equipment_404(self):
        status, _ = _http_get("/api/v1/equipment/99999")
        self.assertEqual(status, 404)
        status, _ = _http_get("/api/v1/equipment/99999/summary")
        self.assertEqual(status, 404)
        status, _ = _http_write(
            "PATCH", "/api/v1/equipment/99999", {"name": "x"}
        )
        self.assertEqual(status, 404)
        status, _ = _http_write("DELETE", "/api/v1/equipment/99999")
        self.assertEqual(status, 404)

    def test_delete_default_refused(self):
        status, body = _http_write(
            "DELETE", f"/api/v1/equipment/{self.default_id}"
        )
        self.assertEqual(status, 409, body)

    def test_unknown_equipment_id_query_param_404(self):
        from_iso = _iso(datetime.now(timezone.utc) - timedelta(hours=1))
        to_iso = _iso(datetime.now(timezone.utc))
        for path in (
            f"/api/v1/analytics/overview?from={_qp(from_iso)}&to={_qp(to_iso)}"
            "&equipment_id=99999",
            f"/api/v1/events?equipment_id=99999",
            "/api/v1/stream/readings?equipment_id=99999",
        ):
            try:
                with urllib.request.urlopen(
                    BASE_URL + path, timeout=15
                ) as resp:
                    got = resp.status
            except urllib.error.HTTPError as e:
                got = e.code
            self.assertEqual(got, 404, path)

    def test_summary_empty_equipment_is_honest(self):
        status, created = _http_write(
            "POST", "/api/v1/equipment",
            {"name": "Empty", "code": "ISO_SUM_B"},
        )
        self.assertEqual(status, 200, created)
        eid = created["equipment"]["id"]

        status, body = _http_get(f"/api/v1/equipment/{eid}/summary")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["equipment"]["code"], "ISO_SUM_B")
        self.assertIsNone(body["last_reading"])
        self.assertIsNone(body["last_reading_at"])
        self.assertIsNone(body["diagnosis"])
        self.assertEqual(body["active_events"], 0)
        self.assertEqual(body["open_episodes"], 0)
        self.assertEqual(body["readings_count"], 0)

    # -- Telemetry / analytics / reports isolation -----------------------

    def _seed_window_readings(self, code, default_n=6, other_n=6,
                              hours_ago=2):
        """Insert deterministic readings for DEFAULT and one new
        equipment inside a fixed past window. Returns (equipment_id,
        from_iso, to_iso, other_n)."""
        self._use_server_db()
        created = equipment_service.create_equipment(
            name="Window", code=code
        )
        eid = created["id"]
        t0 = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        for i in range(default_n):
            database.save_reading({
                "timestamp": t0 + timedelta(seconds=600 * i),
                "voltage": 220.0 + i,
                "current": 12.0,
                "frequency": 60.0,
                "power_factor": 0.93,
                "active_power": 2.5,
                "temperature": 42.0,
                "status": "normal",
                "equipment_id": self.default_id,
            })
        for i in range(other_n):
            database.save_reading({
                "timestamp": t0 + timedelta(seconds=600 * i),
                "voltage": 230.0 + i,
                "current": 15.0,
                "frequency": 60.0,
                "power_factor": 0.90,
                "active_power": 3.0,
                "temperature": 45.0,
                "status": "normal",
                "equipment_id": eid,
            })
        from_iso = _iso(t0 - timedelta(seconds=60))
        to_iso = _iso(t0 + timedelta(seconds=600 * other_n + 60))
        return eid, from_iso, to_iso, other_n

    def test_readings_and_analytics_isolation(self):
        eid, from_iso, to_iso, n = self._seed_window_readings("ISO_WIN_B")

        # Omitted equipment_id -> DEFAULT only.
        status, default_view = _http_get(
            f"/api/v1/analytics/overview?from={_qp(from_iso)}&to={_qp(to_iso)}"
        )
        self.assertEqual(status, 200, default_view)
        self.assertEqual(default_view["readings_count"], 6)
        self.assertEqual(
            default_view["per_metric"]["voltage"]["min"], 220.0
        )

        # equipment_id -> only that equipment's rows.
        status, other_view = _http_get(
            f"/api/v1/analytics/overview?from={_qp(from_iso)}&to={_qp(to_iso)}"
            f"&equipment_id={eid}"
        )
        self.assertEqual(status, 200, other_view)
        self.assertEqual(other_view["readings_count"], n)
        self.assertEqual(
            other_view["per_metric"]["voltage"]["min"], 230.0
        )

        # Code works as well as id.
        status, by_code = _http_get(
            f"/api/v1/analytics/overview?from={_qp(from_iso)}&to={_qp(to_iso)}"
            "&equipment_id=ISO_WIN_B"
        )
        self.assertEqual(status, 200, by_code)
        self.assertEqual(by_code["readings_count"], n)

    def test_history_and_extremes_isolation(self):
        eid, from_iso, to_iso, n = self._seed_window_readings(
            "ISO_HIST_B", hours_ago=4
        )

        status, body = _http_get(
            f"/api/v1/history/extremes?metric=voltage"
            f"&from={_qp(from_iso)}&to={_qp(to_iso)}&equipment_id={eid}"
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["count"], n)
        self.assertEqual(body["min"]["value"], 230.0)

        status, body = _http_get(
            f"/api/v1/history?metric=voltage&from={_qp(from_iso)}&to={_qp(to_iso)}"
            f"&bucket=1h&equipment_id={eid}"
        )
        self.assertEqual(status, 200, body)
        total = sum(bucket["count"] for bucket in body["buckets"])
        self.assertEqual(total, n)

        status, body = _http_get(
            f"/api/v1/stats/summary?equipment_id={eid}"
        )
        self.assertEqual(status, 200, body)
        # readings_count is all-time: exactly this equipment's fixtures,
        # the live loop only writes DEFAULT rows.
        self.assertEqual(body["readings_count"], n)
        self.assertEqual(body["current"]["equipment_id"], eid)

    def test_reports_match_analytics_per_equipment(self):
        eid, from_iso, to_iso, n = self._seed_window_readings(
            "ISO_REP_B", hours_ago=6
        )

        status, analytics = _http_get(
            f"/api/v1/analytics/overview?from={_qp(from_iso)}&to={_qp(to_iso)}"
            f"&equipment_id={eid}"
        )
        self.assertEqual(status, 200)
        status, report = _http_get(
            f"/api/v1/reports/summary?from={_qp(from_iso)}&to={_qp(to_iso)}"
            f"&format=json&equipment_id={eid}"
        )
        self.assertEqual(status, 200, report)
        self.assertEqual(
            report["summary"]["readings_count"],
            analytics["readings_count"],
        )
        self.assertEqual(report["summary"]["readings_count"], n)
        self.assertEqual(
            report["summary"]["energy_kwh"], analytics["energy_kwh"]
        )

        # Streaming CSV: exactly this equipment's rows in the window.
        req = urllib.request.Request(
            BASE_URL + f"/api/v1/reports/summary?from={_qp(from_iso)}"
            f"&to={_qp(to_iso)}&format=csv&equipment_id={eid}"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            self.assertEqual(resp.status, 200)
            text = resp.read().decode()
        lines = [ln for ln in text.strip().splitlines() if ln]
        self.assertEqual(len(lines) - 1, n)  # header + n data rows

    def test_events_isolation_and_scoped_aging(self):
        self._use_server_db()
        created = equipment_service.create_equipment(
            name="EvtB", code="ISO_EVT_B"
        )
        eid = created["id"]

        process_tick_events(
            [_make_event("ISO_EVT_A")], equipment_id=self.default_id
        )
        process_tick_events([_make_event("ISO_EVT_B")], equipment_id=eid)

        # Same condition type on two equipments -> two independent rows.
        status, body = _http_get("/api/v1/events?type=ISO_EVT_A")
        self.assertEqual(status, 200, body)
        self.assertEqual(len(body["events"]), 1)
        self.assertEqual(body["events"][0]["equipment_id"], self.default_id)

        status, body = _http_get(
            f"/api/v1/events?type=ISO_EVT_B&equipment_id={eid}"
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(len(body["events"]), 1)

        # Omitted equipment_id scopes to DEFAULT: B's event is invisible.
        status, body = _http_get("/api/v1/events?type=ISO_EVT_B")
        self.assertEqual(status, 200, body)
        self.assertEqual(len(body["events"]), 0)

        # Aging a DEFAULT tick must not touch B's event.
        for _ in range(6):
            process_tick_events([], equipment_id=self.default_id)
        status, body = _http_get("/api/v1/events?type=ISO_EVT_A")
        self.assertEqual(body["events"][0]["status"], "resolved")
        status, body = _http_get(
            f"/api/v1/events?type=ISO_EVT_B&equipment_id={eid}"
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["events"][0]["status"], "open")

        # Reports events endpoint is scoped too.
        from_iso = _iso(datetime.now(timezone.utc) - timedelta(minutes=10))
        to_iso = _iso(datetime.now(timezone.utc) + timedelta(minutes=10))
        status, body = _http_get(
            f"/api/v1/reports/events?from={_qp(from_iso)}&to={_qp(to_iso)}"
            f"&equipment_id={eid}"
        )
        self.assertEqual(status, 200, body)
        types = [event["event_type"] for event in body["events"]]
        self.assertIn("ISO_EVT_B", types)
        self.assertNotIn("ISO_EVT_A", types)

    def test_episodes_isolation(self):
        self._use_server_db()
        created = equipment_service.create_equipment(
            name="EpB", code="ISO_EP_B"
        )
        eid = created["id"]

        reading = {
            "timestamp": datetime.now(timezone.utc),
            "voltage": 250.0,
            "current": 12.0,
            "frequency": 60.0,
            "power_factor": 0.93,
            "active_power": 2.5,
            "temperature": 42.0,
            "status": "warning",
            "equipment_id": self.default_id,
        }
        diagnosis = {
            "status": "warning",
            "severity": "warning",
            "anomalies": ["high_voltage"],
            "recommendations": ["r"],
            "events": [],
        }
        process_tick_episode(
            diagnosis, reading, equipment_id=self.default_id
        )
        reading_b = dict(reading, equipment_id=eid)
        process_tick_episode(diagnosis, reading_b, equipment_id=eid)

        # Omitted -> DEFAULT scope only.
        status, body = _http_get("/api/v1/diagnostics/episodes?limit=50")
        self.assertEqual(status, 200, body)
        self.assertGreater(len(body["episodes"]), 0)
        for episode in body["episodes"]:
            self.assertEqual(episode["equipment_id"], self.default_id)

        status, body = _http_get(
            f"/api/v1/diagnostics/episodes?limit=50&equipment_id={eid}"
        )
        self.assertEqual(status, 200, body)
        self.assertGreater(len(body["episodes"]), 0)
        for episode in body["episodes"]:
            self.assertEqual(episode["equipment_id"], eid)

        # In-process listing agrees.
        self.assertTrue(
            all(
                ep["equipment_id"] == eid
                for ep in list_episodes(50, equipment_id=eid)
            )
        )

    # -- Simulation per equipment --------------------------------------

    def test_simulation_start_status_sessions_per_equipment(self):
        status, created = _http_write(
            "POST", "/api/v1/equipment",
            {"name": "SimB", "code": "ISO_SIM_B"},
        )
        self.assertEqual(status, 200, created)
        eid = created["equipment"]["id"]

        # Start attributed to equipment B (code accepted too).
        status, started = _http_write(
            "POST", "/api/v1/simulation/start",
            {"mode": "overload", "equipment_id": "ISO_SIM_B"},
        )
        self.assertEqual(status, 200, started)
        self.assertEqual(started["equipment_id"], eid)
        self.assertTrue(started["running"])

        # Per-equipment status views.
        status, body = _http_get(
            f"/api/v1/simulation/status?equipment_id={eid}"
        )
        self.assertEqual(status, 200, body)
        self.assertTrue(body["running"])
        self.assertEqual(body["equipment_id"], eid)

        status, body = _http_get(
            f"/api/v1/simulation/status?equipment_id={self.default_id}"
        )
        self.assertEqual(status, 200, body)
        self.assertFalse(body["running"])

        # Omitted -> DEFAULT view: the other equipment's session is not
        # leaked.
        status, body = _http_get("/api/v1/simulation/status")
        self.assertEqual(status, 200, body)
        self.assertFalse(body["running"])

        # Sessions are scoped.
        status, body = _http_get(
            f"/api/v1/simulation/sessions?equipment_id={eid}"
        )
        self.assertEqual(status, 200, body)
        self.assertGreater(len(body["sessions"]), 0)
        for session in body["sessions"]:
            self.assertEqual(session["equipment_id"], eid)

        # Wait for at least one telemetry tick attributed to B so the
        # equipment actually has data (the summary test below relies on
        # this ordering).
        self.assertTrue(
            _wait_for(
                lambda: _http_get(
                    f"/api/v1/stats/summary?equipment_id={eid}"
                )[1].get("readings_count", 0) >= 1,
                timeout_s=15,
            )
        )

        status, body = _http_write("POST", "/api/v1/simulation/stop")
        self.assertEqual(status, 200, body)
        self.assertTrue(body["stopped"])
        self.assertEqual(body["equipment_id"], eid)

    def test_simulation_on_disabled_equipment_409(self):
        status, created = _http_write(
            "POST", "/api/v1/equipment",
            {"name": "Disabled", "code": "ISO_DIS_B"},
        )
        self.assertEqual(status, 200, created)
        eid = created["equipment"]["id"]
        status, _ = _http_write(
            "PATCH", f"/api/v1/equipment/{eid}", {"enabled": False}
        )
        self.assertEqual(status, 200)

        status, body = _http_write(
            "POST", "/api/v1/simulation/start",
            {"mode": "overload", "equipment_id": eid},
        )
        self.assertEqual(status, 409, body)

        status, _ = _http_write(
            "PATCH", f"/api/v1/equipment/{eid}", {"enabled": True}
        )
        self.assertEqual(status, 200)

    def test_simulation_unknown_equipment_404(self):
        status, _ = _http_write(
            "POST", "/api/v1/simulation/start",
            {"mode": "overload", "equipment_id": 99999},
        )
        self.assertEqual(status, 404)

    def test_legacy_simulation_mode_still_defaults(self):
        # The legacy wrapper keeps working and attributes to DEFAULT.
        req = urllib.request.Request(
            BASE_URL + "/api/simulation/mode/overload",
            data=json.dumps({}).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            self.assertEqual(resp.status, 200)
        status, body = _http_get("/api/v1/simulation/status")
        self.assertEqual(status, 200, body)
        self.assertTrue(body["running"])
        self.assertEqual(body["equipment_id"], self.default_id)
        _http_write("POST", "/api/v1/simulation/stop")

    # -- SSE per equipment ----------------------------------------------

    def _read_sse_data(self, path, want_data=1, timeout_s=20):
        req = urllib.request.Request(BASE_URL + path)
        data_events = []
        with urllib.request.urlopen(req, timeout=timeout_s + 5) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("text/event-stream", resp.headers.get_content_type())
            deadline = time.time() + timeout_s
            while time.time() < deadline and len(data_events) < want_data:
                line = resp.readline().decode("utf-8", errors="replace")
                if not line:
                    break
                if line.startswith("data:"):
                    data_events.append(
                        json.loads(line[len("data:"):].strip())
                    )
        return data_events

    def test_sse_scoped_to_equipment(self):
        status, created = _http_write(
            "POST", "/api/v1/equipment",
            {"name": "SseB", "code": "ISO_SSE_B"},
        )
        self.assertEqual(status, 200, created)
        eid = created["equipment"]["id"]

        status, _ = _http_write(
            "POST", "/api/v1/simulation/start",
            {"mode": "overload", "equipment_id": eid},
        )
        self.assertEqual(status, 200)
        try:
            events = self._read_sse_data(
                f"/api/v1/stream/readings?equipment_id={eid}", want_data=2
            )
        finally:
            _http_write("POST", "/api/v1/simulation/stop")
        self.assertGreater(len(events), 0)
        for event in events:
            self.assertEqual(event["reading"]["equipment_id"], eid)

    def test_stop_scoped_to_equipment(self):
        status, created = _http_write(
            "POST", "/api/v1/equipment",
            {"name": "StopScope", "code": "ISO_STOP_B"},
        )
        self.assertEqual(status, 200, created)
        eid = created["equipment"]["id"]

        status, _ = _http_write(
            "POST", "/api/v1/simulation/start",
            {"mode": "overload", "equipment_id": eid},
        )
        self.assertEqual(status, 200)

        # Stopping another equipment's session is a conflict.
        status, body = _http_write(
            "POST",
            f"/api/v1/simulation/stop?equipment_id={self.default_id}",
        )
        self.assertEqual(status, 409, body)

        # The session is still running for its owner.
        status, body = _http_get(
            f"/api/v1/simulation/status?equipment_id={eid}"
        )
        self.assertTrue(body["running"])

        # The owner can stop it.
        status, body = _http_write(
            "POST", f"/api/v1/simulation/stop?equipment_id={eid}"
        )
        self.assertEqual(status, 200, body)
        self.assertTrue(body["stopped"])

    def test_reset_scoped_to_equipment(self):
        status, created = _http_write(
            "POST", "/api/v1/equipment",
            {"name": "ResetScope", "code": "ISO_RESET_B"},
        )
        self.assertEqual(status, 200, created)
        eid = created["equipment"]["id"]

        status, _ = _http_write(
            "POST", "/api/v1/simulation/start",
            {"mode": "oscillation", "equipment_id": eid},
        )
        self.assertEqual(status, 200)

        status, body = _http_write(
            "POST",
            f"/api/v1/simulation/reset?equipment_id={self.default_id}",
        )
        self.assertEqual(status, 409, body)

        status, body = _http_write(
            "POST", f"/api/v1/simulation/reset?equipment_id={eid}"
        )
        self.assertEqual(status, 200, body)
        self.assertTrue(body["reset"])

    def test_stop_omitted_keeps_legacy_global_behavior(self):
        status, created = _http_write(
            "POST", "/api/v1/equipment",
            {"name": "StopLegacy", "code": "ISO_STOPLEG_B"},
        )
        self.assertEqual(status, 200, created)
        eid = created["equipment"]["id"]

        status, _ = _http_write(
            "POST", "/api/v1/simulation/start",
            {"mode": "overload", "equipment_id": eid},
        )
        self.assertEqual(status, 200)

        # Omitted equipment_id: legacy global stop still works.
        status, body = _http_write("POST", "/api/v1/simulation/stop")
        self.assertEqual(status, 200, body)
        self.assertTrue(body["stopped"])

    def test_summary_with_data(self):
        # ISO_SIM_B ran a simulation above, so it has real data now.
        status, body = _http_get("/api/v1/equipment")
        self.assertEqual(status, 200)
        sim_b = next(
            item for item in body["equipment"] if item["code"] == "ISO_SIM_B"
        )
        status, summary = _http_get(
            f"/api/v1/equipment/{sim_b['id']}/summary"
        )
        self.assertEqual(status, 200, summary)
        self.assertGreater(summary["readings_count"], 0)
        self.assertIsNotNone(summary["last_reading"])
        self.assertEqual(
            summary["last_reading"]["equipment_id"], sim_b["id"]
        )
        self.assertIsNotNone(summary["last_reading_at"])
        self.assertIsNotNone(summary["diagnosis"])


if __name__ == "__main__":
    unittest.main()

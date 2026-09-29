"""Unit tests for the NEXUS 2.1 schema migrations.

Covers:
  - fresh database -> schema v1 with all new tables, columns and the
    timestamp index;
  - idempotency: running init_database()/migrations twice is a no-op;
  - legacy timestamp conversion: naive America/Sao_Paulo timestamps become
    UTC; already-aware values are left effectively unchanged;
  - legacy monitoring_events rows are backfilled as resolved lifecycle
    events.

Run:  python -m unittest discover -s tests -v   (from backend/)
"""
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import database  # noqa: E402
from app.database import migrations  # noqa: E402  # pylint: disable=unused-import

# A fixed recent instant, expressed as a *naive* America/Sao_Paulo timestamp
# the way pre-2.1 code wrote it. Kept within the retention window so the
# startup prune does not delete the fixture rows.
_SP_NOW = datetime.now(ZoneInfo("America/Sao_Paulo")) - timedelta(days=2)
_SP_NOW = _SP_NOW.replace(microsecond=0)
LEGACY_NAIVE_TS = _SP_NOW.replace(tzinfo=None).isoformat(timespec="seconds")
EXPECTED_UTC_TS = _SP_NOW.astimezone(timezone.utc).isoformat()


def _make_v0_database(db_path: str):
    """Create a pre-2.1 database: old schema, naive SP timestamps, v0."""
    conn = sqlite3.connect(db_path)
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
    # Naive timestamp as pre-2.1 code wrote it (America/Sao_Paulo local time).
    conn.execute(
        "INSERT INTO electrical_readings (timestamp, voltage, current,"
        " frequency, power_factor, active_power, temperature, status)"
        " VALUES (?, 220.0, 12.0, 60.0, 0.93, 2.45,"
        " 45.0, 'normal')",
        (LEGACY_NAIVE_TS,),
    )
    conn.execute(
        "INSERT INTO monitoring_events (timestamp, event_type, severity,"
        " message, recommendation) VALUES (?,"
        " 'HIGH_VOLTAGE', 'high', 'msg', 'rec')",
        (LEGACY_NAIVE_TS,),
    )
    conn.execute("PRAGMA user_version = 0")
    conn.commit()
    conn.close()


class MigrationTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "test.db")
        self._old_db_path = database.DB_PATH
        database.DB_PATH = self.db_path

    def tearDown(self):
        database.DB_PATH = self._old_db_path
        self.tmpdir.cleanup()

    def _table_info(self, table):
        conn = sqlite3.connect(self.db_path)
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        conn.close()
        return cols

    def test_fresh_database_gets_schema_v1(self):
        database.init_database()

        conn = sqlite3.connect(self.db_path)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        index = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
            " AND name='idx_readings_ts'"
        ).fetchone()
        conn.close()

        self.assertEqual(version, 1)
        self.assertIn("diagnostic_episodes", tables)
        self.assertIn("simulation_sessions", tables)
        self.assertIn("settings", tables)
        self.assertIsNotNone(index)

        event_cols = self._table_info("monitoring_events")
        for col in (
            "status", "opened_at", "closed_at", "last_seen", "occurrences",
            "last_value", "threshold", "acknowledged_at", "acknowledged_by",
            "equipment_id",
        ):
            self.assertIn(col, event_cols)

    def test_migrations_are_idempotent(self):
        database.init_database()
        database.init_database()  # second run must be a no-op

        conn = sqlite3.connect(self.db_path)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.close()
        self.assertEqual(version, 1)

    def test_legacy_timestamps_converted_from_sao_paulo_to_utc(self):
        _make_v0_database(self.db_path)
        database.init_database()

        conn = sqlite3.connect(self.db_path)
        reading_ts = conn.execute(
            "SELECT timestamp FROM electrical_readings"
        ).fetchone()[0]
        event_ts = conn.execute(
            "SELECT timestamp FROM monitoring_events"
        ).fetchone()[0]
        conn.close()

        # Naive 10:00 SP -> 13:00 UTC.
        self.assertEqual(reading_ts, EXPECTED_UTC_TS)
        self.assertEqual(event_ts, EXPECTED_UTC_TS)

    def test_legacy_events_backfilled_as_resolved(self):
        _make_v0_database(self.db_path)
        database.init_database()

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        event = conn.execute("SELECT * FROM monitoring_events").fetchone()
        conn.close()

        self.assertEqual(event["status"], "resolved")
        self.assertEqual(event["occurrences"], 1)
        self.assertEqual(event["opened_at"], EXPECTED_UTC_TS)
        self.assertEqual(event["closed_at"], EXPECTED_UTC_TS)
        self.assertEqual(event["last_seen"], EXPECTED_UTC_TS)

    def test_already_utc_rows_are_untouched_on_rerun(self):
        _make_v0_database(self.db_path)
        database.init_database()
        database.init_database()

        conn = sqlite3.connect(self.db_path)
        reading_ts = conn.execute(
            "SELECT timestamp FROM electrical_readings"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(reading_ts, EXPECTED_UTC_TS)


if __name__ == "__main__":
    unittest.main()

"""Unit tests for the telemetry data-retention policy.

Covers:
  - prune_old_data(): removes rows older than the retention window and keeps
    recent ones, on both tables;
  - init_database(): prunes stale rows on startup;
  - get_recent_readings()/get_recent_events(): clamp `limit` defensively so a
    caller can never trigger a full-table dump (LIMIT -1 == unlimited in SQLite).

Run:  python -m unittest discover -s tests -v   (from backend/)
Requires no third-party test dependencies.
"""
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import database  # noqa: E402


def _seed_rows(db_path: str, n_readings: int, n_events: int, timestamp: str):
    conn = sqlite3.connect(db_path)
    conn.executemany(
        "INSERT INTO electrical_readings (timestamp, voltage, current, frequency,"
        " power_factor, active_power, temperature, status)"
        " VALUES (?, 220.0, 12.0, 60.0, 0.93, 2.45, 45.0, 'normal')",
        [(timestamp,) for _ in range(n_readings)],
    )
    conn.executemany(
        "INSERT INTO monitoring_events (timestamp, event_type, severity, message,"
        " recommendation) VALUES (?, 'HIGH_VOLTAGE', 'high', 'msg', 'rec')",
        [(timestamp,) for _ in range(n_events)],
    )
    conn.commit()
    conn.close()


def _count(db_path: str, table: str) -> int:
    conn = sqlite3.connect(db_path)
    n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    conn.close()
    return n


class RetentionTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "test.db")
        self._old_db_path = database.DB_PATH
        database.DB_PATH = self.db_path
        database.init_database()

    def tearDown(self):
        database.DB_PATH = self._old_db_path
        self.tmpdir.cleanup()

    def test_prune_removes_old_rows_and_keeps_recent(self):
        old_ts = (datetime.now() - timedelta(days=60)).isoformat()
        recent_ts = datetime.now().isoformat()
        _seed_rows(self.db_path, 10, 5, old_ts)
        _seed_rows(self.db_path, 7, 3, recent_ts)

        pruned = database.prune_old_data()

        self.assertEqual(pruned["readings_deleted"], 10)
        self.assertEqual(pruned["events_deleted"], 5)
        self.assertEqual(_count(self.db_path, "electrical_readings"), 7)
        self.assertEqual(_count(self.db_path, "monitoring_events"), 3)

    def test_prune_on_empty_database_returns_zeros(self):
        pruned = database.prune_old_data()
        self.assertEqual(pruned, {"readings_deleted": 0, "events_deleted": 0})

    def test_prune_never_raises_on_missing_tables(self):
        # Best-effort maintenance must not break startup or the telemetry loop.
        os.remove(self.db_path)
        pruned = database.prune_old_data()
        self.assertEqual(pruned, {"readings_deleted": 0, "events_deleted": 0})

    def test_init_database_prunes_stale_rows_on_startup(self):
        old_ts = (datetime.now() - timedelta(days=90)).isoformat()
        _seed_rows(self.db_path, 20, 10, old_ts)

        database.init_database()  # startup path

        self.assertEqual(_count(self.db_path, "electrical_readings"), 0)
        self.assertEqual(_count(self.db_path, "monitoring_events"), 0)


class LimitClampTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "test.db")
        self._old_db_path = database.DB_PATH
        database.DB_PATH = self.db_path
        database.init_database()
        _seed_rows(self.db_path, 1500, 700, datetime.now().isoformat())

    def tearDown(self):
        database.DB_PATH = self._old_db_path
        self.tmpdir.cleanup()

    def test_readings_huge_limit_is_clamped(self):
        rows = database.get_recent_readings(10**9)
        self.assertEqual(len(rows), database.MAX_HISTORY_LIMIT)

    def test_readings_negative_limit_cannot_dump_table(self):
        # LIMIT -1 means "unlimited" in SQLite; the clamp must neutralize it.
        rows = database.get_recent_readings(-1)
        self.assertEqual(len(rows), 1)

    def test_readings_zero_limit_returns_one_row(self):
        rows = database.get_recent_readings(0)
        self.assertEqual(len(rows), 1)

    def test_readings_normal_limit_unchanged(self):
        rows = database.get_recent_readings(50)
        self.assertEqual(len(rows), 50)

    def test_events_huge_limit_is_clamped(self):
        rows = database.get_recent_events(10**9)
        self.assertEqual(len(rows), database.MAX_EVENTS_LIMIT)

    def test_events_negative_limit_cannot_dump_table(self):
        rows = database.get_recent_events(-1)
        self.assertEqual(len(rows), 1)

    def test_events_normal_limit_unchanged(self):
        rows = database.get_recent_events(20)
        self.assertEqual(len(rows), 20)


if __name__ == "__main__":
    unittest.main()

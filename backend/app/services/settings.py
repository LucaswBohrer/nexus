"""Persistent system settings (NEXUS 2.1).

Operational configuration lives in the ``settings`` table: thresholds,
retention windows, energy tariff and simulation defaults. Purely visual
user preferences (theme, language, date format, favorite metrics, ...)
belong in frontend localStorage and must NOT be added here.

Values are stored JSON-encoded so types (number, null) survive the TEXT
column. Reads go through a small in-memory cache that is invalidated on
every write, so diagnostics pick up threshold changes without a restart.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.database.database import get_connection

logger = logging.getLogger(__name__)

# Setting key -> default value. Keys use dotted namespaces:
#   thresholds.*            electrical engineering limits
#   retention.*             per-table retention windows (days)
#   energy_tariff           currency/kWh, null = unknown
#   simulation.*            simulation defaults
DEFAULTS: dict[str, Any] = {
    "thresholds.voltage_min": 198.0,
    "thresholds.voltage_max": 242.0,
    "thresholds.frequency_min": 59.5,
    "thresholds.frequency_max": 60.5,
    "thresholds.power_factor_min": 0.8,
    "thresholds.temperature_max": 70.0,
    "retention.readings_days": 30,
    "retention.events_days": 90,
    "retention.diagnostic_episodes_days": 90,
    "retention.simulation_sessions_days": 180,
    "energy_tariff": None,
    "simulation.default_intensity": 100,
    "simulation.default_duration_minutes": None,
}

# In-memory read cache. Invalidated per-key on set_setting(). Single-process
# app: no cross-process staleness to worry about.
_cache: dict[str, Any] = {}


def _as_number(value: Any, key: str) -> float:
    # bool is a subclass of int: reject it explicitly, a threshold of
    # True/False is never what the caller meant.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Setting '{key}' must be a number, got {value!r}")
    return float(value)


def _as_int(value: Any, key: str) -> int:
    number = _as_number(value, key)
    if not number.is_integer():
        raise ValueError(f"Setting '{key}' must be an integer, got {value!r}")
    return int(number)


def validate_setting(key: str, value: Any) -> Any:
    """Validate and coerce a single setting value.

    Returns the coerced value that should be persisted. Raises KeyError for
    unknown keys and ValueError for invalid values. Cross-field rules
    (min < max) are checked in set_setting(), which knows the sibling values.
    """
    if key not in DEFAULTS:
        raise KeyError(f"Unknown setting: {key}")

    if key in ("thresholds.voltage_min", "thresholds.voltage_max"):
        number = _as_number(value, key)
        if not 80.0 <= number <= 300.0:
            raise ValueError(
                f"Setting '{key}' must be within 80..300 V, got {value!r}"
            )
        return number
    if key in ("thresholds.frequency_min", "thresholds.frequency_max"):
        number = _as_number(value, key)
        if not 50.0 <= number <= 70.0:
            raise ValueError(
                f"Setting '{key}' must be within 50..70 Hz, got {value!r}"
            )
        return number
    if key == "thresholds.power_factor_min":
        number = _as_number(value, key)
        if not 0.0 <= number <= 1.0:
            raise ValueError(
                f"Setting '{key}' must be within 0..1, got {value!r}"
            )
        return number
    if key == "thresholds.temperature_max":
        number = _as_number(value, key)
        if not -50.0 <= number <= 150.0:
            raise ValueError(
                f"Setting '{key}' must be within -50..150 C, got {value!r}"
            )
        return number
    if key.startswith("retention."):
        days = _as_int(value, key)
        if not 1 <= days <= 365:
            raise ValueError(
                f"Setting '{key}' must be within 1..365 days, got {value!r}"
            )
        return days
    if key == "energy_tariff":
        if value is None:
            return None
        number = _as_number(value, key)
        if number < 0:
            raise ValueError(
                f"Setting '{key}' must be null or >= 0, got {value!r}"
            )
        return number
    if key == "simulation.default_intensity":
        number = _as_number(value, key)
        if not 0 <= number <= 200:
            raise ValueError(
                f"Setting '{key}' must be within 0..200, got {value!r}"
            )
        return int(number) if number.is_integer() else number
    if key == "simulation.default_duration_minutes":
        if value is None:
            return None
        number = _as_number(value, key)
        if number <= 0:
            raise ValueError(
                f"Setting '{key}' must be null or > 0, got {value!r}"
            )
        return number
    # Unreachable: every DEFAULTS key is handled above.
    raise KeyError(f"Unknown setting: {key}")  # pragma: no cover


def _check_cross_field_rules(key: str, coerced: Any) -> None:
    """Enforce min < max pairs using the effective (post-write) values."""
    effective = {k: get_setting(k) for k in DEFAULTS}
    effective[key] = coerced
    pairs = (
        ("thresholds.voltage_min", "thresholds.voltage_max"),
        ("thresholds.frequency_min", "thresholds.frequency_max"),
    )
    for low_key, high_key in pairs:
        low, high = effective[low_key], effective[high_key]
        if low is not None and high is not None and not low < high:
            raise ValueError(
                f"Setting '{low_key}' ({low}) must be < '{high_key}' ({high})"
            )


def get_setting(key: str) -> Any:
    """Return the effective value for `key` (stored value or default)."""
    if key not in DEFAULTS:
        raise KeyError(f"Unknown setting: {key}")
    if key not in _cache:
        connection = get_connection()
        try:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        finally:
            connection.close()
        _cache[key] = json.loads(row["value"]) if row else DEFAULTS[key]
    return _cache[key]


def get_all_settings() -> dict[str, Any]:
    """Return every known setting with its effective value."""
    return {key: get_setting(key) for key in DEFAULTS}


def get_thresholds() -> dict[str, float]:
    """Return the six diagnostic thresholds (short names -> float)."""
    return {
        key.split(".", 1)[1]: float(get_setting(key))
        for key in DEFAULTS
        if key.startswith("thresholds.")
    }


def set_setting(key: str, value: Any) -> Any:
    """Validate, persist and return the coerced value for `key`.

    Raises KeyError for unknown keys, ValueError for invalid values.
    """
    coerced = validate_setting(key, value)
    _check_cross_field_rules(key, coerced)
    connection = get_connection()
    try:
        connection.execute(
            """
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, json.dumps(coerced), datetime.now(timezone.utc).isoformat()),
        )
        connection.commit()
    finally:
        connection.close()
    _cache.pop(key, None)
    logger.info("Setting updated: %s = %r", key, coerced)
    return coerced


def seed_settings() -> int:
    """Insert every missing default. Idempotent; returns rows inserted."""
    connection = get_connection()
    inserted = 0
    try:
        now = datetime.now(timezone.utc).isoformat()
        for key, default in DEFAULTS.items():
            cursor = connection.execute(
                "INSERT OR IGNORE INTO settings (key, value, updated_at)"
                " VALUES (?, ?, ?)",
                (key, json.dumps(default), now),
            )
            inserted += cursor.rowcount
        connection.commit()
    finally:
        connection.close()
    if inserted:
        logger.info("Seeded %d default settings", inserted)
    return inserted

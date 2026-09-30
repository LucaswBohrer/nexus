"""Equipment registry service (NEXUS 2.4).

The registry turns NEXUS from a single-source monitor into a
multi-equipment platform. Every data row (readings, events, episodes,
sessions) is scoped by ``equipment_id``; a deterministic ``DEFAULT``
equipment (code ``"DEFAULT"``) owns all pre-2.4 data and is the fallback
whenever a caller does not name an equipment.

Conventions:
- ``equipment_id`` is the integer primary key. ``code`` is a unique
  human identifier (e.g. ``"PANEL_A"``); both are accepted by
  :func:`resolve_equipment_id`.
- ``enabled`` is a boolean flag; disabled equipment rejects *writes*
  (simulation starts) but keeps its historical data readable.
- Physical deletion is refused while the equipment has historical
  data; prefer logical deactivation via :func:`deactivate_equipment`.
- ``status`` is the operational state: active | inactive | maintenance.
"""
import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.database.database import get_connection

DEFAULT_CODE = "DEFAULT"
DEFAULT_NAME = "Main Electrical System"

STATUSES = ("active", "inactive", "maintenance")

# Every table whose rows are scoped to an equipment.
EQUIPMENT_SCOPED_TABLES = (
    "electrical_readings",
    "monitoring_events",
    "diagnostic_episodes",
    "simulation_sessions",
)


class EquipmentError(ValueError):
    """Validation error (mapped to HTTP 422)."""


class EquipmentNotFound(Exception):
    """Unknown equipment id/code (mapped to HTTP 404)."""


class EquipmentConflict(Exception):
    """The equipment cannot take this action: disabled, or has data
    (mapped to HTTP 409)."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "code": row["code"],
        "name": row["name"],
        "description": row["description"],
        "equipment_type": row["equipment_type"],
        "location": row["location"],
        "status": row["status"],
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _validate_payload(
    data: dict[str, Any],
    *,
    is_create: bool,
    current_id: int | None = None,
) -> dict[str, Any]:
    """Validate and normalize create/update fields. Returns the cleaned
    field dict (only keys present in the input)."""
    cleaned: dict[str, Any] = {}

    if is_create or "name" in data:
        name = (data.get("name") or "").strip() if data.get("name") else ""
        if not name:
            raise EquipmentError("name is required and must not be empty")
        cleaned["name"] = name

    if is_create or "code" in data:
        code = (data.get("code") or "").strip() if data.get("code") else ""
        if not code:
            raise EquipmentError("code is required and must not be empty")
        cleaned["code"] = code

    if is_create or "status" in data:
        status = data.get("status", "active")
        if status not in STATUSES:
            raise EquipmentError(
                f"status must be one of {', '.join(STATUSES)}; got {status!r}"
            )
        cleaned["status"] = status

    if is_create or "enabled" in data:
        cleaned["enabled"] = 1 if data.get("enabled", True) else 0

    for key in ("description", "equipment_type", "location"):
        if key in data:
            value = data[key]
            cleaned[key] = value.strip() if isinstance(value, str) else value

    return cleaned


def _check_code_unique(
    connection: sqlite3.Connection, code: str, current_id: int | None
) -> None:
    row = connection.execute(
        "SELECT id FROM equipment WHERE code = ?", (code,)
    ).fetchone()
    if row is not None and row["id"] != current_id:
        raise EquipmentError(f"equipment code already exists: {code!r}")


def validate_equipment(
    data: dict[str, Any], *, is_create: bool
) -> dict[str, Any]:
    """Public field validation for equipment payloads.

    Returns the cleaned field dict (only keys present in the input).
    Raises EquipmentError on any validation error (missing/blank name
    or code, invalid status). Used by create/update and exposed so API
    layers and callers can validate without touching the database.
    """
    return _validate_payload(data, is_create=is_create)


def create_equipment(
    name: str,
    code: str,
    description: str | None = None,
    equipment_type: str | None = None,
    location: str | None = None,
    status: str = "active",
    enabled: bool = True,
) -> dict[str, Any]:
    """Create a new equipment. Raises EquipmentError (422) on validation
    errors such as a missing name or a duplicate code."""
    cleaned = validate_equipment(
        {
            "name": name,
            "code": code,
            "description": description,
            "equipment_type": equipment_type,
            "location": location,
            "status": status,
            "enabled": enabled,
        },
        is_create=True,
    )
    now = _now_iso()
    connection = get_connection()
    try:
        _check_code_unique(connection, cleaned["code"], None)
        cursor = connection.execute(
            """
            INSERT INTO equipment (
                code, name, description, equipment_type, location,
                status, enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cleaned["code"],
                cleaned["name"],
                cleaned.get("description"),
                cleaned.get("equipment_type"),
                cleaned.get("location"),
                cleaned["status"],
                cleaned["enabled"],
                now,
                now,
            ),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM equipment WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        return _row_to_dict(row)
    finally:
        connection.close()


def get_equipment(equipment_id: int) -> dict[str, Any] | None:
    """Return the equipment dict, or None when the id is unknown."""
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT * FROM equipment WHERE id = ?", (equipment_id,)
        ).fetchone()
        return _row_to_dict(row) if row is not None else None
    finally:
        connection.close()


def get_equipment_by_code(code: str) -> dict[str, Any] | None:
    """Return the equipment dict, or None when the code is unknown."""
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT * FROM equipment WHERE code = ?", (code,)
        ).fetchone()
        return _row_to_dict(row) if row is not None else None
    finally:
        connection.close()


def get_default_equipment() -> dict[str, Any]:
    """Return the deterministic DEFAULT equipment.

    The v4 migration seeds it, but this defensively creates it if the
    row is missing (e.g. databases provisioned outside init_database),
    because every code path falls back to it.
    """
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT * FROM equipment WHERE code = ?", (DEFAULT_CODE,)
        ).fetchone()
        if row is None:
            now = _now_iso()
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO equipment (
                    code, name, description, equipment_type, location,
                    status, enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'active', 1, ?, ?)
                """,
                (
                    DEFAULT_CODE,
                    DEFAULT_NAME,
                    "Default installation monitored before NEXUS 2.4",
                    "electrical_panel",
                    None,
                    now,
                    now,
                ),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM equipment WHERE id = ?",
                (cursor.lastrowid or 0,),
            ).fetchone()
            if row is None:  # lost the INSERT OR IGNORE race
                row = connection.execute(
                    "SELECT * FROM equipment WHERE code = ?", (DEFAULT_CODE,)
                ).fetchone()
        return _row_to_dict(row)
    finally:
        connection.close()


def list_equipment() -> list[dict[str, Any]]:
    """All registered equipment, oldest first. The registry is tiny, so
    no paging is needed."""
    connection = get_connection()
    try:
        rows = connection.execute(
            "SELECT * FROM equipment ORDER BY id ASC"
        ).fetchall()
        return [_row_to_dict(row) for row in rows]
    finally:
        connection.close()


def update_equipment(
    equipment_id: int, **fields: Any
) -> dict[str, Any]:
    """Partial update. Raises EquipmentNotFound (404) for unknown ids
    and EquipmentError (422) on validation errors."""
    existing = get_equipment(equipment_id)
    if existing is None:
        raise EquipmentNotFound(f"equipment not found: {equipment_id!r}")
    cleaned = validate_equipment(fields, is_create=False)
    if "code" in cleaned and cleaned["code"] != existing["code"]:
        connection = get_connection()
        try:
            _check_code_unique(connection, cleaned["code"], equipment_id)
        finally:
            connection.close()
    if not cleaned:
        return existing
    cleaned["updated_at"] = _now_iso()
    assignments = ", ".join(f"{key} = ?" for key in cleaned)
    values = list(cleaned.values()) + [equipment_id]
    connection = get_connection()
    try:
        connection.execute(
            f"UPDATE equipment SET {assignments} WHERE id = ?", values
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM equipment WHERE id = ?", (equipment_id,)
        ).fetchone()
        return _row_to_dict(row)
    finally:
        connection.close()


def deactivate_equipment(equipment_id: int) -> dict[str, Any]:
    """Logical deactivation: historical data stays readable, new writes
    (simulation starts) are refused with 409."""
    return update_equipment(equipment_id, enabled=False)


def activate_equipment(equipment_id: int) -> dict[str, Any]:
    return update_equipment(equipment_id, enabled=True)


def has_historical_data(equipment_id: int) -> bool:
    """True when any scoped table still references the equipment."""
    connection = get_connection()
    try:
        for table in EQUIPMENT_SCOPED_TABLES:
            count = connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE equipment_id = ?",
                (equipment_id,),
            ).fetchone()[0]
            if count:
                return True
        return False
    finally:
        connection.close()


def delete_equipment(equipment_id: int) -> None:
    """Physical delete, only for equipment without historical data.

    Raises EquipmentNotFound (404) for unknown ids and
    EquipmentConflict (409) for DEFAULT or for equipment that still has
    data. Prefer :func:`deactivate_equipment` for anything real.
    """
    equipment = get_equipment(equipment_id)
    if equipment is None:
        raise EquipmentNotFound(f"equipment not found: {equipment_id!r}")
    if equipment["code"] == DEFAULT_CODE:
        raise EquipmentConflict(
            "the DEFAULT equipment cannot be deleted; deactivate it instead"
        )
    if has_historical_data(equipment_id):
        raise EquipmentConflict(
            "equipment has historical data and cannot be deleted;"
            " deactivate it instead"
        )
    connection = get_connection()
    try:
        connection.execute(
            "DELETE FROM equipment WHERE id = ?", (equipment_id,)
        )
        connection.commit()
    finally:
        connection.close()


def resolve_equipment_id(value: Any) -> int:
    """Resolve an equipment reference to its integer id.

    - ``None`` -> the DEFAULT equipment id (backward compatibility:
      every legacy/omitted call keeps working);
    - an integer (or digit string) -> that id, 404 when unknown;
    - any other string -> treated as ``code``, 404 when unknown.
    """
    if value is None:
        return get_default_equipment()["id"]
    if isinstance(value, str) and not value.lstrip("-").isdigit():
        equipment = get_equipment_by_code(value)
        if equipment is None:
            raise EquipmentNotFound(f"equipment not found: {value!r}")
        return equipment["id"]
    try:
        equipment_id = int(value)
    except (TypeError, ValueError) as exc:
        raise EquipmentNotFound(f"equipment not found: {value!r}") from exc
    if get_equipment(equipment_id) is None:
        raise EquipmentNotFound(f"equipment not found: {value!r}")
    return equipment_id


def require_writable_equipment(value: Any) -> int:
    """Resolve like :func:`resolve_equipment_id` and additionally refuse
    disabled equipment (409), for write paths such as simulation start."""
    equipment_id = resolve_equipment_id(value)
    equipment = get_equipment(equipment_id)
    if equipment is not None and not equipment["enabled"]:
        raise EquipmentConflict(
            f"equipment {equipment['code']!r} is disabled and rejects writes"
        )
    return equipment_id

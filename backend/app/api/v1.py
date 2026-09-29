"""NEXUS API v1 (NEXUS 2.1).

New functionality lives here. The legacy /api/* endpoints keep their exact
contracts and are implemented in app.api.routes.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import require_api_key
from app.services import settings as settings_service

router = APIRouter(prefix="/api/v1")


class SettingUpdate(BaseModel):
    value: Any


@router.get("/settings")
def list_settings():
    """Return every known setting with its effective value."""
    return {"settings": settings_service.get_all_settings()}


@router.get("/settings/{key}")
def get_setting(key: str):
    """Return a single setting. 404 for unknown keys."""
    try:
        value = settings_service.get_setting(key)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown setting: {key}")
    return {"key": key, "value": value}


@router.put("/settings/{key}", dependencies=[Depends(require_api_key)])
def update_setting(key: str, body: SettingUpdate):
    """Update a setting. 404 for unknown keys, 422 for invalid values."""
    try:
        value = settings_service.set_setting(key, body.value)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown setting: {key}")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"key": key, "value": value}

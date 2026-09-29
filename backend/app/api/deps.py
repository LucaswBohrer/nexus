"""Shared API dependencies."""

from fastapi import HTTPException, Request

from app.config import settings


def require_api_key(request: Request):
    """Optional write protection for POST/PUT/PATCH endpoints.

    When NEXUS_API_KEY is set, the request must carry a matching X-API-Key
    header, otherwise it is rejected with 401. GETs stay public. When the
    variable is unset, no enforcement happens so local development is never
    blocked.

    This is NOT real authentication: never ship the secret to the frontend.
    It is a thin optional guard for local demos.
    """
    expected = settings.api_key
    if not expected:
        return
    provided = request.headers.get("X-API-Key")
    if provided != expected:
        raise HTTPException(
            status_code=401, detail="Invalid or missing X-API-Key"
        )

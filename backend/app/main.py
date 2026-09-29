from contextlib import asynccontextmanager
import json
import logging
import os
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.api.v1 import router as v1_router
from app.config import APP_VERSION, settings
from app.database import database as database_module
from app.database.database import get_connection, init_database
from app.services.errors import record_error
from app.services.monitoring import telemetry_service
from app.services.settings import seed_settings


class JsonFormatter(logging.Formatter):
    """One JSON object per line: {"ts", "level", "logger", "message"}."""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
        )


def _configure_logging() -> None:
    # NEXUS_LOG_JSON=1 switches application logging to one JSON object
    # per line (no new dependencies). Best-effort: uvicorn's own access
    # loggers keep their handlers; app.* loggers emit JSON.
    if os.environ.get("NEXUS_LOG_JSON") == "1":
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        root = logging.getLogger()
        root.handlers.clear()
        root.addHandler(handler)
        root.setLevel(logging.INFO)


_configure_logging()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "NEXUS API starting (database=%s, cors_origins=%s)",
        settings.database_path,
        settings.cors_origins_list,
    )
    init_database()
    seed_settings()
    await telemetry_service.start()
    logger.info("NEXUS API ready")
    yield
    await telemetry_service.stop()
    logger.info("NEXUS API stopped")


app = FastAPI(
    title="NEXUS API",
    description="Intelligent Electrical Monitoring System API",
    version="0.1.0",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception):
    # Preserve HTTPException semantics (status codes); only genuine 500s
    # are recorded in the error ring buffer.
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            headers=exc.headers,
            content={"detail": exc.detail},
        )
    record_error(
        f"Unhandled {type(exc).__name__}: {exc}",
        context=f"{request.method} {request.url.path}",
    )
    logger.exception("Unhandled exception")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


app.include_router(router)
app.include_router(v1_router)


@app.get("/")
def root():
    return {
        "name": "NEXUS",
        "description": "Intelligent Electrical Monitoring System",
        "version": "0.1.0",
        "status": "operational",
    }


@app.get("/api/health")
def health():
    # A static "healthy" is useless to orchestrators: verify the critical
    # dependency (SQLite) so a wedged database surfaces as 503 instead of
    # a false "healthy".
    try:
        connection = get_connection()
        try:
            # NOTE: `SELECT 1` alone never touches the file (constant
            # expression), so it would not detect a corrupted database.
            # Reading sqlite_master forces SQLite to open and parse it.
            connection.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
            readings_count = connection.execute(
                "SELECT COUNT(*) FROM electrical_readings"
            ).fetchone()[0]
        finally:
            connection.close()
    except Exception:
        logger.exception("Health check failed: database unreachable")
        raise HTTPException(status_code=503, detail="database unreachable")

    tick_metrics = telemetry_service.get_tick_metrics()
    last_tick_at = tick_metrics["last_tick_at"]
    last_tick_age_ms = None
    if last_tick_at is not None:
        last_tick_age_ms = (
            datetime.now(timezone.utc) - datetime.fromisoformat(last_tick_at)
        ).total_seconds() * 1000

    db_path = database_module.DB_PATH
    return {
        # Legacy contract (additive only).
        "status": "healthy",
        "service": "nexus-api",
        "database": "ok",
        # NEXUS 2.1 observability.
        "version": APP_VERSION,
        "uptime_s": telemetry_service.get_uptime_seconds(),
        "db_size_bytes": os.path.getsize(db_path) if os.path.exists(db_path) else 0,
        "readings_count": readings_count,
        "last_tick_age_ms": last_tick_age_ms,
    }

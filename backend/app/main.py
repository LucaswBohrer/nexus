from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.v1 import router as v1_router
from app.config import settings
from app.database.database import get_connection, init_database
from app.services.monitoring import telemetry_service
from app.services.settings import seed_settings


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
        finally:
            connection.close()
    except Exception:
        logger.exception("Health check failed: database unreachable")
        raise HTTPException(status_code=503, detail="database unreachable")

    return {
        "status": "healthy",
        "service": "nexus-api",
        "database": "ok",
    }


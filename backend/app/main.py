from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import settings
from app.database.database import init_database
from app.services.monitoring import telemetry_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_database()
    await telemetry_service.start()
    yield
    await telemetry_service.stop()


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
    return {
        "status": "healthy",
        "service": "nexus-api",
    }


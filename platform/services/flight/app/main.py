"""Flight Service — main FastAPI application."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.v1.drones import router as drones_router
from app.api.v1.drones import telemetry_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"🚀 Flight service started on port {settings.service_port}")
    yield
    print("🛑 Flight service stopped")


app = FastAPI(
    title="Traffic Platform - Flight Service",
    description="Drone management, telemetry, and mission planning",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(drones_router, prefix="/api/v1")
app.include_router(telemetry_router, prefix="/api/v1")


@app.get("/")
async def root():
    return {"service": "flight", "version": "0.1.0", "status": "running"}


@app.get("/health")
async def health():
    return {"status": "healthy"}

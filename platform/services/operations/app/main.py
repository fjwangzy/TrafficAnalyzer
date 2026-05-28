"""Operations service main application."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import ops_settings
from app.core.database import init_db, close_db
from app.api.v1 import auth


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    await init_db()
    print(f"🚀 Operations service started on port {ops_settings.service_port}")
    print(f"   - Database: {ops_settings.database_url}")
    print(f"   - Debug: {ops_settings.debug}")
    yield
    # Shutdown
    await close_db()
    print("🛑 Operations service stopped")


# Create FastAPI app
app = FastAPI(
    title="Traffic Platform - Operations Service",
    description="User management, authentication, and business operations",
    version="0.1.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=ops_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/api/v1")


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "operations",
        "version": "0.1.0",
        "status": "running",
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}

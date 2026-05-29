"""Traffic Platform Monolith — main FastAPI application."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import init_db, close_db
from app.middleware.auth import AuthMiddleware
from app.kafka.ws_manager import WSManager
from app.kafka.consumer import KafkaConsumerService
from app.services.alert_engine import AlertEngine
from app.utils.influx_query import InfluxQuery
from app.api.v1 import intersections, alerts, system, trajectories, video, calibration, auth
from app.api.v1.drones import router as drones_router
from app.api.v1.drones import telemetry_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # ── Initialize database ──
    try:
        await init_db()
        logger.info(f"Database initialized: {settings.db_host}:{settings.db_port}")
    except Exception as e:
        logger.warning(f"Database unavailable (auth features disabled): {e}")

    # ── Initialize components ──
    ws_manager = WSManager()
    alert_engine = AlertEngine(ws_manager, settings)

    # InfluxDB (optional — graceful fallback if unavailable)
    influx = None
    try:
        influx = InfluxQuery(
            host=settings.influx_host,
            port=settings.influx_port,
            database=settings.influx_db,
            user=settings.influx_user,
            password=settings.influx_pass,
        )
        logger.info(f"InfluxDB connected: {settings.influx_host}:{settings.influx_port}")
    except Exception as e:
        logger.warning(f"InfluxDB unavailable (historical queries disabled): {e}")

    # Kafka consumer (optional — graceful fallback if unavailable)
    kafka_service = None
    try:
        kafka_service = KafkaConsumerService(
            bootstrap_servers=settings.kafka_bootstrap,
            group_id=settings.kafka_consumer_group,
            topics_pattern=settings.kafka_topics_pattern,
            ws_manager=ws_manager,
            alert_engine=alert_engine,
        )
        await kafka_service.start()
        logger.info(f"Kafka consumer started: {settings.kafka_bootstrap}")
    except Exception as e:
        logger.warning(f"Kafka consumer failed to start (real-time disabled): {e}")

    # Store on app state
    app.state.ws_manager = ws_manager
    app.state.alert_engine = alert_engine
    app.state.influx = influx
    app.state.kafka_service = kafka_service
    app.state.settings = settings

    logger.info(f"🚀 Traffic Platform started on port {settings.service_port}")
    logger.info(f"   - Database: {settings.db_host}:{settings.db_port}")
    logger.info(f"   - Kafka: {settings.kafka_bootstrap}")
    logger.info(f"   - InfluxDB: {settings.influx_host}:{settings.influx_port}")

    yield

    # ── Shutdown ──
    if kafka_service:
        await kafka_service.stop()
    await ws_manager.close_all()
    if influx:
        influx.close()
    await close_db()
    logger.info("🛑 Traffic Platform stopped")


# Create FastAPI app
app = FastAPI(
    title="Traffic Platform",
    description="Unified traffic analysis platform — monolith architecture",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add authentication middleware
app.add_middleware(AuthMiddleware)

# Include API routers
app.include_router(auth.router, prefix="/api/v1")
app.include_router(intersections.router, prefix="/api/v1")
app.include_router(alerts.router, prefix="/api/v1")
app.include_router(system.router, prefix="/api/v1")
app.include_router(trajectories.router, prefix="/api/v1")
app.include_router(video.router, prefix="/api/v1")
app.include_router(calibration.router, prefix="/api/v1")
app.include_router(drones_router, prefix="/api/v1")
app.include_router(telemetry_router, prefix="/api/v1")


@app.get("/")
async def root():
    return {
        "service": "traffic-platform",
        "version": "1.0.0",
        "architecture": "monolith",
        "status": "running",
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/ready")
async def readiness_check():
    """Check if all dependencies are ready."""
    services = {
        "database": "healthy",
        "kafka": "unknown",
        "influxdb": "unknown",
    }

    # Check Kafka
    kafka_service = app.state.kafka_service if hasattr(app.state, "kafka_service") else None
    if kafka_service and kafka_service._running:
        services["kafka"] = "healthy"
    elif kafka_service:
        services["kafka"] = "unhealthy"
    else:
        services["kafka"] = "not_configured"

    # Check InfluxDB
    influx = app.state.influx if hasattr(app.state, "influx") else None
    if influx:
        services["influxdb"] = "healthy"
    else:
        services["influxdb"] = "not_configured"

    all_ready = all(s == "healthy" or s == "not_configured" for s in services.values())

    return {
        "status": "ready" if all_ready else "degraded",
        "services": services,
    }


# ── WebSocket endpoint ──
@app.websocket("/ws/realtime")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time data push."""
    ws_manager: WSManager = websocket.app.state.ws_manager
    await ws_manager.connect(websocket)

    try:
        while True:
            raw = await websocket.receive_text()
            await ws_manager.handle_message(websocket, raw)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await ws_manager.disconnect(websocket)

"""Traffic Platform Monolith — main FastAPI application."""
import logging
import hashlib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import init_db, close_db, async_session_maker
from app.middleware.auth import AuthMiddleware
from app.kafka.ws_manager import WSManager
from app.kafka.consumer import KafkaConsumerService
from app.services.alert_engine import AlertEngine, SqlAlertStore
from app.services.lane_annotation_store import LaneAnnotationStore
from app.services.pipeline_manager import PipelineManager
from app.services.survey_worker import SurveyWorker
from app.services.mission_orchestrator import MissionOrchestrator, PipelineManagerAdapter
from app.services.metric_store import PostgresMetricStoreAdapter
from app.services.enforcement_service import EnforcementService
from app.services.dashboard_read_model import DashboardReadModel
from app.services.road_context import (
    FallbackRoadContextAdapter,
    FixtureRoadContextAdapter,
    Road9RoadContextAdapter,
    RoadContext,
    RoadContextResult,
)
from app.api.v1 import intersections, alerts, system, trajectories, video, calibration, auth, users, survey, enforcement, dashboard
from app.api.v1.drones import router as drones_router
from app.api.v1.drones import telemetry_router
from app.api.v1.pipelines import router as pipelines_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # ── Initialize database ──
    db_available = False
    try:
        db_available = await init_db()
        if not db_available:
            raise RuntimeError("database initialization failed")
        logger.info(f"Database initialized: {settings.db_host}:{settings.db_port}")
    except Exception as e:
        logger.warning(f"Database unavailable (auth features disabled): {e}")

    # ── Initialize components ──
    ws_manager = WSManager()
    alert_store = SqlAlertStore(async_session_maker) if db_available else None
    alert_engine = AlertEngine(ws_manager, settings, alert_store=alert_store)
    await alert_engine.load_persisted_alerts()
    lane_annotation_store = LaneAnnotationStore(
        db_path=settings.lane_annotation_db_path,
        hover_seconds=settings.lane_annotation_hover_seconds,
        hover_radius_m=settings.lane_annotation_hover_radius_m,
    )

    metric_store = PostgresMetricStoreAdapter(async_session_maker) if db_available else None
    enforcement_service = EnforcementService(async_session_maker) if db_available else None
    dashboard_read_model = DashboardReadModel(async_session_maker) if db_available else None

    # Kafka consumer (optional — graceful fallback if unavailable)
    kafka_service = None
    try:
        if metric_store is None:
            raise RuntimeError("database-backed MetricStore is unavailable")
        kafka_service = KafkaConsumerService(
            bootstrap_servers=settings.kafka_bootstrap,
            group_id=settings.kafka_consumer_group,
            topics_pattern=settings.kafka_topics_pattern,
            ws_manager=ws_manager,
            alert_engine=alert_engine,
            lane_annotation_store=lane_annotation_store,
            metric_store=metric_store,
        )
        await kafka_service.start()
        if kafka_service._consumer is not None:
            logger.info(f"Kafka consumer started: {settings.kafka_bootstrap}")
        else:
            logger.warning(f"Kafka consumer degraded: {settings.kafka_bootstrap}")
    except Exception as e:
        logger.warning(f"Kafka consumer failed to start (real-time disabled): {e}")

    # Pipeline manager (always available — manages detection pipeline processes)
    pipeline_manager = PipelineManager(
        kafka_bootstrap=settings.kafka_bootstrap,
        pipeline_python=settings.pipeline_python,
        frame_stride=settings.pipeline_frame_stride,
    )
    mission_orchestrator = None
    if db_available:
        fixture_values = {}
        if settings.local_road_fixture_enabled:
            project_root = Path(__file__).resolve().parents[2]
            roads_path = (project_root / settings.local_road_fixture_roads_json).resolve()
            checksum = hashlib.sha256(roads_path.read_bytes()).hexdigest() if roads_path.is_file() else "unavailable"
            fixture_values[(settings.local_road_fixture_inter_id, settings.local_road_fixture_version)] = RoadContextResult(
                inter_id=settings.local_road_fixture_inter_id,
                road_data_version=settings.local_road_fixture_version,
                source="local_fixture",
                checksum=checksum,
                coordinate_reference={"metric": "ENU", "display": "GCJ02", "status": "unverified"},
                intersection={"roads_json": settings.local_road_fixture_roads_json},
                links=(),
                lanes=(),
                visual_bindings=({
                    "local_lane_id": "fixture",
                    "canonical_link_id": None,
                    "canonical_lane_id": None,
                    "roads_json": settings.local_road_fixture_roads_json,
                    "status": "candidate",
                },),
                quality_status="unverified",
            )
        road_context = RoadContext(
            FallbackRoadContextAdapter(
                Road9RoadContextAdapter(async_session_maker),
                FixtureRoadContextAdapter(fixture_values),
            )
        )
        mission_orchestrator = MissionOrchestrator(
            async_session_maker,
            PipelineManagerAdapter(pipeline_manager),
            road_context,
            poll_sec=settings.mission_scheduler_poll_sec,
        )
    survey_worker = SurveyWorker()
    if db_available:
        await survey_worker.start()
        await mission_orchestrator.start()

    # Store on app state
    app.state.ws_manager = ws_manager
    app.state.alert_engine = alert_engine
    app.state.lane_annotation_store = lane_annotation_store
    app.state.metric_store = metric_store
    app.state.enforcement_service = enforcement_service
    app.state.dashboard_read_model = dashboard_read_model
    app.state.kafka_service = kafka_service
    app.state.pipeline_manager = pipeline_manager
    app.state.survey_worker = survey_worker
    app.state.mission_orchestrator = mission_orchestrator
    app.state.settings = settings
    app.state.db_available = db_available

    logger.info(f"🚀 Traffic Platform started on port {settings.service_port}")
    logger.info(f"   - Database: {settings.db_host}:{settings.db_port}")
    logger.info(f"   - Kafka: {settings.kafka_bootstrap}")
    if metric_store:
        logger.info("   - MetricStore: PostgreSQL/TimescaleDB")

    yield

    # ── Shutdown ──
    if mission_orchestrator:
        await mission_orchestrator.stop()
    await pipeline_manager.stop_all()
    await survey_worker.stop()
    if kafka_service:
        await kafka_service.stop()
    await ws_manager.close_all()
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
app.include_router(pipelines_router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(survey.router, prefix="/api/v1")
app.include_router(survey.evidence_router, prefix="/api/v1")
app.include_router(enforcement.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")


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
        "database": "healthy" if getattr(app.state, "db_available", False) else "degraded",
        "kafka": "unknown",
        "timescaledb": "unknown",
        "pipeline_manager": "healthy",
    }

    # Check Kafka
    kafka_service = app.state.kafka_service if hasattr(app.state, "kafka_service") else None
    if kafka_service and kafka_service._running and kafka_service._consumer is not None:
        services["kafka"] = "healthy"
    elif kafka_service:
        services["kafka"] = "degraded"
    else:
        services["kafka"] = "not_configured"

    metric_store = getattr(app.state, "metric_store", None)
    if metric_store:
        try:
            capabilities = await metric_store.capabilities()
            services["timescaledb"] = "healthy" if capabilities["timescaledb"] else "degraded"
        except Exception:
            services["timescaledb"] = "degraded"
    else:
        services["timescaledb"] = "not_configured"

    # Pipeline manager
    pm = getattr(app.state, "pipeline_manager", None)
    services["pipeline_manager"] = "healthy" if pm else "not_configured"
    pipelines_active = pm.get_active_count() if pm else 0

    all_ready = all(
        v in ("healthy", "not_configured")
        for k, v in services.items()
        if k != "pipelines_active"
    )

    return {
        "status": "ready" if all_ready else "degraded",
        "services": services,
        "pipelines_active": pipelines_active,
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

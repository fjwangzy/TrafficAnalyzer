"""Traffic Platform Monolith — main FastAPI application."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1 import (
    alerts,
    auth,
    calibration,
    dashboard,
    enforcement,
    events,
    intersections,
    survey,
    system,
    trajectories,
    users,
    video,
)
from app.api.v1.drones import router as drones_router
from app.api.v1.drones import telemetry_router
from app.api.v1.pipelines import router as pipelines_router
from app.core.config import settings
from app.core.database import async_session_maker, close_db, init_db, init_replay_v2_db
from app.kafka.consumer import KafkaConsumerService
from app.kafka.ws_manager import WSManager
from app.middleware.auth import AuthMiddleware
from app.services.alert_engine import AlertEngine, SqlAlertStore
from app.services.audit_service import AuditService
from app.services.dashboard_read_model import DashboardReadModel
from app.services.dashboard_situation import DashboardSituationReadModel
from app.services.enforcement_service import EnforcementService
from app.services.event_center import EventCenter
from app.services.lane_annotation_store import LaneAnnotationStore
from app.services.metric_store import PostgresMetricStoreAdapter
from app.services.replay_repository import PostgresReplayRepository
from app.services.replay_v2_metric_store import ReplayV2MetricStoreAdapter
from app.services.mission_orchestrator import MissionOrchestrator, PipelineManagerAdapter
from app.services.pipeline_manager import PipelineManager
from app.services.road_context import (
    Road9RoadContextAdapter,
    RoadContext,
)
from app.services.survey_worker import SurveyWorker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    replay_profile = settings.app_runtime_profile == "replay_v2"
    # ── Initialize database ──
    db_available = False
    try:
        db_available = (
            await init_replay_v2_db() if replay_profile else await init_db()
        )
        if not db_available:
            raise RuntimeError("database initialization failed")
        logger.info(f"Database initialized: {settings.db_host}:{settings.db_port}")
    except Exception as e:
        logger.warning(f"Database unavailable (auth features disabled): {e}")

    # ── Initialize components ──
    ws_manager = WSManager()
    event_center = (
        EventCenter(
            async_session_maker,
            # Listing events must remain read-only and bounded while native MPS
            # replay is appending telemetry.  Quality-gap materialization is an
            # explicit maintenance workflow, never part of GET /events.
            materialize_on_list=False,
        )
        if db_available
        else None
    )
    alert_store = SqlAlertStore(async_session_maker) if db_available else None
    alert_engine = AlertEngine(
        ws_manager, settings, alert_store=alert_store, event_center=event_center
    )
    await alert_engine.load_persisted_alerts()
    if event_center:
        await event_center.sync_alerts()
        await event_center.sync_survey_reports()
    lane_annotation_store = LaneAnnotationStore(
        db_path=settings.lane_annotation_db_path,
        hover_seconds=settings.lane_annotation_hover_seconds,
        hover_radius_m=settings.lane_annotation_hover_radius_m,
    )

    metric_store = (
        ReplayV2MetricStoreAdapter(async_session_maker)
        if db_available and replay_profile
        else PostgresMetricStoreAdapter(async_session_maker)
        if db_available
        else None
    )
    replay_repository = (
        PostgresReplayRepository(async_session_maker)
        if db_available and replay_profile
        else None
    )
    audit_service = AuditService(async_session_maker) if db_available else None
    enforcement_service = EnforcementService(async_session_maker) if db_available else None
    situation_reader = DashboardSituationReadModel(
        settings,
        cache_ttl_sec=settings.dashboard_situation_cache_ttl_sec,
        cache_limit=settings.dashboard_situation_cache_limit,
    )
    dashboard_read_model = (
        DashboardReadModel(async_session_maker, situation_reader=situation_reader)
        if db_available else None
    )

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
            lane_annotation_store=(
                lane_annotation_store if settings.lane_annotation_auto_tasks_enabled else None
            ),
            metric_store=metric_store,
            dispatch_realtime=True,
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
        camera_id_start=settings.pipeline_camera_id_start,
    )
    mission_orchestrator = None
    road_context = None
    if db_available:
        road_context = RoadContext(Road9RoadContextAdapter(async_session_maker))
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
    app.state.replay_repository = replay_repository
    app.state.audit_service = audit_service
    app.state.enforcement_service = enforcement_service
    app.state.dashboard_read_model = dashboard_read_model
    app.state.event_center = event_center
    app.state.kafka_service = kafka_service
    app.state.pipeline_manager = pipeline_manager
    app.state.survey_worker = survey_worker
    app.state.mission_orchestrator = mission_orchestrator
    app.state.road_context = road_context
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
    if survey_worker:
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
app.include_router(events.router, prefix="/api/v1")
app.mount("/hls", StaticFiles(directory=settings.hls_output_dir, check_dir=False), name="hls")


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
        services[name] == "healthy"
        for name in ("database", "kafka", "timescaledb", "pipeline_manager")
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

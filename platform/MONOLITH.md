# Traffic Platform — Monolith Architecture

## Overview

The Traffic Platform has been refactored from a microservices architecture to a monolith architecture. All backend services (gateway, operations, vision, flight) are now consolidated into a single FastAPI application.

## Architecture Changes

### Before (Microservices)
- **Gateway** (port 8000) — API gateway with auth middleware and proxy routing
- **Operations** (port 8001) — User management and authentication
- **Vision** (port 8002) — Traffic analysis, Kafka consumer, alerts, WebSocket
- **Flight** (port 8003) — Drone management
- **Annotation** (port 8004) — Label annotation (placeholder)

### After (Monolith)
- **Platform** (port 8000) — Single FastAPI application with all functionality

## Directory Structure

```
platform/
├── app/                          # Monolith application
│   ├── main.py                   # Main FastAPI app with lifespan
│   ├── core/
│   │   ├── config.py             # Unified settings
│   │   └── database.py           # PostgreSQL connection
│   ├── middleware/
│   │   └── auth.py               # JWT authentication middleware
│   ├── api/v1/                   # All API endpoints
│   │   ├── auth.py               # Authentication endpoints
│   │   ├── intersections.py      # Intersection management
│   │   ├── alerts.py             # Alert system
│   │   ├── system.py             # System metrics
│   │   ├── trajectories.py       # Trajectory analysis
│   │   ├── video.py              # Video streaming
│   │   ├── calibration.py        # Calibration data
│   │   └── drones.py             # Drone management
│   ├── kafka/
│   │   ├── consumer.py           # Kafka consumer service
│   │   └── ws_manager.py         # WebSocket manager
│   ├── services/
│   │   ├── auth_service.py       # Authentication logic
│   │   └── alert_engine.py       # Alert detection engine
│   ├── models/
│   │   ├── user.py               # User database model
│   │   └── drone_store.py        # In-memory drone data
│   ├── schemas/
│   │   └── auth.py               # Pydantic schemas
│   └── utils/
│       └── influx_query.py       # InfluxDB query helper
├── docker/
│   └── docker-compose.platform.yml  # Updated compose file
├── Dockerfile                    # Unified Dockerfile
├── pyproject.toml                # Unified dependencies
└── scripts/
    └── run_local.py              # Local development script
```

## Running Locally

### Prerequisites
- Python 3.11+
- PostgreSQL 16 (optional, graceful degradation if unavailable)
- Kafka (optional, graceful degradation if unavailable)
- InfluxDB 1.8 (optional, graceful degradation if unavailable)

### Start the Application

```bash
cd platform
pip install -e .
python scripts/run_local.py
```

Or directly with uvicorn:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Test Endpoints

```bash
# Health check
curl http://localhost:8000/health

# Readiness check
curl http://localhost:8000/ready

# List intersections (requires auth)
curl -H "Authorization: Bearer <token>" http://localhost:8000/api/v1/intersections

# Register user
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "email": "admin@example.com", "password": "password123", "role": "admin"}'

# Login
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "password123"}'
```

## Running with Docker

```bash
cd platform/docker
docker compose -f docker-compose.platform.yml up -d --build
```

This starts:
- PostgreSQL (port 5432)
- InfluxDB (port 8086)
- Kafka (port 9092)
- **Platform** (port 8000) — the monolith application
- Frontend (port 8080)

### Test Docker Deployment

```bash
# Health check
curl http://localhost:8000/health

# Readiness check (should show all services healthy)
curl http://localhost:8000/ready

# Frontend
open http://localhost:8080
```

## API Endpoints

All endpoints are mounted under `/api/v1/`:

### Authentication
- `POST /auth/register` — Register new user
- `POST /auth/login` — Login and get JWT token
- `GET /auth/me` — Get current user info

### Intersections
- `GET /intersections` — List all intersections
- `GET /intersections/summary` — System-wide summary
- `GET /intersections/{id}` — Get intersection
- `GET /intersections/{id}/stats` — Historical stats
- `GET /intersections/{id}/lane-stats` — Lane-level stats

### Alerts
- `GET /alerts` — List alerts
- `GET /alerts/{id}` — Get alert
- `POST /alerts/{id}/acknowledge` — Acknowledge alert

### System
- `GET /system/health` — System health
- `GET /system/gpu` — GPU metrics
- `GET /system/gpu/history` — GPU history
- `GET /system/kafka/topics` — Kafka topics
- `GET /system/models` — Available models

### Trajectories
- `GET /trajectories/{id}` — Track events
- `GET /trajectories/{id}/heatmap` — Trajectory heatmap
- `GET /trajectories/{id}/turn-summary` — Turn behavior
- `GET /trajectories/{id}/lane-change-heatmap` — Lane changes

### Video
- `GET /video/streams` — List streams
- `POST /video/streams/{id}/start` — Start stream
- `POST /video/streams/{id}/stop` — Stop stream

### Calibration
- `GET /calibration/summary` — Calibration summary
- `GET /calibration/records` — List records
- `GET /calibration/records/{key}` — Get record
- `GET /calibration/coverage/{id}` — Coverage heatmap

### Drones
- `GET /drones` — List drones
- `GET /drones/{id}` — Get drone
- `GET /drones/{id}/trajectory` — Flight trajectory
- `GET /drones/{id}/hover-points` — Hover points
- `GET /missions` — List missions
- `GET /missions/{id}` — Get mission
- `GET /telemetry/{id}` — Latest telemetry
- `GET /telemetry/{id}/history` — Telemetry history

### WebSocket
- `WS /ws/realtime` — Real-time data push

## Configuration

All configuration is in `app/core/config.py` and uses environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVICE_PORT` | 8000 | Application port |
| `DB_HOST` | localhost | PostgreSQL host |
| `DB_PORT` | 5432 | PostgreSQL port |
| `DB_USER` | traffic | Database user |
| `DB_PASSWORD` | traffic123 | Database password |
| `DB_NAME` | traffic_platform | Database name |
| `KAFKA_BOOTSTRAP` | kafka:9092 | Kafka bootstrap servers |
| `INFLUX_HOST` | influxdb | InfluxDB host |
| `INFLUX_PORT` | 8086 | InfluxDB port |
| `INFLUX_DB` | traffic | InfluxDB database |
| `JWT_SECRET_KEY` | (hardcoded) | JWT signing key |

## Frontend Integration

The frontend (`traffic-fly-console`) connects to the monolith at:
- **Local**: `http://localhost:8000/api/v1`
- **Docker**: `http://localhost:8000/api/v1`

Set `VITE_API_BASE` environment variable in the frontend to configure the API URL.

## Graceful Degradation

The application is designed to start even when dependencies are unavailable:

- **PostgreSQL unavailable**: Auth features disabled, other features work
- **Kafka unavailable**: Real-time WebSocket updates disabled, historical queries work
- **InfluxDB unavailable**: Historical queries return empty, real-time features work

Check `/ready` endpoint to see which services are available.

## Migration Notes

### What Changed
1. Consolidated 4 microservices into 1 application
2. Merged all configurations into unified `Settings` class
3. Integrated auth middleware directly (no more proxy)
4. Single Dockerfile instead of 4
5. Simplified docker-compose (removed service containers)

### What Stayed the Same
1. All API endpoints maintain same paths and contracts
2. Frontend requires no changes (uses relative paths)
3. Database schema unchanged
4. Kafka message format unchanged
5. InfluxDB queries unchanged

## Benefits

1. **Simpler deployment**: One container instead of four
2. **Faster development**: No inter-service network calls
3. **Easier debugging**: Single process to attach debugger
4. **Reduced complexity**: No service discovery, no proxy routing
5. **Lower resource usage**: One Python process instead of four

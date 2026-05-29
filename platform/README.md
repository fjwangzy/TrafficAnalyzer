# Traffic Platform

Unified traffic analysis platform — **monolith architecture**.

## Quick Start

### Local Development

```bash
cd platform
pip install -e .
python scripts/run_local.py
```

The application will start on `http://localhost:8000`.

**Note**: The application gracefully degrades when dependencies are unavailable:
- PostgreSQL unavailable → auth features disabled
- Kafka unavailable → real-time updates disabled
- InfluxDB unavailable → historical queries return empty

### Docker Deployment

```bash
cd platform/docker
docker compose -f docker-compose.platform.yml up -d --build
```

This starts the complete stack:
- **Platform** (port 8000) — monolith application
- PostgreSQL (port 5432)
- Kafka (port 9092)
- InfluxDB (port 8086)
- Frontend (port 8080)

## Architecture

The platform uses a **monolith architecture** — a single FastAPI application that consolidates all backend services:

- **Authentication & Users** — JWT-based auth, user management
- **Intersections** — Traffic intersection data and statistics
- **Alerts** — Rule-based and VLM-based alert detection
- **Video** — HLS video streaming
- **Trajectories** — Vehicle trajectory analysis
- **Calibration** — Camera calibration data
- **Drones** — Drone management and telemetry
- **System** — Health checks, GPU metrics, Kafka stats
- **WebSocket** — Real-time data push

See [MONOLITH.md](MONOLITH.md) for detailed architecture documentation.

## API Endpoints

All API endpoints are mounted under `/api/v1/`:

### Authentication
- `POST /auth/register` — Register new user
- `POST /auth/login` — Login and get JWT token
- `GET /auth/me` — Get current user info

### Intersections
- `GET /intersections` — List all intersections
- `GET /intersections/summary` — System-wide summary
- `GET /intersections/{id}` — Get intersection details
- `GET /intersections/{id}/stats` — Historical statistics
- `GET /intersections/{id}/lane-stats` — Lane-level statistics

### Alerts
- `GET /alerts` — List alerts (with filters)
- `GET /alerts/{id}` — Get alert details
- `POST /alerts/{id}/acknowledge` — Acknowledge alert

### System
- `GET /system/health` — System health check
- `GET /system/gpu` — GPU metrics
- `GET /system/gpu/history` — GPU history
- `GET /system/kafka/topics` — Kafka topic stats
- `GET /system/models` — Available YOLO models

### Trajectories
- `GET /trajectories/{id}` — Track events
- `GET /trajectories/{id}/heatmap` — Trajectory heatmap
- `GET /trajectories/{id}/turn-summary` — Turn behavior distribution
- `GET /trajectories/{id}/lane-change-heatmap` — Lane change heatmap

### Video
- `GET /video/streams` — List active streams
- `POST /video/streams/{id}/start` — Start HLS stream
- `POST /video/streams/{id}/stop` — Stop HLS stream

### Calibration
- `GET /calibration/summary` — Calibration summary
- `GET /calibration/records` — List calibration records
- `GET /calibration/records/{key}` — Get specific record
- `GET /calibration/coverage/{id}` — Coverage heatmap

### Drones
- `GET /drones` — List all drones
- `GET /drones/{id}` — Get drone details
- `GET /drones/{id}/trajectory` — Flight trajectory
- `GET /drones/{id}/hover-points` — Hover points
- `GET /missions` — List missions
- `GET /missions/{id}` — Get mission details
- `GET /telemetry/{id}` — Latest telemetry
- `GET /telemetry/{id}/history` — Telemetry history

### WebSocket
- `WS /ws/realtime` — Real-time data push (subscribe to channels)

## Testing

### Health Check
```bash
curl http://localhost:8000/health
```

### Readiness Check
```bash
curl http://localhost:8000/ready
```

Returns status of all dependencies (database, Kafka, InfluxDB).

### Register User
```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "email": "admin@example.com",
    "password": "password123",
    "role": "admin"
  }'
```

### Login
```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "password123"
  }'
```

### Protected Endpoint
```bash
TOKEN="<token_from_login_response>"
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/intersections
```

## Configuration

All configuration is managed through environment variables. See `app/core/config.py` for the complete list.

Key variables:

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
| `JWT_SECRET_KEY` | (hardcoded) | JWT signing key (change in production!) |

## Frontend Integration

The frontend (`traffic-fly-console`) connects to the platform API:

```typescript
// traffic-fly-console/src/lib/api.ts
const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'
```

For local development, set `VITE_API_BASE=http://localhost:8000/api/v1` in the frontend `.env` file.

## Project Structure

```
platform/
├── app/                          # Monolith application
│   ├── main.py                   # FastAPI app entry point
│   ├── core/                     # Configuration and database
│   ├── middleware/               # JWT authentication
│   ├── api/v1/                   # All API endpoints
│   ├── kafka/                    # Kafka consumer and WebSocket
│   ├── services/                 # Business logic
│   ├── models/                   # Database models
│   ├── schemas/                  # Pydantic schemas
│   └── utils/                    # Utilities
├── scripts/
│   └── run_local.py              # Local development script
├── docker/
│   └── docker-compose.platform.yml  # Docker Compose config
├── Dockerfile                    # Docker build file
├── pyproject.toml                # Python dependencies
├── MONOLITH.md                   # Architecture documentation
└── REFACTORING_SUMMARY.md        # Migration details
```

## Development

### Install Dependencies
```bash
pip install -e .
```

### Run with Auto-Reload
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Run Tests
```bash
pytest
```

### Format Code
```bash
black app/
ruff check app/ --fix
```

## Documentation

- [MONOLITH.md](MONOLITH.md) — Detailed architecture documentation
- [REFACTORING_SUMMARY.md](REFACTORING_SUMMARY.md) — Migration from microservices
- [API Contracts](../docs/API_CONTRACTS.md) — API specifications
- [Database Schema](../docs/DATABASE_SCHEMA.md) — Database structure

## License

See [LICENSE](../LICENSE) for details.

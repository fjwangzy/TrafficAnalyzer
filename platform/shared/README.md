# Traffic Platform Shared Library

共享模型和工具库，供所有微服务使用。

## 安装

```bash
cd platform/shared
pip install -e .
```

## 模块结构

### models/ - Pydantic 领域模型

- `intersection.py` - Intersection, Lane, LaneStats
- `vehicle.py` - VehicleDetection, Track, TurnBehavior, LaneChangeEvent
- `alert.py` - Alert, AlertType, AlertSeverity, AlertStatus
- `drone.py` - Drone, DroneTelemetry, DroneStatus
- `calibration.py` - CalibrationRecord, CalibrationQuality
- `report.py` - Report
- `webhook.py` - Webhook, WebhookChannel, AlertPushLog
- `kafka_messages.py` - StatsMessage, DetectionsMessage, TrackCompleteMessage, VLMAnalysisMessage, SystemMetricsMessage

### config/ - 配置管理

基于 `pydantic-settings` 的配置管理：

```python
from traffic_platform.config import get_settings

settings = get_settings()
print(settings.db.url)
print(settings.kafka.bootstrap_servers)
print(settings.jwt.secret_key)
```

支持通过环境变量或 `.env` 文件配置：

```bash
export DB_HOST=localhost
export DB_PORT=5432
export KAFKA_BOOTSTRAP_SERVERS=kafka:9092
export JWT_SECRET_KEY=your-secret-key
```

### auth/ - JWT 认证

```python
from traffic_platform.auth import create_access_token, verify_token, get_current_user

# 创建 token
token = create_access_token(
    data={"sub": "user123", "username": "admin", "role": "admin"}
)

# 验证 token
payload = verify_token(token)
print(payload.username, payload.role)

# FastAPI 依赖注入
from fastapi import Depends

@app.get("/protected")
async def protected_route(user: TokenPayload = Depends(get_current_user)):
    return {"user": user.username}

# 角色控制
from traffic_platform.auth.jwt import require_role

@app.get("/admin-only")
async def admin_route(user: TokenPayload = Depends(require_role("admin"))):
    return {"message": "Admin access granted"}
```

### utils/ - 工具函数

#### InfluxDB 客户端

```python
from traffic_platform.utils import get_influx_client

client = get_influx_client()

# 查询路口统计
stats = client.query_stats("INT_001", time_range="1h", group_by="1m")

# 查询车道级指标
lane_stats = client.query_lane_stats("INT_001", lane_id=1, time_range="1h")

# 查询轨迹事件
tracks = client.query_track_events("INT_001", time_range="1h")

# 写入数据点
client.write_point(
    measurement="intersection_stats",
    tags={"intersection_id": "INT_001"},
    fields={"total_vehicles": 150, "congestion_index": 2.5},
)
```

#### 时间工具

```python
from traffic_platform.utils import format_timestamp, get_time_range, TimeRange

# 格式化时间
formatted = format_timestamp(datetime.now())  # "2026-05-28 14:30:00"

# 获取时间范围
start, end = get_time_range(TimeRange.LAST_24_HOURS)

# 格式化持续时间
duration = format_duration(3665)  # "1h 1m 5s"
```

## 依赖关系

本库被以下服务依赖：

- `platform/gateway` - API 网关
- `platform/services/operations` - 运营服务
- `platform/services/vision-analysis` - 视觉分析服务
- `platform/services/flight-control` - 飞控服务
- `platform/services/annotation` - 标注服务

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest

# 代码格式化
black .
ruff check .
```

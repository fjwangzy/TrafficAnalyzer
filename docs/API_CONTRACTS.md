# API_CONTRACTS.md — TrafficAnalyzer API 契约

> 基于 commit `e69acee` 的真实代码分析。

## 1. Kafka 消息契约

### Topic 命名
- 统计：`statistics_{camera_id}`（如 `statistics_1`）
- 完成轨迹：`track_complete_{camera_id}`（如 `track_complete_1`）
- 冲突事件：`conflicts_{camera_id}`（如 `conflicts_1`）

### 统计消息格式（statistics_{n}，向后兼容扩展）
```json
{
  "camera_id": "id_1",
  "cars": 12,
  "msg_type": "stats",
  "intersection_id": "INT_camera_1",
  "road_1": 4.2,
  "road_2": 3.8,
  "road_3": null,
  "road_4": 2.1,
  "road_5": 1.5,
  "direction_flow": {
    "straight": {"count": 5, "avg_speed_kmh": 28.3, "avg_headway_sec": 2.1, "min_headway_sec": 1.5},
    "left_turn": {"count": 3, "avg_speed_kmh": 22.1, "avg_headway_sec": null, "min_headway_sec": null},
    "right_turn": {"count": 2, "avg_speed_kmh": 25.0, "avg_headway_sec": null, "min_headway_sec": null},
    "u_turn": {"count": 0, "avg_speed_kmh": 0, "avg_headway_sec": null, "min_headway_sec": null},
    "unknown": {"count": 1}
  },
  "queue_count": 2,
  "avg_speed_kmh": 26.5,
  "lane_stats": null,
  "conflict_count": 0,
  "drone_position": {
    "anchor_lat": 31.234567,
    "anchor_lon": 121.456789,
    "easting_m": 15.3,
    "northing_m": -8.2
  },
  "is_hovering": false
}
```

### 完成轨迹消息格式（track_complete_{n}）
```json
{
  "msg_type": "track_complete",
  "intersection_id": "INT_camera_1",
  "track_id": 142,
  "start_road": 1,
  "exit_road": 3,
  "turn_behavior": "left_turn",
  "vehicle_class": "motor",
  "yolo_class_id": 2,
  "duration_sec": 8.4,
  "avg_speed_kmh": 22.3,
  "max_speed_kmh": 35.1,
  "trajectory_px": [[100,200], [105,210]],
  "trajectory_world_m": [[12.3, -5.2], [12.8, -4.9]],
  "entry_point_m": [10.1, -6.5],
  "exit_point_m": [18.4, 2.1],
  "world_anchor_lat_lon": [31.234567, 121.456789],
  "timestamp_first": 120.5,
  "timestamp_last": 128.9
}
```

### 冲突事件消息格式（conflicts_{n}）
```json
{
  "msg_type": "conflict",
  "intersection_id": "INT_camera_1",
  "motor_id": 142,
  "non_motor_id": 156,
  "motor_position_m": [12.3, -5.2],
  "non_motor_position_m": [12.8, -4.9],
  "distance_m": 2.3,
  "ttc_sec": 1.5,
  "severity": "warning",
  "motor_speed_kmh": 25.0,
  "world_anchor_lat_lon": [31.234567, 121.456789]
}
```

### 世界坐标说明

所有世界坐标使用**东北天(ENU)**坐标系，单位为米，原点为世界锚点GPS位置：
- `easting_m` (+X) = 东向偏移
- `northing_m` (+Y) = 北向偏移

**GPS还原公式**：
```
lat = anchor_lat + northing_m / 111320
lon = anchor_lon + easting_m / (111320 × cos(radians(anchor_lat)))
```

### 字段说明（统计消息）
| 字段 | 类型 | 说明 |
|------|------|------|
| `camera_id` | string | 格式 `id_{N}`，N 为摄像头编号 |
| `cars` | int | 当前帧滑动窗口平均车辆数 |
| `road_1` ~ `road_5` | float \| null | 每条道路的车辆活跃度（辆/分钟） |
| `msg_type` | string | 消息类型标识（"stats"） |
| `intersection_id` | string | 路口标识（`INT_camera_{N}`） |
| `direction_flow` | dict \| null | 方向流量统计（始终输出） |
| `queue_count` | int | 当前排队车辆数 |
| `avg_speed_kmh` | float | 整体平均车速 |
| `lane_stats` | dict \| null | 车道级统计（有标注时输出） |
| `conflict_count` | int | 当前帧冲突事件数 |
| `drone_position` | dict \| null | 无人机位置（有遥测时输出） |
| `is_hovering` | bool | 是否悬停 |

### 发送频率
- 由 `kafka_producer_node.how_often_sec` 控制（默认 1 秒）
- 第一帧始终发送

### 生产者
- 文件：`nodes/KafkaProducerNode.py`
- 序列化：`json.dumps(x).encode("utf-8")`
- 同步发送：`.get(timeout=1)`（阻塞等待 broker 确认）

### 消费者
- Telegraf `[[inputs.kafka_consumer]]`
- 配置：`services/telegraf/telegraf.conf`

### ⚠️ 契约约束
- **不可更改字段名**：Grafana 仪表盘的 InfluxQL 查询直接引用 `road_1`~`road_5`
- **不可更改 road 数量**：硬编码 5 条道路，增减需要同时修改 CalcStatisticsNode、KafkaProducerNode、Telegraf、Grafana 仪表盘
- **不可更改 topic 命名规则**：Telegraf 配置中按 topic 名匹配

## 2. Flask 视频流 API

### 端点

#### `GET /`
- 返回：HTML 页面（`utils_local/templates/index.html`）
- 内容：包含 `<img src="/video"/>` 的简单页面

#### `GET /video`
- 返回：`multipart/x-mixed-replace; boundary=frame` MJPEG 流
- 每帧格式：JPEG 编码的 numpy 数组
- 帧尺寸：由 `video_server_node.output_size` 控制（默认 `[800, 470]`）
- 绑定地址：`0.0.0.0:8100`

### 技术细节
- 使用 Flask 的 `Response` 生成器实现流式推送
- 帧通过 `cv2.imencode('.jpg', frame)` 编码
- 服务器在守护线程中运行（`Thread(daemon=True)`）
- 帧更新通过 `self._frame` 实例变量，无锁保护（可能出现撕裂）

## 3. Nginx 反向代理路由

### 路由规则
```nginx
location ~ ^/camera_(\d+)$ {
    resolver 127.0.0.11 [::1];
    set $camera_id $1;
    proxy_pass http://traffic_analyzer_camera_$camera_id:8100/video;
}
```

### 访问方式
| URL | 代理到 |
|-----|--------|
| `http://localhost:8009/camera_1` | `traffic_analyzer_camera_1:8100/video` |
| `http://localhost:8009/camera_2` | `traffic_analyzer_camera_2:8100/video` |
| `http://localhost:8009/camera_N` | `traffic_analyzer_camera_N:8100/video` |

### 约束
- 容器名必须遵循 `traffic_analyzer_camera_{N}` 格式
- Nginx 使用 Docker 内部 DNS（`127.0.0.11`）解析容器名
- 只代理 `/video` 端点，不代理 `/`

## 4. InfluxDB 数据模型

### 数据库
- 名称：`influx`
- 版本：InfluxDB 1.8
- 保留策略：30 天自动删除

### Measurement
- 命名：`camera_{N}`（由 Telegraf `name_override` 控制）
- 每个摄像头一个 measurement

### 字段
| 字段 | 类型 | 说明 |
|------|------|------|
| `cars` | float | 车辆总数（滑动窗口平均） |
| `road_1` ~ `road_5` | float | 道路活跃度（辆/分钟） |
| `camera_id` | string | 摄像头标识（`id_N`） |

### 标签
- 无自定义标签（Telegraf 默认添加 `host` 标签）

### 查询示例（Grafana InfluxQL）
```sql
-- 车辆数时序图
SELECT mean("cars") FROM "camera_1" WHERE $timeFilter GROUP BY time($interval)

-- 当前道路拥堵
SELECT road_1, road_2, road_3, road_4, road_5 FROM "camera_1" ORDER BY time DESC LIMIT 1

-- 道路拥堵趋势
SELECT road_1, road_2, road_3, road_4, road_5 FROM "camera_1" ORDER BY time DESC
```

## 5. 管道节点接口

### 标准接口
```python
class SomeNode:
    def __init__(self, config: dict) -> None:
        """从 Hydra 配置字典初始化节点"""
        ...

    def process(self, frame_element: FrameElement) -> FrameElement:
        """处理一帧，返回增强的 FrameElement"""
        if isinstance(frame_element, VideoEndBreakElement):
            return frame_element
        ...
        return frame_element
```

### 特殊接口

#### VideoReader（生成器模式）
```python
def process(self) -> Generator[FrameElement, None, None]:
    """逐帧产出 FrameElement，流结束时产出 VideoEndBreakElement"""
```

#### VideoSaverNode（终端节点）
```python
def process(self, frame_element: FrameElement) -> None:
    """写入帧到文件，收到 VideoEndBreakElement 时释放资源"""
```

#### FlaskServerVideoNode.VideoServer（终端节点）
```python
def process(self, frame_element: FrameElement) -> None:
    """更新帧缓冲区，Flask 线程持续推送"""
```

## 6. Grafana API（管理脚本使用）

### 获取仪表盘
```
GET http://localhost:3111/api/dashboards/uid/{uid}
Authorization: Basic {base64(admin:admin)}
```

### 更新仪表盘
```
POST http://localhost:3111/api/dashboards/db
Content-Type: application/json
{
  "dashboard": {...},
  "message": "update reason",
  "overwrite": true
}
```

### 已知仪表盘 UID
| 摄像头 | UID |
|--------|-----|
| Camera 1 | `edycr94pt2mm8b` |
| Camera 2 | `adycu34xs035sb` |

### ⚠️ 安全风险
- `export_dashboards.py` 和 `fetch_dashboard.py` 中硬编码了 `admin:admin` 凭据
- 这些脚本仅用于开发环境，生产环境不应使用

---

## 7. 平台 Web 服务 API（platform/app/api/v1/）

> 2026-05-29 从微服务重构为单体架构，所有端点路径和响应格式保持不变。

### 基础 URL
- 本地开发：`http://localhost:8000`
- Docker Compose：`http://localhost:8000`（通过 nginx 代理：`http://localhost:8080/api/`）

### 健康检查端点（无需认证）

#### `GET /health`
- 返回：`{"status": "healthy"}`
- 用途：存活检查（liveness probe）

#### `GET /ready`
- 返回：
```json
{
  "status": "ready",
  "services": {
    "database": "healthy",
    "kafka": "healthy",
    "influxdb": "healthy",
    "websocket": "healthy"
  }
}
```
- 用途：就绪检查（readiness probe），各服务可能为 `healthy`、`degraded` 或 `unavailable`

### 认证端点（无需 JWT）

#### `POST /api/v1/auth/register`
- 请求体：
```json
{
  "username": "string",
  "email": "user@example.com",
  "password": "string",
  "role": "viewer"
}
```
- 返回（201）：
```json
{
  "id": 1,
  "username": "string",
  "email": "user@example.com",
  "role": "viewer",
  "is_active": true
}
```
- 错误（400）：`{"detail": "Username already registered"}`

#### `POST /api/v1/auth/login`
- 请求体：
```json
{
  "username": "string",
  "password": "string"
}
```
- 返回（200）：
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```
- 错误（401）：`{"detail": "Incorrect username or password"}`

#### `GET /api/v1/auth/me`
- 请求头：`Authorization: Bearer <token>`
- 返回（200）：
```json
{
  "id": 1,
  "username": "string",
  "email": "user@example.com",
  "role": "admin",
  "is_active": true
}
```

### 受保护端点（需 Bearer token）

#### `GET /api/v1/intersections`
- 请求头：`Authorization: Bearer <token>`
- 返回（200）：
```json
{
  "intersections": [
    {
      "id": "int-001",
      "name": "Demo Roundabout A",
      "roads": 5,
      "cameras": 2
    }
  ]
}
```

#### `GET /api/v1/drones`
- 请求头：`Authorization: Bearer <token>`
- 返回（200）：
```json
[
  {
    "id": "DJI-M300-001",
    "model": "DJI Matrice 300 RTK",
    "status": "idle",
    "battery": 85
  }
]
```

#### `POST /api/v1/drones`
- 请求头：`Authorization: Bearer <token>`
- 请求体：
```json
{
  "id": "string",
  "model": "string",
  "status": "idle"
}
```
- 返回（201）：创建的无人机对象

#### `GET /api/v1/system/health`
- 请求头：`Authorization: Bearer <token>`
- 返回（200）：
```json
{
  "status": "healthy",
  "uptime_seconds": 3600,
  "kafka_connected": true,
  "influxdb_connected": true
}
```

### WebSocket 端点

#### `WS /ws/{channel}`
- 连接后发送订阅消息：
```json
{
  "action": "subscribe",
  "channels": ["stats:int-001", "alerts:int-001"]
}
```
- 服务端推送消息格式：
```json
{
  "type": "stats",
  "data": {
    "intersection_id": "int-001",
    "cars": 12,
    "timestamp": "2026-05-29T10:00:00Z"
  }
}
```
- Channel 命名：
  - `stats:{intersection_id}` — 实时统计
  - `alerts:{intersection_id}` — 告警
  - `detections:{intersection_id}` — 检测事件

### 认证机制
- JWT token 在 `Authorization: Bearer <token>` 头中传递
- Token 包含 `sub`（user_id）、`username`、`role` 字段
- 中间件在 `platform/app/middleware/auth.py` 中实现
- 公开路径白名单：`/health`、`/ready`、`/api/v1/auth/login`、`/api/v1/auth/register`、`/docs`、`/openapi.json`

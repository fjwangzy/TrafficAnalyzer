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
  "active_tracks": 12,
  "active_trajectories": [
    {
      "track_id": 142,
      "vehicle_class": "motor",
      "yolo_class_id": 3,
      "direction_class": "straight",
      "turn_behavior": null,
      "duration_sec": 3.2,
      "avg_speed_kmh": 18.4,
      "max_speed_kmh": 27.6,
      "trajectory_px": [[100,200], [105,210]],
      "trajectory_world_m": [[12.3, -5.2], [12.8, -4.9]],
      "current_point_m": [12.8, -4.9],
      "world_anchor_lat_lon": [31.234567, 121.456789],
      "timestamp_first": 120.5,
      "timestamp_last": 123.7
    }
  ],
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
  "lane_source": "model",
  "lanes": [],
  "road_polygons": {
    "1": [1195, 361, 1297, 310, 1399, 315, 1350, 380]
  },
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
  "arrival_time_delta_sec": 0.0,
  "motor_arrival_ttc_sec": 1.5,
  "non_motor_arrival_ttc_sec": 1.5,
  "severity": "warning",
  "motor_speed_kmh": 25.0,
  "world_anchor_lat_lon": [31.234567, 121.456789]
}
```

冲突检测默认启用（`conflict_detection.enabled: true`），但无有效单应性矩阵或双方世界坐标速度向量时会自动跳过，避免像素距离误报。`ttc_sec` 基于 motor/non_motor 当前世界坐标速度向量做未来 `0-5s` 轨迹预测；双方未来位置在同一预测时刻进入 `collision_radius_m`（默认 `2.0m`），或双方预测路径存在空间交点且到达时间差不超过 `arrival_time_tolerance_sec`（默认 `1.0s`）时触发。只有未来轨迹碰撞才会上报 `conflict`。`distance_m` 表示预测冲突时刻的双方距离，路径交点场景为 `0.0`；`motor_position_m` / `non_motor_position_m` 表示预测冲突点附近的双方未来世界坐标。`motor_arrival_ttc_sec` / `non_motor_arrival_ttc_sec` 表示双方到达冲突点的预测时间。`motor_id` / `non_motor_id` 轨迹对同级别事件不重复上报，但允许从 `warning` 升级为 `critical` 再次上报，直到轨迹清理后释放状态。Platform Kafka consumer 的实时冲突缓存和 WebSocket 推送同样按 `motor_id` / `non_motor_id` upsert，同级重复消息会被丢弃，升级消息会替换原事件并重新推送。机非分类由 `vehicle_classification.non_motor_class_names` / `non_motor_class_ids` 配置非机动车集合；未配置的已知检测类别按机动车处理。摩托车、电动车相关类别默认归入非机动车。

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
| `active_tracks` | int | 当前帧活跃跟踪目标数 |
| `active_trajectories` | array | 当前活跃轨迹轻量快照，用于平台 BEV 与检测画面同频实时投放；每项包含最近尾部 `trajectory_px`、`trajectory_point_count`、`trajectory_tail_start`、`is_trajectory_tail`，有有效单应性/运动补偿时包含尾部 `trajectory_world_m`、`current_point_m`、`world_anchor_lat_lon` |
| `road_1` ~ `road_5` | float \| null | 每条道路的车辆活跃度（辆/分钟） |
| `msg_type` | string | 消息类型标识（"stats"） |
| `intersection_id` | string | 路口标识（`INT_camera_{N}`） |
| `direction_flow` | dict \| null | 方向流量统计（始终输出） |
| `queue_count` | int | 当前排队车辆数 |
| `avg_speed_kmh` | float | 整体平均车速 |
| `lane_stats` | dict \| null | 车道级统计（有标注或模型检测时输出） |
| `lane_source` | string \| null | 车道数据来源：`"manual"` / `"model"` / `"auto"` / `null` |
| `road_polygons` | dict | 当前检测配置中的道路多边形，供悬停生成标注任务后导出复用 |
| `conflict_count` | int | 当前帧冲突事件数 |
| `drone_position` | dict \| null | 无人机位置（有遥测时输出） |
| `is_hovering` | bool | 是否悬停 |

### 发送频率
- 由 `kafka_producer_node.how_often_sec` 控制（默认 1 秒）
- 第一帧始终发送
- `active_trajectories` 随统计消息发送，是活跃轨迹的当前尾部快照，避免长时间运行时 Kafka 单条消息无限增长；console 按 `track_id` 累积尾部点列用于 BEV 显示和 GeoJSON 导出，车辆离场/超出分析窗口后的完整轨迹仍通过 `track_complete_{n}` 发送。

### BEV GeoJSON 导出
- Console BEV 视图导出时会合并三类轨迹：当前活跃轨迹快照、当前会话已完成轨迹、历史 API 查询轨迹。
- 展示层可限制绘制数量以保持流畅，但导出使用当前会话缓存的全量轨迹数据，不受 BEV 显示上限裁剪。
- GeoJSON `properties` 会保留 `trajectory_world_m`、`trajectory_px`、`track_id`、车辆类型、速度、时间戳、转向行为等原始字段，便于离线复盘。

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
- 帧尺寸：由 `video_server_node.output_size` 控制（默认 `[1280, 720]`）
- JPEG 质量：由 `video_server_node.jpeg_quality` 控制（默认 `92`）
- 绑定地址：`0.0.0.0:8100`

### 技术细节
- 使用 Flask 的 `Response` 生成器实现流式推送
- 帧通过 `cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])` 编码
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
- Docker Compose：Platform API `http://localhost:8000`；Console `http://localhost:8080`（Console 内部通过 `/api/` 代理到 `platform:8000`）

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

### 用户只读端点（需要 JWT）

#### `GET /api/v1/users`
- 用途：Console 的 Admin / Users 页面展示真实平台用户，不返回密码哈希。
- 返回：
```json
[
  {
    "id": 1,
    "username": "admin",
    "email": "admin@example.com",
    "role": "admin",
    "is_active": true,
    "created_at": "2026-05-29T00:00:00"
  }
]
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
  "channels": ["intersection:INT_camera_1", "alerts", "telemetry:drone_001"]
}
```
- 服务端推送消息格式：
```json
{
  "channel": "intersection:INT_camera_1",
  "type": "stats",
  "data": {
    "intersection_id": "INT_camera_1",
    "cars": 12,
    "direction_flow": {...},
    "drone_position": {...}
  },
  "ts": 1234567890.123
}
```
- Channel 命名（已对齐 Kafka topic）：
  - `intersection:{intersection_id}` — 实时统计 + 轨迹完成 + 冲突事件
  - `alerts` — 系统级告警（AlertEngine 触发）
  - `telemetry:{drone_id}` — 无人机实时遥测
  - `system` — GPU/系统指标

### 认证机制
- JWT token 在 `Authorization: Bearer <token>` 头中传递
- Token 包含 `sub`（user_id）、`username`、`role` 字段
- 中间件在 `platform/app/middleware/auth.py` 中实现
- 公开路径白名单：`/health`、`/ready`、`/api/v1/auth/login`、`/api/v1/auth/register`、`/docs`、`/openapi.json`

## 8. 平台 REST API（43 条路由）

### 管道管理 `/api/v1/pipelines`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/pipelines` | 列出所有管道实例 |
| GET | `/api/v1/pipelines/summary` | 管道概览（running/stopped/error 计数） |
| POST | `/api/v1/pipelines` | 启动新管道（201 Created） |
| GET | `/api/v1/pipelines/{id}` | 获取管道详情 |
| GET | `/api/v1/pipelines/{id}/status` | 获取管道健康状态 |
| DELETE | `/api/v1/pipelines/{id}` | 停止管道（进程组 SIGTERM → 10s → SIGKILL） |

#### 启动管道请求体
```json
{
  "drone_id": "drone_001",
  "intersection_id": "INT_camera_1",
  "video_src": "rtsp://192.168.1.100:554/stream",
  "roads_json": "configs/entry_exit_lanes.json",
  "telemetry_source": "srt",
  "telemetry_file_path": "test_videos/inter_xqh/telemetry.srt"
}
```

`roads_json` 可传空字符串，平台会把子进程 `ROADS_JSON` 置空，检测管道按无道路标注模式运行。未显式传自定义道路文件且仍为默认 `configs/entry_exit_lanes.json` 时，平台会优先查找该路口已保存的人工车道标注导出文件。

本地开发可通过环境变量控制平台启动的检测器子进程：
- `PIPELINE_PYTHON`：检测器 Python 解释器，例如 `/Users/yaoyao/miniconda3/envs/py312/bin/python`
- `PIPELINE_FRAME_STRIDE`：写入检测器 `FRAME_STRIDE` 环境变量，例如 `3`
- `KAFKA_BOOTSTRAP`：检测器和平台 Kafka 地址，例如 `localhost:9092`

平台会为每条检测管道创建独立进程组；停止管道时终止整个进程组，避免 `main_optimized.py` 的 multiprocessing worker 被父进程遗留后继续向 Kafka 写数据。

#### 管道响应体
```json
{
  "pipeline_id": "pipe-a1b2c3d4",
  "drone_id": "drone_001",
  "intersection_id": "INT_camera_1",
  "video_src": "rtsp://...",
  "roads_json": "configs/entry_exit_lanes.json",
  "topic_name": "statistics_10",
  "camera_id": 10,
  "video_port": 8101,
  "status": "running",
  "started_at": 1234567890.123,
  "stopped_at": 0,
  "error_message": "",
  "uptime_seconds": 120.5
}
```

### 路口管理 `/api/v1/intersections`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/intersections` | 列出所有路口 |
| GET | `/api/v1/intersections/summary` | 系统级概览（车流量/拥堵/告警/无人机在线/管道数） |
| GET | `/api/v1/intersections/{id}` | 路口详情（含当前分配的无人机信息） |
| GET | `/api/v1/intersections/{id}/stats` | 历史统计（InfluxDB） |
| GET | `/api/v1/intersections/{id}/lane-stats` | 车道级历史统计 |

### 无人机管理 `/api/v1/drones`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/drones` | 列出所有无人机（drone_store 实时状态） |
| GET | `/api/v1/drones/{id}` | 无人机详情 + 最后遥测 |
| GET | `/api/v1/drones/{id}/trajectory` | 无人机飞行轨迹 |
| GET | `/api/v1/drones/{id}/hover-points` | 悬停点位列表 |
| GET | `/api/v1/telemetry/{id}` | 最新遥测数据 |
| GET | `/api/v1/telemetry/{id}/history` | 遥测历史 |
| GET | `/api/v1/missions` | 任务列表 |
| GET | `/api/v1/missions/{id}` | 任务详情 |

### 系统监控 `/api/v1/system`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/system/health` | 健康检查（含 pipelines_active） |
| GET | `/api/v1/system/gpu` | GPU 实时指标 |
| GET | `/api/v1/system/gpu/history` | GPU 历史（InfluxDB） |
| GET | `/api/v1/system/kafka/topics` | Kafka topic 状态 |
| GET | `/api/v1/system/kafka/consumers` | Kafka consumer group 状态 |
| GET | `/api/v1/system/models` | YOLO 模型列表 |

### 标定中心 `/api/v1/calibration`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/calibration/summary` | 标定参数摘要 |
| GET | `/api/v1/calibration/records` | 标定参数记录 |
| GET | `/api/v1/calibration/lane-tasks` | 车道标注任务列表 |
| GET | `/api/v1/calibration/lane-tasks/{task_id}/image` | 车道标注任务 JPEG 快照，供浏览器画布加载 |
| GET | `/api/v1/calibration/lane-annotations` | 已保存车道标注参数列表 |
| GET | `/api/v1/calibration/lane-annotations/{intersection_id}` | 查询某路口可复用车道参数 |
| POST | `/api/v1/calibration/lane-tasks/{task_id}/annotation` | 保存人工车道标注结果 |

车道标注任务由 Kafka `stats` 消息触发：同一路口 `is_hovering=true` 且 `drone_position.easting_m/northing_m` 在 `lane_annotation_hover_radius_m` 半径内持续超过 `lane_annotation_hover_seconds`（默认 30 秒），并且该路口没有已保存人工车道参数时，平台生成一个 `pending` 任务。悬停 stats 会携带压缩 JPEG 快照字段 `annotation_snapshot_jpeg` 以及 `annotation_snapshot_width/height`；平台收到后落盘为任务图片，并通过 `image_url` 返回给 console 车道标注画布。

保存请求：

```json
{
  "lanes": [
    {
      "lane_id": "L1",
      "name": "直行车道",
      "direction": "straight",
      "polygon": [0, 0, 10, 0, 10, 20, 0, 20]
    }
  ],
  "roads": {
    "1": [0, 0, 10, 0, 10, 20, 0, 20]
  }
}
```

保存后平台会写入 `lane_annotation_db_path`，并导出管道可直接读取的扩展 JSON：

```json
{
  "roads": {"1": [0, 0, 10, 0, 10, 20, 0, 20]},
  "lanes": {
    "L1": {
      "name": "直行车道",
      "direction": "straight",
      "polygon": [0, 0, 10, 0, 10, 20, 0, 20]
    }
  },
  "calibration": {"source": "manual_lane_annotation"}
}
```

后续飞行启动检测管道时，将该导出文件作为 `roads_json` 即可复用人工车道标注；`VideoReader` 会读取 `lanes` 并让 `LaneDetectionNode` 标记为 `lane_source="manual"`。

平台 `POST /api/v1/pipelines` 在调用方未显式指定自定义 `roads_json`（仍为默认 `configs/entry_exit_lanes.json`）时，会优先查找该 `intersection_id` 的已保存车道标注，命中后自动把 `roads_json` 替换为导出文件路径。

### 就绪检查 `/ready`

```json
{
  "status": "ready",
  "services": {
    "database": "healthy",
    "kafka": "healthy",
    "influxdb": "healthy",
    "pipeline_manager": "healthy"
  },
  "pipelines_active": 2
}
```

## 9. WebSocket 消息类型

### `stats` 消息
通过 `intersection:{id}` 频道推送，与 Kafka statistics topic 格式一致（含 direction_flow, drone_position, lane_stats）。

### `track_complete` 消息
通过 `intersection:{id}` 频道推送，与 Kafka track_complete topic 格式一致（含 trajectory_px, trajectory_world_m, turn_behavior）。

### `conflict` 消息
通过 `intersection:{id}` 频道推送，与 Kafka conflicts topic 格式一致。
- Monitoring 页面会保留并显示最近 20 个实时冲突 pair；同一 `motor_id` / `non_motor_id` 的重复消息会合并为一条事件行。点击事件行会在 BEV 上叠加 motor/non_motor 短时回放层，回放控制状态与实时 `active_trajectories` 投放解耦。
- severity="critical" → AlertEngine 创建 P1 告警
- severity="warning" → AlertEngine 创建 P2 告警

### `telemetry` 消息
通过 `telemetry:{drone_id}` 频道推送：
```json
{
  "channel": "telemetry:drone_001",
  "type": "telemetry",
  "data": {
    "drone_id": "drone_001",
    "lat": 36.702909,
    "lon": 117.022330,
    "alt_agl": 130.0,
    "gimbal_pitch": -90.0,
    "gimbal_yaw": 0.8,
    "horizontal_speed": 0.0,
    "is_hovering": true,
    "timestamp": 1234567890.123
  },
  "ts": 1234567890.456
}
```

### `alert_new` 消息
通过 `alerts` 频道推送（AlertEngine 触发）：
```json
{
  "channel": "alerts",
  "type": "alert_new",
  "data": {
    "id": "alert-xxx",
    "intersection_id": "INT_camera_1",
    "alert_type": "conflict",
    "severity": "P1",
    "title": "机非冲突 (TTC=1.5s)",
    "status": "open",
    "created_at": "2026-05-30T21:00:00Z"
  },
  "ts": 1234567890.789
}
```

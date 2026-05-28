# 无人机交通态势监测平台 — 功能/服务/模型规格

> 日期：2026-05-28
> 方案：Layer-first 分 3 批交付
> 关联规划：`docs/无人机交通态势监测_POC规划_v1.0.md`
> 关联 spec：`docs/superpowers/specs/2026-05-27-annotation-tool-design.md`

---

## 1. Context

无人机路口交通态势监测系统需要一个统一平台 UI，为 CTO/技术负责人展示工程能力，为交警/交管部门提供实时指挥和告警闭环。当前系统已有 TrafficAnalyzer 管道（YOLO + ByteTrack + Kafka + InfluxDB + Grafana）和标注工具（已完成 spec），但缺少：

- 统一的前端入口（导航、主题、路由）
- 实时数据推送通道（WebSocket）
- 视频流浏览器播放方案（HLS）
- 告警规则引擎和推送服务
- GIS 地图总览
- 报告生成服务

本 spec 定义平台的**功能、服务、模型**三层设计，UI 层由 open design 工具细化。

---

## 2. 关键决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 项目组织 | Monorepo（`platform/frontend/` + `platform/backend/`） | 前后端类型共享，一个 docker-compose 启动 |
| 标注工具集成 | iframe 嵌入（已有 Vanilla JS 实现） | 复用已有代码，不重写 |
| 分解方式 | 按技术层分 3 批（基础设施 → 业务页面 → 高级功能） | 组件复用率高，代码质量好 |
| 主题系统 | 纯 CSS 变量换肤（CTO/交警双主题） | 布局功能不变，只切配色 |
| 实时数据 | FastAPI + WebSocket（自建，不嵌入 Grafana） | 最灵活，UI 风格统一 |
| GIS 地图 | OpenLayers + 高德/天地图瓦片 | 国内合规，免费 |
| 视频播放 | HLS 推流（FFmpeg 转码，hls.js 播放） | 画质好，带宽低，支持自适应码率 |

---

## 3. 数据模型

### 3.1 领域模型（Pydantic）

```python
# ═══════════════════════════════════════════
# 路口与车道
# ═══════════════════════════════════════════

class Intersection(BaseModel):
    id: str                    # "INT_小清河水屯"
    name: str                  # "小清河北路×水屯路"
    center_lat: float          # 36.7029103
    center_lon: float          # 117.0222766
    lane_count: int            # 5
    lanes: list[Lane]
    status: str                # active/inactive/error
    current_drone_id: str | None
    last_active_at: datetime | None

class Lane(BaseModel):
    id: int                    # 1, 2, 3...
    name: str                  # "南向北直行"
    direction: str             # inbound/outbound
    width_m: float             # 3.5
    polygon_bev: list[list[float]]  # [[x,y],...]
    speed_limit: int | None    # km/h

class LaneStats(BaseModel):
    """车道级实时统计（每秒刷新）"""
    lane_id: int
    flow_veh_per_min: float    # 交通流量（辆/分钟）
    headway_sec: float | None  # 车头时距（秒），车道内 <2 辆车时为 None
    queue_length_m: float      # 排队长度（米），<2 辆车时为 0
    vehicle_count: int         # 当前车道内车辆数
    avg_speed_kmh: float       # 车道内平均速度

class TurnBehavior(str, Enum):
    """转向行为分类（基于 BEV 轨迹的进出车道组合）"""
    STRAIGHT = "straight"      # 直行：进车道与出车道方向相同
    LEFT_TURN = "left_turn"    # 左转
    RIGHT_TURN = "right_turn"  # 右转
    U_TURN = "u_turn"          # 掉头：进车道与出车道方向相反

class LaneChangeEvent(BaseModel):
    """单次换道事件"""
    from_lane: int             # 换道前车道 ID
    to_lane: int               # 换道后车道 ID
    bev_x: float               # 换道发生位置 X（米）
    bev_y: float               # 换道发生位置 Y（米）
    timestamp: float           # 换道发生时刻

# ═══════════════════════════════════════════
# 车辆检测与轨迹
# ═══════════════════════════════════════════

class VehicleDetection(BaseModel):
    """单帧检测结果（Kafka 消息体）"""
    track_id: int
    class_id: int              # COCO 2-9
    class_name: str            # car/truck/bus...
    bbox: list[float]          # [x1,y1,x2,y2] 像素
    bev_x: float | None        # BEV 坐标（米）
    bev_y: float | None
    confidence: float
    lane_id: int | None
    speed_kmh: float | None    # BEV 帧间差分
    timestamp: float

class Track(BaseModel):
    """完整轨迹（内存中维护）"""
    track_id: int
    class_name: str
    first_seen: float
    last_seen: float
    start_lane: int | None
    end_lane: int | None
    positions: list[tuple[float,float,float]]
    # [(bev_x, bev_y, ts), ...]
    total_distance_m: float
    avg_speed_kmh: float
    is_anomaly: bool           # 逆行/异常停车
    turn_behavior: TurnBehavior | None   # 转向行为（轨迹完成时计算）
    lane_changes: list[LaneChangeEvent]  # 换道事件列表

# ═══════════════════════════════════════════
# 告警
# ═══════════════════════════════════════════

class AlertType(str, Enum):
    ACCIDENT = "accident"
    RETROGRADE = "retrograde"
    ILLEGAL_PARKING = "illegal_parking"
    QUEUE_OVERFLOW = "queue_overflow"
    CONGESTION = "congestion"
    CALIBRATION_DRIFT = "calibration_drift"

class AlertSeverity(str, Enum):
    P1 = "P1"    # 事故/逆行（需立即处理）
    P2 = "P2"    # 排队超限/拥堵
    P3 = "P3"    # 标定漂移/设备异常

class AlertStatus(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"

class Alert(BaseModel):
    id: str                    # UUID
    intersection_id: str
    alert_type: AlertType
    severity: AlertSeverity
    status: AlertStatus
    title: str                 # "逆行事件"
    description: str | None    # VLM 语义描述
    timestamp: datetime
    snapshot_url: str | None   # 告警截图
    video_clip_url: str | None # 前后30s视频
    vlm_summary: str | None    # Qwen-VL 分析
    track_ids: list[int]       # 关联轨迹
    acknowledged_by: str | None
    acknowledged_at: datetime | None

**告警截图和视频片段生成机制**：

- **snapshot_url**：告警触发时，AlertEngine 从 VideoService 请求当前帧截图（FFmpeg 从 HLS 流截取单帧 JPEG），保存到 `/snapshots/{alert_id}.jpg`，URL 指向 `/api/v1/alerts/{id}/snapshot`
- **video_clip_url**：告警触发后，AlertEngine 异步调用 VideoService 生成前后 30 秒视频片段（FFmpeg 从 HLS 流截取 60 秒 MP4），保存到 `/clips/{alert_id}.mp4`，URL 指向 `/api/v1/alerts/{id}/video-clip`。如果生成失败（HLS 流不可用），video_clip_url 为 None

```python
# AlertEngine._create_alert 中
async def _create_alert(self, int_id, alert_type, severity, title, **kwargs):
    alert = Alert(...)

    # 截图（同步，快速）
    try:
        snapshot_path = await self.video_service.capture_frame(
            stream_id=int_id,
            output_path=f"/snapshots/{alert.id}.jpg"
        )
        alert.snapshot_url = f"/api/v1/alerts/{alert.id}/snapshot"
    except Exception:
        alert.snapshot_url = None

    # 视频片段（异步，耗时）
    asyncio.create_task(self._generate_video_clip(alert, int_id))
```


# ═══════════════════════════════════════════
# 无人机
# ═══════════════════════════════════════════

class DroneStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    FLYING = "flying"
    HOVERING = "hovering"
    RETURNING = "returning"

class Drone(BaseModel):
    id: str                    # "drone_001"
    name: str                  # "M300 RTK #1"
    status: DroneStatus
    battery_pct: int
    current_intersection_id: str | None
    last_telemetry: DroneTelemetry | None

class DroneTelemetry(BaseModel):
    drone_id: str
    intersection_id: str
    lat: float
    lon: float
    alt_agl: float
    gimbal_pitch: float
    gimbal_roll: float
    gimbal_yaw: float
    drone_pitch: float
    drone_roll: float
    drone_yaw: float
    gps_type: str              # RTK_FIXED/RTK_FLOAT/SINGLE
    satellite_count: int
    wind_speed: float          # m/s
    battery_pct: int
    video_bitrate: float       # Mbps
    timestamp: float

    def calib_key(self) -> str:
        h = int(self.alt_agl / 2) * 2
        p = int((self.gimbal_pitch + 90) / 2) * 2 - 90
        return f"{self.intersection_id}__H{h}__P{p}"

# ═══════════════════════════════════════════
# Webhook 推送
# ═══════════════════════════════════════════

class WebhookChannel(str, Enum):
    WECOM = "wecom"            # 企业微信
    DINGTALK = "dingtalk"      # 钉钉
    HTTP_POST = "http_post"    # 通用 HTTP
    SMS = "sms"                # 短信

class Webhook(BaseModel):
    id: str                    # UUID
    name: str                  # "交管值班群"
    channel: WebhookChannel
    url: str
    token: str | None
    enabled: bool
    severity_filter: list[AlertSeverity]  # [P1, P2]
    rate_limit_sec: int        # 最小推送间隔
    created_at: datetime

class AlertPushLog(BaseModel):
    id: str
    alert_id: str
    webhook_id: str
    channel: WebhookChannel
    status: str                # success/failed
    response_code: int | None
    error_message: str | None
    pushed_at: datetime

# ═══════════════════════════════════════════
# 标定与报告
# ═══════════════════════════════════════════

class CalibrationQuality(str, Enum):
    OK = "ok"
    INTERPOLATED = "interpolated"
    DEGRADED = "degraded"
    MISSING = "missing"

class CalibrationRecord(BaseModel):
    """calibration_db.json 中的单条记录"""
    intersection_id: str
    calib_key: str             # "INT_xx__H164__P-90"
    H_mat: list[list[float]]   # 3x3
    altitude_agl: float
    gimbal_pitch: float
    output_size: list[int]     # [1280, 720]
    pixel_scale: float
    lane_polygons_bev: dict[str, list[list[float]]]
    quality: dict              # score/error/...
    source_points: dict        # pixel/world
    template: str
    versions: list[dict]
    lock: dict | None
    calibrated_at: str
    calibrated_by: str

class Report(BaseModel):
    id: str
    intersection_id: str
    title: str                 # "早高峰分析报告"
    period_start: datetime
    period_end: datetime
    total_vehicles: int
    congestion_periods: list[dict]
    anomaly_events: list[str]  # alert_ids
    lane_utilization: dict[str, float]
    lane_headway_stats: dict[str, dict]    # {lane_id: {avg, min, below_2s_pct}}
    lane_queue_stats: dict[str, dict]      # {lane_id: {avg, max}}
    turn_distribution: dict[str, int]      # {straight: 120, left_turn: 45, ...}
    turn_flow_matrix: list[dict]           # [{start_lane, turn_behavior, count}, ...]
    lane_change_rate: float                # 换道次数/总车辆数
    lane_change_matrix: list[dict]         # [{from_lane, to_lane, count}, ...]
    lane_change_heatmap: list[dict]        # [{bev_x, bev_y, density}, ...]
    ai_summary: str | None     # VLM 生成
    pdf_url: str | None
    generated_at: datetime
```

### 3.2 Kafka 消息格式

Topic: `drone_{drone_id}_intersection_{intersection_id}`

**消息类型 1：实时统计**（每秒 1 条，CalcStatisticsNode 输出）

```json
{
  "msg_type": "stats",
  "intersection_id": "INT_小清河水屯",
  "drone_id": "drone_001",
  "timestamp": 1716800000.123,
  "camera_id": "id_1",
  "cars": 12,
  "road_1": 4.2,
  "road_2": 3.8,
  "road_3": 2.1,
  "road_4": 1.5,
  "road_5": 0.4,
  "congestion_index": 2.3,
  "queue_length_m": 45.2,
  "calib_quality": "ok",
  "lane_match_rate": 0.94,
  "lanes": [
    {
      "lane_id": 1,
      "flow_veh_per_min": 4.2,
      "headway_sec": 14.3,
      "queue_length_m": 45.2,
      "vehicle_count": 3,
      "avg_speed_kmh": 22.1
    },
    {
      "lane_id": 2,
      "flow_veh_per_min": 3.8,
      "headway_sec": 15.8,
      "queue_length_m": 32.0,
      "vehicle_count": 2,
      "avg_speed_kmh": 28.5
    },
    {
      "lane_id": 3,
      "flow_veh_per_min": 2.1,
      "headway_sec": 28.6,
      "queue_length_m": 12.5,
      "vehicle_count": 1,
      "avg_speed_kmh": 35.0
    }
  ]
}
```

**消息类型 2：车辆检测**（每帧，可选开启）

```json
{
  "msg_type": "detections",
  "intersection_id": "INT_小清河水屯",
  "frame_ts": 1716800000.033,
  "vehicles": [
    {
      "track_id": 42,
      "class_name": "car",
      "bbox": [120, 80, 180, 140],
      "bev_x": 5.2,
      "bev_y": 23.1,
      "confidence": 0.92,
      "lane_id": 2,
      "speed_kmh": 35.4
    }
  ]
}
```

**消息类型 3：轨迹完成**（车辆离开视野时）

```json
{
  "msg_type": "track_complete",
  "intersection_id": "INT_小清河水屯",
  "track_id": 42,
  "class_name": "car",
  "first_seen": 1716799990.0,
  "last_seen": 1716800000.0,
  "start_lane": 2,
  "end_lane": 3,
  "total_distance_m": 85.3,
  "avg_speed_kmh": 30.7,
  "is_anomaly": false,
  "positions_bev": [[5.2,23.1],[5.3,24.5],[5.1,26.0]],
  "turn_behavior": "left_turn",
  "lane_changes": [
    {
      "from_lane": 2,
      "to_lane": 3,
      "bev_x": 5.3,
      "bev_y": 24.5,
      "timestamp": 1716799995.0
    }
  ]
}
```

**消息类型 4：VLM 语义分析**（每 45 帧）

```json
{
  "msg_type": "vlm_analysis",
  "intersection_id": "INT_小清河水屯",
  "frame_ts": 1716800000.0,
  "accident": false,
  "congestion_level": 1,
  "visible_lanes": 5,
  "anomaly": null,
  "summary": "路口轻度拥堵，南向北方向车流较大"
}
```

**消息类型 5：系统指标**（每 5 秒）

```json
{
  "msg_type": "system_metrics",
  "intersection_id": "INT_小清河水屯",
  "timestamp": 1716800000.0,
  "fps": 28.5,
  "inference_ms": 14.2,
  "tracking_ms": 3.1,
  "track_buffer_size": 125,
  "track_buffer_max": 250,
  "gpu_util_pct": 43,
  "gpu_vram_used_mb": 6200,
  "gpu_vram_total_mb": 8192,
  "gpu_temp_c": 62,
  "kafka_lag": 2
}
```

### 3.3 InfluxDB 测量结构

**measurement: `intersection_stats`**

```
tags:
  intersection_id = "INT_小清河水屯"
  drone_id = "drone_001"
  calib_quality = "ok"
fields:
  cars = 12i
  road_1 = 4.2                  # 各车道流量（evts/min），保留向后兼容
  road_2 = 3.8
  road_3 = 2.1
  road_4 = 1.5
  road_5 = 0.4
  congestion_index = 2.3
  queue_length_m = 45.2          # 最长排队长度（所有车道最大值）
  lane_match_rate = 0.94
  # 车道级指标（动态字段，按实际车道数写入）
  lane_1_flow = 4.2              # 车道 1 流量（辆/分钟）
  lane_1_headway = 14.3          # 车道 1 车头时距（秒）
  lane_1_queue = 45.2            # 车道 1 排队长度（米）
  lane_1_count = 3i              # 车道 1 当前车辆数
  lane_1_speed = 22.1            # 车道 1 平均速度（km/h）
  lane_2_flow = 3.8
  lane_2_headway = 15.8
  lane_2_queue = 32.0
  lane_2_count = 2i
  lane_2_speed = 28.5
  lane_3_flow = 2.1
  lane_3_headway = 28.6
  lane_3_queue = 12.5
  lane_3_count = 1i
  lane_3_speed = 35.0
```

**measurement: `track_events`**

```
tags:
  intersection_id = "INT_小清河水屯"
  class_name = "car"
  start_lane = "2"
  end_lane = "3"
  is_anomaly = "false"
  turn_behavior = "left_turn"    # straight/left_turn/right_turn/u_turn
  has_lane_change = "true"       # 是否发生换道
fields:
  duration_sec = 10.0
  total_distance_m = 85.3
  avg_speed_kmh = 30.7
  track_id = 42i
  lane_change_count = 1i         # 换道次数
  lane_change_1_x = 5.3          # 第 1 次换道 BEV X
  lane_change_1_y = 24.5         # 第 1 次换道 BEV Y
  lane_change_1_from = "2"       # 换道前车道
  lane_change_1_to = "3"         # 换道后车道
```

**measurement: `turn_stats`**（按路口+时间段聚合的转向统计）

```
tags:
  intersection_id = "INT_小清河水屯"
  start_lane = "2"
  turn_behavior = "left_turn"
fields:
  count = 15i                    # 该时间段内该转向行为的车辆数
  avg_speed_kmh = 25.3
```

**measurement: `vlm_analysis`**

```
tags:
  intersection_id = "INT_小清河水屯"
  congestion_level = "1"
fields:
  accident = false
  visible_lanes = 5i
  has_anomaly = false
```

**measurement: `system_metrics`**

```
tags:
  intersection_id = "INT_小清河水屯"
fields:
  fps = 28.5
  inference_ms = 14.2
  tracking_ms = 3.1
  track_buffer_size = 125i
  gpu_util_pct = 43i
  gpu_vram_used_mb = 6200i
  gpu_temp_c = 62i
  kafka_lag = 2i
```

### 3.4 WebSocket 消息协议

**客户端 → 服务端**

```json
{"action": "subscribe", "channel": "intersection:INT_小清河水屯"}
{"action": "subscribe", "channel": "alerts"}
{"action": "subscribe", "channel": "system"}
{"action": "subscribe", "channel": "drones"}
{"action": "subscribe", "channel": "drone:drone_001"}
{"action": "unsubscribe", "channel": "intersection:INT_小清河水屯"}
{"action": "ping"}
```

**服务端 → 客户端**

```json
{
  "channel": "intersection:INT_小清河水屯",
  "type": "stats",
  "data": {
    "cars": 12,
    "roads": [4.2, 3.8, 2.1, 1.5, 0.4],
    "lanes": [
      {"lane_id": 1, "flow": 4.2, "headway": 14.3, "queue": 45.2, "count": 3, "speed": 22.1},
      {"lane_id": 2, "flow": 3.8, "headway": 15.8, "queue": 32.0, "count": 2, "speed": 28.5},
      {"lane_id": 3, "flow": 2.1, "headway": 28.6, "queue": 12.5, "count": 1, "speed": 35.0}
    ],
    ...
  },
  "ts": 1716800000.123
}

{
  "channel": "alerts",
  "type": "alert_new",
  "data": {"id": "uuid-xxx", "alert_type": "retrograde", "severity": "P1", ...},
  "ts": 1716800000.500
}

{"action": "pong", "ts": 1716800000.000}
{"action": "subscribed", "channel": "intersection:INT_小清河水屯"}
```

---

## 4. 服务架构

### 4.1 FastAPI 生命周期

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动
    config = load_config()
    influx = InfluxClient(config.influxdb_url, config.influxdb_db)
    calib_store = CalibStore(config.calibration_db_path)
    ws_manager = WSManager()
    alert_engine = AlertEngine(influx, ws_manager)
    kafka_service = KafkaConsumerService(config.kafka_bootstrap, ws_manager, alert_engine)
    await kafka_service.start()

    app.state.influx = influx
    app.state.calib_store = calib_store
    app.state.kafka_service = kafka_service
    app.state.ws_manager = ws_manager
    app.state.alert_engine = alert_engine

    yield

    # 关闭
    await kafka_service.stop()
    await ws_manager.close_all()
    await influx.close()
```

### 4.2 KafkaConsumerService

后台服务：消费管道 Kafka topic，聚合后推送到 WebSocket，同时写入内存缓存。

**核心逻辑**：

```python
class KafkaConsumerService:
    async def _consume_loop(self):
        async for msg in self.consumer:
            data = msg.value
            msg_type = data.get("msg_type")
            int_id = data.get("intersection_id")

            if msg_type == "stats":
                self._latest[int_id] = data
                await self.ws_manager.broadcast(f"intersection:{int_id}", {...})
                await self.alert_engine.check_stats(data)

            elif msg_type == "track_complete":
                await self.ws_manager.broadcast(f"intersection:{int_id}", {...})
                if data.get("is_anomaly"):
                    await self.alert_engine.on_anomaly_track(data)

            elif msg_type == "vlm_analysis":
                await self.ws_manager.broadcast(f"intersection:{int_id}", {...})
                if data.get("accident") or data.get("anomaly"):
                    await self.alert_engine.on_vlm_alert(data)

            elif msg_type == "system_metrics":
                await self.ws_manager.broadcast("system", {...})
```

### 4.3 InfluxClient

InfluxDB 1.8 查询客户端（InfluxQL），提供历史数据查询。

**核心方法**：

- `query_stats(intersection_id, period, granularity)` — 路口历史统计
- `query_lane_stats(intersection_id, period, granularity)` — 车道级指标时序（flow/headway/queue/speed per lane）
- `query_track_events(intersection_id, period)` — 轨迹事件
- `query_turn_summary(intersection_id, period)` — 转向行为聚合统计
- `query_lane_changes(intersection_id, period, lane_id)` — 换道事件列表
- `query_lane_change_heatmap(intersection_id, period)` — 换道位置热力图
- `query_system_metrics(period, granularity)` — 系统指标
- `query_peak_analysis(intersection_id, start, end)` — 高峰分析（报告用）

### 4.4 WSManager

WebSocket 连接池 + 多路复用广播。

**核心方法**：

- `connect(ws)` / `disconnect(ws)` — 连接管理
- `handle_message(ws, raw)` — 处理订阅/取消/心跳
- `broadcast(channel, message)` — 向所有订阅该 channel 的连接广播

**重连策略**：指数退避 1s → 2s → 4s → ... → 30s，重连后自动恢复订阅列表，心跳 30s。

### 4.5 AlertEngine

两层告警触发：规则层（阈值检测）+ 语义层（VLM 异常检测）。

**规则配置**：

```python
AlertRules(
    queue_overflow_threshold_m=80.0,   # 排队超 80m 触发 P2
    congestion_severe_threshold=4.0,    # 拥堵指数 >4 触发 P2
    calibration_drift_match_rate=0.80,  # 匹配率 <80% 触发 P3
    consecutive_congestion_frames=30,   # 连续 30 帧严重拥堵触发 P2
)
```

**触发逻辑**：

- `check_stats(stats)` — 检查统计数据（排队/拥堵/标定漂移）
- `on_anomaly_track(track_data)` — 异常轨迹（逆行/异常停车）
- `on_vlm_alert(vlm_data)` — VLM 检测到事故/异常

**推送流程**：创建 Alert → WebSocket 广播 → 异步 Webhook 推送（带频率限制）。

### 4.6 VideoService

管理 FFmpeg 子进程，将管道 MJPEG 流转为 HLS。

**核心方法**：

```python
async def start_stream(stream_id, source_url, hls_time=2, hls_list_size=10):
    cmd = [
        "ffmpeg", "-y",
        "-i", source_url,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-tune", "zerolatency",
        "-g", str(hls_time * 15),
        "-f", "hls",
        "-hls_time", str(hls_time),
        "-hls_list_size", str(hls_list_size),
        "-hls_flags", "delete_segments+append_list",
        "-hls_segment_filename", f"{output_dir}/seg_%04d.ts",
        f"{output_dir}/index.m3u8",
    ]
    proc = await asyncio.create_subprocess_exec(*cmd, ...)
    return {"stream_id": stream_id, "hls_url": f"/hls/{stream_id}/index.m3u8"}

async def capture_frame(stream_id: str, output_path: str) -> str:
    """从 HLS 流截取当前帧为 JPEG（用于告警截图）"""
    hls_url = f"/hls/{stream_id}/index.m3u8"
    cmd = [
        "ffmpeg", "-y",
        "-i", hls_url,
        "-vframes", "1",
        "-q:v", "2",
        output_path,
    ]
    proc = await asyncio.create_subprocess_exec(*cmd, ...)
    await proc.wait()
    return output_path

async def generate_clip(stream_id: str, output_path: str,
                         duration_before: int = 30, duration_after: int = 30) -> str:
    """从 HLS 流截取前后 N 秒视频片段（用于告警视频回放）"""
    hls_url = f"/hls/{stream_id}/index.m3u8"
    total_duration = duration_before + duration_after
    cmd = [
        "ffmpeg", "-y",
        "-i", hls_url,
        "-t", str(total_duration),
        "-c:v", "libx264",
        "-preset", "fast",
        output_path,
    ]
    proc = await asyncio.create_subprocess_exec(*cmd, ...)
    await proc.wait()
    return output_path
```

**延迟预估**：FFmpeg 编码 ~50ms + HLS 分片 2s×2 = ~4s + 网络 ~100ms = **约 4-6 秒**。

### 4.7 ReportService

生成交通分析报告（PDF）。

**生成流程**：

1. 查询 InfluxDB 历史统计
2. 查询告警事件列表
3. 计算拥堵时段（congestion_index > 3.0 的连续区间）
4. 计算车道利用率（各车道流量占比）
5. 生成 Report 对象
6. 后台任务生成 PDF（WeasyPrint/ReportLab）
7. VLM 异步填充 AI 摘要

---

## 5. 功能规格

### 5.1 F1. Dashboard（首页）

**GIS 总览地图**：

- 显示所有路口位置（marker + 拥堵色块：绿<2 / 黄2-4 / 红>4）
- 显示在线无人机位置（图标 + 航向箭头）
- 告警闪烁标记（红色脉冲动画）
- 点击路口 → 跳转 `/realtime/{id}`
- Hover 路口 → tooltip 显示实时 cars/congestion/calib_quality

**KPI 卡片组**（6 个）：

- 总车流量（所有路口 cars 求和，趋势 vs 昨日同时段）
- 当前拥堵指数（最高单路口值）
- 异常事件数（今日 OPEN 状态告警计数）
- 在线无人机数（status != offline）
- GPU 利用率（system_metrics 最新值）
- 系统延迟（Kafka lag × 帧间隔估算）

**实时告警流**：

- 显示最近 20 条 OPEN 告警
- WebSocket 实时追加新告警
- 点击告警 → 跳转 `/alerts/{id}`

**API 依赖**：

```
GET  /api/v1/intersections
GET  /api/v1/intersections/summary
GET  /api/v1/alerts?status=open&limit=20
WS   subscribe: system
WS   subscribe: alerts
WS   subscribe: drones
```

### 5.2 F2. 标定中心

**标定工作台**（iframe 嵌入已有标注工具）：

- iframe src = `/annotation/calibrate`
- 消息通信：postMessage 协议（标定完成 → 平台刷新标定列表）
- 传递参数：`intersection_id`（URL query）

**标定列表**：

- 读取 `calibration_db.json` 所有记录
- 显示：intersection_id / calib_key / altitude / pitch / quality / version / locked
- 操作：查看详情 / 锁定 / 删除 / 回滚版本

**覆盖率热图**：

- X 轴：俯仰角（-90° ~ -70°，步长 2°）
- Y 轴：高度（100m ~ 200m，步长 2m）
- 颜色：精确标定(绿) / 可插值(黄) / 未覆盖(红)
- 按 intersection_id 筛选

**标定质量监控**：

- 实时显示当前生效标定的 calib_quality / lane_match_rate
- 标定漂移告警（lane_match_rate < 80% 持续 60s）

**API 依赖**：

```
GET  /api/v1/calibration/summary
GET  /api/v1/calibration/records
GET  /api/v1/calibration/records/{key}
GET  /api/v1/calibration/coverage/{int_id}
POST /api/v1/calibration/records/{key}/lock
POST /api/v1/calibration/records/{key}/unlock
POST /api/v1/calibration/records/{key}/rollback
DELETE /api/v1/calibration/records/{key}
```

### 5.3 F3. Platform Shell（基础设施）

**WebSocket 连接管理**：

- 全局单连接，多路复用（按 channel 订阅/取消）
- 自动重连：指数退避 1s → 2s → 4s → ... → 30s
- 重连后自动恢复之前的订阅列表
- 心跳 30s，60s 无响应断开重连
- 连接状态全局可查（store）

**主题切换**：

- 两种主题：CTO 科技风 / 交警业务风
- 纯 CSS 变量切换（`data-theme` 属性）
- 持久化到 localStorage
- 条件动画：CTO 模式启用 glow/数据流动画

**Debug Overlay**：

- 快捷键 D 切换显示
- 仅在 CTO 模式下可用
- 显示：FPS / GPU / 推理耗时 / Track Buffer / Kafka lag

### 5.4 F4. 实时路口监测

**单路口详情页**（核心页面）：

**实时视频**：

- HLS 播放（hls.js），延迟约 4-6s
- Canvas overlay 叠加 YOLO bbox + track_id + 车道标签
- bbox 数据通过 WebSocket 推送（与视频帧时间戳对齐）
- 控制：暂停/播放、YOLO 框开关、热成像切换（RGB/IR）

**BEV 鸟瞰图**：

- Konva.js 渲染车道多边形 + 实时车辆点 + 轨迹线
- 点击车道 → 显示该车道实时统计面板：
  - 交通流量（flow_veh_per_min）
  - 车头时距（headway_sec）+ 安全阈值线（2s 警戒）
  - 排队长度（queue_length_m）+ 排队车辆高亮
  - 车道内车辆数 + 平均速度
- 车道颜色编码：绿(畅通 headway>5s) / 黄(轻度 2-5s) / 红(拥堵 <2s)
- 换道位置标记：在 BEV 上以虚线箭头标注最近 N 次换道事件发生位置

**实时指标图表**：

- 流量趋势（折线图，最近 10 分钟，1s 粒度，多车道叠加）
- 各车道流量（柱状图，颜色编码）
- 各车道车头时距（分组柱状图，附 2s 安全阈值线）
- 各车道排队长度（堆叠面积图）
- 拥堵指数（仪表盘 0-5）
- 转向行为分布（饼图：直行/左转/右转/掉头占比，来自 track_complete 聚合）
- 换道热力图（BEV 上叠加换道位置密度热力，来自 track_complete 聚合）
- 告警时间轴（最近 1 小时告警标记）

**bbox overlay 时间戳对齐**：

```
管道侧（每帧）→ Kafka (msg_type: detections)
     ↓
KafkaConsumerService → 缓存最近 5 帧 detections（按 frame_ts 排序）
     ↓
WebSocket 推送 {type: "detections", data: {frame_ts, vehicles: [...]}}
     ↓
HLSVideoPlayer:
  video.currentTime → frame_ts 映射
  取最近一帧 detections 绘制 Canvas
  容差: ±500ms（HLS 延迟波动）
  超过容差: 隐藏 bbox（避免错位）

# 前端维护 video_time → real_time 偏移量：
#   offset = real_time_at_video_play - video.currentTime
# 然后用 offset 找到当前 video 画面对应的 bbox 数据帧
```

**多路口总览页**：

- 网格布局显示所有活跃路口缩略卡片
- 每个卡片：视频缩略 + 车流量 + 拥堵指数 + calib_quality
- 点击 → 跳转单路口详情

**API 依赖**：

```
GET  /api/v1/intersections/{id}
GET  /api/v1/intersections/{id}/stats?period=10m&granularity=1s
GET  /api/v1/intersections/{id}/lane-stats?period=10m&granularity=1s
GET  /api/v1/intersections/{id}/turn-stats?period=1h
GET  /api/v1/intersections/{id}/lane-changes?period=1h
GET  /api/v1/video/streams
POST /api/v1/video/streams/{id}/start
WS   subscribe: intersection:{id}
WS   subscribe: alerts:{id}
```

### 5.5 F5. 告警中心

**告警列表**：

- 分页显示所有告警（最新优先）
- 过滤：severity（P1/P2/P3）、status（open/acknowledged/resolved）、路口、时间范围
- WebSocket 实时追加新告警
- 操作：确认告警（acknowledge）、查看详情

**告警详情**：

- 告警截图（从管道帧截取的 JPEG）
- 前后 30 秒视频回放（HLS clip）
- VLM 语义摘要（Qwen-VL 分析结果）
- 关联轨迹列表（track_id + BEV 轨迹线）
- 推送记录（哪些 Webhook 收到了推送 + 状态）

**Webhook 配置**：

- CRUD 管理 Webhook 渠道
- 支持类型：企业微信 / 钉钉 / HTTP POST / 短信
- 每个 Webhook 可配置：severity 过滤 + 频率限制
- 测试推送按钮

**Webhook 推送消息格式**：

**企业微信**：

```json
{
  "msgtype": "markdown",
  "markdown": {
    "content": "## 🚨 逆行告警\n> 路口：小清河北路×水屯路\n> 时间：2026-05-28 07:33:45\n> 等级：P1\n> [查看详情](http://platform:8080/alerts/uuid-xxx)"
  }
}
```

**钉钉**：

```json
{
  "msgtype": "actionCard",
  "actionCard": {
    "title": "逆行告警 - INT_小清河水屯",
    "text": "## 逆行告警\n路口：小清河北路×水屯路...",
    "singleTitle": "查看详情",
    "singleURL": "http://platform:8080/alerts/uuid-xxx"
  }
}
```

**通用 HTTP POST**：

```json
{
  "event": "alert",
  "alert_id": "uuid-xxx",
  "intersection_id": "INT_小清河水屯",
  "alert_type": "retrograde",
  "severity": "P1",
  "title": "逆行事件",
  "timestamp": "2026-05-28T07:33:45Z",
  "snapshot_url": "http://platform:8080/api/v1/alerts/uuid-xxx/snapshot"
}
```

**API 依赖**：

```
GET  /api/v1/alerts
GET  /api/v1/alerts/{id}
POST /api/v1/alerts/{id}/acknowledge
GET  /api/v1/alerts/{id}/snapshot
GET  /api/v1/alerts/{id}/video-clip
GET  /api/v1/alerts/{id}/push-logs
GET  /api/v1/alerts/webhooks
POST /api/v1/alerts/webhooks
PUT  /api/v1/alerts/webhooks/{id}
DELETE /api/v1/alerts/webhooks/{id}
POST /api/v1/alerts/webhooks/{id}/test
```

### 5.6 F6. 视频分析中心

**实时视频分析**：

- 视频流 + YOLO 检测列表（实时 track_id 表）
- VLM JSON 输出实时显示（Qwen-VL 语义分析结果）
- 事件流（异常事件实时列表）

**回放分析**：

- 选择时间范围 + 路口 → 回放 HLS 录像
- 叠加历史检测框 + 轨迹线
- 时间轴拖拽 + 关键帧标记（告警时间点）

**轨迹分析**：

- 从 InfluxDB track_events 查询轨迹数据
- BEV 画布上渲染所有轨迹线（颜色按速度编码）
- 路径热力图（统计高频行驶路径）
- 逆行轨迹高亮（红色 + 闪烁）
- 单车轨迹回放（点击 track_id → 动画回放）
- 转向行为可视化：
  - 按 turn_behavior 过滤轨迹（直行/左转/右转/掉头）
  - 每种转向用不同颜色渲染（直行=白、左转=绿、右转=蓝、掉头=红）
  - 转向统计饼图（各转向类型占比）
- 换道位置分析：
  - BEV 上渲染所有换道事件位置（圆点 + 箭头 from→to）
  - 换道热力图（高频换道区域高亮）
  - 按车道筛选换道事件（从哪条车道换到哪条）
  - 换道频率统计（换道次数/总车辆数）

**VLM 语义分析**：

- 左侧：视频帧（可暂停选帧）
- 右侧：Qwen-VL JSON 输出实时显示
- Prompt Playground：编辑 Prompt + 实时测试 + 推理耗时
- 历史 VLM 分析记录列表

**API 依赖**：

```
GET  /api/v1/video/streams
POST /api/v1/video/streams/{id}/start
GET  /api/v1/video/replay/{int_id}?start=...&end=...
GET  /api/v1/trajectories/{int_id}?period=1h&limit=500&turn_behavior=left_turn
GET  /api/v1/trajectories/{int_id}/heatmap
GET  /api/v1/trajectories/{int_id}/turn-summary?period=1h
GET  /api/v1/trajectories/{int_id}/lane-change-heatmap?period=1h
GET  /api/v1/vlm/history/{int_id}
POST /api/v1/vlm/test  body: {frame_url, prompt}
```

### 5.7 F7. 报告中心

**报告生成流程**：

1. 选择路口 + 时间范围（如：早高峰 07:00-09:00）
2. 后端查询 InfluxDB 历史数据 + 告警列表
3. 计算：拥堵时段 / 各车道利用率 / 异常事件清单
4. VLM 生成 AI 摘要（异步，可先出报告后补充）
5. 生成 PDF（WeasyPrint / ReportLab）
6. 提供下载链接

**报告内容模块**：

- 概览：总车流量 / 平均拥堵指数 / 异常事件数
- 时序图：流量趋势 + 拥堵指数趋势
- 拥堵时段表：开始/结束时间 + 峰值 + 持续时长
- 车道级分析：
  - 各车道流量占比饼图
  - 各车道车头时距时序图（标注低于 2s 安全阈值的时段）
  - 各车道排队长度最大值时序图
- 转向行为分析：
  - 转向类型分布饼图（直行/左转/右转/掉头占比）
  - 各进车道的转向流量矩阵（start_lane × turn_behavior）
- 换道行为分析：
  - 换道频率（换道次数/总车辆数）
  - 高频换道区域 BEV 热力图
  - 换道矩阵（from_lane × to_lane 次数统计）
- 异常事件清单：时间 + 类型 + 严重等级 + VLM 描述
- AI 总结：Qwen-VL 生成的自然语言路况报告

**报告管理**：

- 历史报告列表（路口 + 时间 + 生成时间）
- 在线预览 / PDF 下载
- 定时生成（每日早高峰自动报告，P2 阶段）

**API 依赖**：

```
GET  /api/v1/reports
POST /api/v1/reports/generate  body: {intersection_id, start, end, title}
GET  /api/v1/reports/{id}
GET  /api/v1/reports/{id}/pdf
GET  /api/v1/reports/{id}/status
```

### 5.8 F8. 无人机管理

**飞行监控**：

- 无人机列表：id / 名称 / 状态 / 电量 / 当前路口
- 实时遥测面板：GPS / 高度 / 云台角 / 风速 / RTK 状态 / 图传码率
- WebSocket 实时刷新（subscribe: drone:{id}）
- 状态颜色编码：在线(绿) / 飞行中(蓝) / 低电量(黄) / 离线(红)

**飞行轨迹回放**：

- GIS 地图上渲染飞行轨迹线
- 悬停点标记（圆点 + 悬停时长）
- 告警点标记（红色 + 告警类型）
- 时间轴同步：拖动时间轴 → 地图上移动无人机图标 + 联动视频回放

**航线任务管理**（P2 阶段）：

- 预定义航线列表（每个路口一条）
- 航线参数：航点坐标 / 悬停高度 / 云台角 / 悬停时长
- mission.json 格式管理

**API 依赖**：

```
GET  /api/v1/drones
GET  /api/v1/drones/{id}
GET  /api/v1/drones/{id}/trajectory?start=...&end=...
GET  /api/v1/drones/{id}/hover-points
GET  /api/v1/missions
GET  /api/v1/missions/{id}
WS   subscribe: drones
WS   subscribe: drone:{id}
```

### 5.9 F9. 系统管理

**GPU 监控**：

- GPU0（YOLO）/ GPU1（Qwen-VL）分别展示
- 指标：利用率 / VRAM 用量 / 温度 / 推理队列深度
- 时序图（最近 30 分钟，5s 粒度）
- 数据来源：Kafka system_metrics 消息

**Kafka 监控**：

- Topic 列表：名称 / 分区数 / TPS / Consumer lag
- Consumer group 状态
- 数据来源：Kafka AdminClient API

**模型管理**：

- YOLO 模型切换（YOLO11n/s/m，热更新 API）
- VLM Prompt 模板在线编辑 + 保存
- 检测参数调节：confidence / imgsz / track_buffer
- 模型文件列表（weights/ 目录扫描）

**用户管理**（POC 简化版）：

- 简单用户名/密码（JWT）
- 角色：admin（全权限）/ operator（标定+监测）/ viewer（只读）
- POC 阶段不接入 LDAP/OAuth

**API 依赖**：

```
GET  /api/v1/system/health
GET  /api/v1/system/gpu
GET  /api/v1/system/gpu/history?period=30m
GET  /api/v1/system/kafka/topics
GET  /api/v1/system/kafka/consumers
GET  /api/v1/system/kafka/lag
GET  /api/v1/system/models
POST /api/v1/system/models/switch  body: {model_name: "yolo11m.pt"}
GET  /api/v1/system/models/prompts
PUT  /api/v1/system/models/prompts/{id}
POST /api/v1/system/models/config  body: {confidence: 0.18, imgsz: 1280}
POST /api/v1/auth/login  body: {username, password}
GET  /api/v1/auth/me
```

### 5.10 F10. 移动端（交警告警场景）

**告警推送**：

- 通过 Webhook 推送到企业微信/钉钉（P1/P2 告警）
- 推送内容：告警标题 + 截图缩略图 + 时间 + 路口 + "查看详情"链接
- 点击链接 → 移动端 H5 页面

**移动端 H5 页面**（响应式，复用平台前端）：

- 告警详情页：截图 + 视频回放 + 路口位置
- 简化版路口监测页：视频 + 核心指标
- GIS 简版：路口位置 + 拥堵色块

**技术要求**：

- 前端响应式布局（Tailwind `md:` `lg:` 断点）
- HLS 视频在移动端原生 `<video>` 播放
- 无需原生 App（PWA 可选，P2 阶段）

---

## 6. 完整 API 清单

### 6.1 REST 端点

```
# 认证
POST   /api/v1/auth/login
GET    /api/v1/auth/me

# 路口
GET    /api/v1/intersections
GET    /api/v1/intersections/summary
GET    /api/v1/intersections/{id}
GET    /api/v1/intersections/{id}/stats?period=1h&granularity=1m
GET    /api/v1/intersections/{id}/lane-stats?period=10m&granularity=1s
GET    /api/v1/intersections/{id}/turn-stats?period=1h
GET    /api/v1/intersections/{id}/lane-changes?period=1h&lane_id=2

# 告警
GET    /api/v1/alerts?severity=P1&status=open&limit=50&offset=0
GET    /api/v1/alerts/{id}
POST   /api/v1/alerts/{id}/acknowledge
GET    /api/v1/alerts/{id}/snapshot
GET    /api/v1/alerts/{id}/video-clip
GET    /api/v1/alerts/{id}/push-logs
GET    /api/v1/alerts/webhooks
POST   /api/v1/alerts/webhooks
PUT    /api/v1/alerts/webhooks/{id}
DELETE /api/v1/alerts/webhooks/{id}
POST   /api/v1/alerts/webhooks/{id}/test

# 视频流
GET    /api/v1/video/streams
POST   /api/v1/video/streams/{id}/start
POST   /api/v1/video/streams/{id}/stop
GET    /api/v1/video/replay/{int_id}?start=...&end=...

# 轨迹
GET    /api/v1/trajectories/{int_id}?period=1h&limit=500&class_name=car&turn_behavior=left_turn
GET    /api/v1/trajectories/{int_id}/heatmap
GET    /api/v1/trajectories/{int_id}/turn-summary?period=1h
GET    /api/v1/trajectories/{int_id}/lane-change-heatmap?period=1h
GET    /api/v1/trajectories/{int_id}/{track_id}

# VLM
GET    /api/v1/vlm/history/{int_id}
POST   /api/v1/vlm/test

# 标定
GET    /api/v1/calibration/summary
GET    /api/v1/calibration/records
GET    /api/v1/calibration/records/{key}       # key = "INT_xxx__H164__P-90"
GET    /api/v1/calibration/coverage/{int_id}
POST   /api/v1/calibration/records/{key}/lock
POST   /api/v1/calibration/records/{key}/unlock
POST   /api/v1/calibration/records/{key}/rollback
DELETE /api/v1/calibration/records/{key}

# 报告
GET    /api/v1/reports
POST   /api/v1/reports/generate
GET    /api/v1/reports/{id}
GET    /api/v1/reports/{id}/pdf
GET    /api/v1/reports/{id}/status

# 无人机
GET    /api/v1/drones
GET    /api/v1/drones/{id}
GET    /api/v1/drones/{id}/trajectory?start=...&end=...
GET    /api/v1/drones/{id}/hover-points
GET    /api/v1/missions
GET    /api/v1/missions/{id}

# 系统
GET    /api/v1/system/health
GET    /api/v1/system/gpu
GET    /api/v1/system/gpu/history?period=30m
GET    /api/v1/system/kafka/topics
GET    /api/v1/system/kafka/consumers
GET    /api/v1/system/kafka/lag
GET    /api/v1/system/models
POST   /api/v1/system/models/switch
GET    /api/v1/system/models/prompts
PUT    /api/v1/system/models/prompts/{id}
POST   /api/v1/system/models/config
```

**统计**：REST 端点 57 个，WebSocket Channels 6 类。

### 6.2 WebSocket Channels

```
WS /ws/realtime

Channels:
  intersection:{id}   # 路口实时 stats + detections + tracks
  alerts              # 全局告警
  alerts:{int_id}     # 路口告警
  system              # 系统指标（GPU/FPS/Kafka）
  drones              # 所有无人机状态
  drone:{drone_id}    # 单无人机遥测
```

---

## 7. 管道侧改造

### 7.1 已有能力（无需改动）

- RTSP/MJPEG 视频输出（FlaskServerVideoNode :8100）
- Kafka 统计消息推送（KafkaProducerNode → statistics topic）
- InfluxDB 写入（Telegraf 消费 Kafka → 写入 InfluxDB）
- calibration_db.json 读取（标注工具已完成）

### 7.2 需要扩展的模块

**KafkaProducerNode**：新增 msg_type 字段

- 现有消息只发 stats（cars + road_1~5），需增加：
  - msg_type: "stats" | "detections" | "track_complete" | "vlm_analysis" | "system_metrics"
  - topic 命名改为 `drone_{drone_id}_intersection_{int_id}`
  - 新增字段：congestion_index / queue_length_m / calib_quality / lane_match_rate

**CalcStatisticsNode**：新增拥堵指数 + 排队长度 + 车道级五项指标计算

- `congestion_index`：加权平均拥堵度
  ```
  weights = [1.0, 1.0, 0.8, 0.8, 0.6]  # 直行车道权重 > 转弯车道
  per_lane_congestion = [min(evts_per_min[i] / 10.0, 5.0) for i in lanes]
  congestion_index = sum(w * c for w, c in zip(weights, per_lane_congestion)) / sum(weights)
  # 输出范围 0-5，0=畅通，5=严重拥堵
  ```
- `queue_length_m`：最长排队长度（米）
  ```
  queue_length_m = max(
    max(vehicles_bev_y[lane]) - min(vehicles_bev_y[lane])
    for lane in active_lanes if len(vehicles_bev_y[lane]) >= 2
  )
  ```
- `lane_flow`（车道级交通流量）：
  ```
  # 使用滑动窗口（60s）统计每个车道的通过车辆数
  # flow_veh_per_min = window_count / window_duration_sec * 60
  for lane in active_lanes:
      recent_passes = [t for t in lane_pass_timestamps[lane] if t > now - 60]
      lane.flow_veh_per_min = len(recent_passes) / 60.0 * 60
  ```
- `headway_sec`（车头时距）：
  ```
  # 车头时距 = 同一车道内前后两辆车通过同一参考线的时间差
  # 参考线取车道中间 Y 坐标
  for lane in active_lanes:
      vehicles_in_lane = sorted(
          [v for v in tracked_vehicles if v.lane_id == lane],
          key=lambda v: v.last_cross_time
      )
      if len(vehicles_in_lane) >= 2:
          # 取最近两次通过参考线的时间差
          headways = [
              vehicles_in_lane[i+1].last_cross_time - vehicles_in_lane[i].last_cross_time
              for i in range(len(vehicles_in_lane) - 1)
          ]
          lane.headway_sec = mean(headways)  # 平均车头时距
      else:
          lane.headway_sec = None  # 车道内车辆不足，无法计算
  ```
- `lane_queue_m`（车道级排队长度）：
  ```
  # 每个车道：该车道内所有车辆 BEV Y 坐标的 max - min
  for lane in active_lanes:
      y_coords = [v.bev_y for v in tracked_vehicles if v.lane_id == lane and v.speed_kmh < 5.0]
      # 只统计低速车辆（<5km/h 视为排队中）
      if len(y_coords) >= 2:
          lane.queue_length_m = max(y_coords) - min(y_coords)
      else:
          lane.queue_length_m = 0.0
  ```

**TrackerInfoUpdateNode**：轨迹完成时计算转向行为 + 检测换道 + 发送 track_complete

- `turn_behavior`（转向行为分类）：
  ```
  # 基于车辆的 start_lane 和 end_lane 方向属性判断
  # 需要从车道配置中读取每个车道的方向（direction 字段）
  start_dir = lane_config[track.start_lane].direction   # "north"/"south"/"east"/"west"
  end_dir = lane_config[track.end_lane].direction

  # 直行：进出方向相同
  if start_dir == opposite(end_dir):
      turn = "straight"
  # 左转：end_dir 是 start_dir 逆时针 90°
  elif end_dir == ccw90(start_dir):
      turn = "left_turn"
  # 右转：end_dir 是 start_dir 顺时针 90°
  elif end_dir == cw90(start_dir):
      turn = "right_turn"
  # 掉头：进出方向相同（同向车道）
  elif start_dir == end_dir:
      turn = "u_turn"
  ```
- `lane_changes`（换道检测）：
  ```
  # 检测逻辑：当连续 track 的 lane_id 发生变化时，记录一次换道事件
  # 过滤条件：排除短暂误判（lane_id 抖动），要求新 lane_id 持续 >= 5 帧

  lane_history = []  # [(lane_id, start_frame, end_frame), ...]
  current_lane = track.positions[0].lane_id
  current_start = 0

  for i, pos in enumerate(track.positions):
      if pos.lane_id != current_lane:
          # 记录上一段
          lane_history.append((current_lane, current_start, i - 1))
          current_lane = pos.lane_id
          current_start = i
  lane_history.append((current_lane, current_start, len(track.positions) - 1))

  # 过滤：只保留持续 >= 5 帧的车道段
  stable_segments = [seg for seg in lane_history if seg[2] - seg[1] >= 5]

  # 相邻稳定段之间就是换道事件
  lane_changes = []
  for i in range(len(stable_segments) - 1):
      from_lane = stable_segments[i][0]
      to_lane = stable_segments[i + 1][0]
      change_frame = stable_segments[i][2]  # 换道发生帧
      bev_pos = track.positions[change_frame]
      lane_changes.append(LaneChangeEvent(
          from_lane=from_lane, to_lane=to_lane,
          bev_x=bev_pos.bev_x, bev_y=bev_pos.bev_y,
          timestamp=bev_pos.ts
      ))
  ```
- 轨迹完成时发送 track_complete 消息（含 turn_behavior + lane_changes）：
  ```
  # 当 track 离开视野（连续 N 帧未检测到）时：
  track.turn_behavior = classify_turn(track.start_lane, track.end_lane)
  track.lane_changes = detect_lane_changes(track)
  kafka_produce("track_complete", track.to_dict())
  ```

### 7.3 需要新增的模块（POC 规划中已定义）

- **DroneTelemetry**（elements/）：SRT 遥测数据类
- **IPMNode**（nodes/）：透视变换 → BEV 坐标
- **VLMBypassNode**（nodes/）：Qwen-VL 语义分析旁路
- **EISNode**（nodes/）：电子画面稳定（P2）
- **CalibrationEngine**（calibration/）：标定库查表 + 三级命中

---

## 8. 部署配置

### 8.1 Nginx 配置

```nginx
server {
    listen 8080;
    server_name localhost;

    # 前端静态文件
    location / {
        root /usr/share/nginx/html;
        try_files $uri $uri/ /index.html;
    }

    # FastAPI 后端 API
    location /api/ {
        proxy_pass http://platform-api:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # WebSocket
    location /ws/ {
        proxy_pass http://platform-api:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400;
    }

    # HLS 视频流
    location /hls/ {
        alias /hls/;
        add_header Cache-Control no-cache;
        add_header Access-Control-Allow-Origin *;
    }

    # 标注工具 iframe 嵌入
    location /annotation/ {
        proxy_pass http://annotation-tool:5000/;
        proxy_set_header Host $host;
    }

    # Grafana 嵌入
    location /grafana/ {
        proxy_pass http://grafana:3000/;
        proxy_set_header Host $host;
    }
}
```

### 8.2 Docker Compose

```yaml
version: '3.8'

services:
  platform-frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "8080:8080"
    volumes:
      - ./nginx.platform.conf:/etc/nginx/conf.d/default.conf
      - hls_data:/hls:ro
    depends_on:
      - platform-api
    networks:
      - platform-net
      - traffic-net

  platform-api:
    build:
      context: ./backend
      dockerfile: Dockerfile
    environment:
      - KAFKA_BOOTSTRAP=kafka:9092
      - INFLUXDB_URL=http://influxdb:8086
      - INFLUXDB_DB=influx
      - HLS_OUTPUT_DIR=/hls
      - CALIBRATION_DB=/calibration/calibration_db.json
      - PIPELINE_VIDEO_URL=http://traffic_analyzer_camera_1:8100/video
    volumes:
      - hls_data:/hls
      - ../configs:/calibration:ro
    depends_on:
      - kafka
      - influxdb
    networks:
      - platform-net
      - traffic-net

  annotation-tool:
    build:
      context: ../annotation
      dockerfile: Dockerfile
    environment:
      - CALIB_DB_PATH=/configs/calibration_db.json
      - FLIGHTS_DIR=/flights
    volumes:
      - ../configs:/configs
      - ../flights:/flights:ro
    networks:
      - platform-net

volumes:
  hls_data:

networks:
  platform-net:
    driver: bridge
  traffic-net:
    external: true
    name: traffic_analyzer_default
```

---

## 9. 验证方案

### 9.1 单元测试

| 模块 | 测试内容 |
|---|---|
| KafkaConsumerService | 消息解析、WebSocket 广播、内存缓存更新 |
| InfluxClient | InfluxQL 查询构建、结果解析 |
| WSManager | 连接管理、订阅/取消、广播、断线重连 |
| AlertEngine | 规则触发（排队/拥堵/标定漂移）、VLM 告警、Webhook 推送 |
| VideoService | FFmpeg 进程启动/停止、HLS 输出目录管理 |
| ReportService | 拥堵时段识别、车道利用率计算、PDF 生成 |

### 9.2 集成测试

1. 启动 TrafficAnalyzer 管道（模拟数据）
2. 启动 Platform API + Frontend
3. 验证 Kafka 消息消费 → WebSocket 推送 → 前端实时更新
4. 验证 HLS 视频流播放 + bbox overlay 时间戳对齐
5. 触发告警规则 → 验证 WebSocket 推送 + Webhook 推送
6. 生成报告 → 验证 PDF 内容完整性

### 9.3 CTO 演示验证

1. 打开平台首页 → GIS 总览 + KPI 卡片 + 告警流
2. 点击路口 → 实时视频 + BEV 鸟瞰图 + 实时图表
3. 切换 CTO/交警主题 → 视觉风格切换
4. 触发逆行告警 → WebSocket 实时推送 + 企业微信收到推送
5. 进入标定中心 → iframe 嵌入标注工具 → 5 分钟完成新路口标定
6. 按 D 键 → Debug Overlay 显示 FPS/GPU/推理耗时
7. 全程无卡顿

---

*文档版本：v1.0 | 2026-05-28*
*下一步：UI 层由 open design 工具细化，本 spec 聚焦功能/服务/模型实现*

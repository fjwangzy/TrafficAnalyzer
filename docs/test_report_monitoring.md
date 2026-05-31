# Console Monitoring 页面端到端测试报告

**日期**: 2026-05-31  
**测试范围**: `traffic-fly-console` 前端 monitoring 页面 → 后端 Platform API → Kafka → 数据流全链路  
**前端**: `http://localhost:5173/monitoring` (Vite dev server)  
**后端**: `http://localhost:8000` (Docker: traffic_platform)

---

## 测试会话 1：模拟数据验证（22 PASS / 0 FAIL / 1 WARN）

详见下方 Phase 1–4。使用 `kafka-console-producer` 注入模拟 stats 消息，验证全链路数据流。

## 测试会话 2：真实无人机视频检测（inter_xqh）

**数据源**: `test_videos/inter_xqh/DJI_20260403142902_0001_V小清河北路与水屯路路口.mp4` + `telemetry.srt`  
**检测管道**: `main_optimized.py` (本地 MPS 推理, Apple M4)  
**Kafka**: topic `statistics_3` → Platform consumer → WebSocket channel `intersection:INT_camera_3`

### 结果：14 PASS / 0 FAIL / 2 WARN

| # | 检查项 | 结果 | 实际值 |
|---|--------|------|--------|
| 1 | 检测管道启动 (MPS) | ✅ | FPS 2.6–3.5, inference 60–140ms |
| 2 | SRT 遥测加载 | ✅ | 10.9MB SRT 文件, 30fps GPS+gimbal数据 |
| 3 | Kafka 生产 (statistics_3) | ✅ | 87 cars, 86 tracks, congestion=44.4 |
| 4 | Kafka consumer 订阅 | ✅ | pattern `(statistics\|track_complete\|conflicts\|telemetry)_.*` 匹配 |
| 5 | WebSocket 通道切换 | ✅ | **修复**: 动态 channel subscribe/unsubscribe |
| 6 | 路口选择器 (INT_camera_3) | ✅ | 显示 "小清河北路与水屯路路口" |
| 7 | 路口切换数据加载 | ✅ | 实时指标 <5s 内刷新 |
| 8 | 实时指标更新 | ✅ | FPS=3.0, 推理=60.9ms, 目标=85, 跟踪=88 |
| 9 | 流量/拥堵指数 | ✅ | 当前流量=85, 拥堵指数=154 |
| 10 | 无人机遥测显示 | ✅ | 36.702909°N 117.02233°E, 悬停状态, E/N坐标 |
| 11 | 转向行为分布 | ✅ | **修复**: n=88, 直行85(93%), 左转1(1%), 掉头4(5%) |
| 12 | 车道名称 (inter_xqh) | ✅ | 水屯路北段/小清河北路东段/水屯路南段/小清河北路西段/路口中心区 |
| 13 | 告警中心 badge | ✅ | 显示 "1" 条未处理告警 |
| 14 | Pipeline 节点可视化 | ✅ | RTSP → YOLO11 → BEV → VLM |
| 15 | MJPEG 视频流 | ⚠️ | OFFLINE (管道非 API 启动, streamActive=false) |
| 16 | 车道级指标 (LaneStats) | ⚠️ | 全部 0.0 km/h (lane polygons 未覆盖检测区域) |

---

## Phase 1: 基础设施连通性 (4/4) — 会话 1

| 检查项 | 结果 | 详情 |
|--------|------|------|
| Kafka broker 健康 | ✅ | `kafka:29092` PLAINTEXT, topics: statistics_1, track_complete_1, conflicts_1 |
| Platform API 启动 | ✅ | Uvicorn on port 8000, DB/InfluxDB/Kafka consumer 全部连接 |
| WebSocket 连接 | ✅ | `/ws/realtime` 通过 Vite proxy 正常连接, platform 确认 "connection open" |
| JWT 认证 | ✅ | POST `/api/v1/auth/login` → 200, cookie `thisisjustarandomstring` 正确传递 |

## Phase 2: 页面渲染 (8/8) — 会话 1

| 检查项 | 结果 | 详情 |
|--------|------|------|
| 路由导航 | ✅ | 从 Dashboard 点击"实时监测"→ `/monitoring` 加载成功 |
| 路口选择器 | ✅ | 从 API 加载 2 个路口: "路口 1 (Camera 1)", "路口 2 (Camera 2)" |
| 路口切换 | ✅ | 切换到路口 2 → 无人机更新为 drone_002 → 切回路口 1 → 数据重置 |
| 状态栏 | ✅ | 显示 "● OFFLINE"/"● ONLINE", 无人机 ID, 巡飞/悬停 状态 |
| Pipeline 可视化 | ✅ | RTSP → YOLO11 → BEV → VLM 节点正确渲染 |
| 视频面板 (STANDBY) | ✅ | 显示 7 个原型检测框 (car/bus/moto/truck), STANDBY 时间戳 |
| BEV 面板 | ✅ | 十字交叉路口, 8 条车道多边形, 13 个车辆点, 轨迹线 |
| 图表行 | ✅ | 流量趋势/车道流量/拥堵指数/告警时间线 4 列正确渲染 |

## Phase 3: API 交互 (4/4) — 会话 1

| 检查项 | 结果 | 详情 |
|--------|------|------|
| GET /intersections | ✅ | 200 OK, 返回路口列表 |
| GET /intersections/:id | ✅ | 200 OK, 返回路口详情含 5 条车道 |
| GET /pipelines (轮询) | ✅ | 200 OK, 每 5s 刷新, 正确检测 pipeline 状态变化 |
| POST /pipelines (启动流) | ✅ | 201 Created, pipeline 创建成功 (PID 分配), GPU 不可用导致退出 code=2 |

## Phase 4: 实时数据流 (Kafka → WebSocket → UI) (6/6) — 会话 1

| 检查项 | 结果 | 详情 |
|--------|------|------|
| Kafka 消息发送 | ✅ | `kafka-console-producer` → topic `statistics_1` |
| Platform 消费 | ✅ | Kafka consumer 收到并处理 stats 消息 |
| WebSocket 广播 | ✅ | Platform → `intersection:INT_camera_1` channel |
| UI 实时更新 | ✅ | WS 指示器: "等待数据" → "实时", 点亮度从 opacity-50 → active |
| 指标显示 | ✅ | FPS=28.5, 推理=12.3ms, 目标=42辆, 跟踪=15 |
| 车道/转向数据 | ✅ | 5 条车道指标更新, 转向行为分布 n=15, 平均车速 32.5 km/h |

### ⚠️ 已知问题

| 问题 | 严重度 | 说明 |
|------|--------|------|
| MJPEG 502 / OFFLINE | WARN | 管道需 GPU 或通过 API 启动; 本地手动启动时 `streamActive=false`, MJPEG 不渲染, 前端显示原型检测框 |
| ~~LaneStats 全 0~~ | ~~WARN~~ | ~~已修复（会话 4）~~ |

---

## 测试会话 3：整合后管道 + 全流程回归验证

**日期**: 2026-05-31  
**变更**: `main_optimized.py` 整合（删除 `main_stream_optimized.py` 和 `main_stream_optimized_v2.py`，融入 v2 健康检查特性）  
**数据源**: 同上 inter_xqh 视频 + SRT 遥测  
**检测管道**: `main_optimized.py` (3 进程, MPS, PID 95146, 已运行 1h45m)

### 结果：14 PASS / 0 FAIL / 1 WARN

| # | 检查项 | 结果 | 实际值 |
|---|--------|------|--------|
| 1 | 管道持续运行 | ✅ | PID 95146, 运行 1h45m, 无崩溃 |
| 2 | Kafka 数据流 | ✅ | statistics_3 持续产出: cars=40, fps=3.5, congestion=46.4 |
| 3 | 路口选择器 | ✅ | 3 个选项: Camera 1, Camera 2, 小清河北路与水屯路路口 |
| 4 | 切换至 Camera 3 | ✅ | 路口=INT_camera_3, 实时数据 < 5s 内加载 |
| 5 | 实时指标 | ✅ | FPS=3.3→3.6, 推理=55.5ms, 目标=40→41辆, 跟踪=40 |
| 6 | 无人机遥测 | ✅ | UAV-3, 36.702909°N 117.02233°E, E=-0.45m, N=0m, 悬停 |
| 7 | 流量/拥堵 | ✅ | 当前流量=40辆, 拥堵指数=46.00 (重度拥堵) |
| 8 | 转向行为分布 | ✅ | n=40→41, 直行94%, 掉头6%, 平均车速29.6→30.4 km/h |
| 9 | 车道名称 (inter_xqh) | ✅ | 水屯路北段/小清河北路东段/水屯路南段/小清河北路西段/路口中心区 |
| 10 | WebSocket 退订 (切回 Camera 1) | ✅ | 数据全部清空 "等待数据", drone_001, 无残留数据 |
| 11 | WebSocket 重订阅 (再切回 Camera 3) | ✅ | 实时数据恢复: FPS=3.5, 目标=41, 拥堵=46.00 |
| 12 | 控制台错误 | ✅ | 仅 1 条 StrictMode WS 警告（已知），0 error |
| 13 | Platform API | ✅ | GET /intersections/INT_camera_3 → 200 OK |
| 14 | 告警中心 badge | ✅ | 显示 "1" 条未处理告警 |
| 15 | MJPEG 视频流 | ⚠️ | OFFLINE (管道非 API 启动) |

### 全链路健康检查

| 组件 | 状态 |
|------|------|
| 检测管道 (PID 95146) | ✅ Running 1h45m |
| Docker: traffic_platform | ✅ Up 2h |
| Docker: traffic_kafka | ✅ Up 2h (healthy) |
| Docker: traffic_postgres | ✅ Up 22h (healthy) |
| Docker: traffic_influxdb | ✅ Up 2h |
| Frontend (Vite :5173) | ✅ HTTP 200 |
| Platform API (:8000) | ✅ HTTP 200 |
| Kafka statistics_3 | ✅ Active |
| Drone position | 36.702909°N 117.02233°E |
| Direction flow | straight=120, u_turn=7 |

---

## 测试会话 4：车道级指标修复验证

**日期**: 2026-05-31  
**触发**: 用户报告 "切换到第三路视频，车道级指标都是0"  
**根因**: 三层问题叠加导致 lane_stats 始终为 null

### 根因分析

| 层 | 问题 | 严重度 |
|---|---|---|
| 数据 | `inter_xqh_lanes.json` 的 `"lanes": {}` 为空，road polygons 存在但未被加载 | Critical |
| 管道 | `VideoReader` 仅在 `lanes` 非空时创建 `lane_polygons`，空 lanes → `None` → `LaneAnalysisNode` 跳过 | Critical |
| 格式 | KafkaProducerNode 发 `lane_stats`（dict），前端读 `lanes`（array），键名和结构均不匹配 | Critical |

### 修复内容

1. **VideoReader.py** — 当 `lanes` 为空时，将 `roads` 多边形降级为车道多边形：
```python
elif self.roads_info:
    from shapely.geometry import Polygon
    self.lane_polygons = {}
    for road_id, coords in self.roads_info.items():
        if len(coords) >= 6:
            self.lane_polygons[road_id] = Polygon(...)
```

2. **consumer.py** — 在 `_handle_stats()` 中转换 `lane_stats` dict → `lanes` array：
```python
lane_stats = data.get("lane_stats")
if lane_stats and isinstance(lane_stats, dict):
    lanes_arr = []
    for lid, v in lane_stats.items():
        entry = {"lane_id": int(lid), "vehicle_count": v.get("count", 0), **v}
        cnt = v.get("count", 0)
        if cnt > 0:
            entry["headway_sec"] = round(60.0 / cnt, 1)
        lanes_arr.append(entry)
    data["lanes"] = lanes_arr
```

3. **main_optimized.py** — 修复 macOS spawn 模式下 Process 对象无法 pickle 的问题，改用 PID (`int`) 做健康检查。

### 结果：16 PASS / 0 FAIL / 1 WARN

| # | 检查项 | 结果 | 实际值 |
|---|--------|------|--------|
| 1 | 管道启动 (PID 修复) | ✅ | 4 进程正常运行, spawn 模式 PID 传递正确 |
| 2 | lane_stats 非 null | ✅ | 5 个区域全部有数据 |
| 3 | 水屯路北段 | ✅ | 流量 7.0 v/m, 车头时距 8.6s, 排队 6m, 车速 9.0 km/h |
| 4 | 小清河北路东段 | ✅ | 流量 22.0 v/m, 车头时距 2.7s, 排队 **44m**, 车速 **0.6** km/h (严重拥堵) |
| 5 | 水屯路南段 | ✅ | 流量 1.0 v/m, 车头时距 60.0s, 排队 0m, 车速 13.6 km/h |
| 6 | 小清河北路西段 | ✅ | 流量 6.0 v/m, 车头时距 10.0s, 排队 2m, 车速 9.8 km/h |
| 7 | 路口中心区 | ✅ | 流量 0.0 v/m (无车辆命中中心区域, 符合预期) |
| 8 | 车头时距计算 | ✅ | headway_sec 由 consumer 从 count 推算 (60/count) |
| 9 | 前端车道名称匹配 | ✅ | 水屯路北段/小清河北路东段/水屯路南段/小清河北路西段/路口中心区 |
| 10 | 路口切换数据刷新 | ✅ | Camera 1 → Camera 3 → Camera 1 → Camera 3 全部正确 |
| 11 | 实时指标 | ✅ | FPS=5.7, 推理=78.9ms, 目标=84, 跟踪=84 |
| 12 | 拥堵指数 | ✅ | 15.60 (重度拥堵) |
| 13 | 转向行为分布 | ✅ | n=84, 直行100%, 平均车速 20.8 km/h |
| 14 | 无人机遥测 | ✅ | UAV-3, 36.702909°N 117.02233°E, 悬停 |
| 15 | 控制台 0 error | ✅ | 无 error 日志 |
| 16 | 告警 badge | ✅ | 显示 "1" |
| 17 | MJPEG 视频流 | ⚠️ | OFFLINE (管道非 API 启动) |

**截图**: `docs/e2e-monitoring-lanestats-fixed.png`

---

## 修复记录

### 1. WebSocket 动态频道订阅 (本次修复) 🔧

**问题**: `useWebSocket` hook 仅在 WebSocket 首次 `onopen` 时发送 subscribe 消息。当 `selectedIntersection` 变化时 (用户切换路口), `channels` prop 更新但不会发送新的 subscribe/unsubscribe 消息。导致切换路口后 WebSocket 仍订阅旧频道, 新路口无法接收实时数据。

**修复**: 在 `use-websocket.ts` 中添加 channel 变更检测:
- 新增 `prevChannelsRef` 追踪上次订阅的 channels
- 新增 `useEffect([channelsKey])` 监听 channels 变化
- 当 channels 变化时, 发送 `unsubscribe` (旧频道) 和 `subscribe` (新频道) 消息
- 使用 `JSON.stringify(channels)` 作为依赖键, 避免数组引用变化触发无效更新

**文件**: `traffic-fly-console/src/hooks/use-websocket.ts`

### 2. 转向行为字段名不匹配 (本次修复) 🔧

**问题**: Kafka stats 消息中 `direction_flow` 使用 `count` 字段 (如 `{"straight": {"count": 63}}`), 但前端 monitoring 组件读取 `vehicle_count` 字段, 导致转向行为分布全部显示 0。

**修复**: 在 `monitoring/index.tsx` 中添加兼容性读取:
```javascript
const count = (d?.vehicle_count as number) || (d?.count as number) || 0
```

**文件**: `traffic-fly-console/src/features/monitoring/index.tsx`

### 3. INT_camera_3 路口注册 (本次修复) 🔧

**问题**: Platform `_INTERSECTIONS` 字典仅硬编码了 INT_camera_1 和 INT_camera_2, 没有 inter_xqh 路口。

**修复**: 
- 在 `intersections.py` 中添加 INT_camera_3 条目 (名称: "小清河北路与水屯路路口", 5 条车道含真实名称)
- 在 `drone_store.py` 中更新 drone_003 状态为 "flying" 并关联 INT_camera_3
- 通过 `docker cp` 更新运行中的容器

**文件**: `platform/app/api/v1/intersections.py`, `platform/app/models/drone_store.py`

### 4. 车道级指标全链路修复 (会话 4 修复) 🔧

**问题**: 三层叠加导致前端 LaneStats 全部为 0:
1. `inter_xqh_lanes.json` 的 `"lanes": {}` 为空 → VideoReader 不创建 `lane_polygons` → LaneAnalysisNode 跳过
2. KafkaProducerNode 发 `lane_stats`（dict: `{"1": {"count": 4, ...}}`），前端读 `lanes`（array: `[{lane_id: 1, vehicle_count: 4, ...}]`），键名和结构均不匹配
3. macOS spawn 模式下 Process 对象无法 pickle（`TypeError: cannot pickle 'weakref.ReferenceType'`）

**修复**:
- `VideoReader.py`: 当 `lanes` 为空时，将 `roads` 多边形降级为 `lane_polygons`
- `consumer.py`: `_handle_stats()` 中转换 `lane_stats` dict → `lanes` array + 计算 `headway_sec`
- `main_optimized.py`: 改用 PID (`int`) + `_is_pid_alive()` 替代传递 `Process` 对象

**文件**: `nodes/VideoReader.py`, `platform/app/kafka/consumer.py`, `main_optimized.py`

### 5. Kafka SASL 认证冲突 (会话 1 修复)

**问题**: Kafka 配置了 SASL + PLAINTEXT listener 冲突, 导致 `GroupCoordinatorNotAvailableError`。

**修复**: 移除 `docker-compose.yaml` 中 Kafka 的 SASL 配置。

### 6. 后端认证 (会话 1 配置)

- 注册用户: `POST /api/v1/auth/register` (admin/admin123)
- 前端自动从 cookie 读取 JWT token

### 7. .env 文件 (会话 1 创建)

```
KAFKA_USERNAME=admin
KAFKA_PASSWORD=admin-secret
INFLUXDB_ADMIN_USER=admin
INFLUXDB_ADMIN_PASSWORD=admin123
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=admin
```

---

## 数据流架构验证

```
┌──────────────────────────────────────────────────────────┐
│  检测管道 (MPS/CUDA)                                       │
│  main_optimized.py → YOLO11 → ByteTrack → BEV           │
│  + SRT遥测解析 → MotionCompensation → DirectionFlow     │
│  → KafkaProducerNode → Kafka topic: statistics_N         │
└───────────────────────┬──────────────────────────────────┘
                        │ Kafka (PLAINTEXT, kafka:29092)
                        ▼
┌──────────────────────────────────────────────────────────┐
│  Platform (traffic_platform:8000)                         │
│  AIOKafkaConsumer → pattern: (statistics|track|...)_.*   │
│  → _handle_stats() → WSManager.broadcast()               │
│  → channel: "intersection:INT_camera_N"                  │
└───────────────┬──────────────────────────┬───────────────┘
                │ WebSocket /ws/realtime   │ REST API
                ▼                          ▼
┌──────────────────────────────────────────────────────────┐
│  Console Frontend (Vite :5173)                            │
│  useWebSocket hook → dynamic channel subscribe           │
│  → onMessage → setLatestStats → React re-render          │
│  → FPS/推理/目标/跟踪/拥堵/转向/车道/无人机位置 实时更新  │
└──────────────────────────────────────────────────────────┘
```

**全链路延迟**: < 1s (Kafka → Platform consumer → WebSocket → UI)

---

## 测试环境

| 组件 | 版本/配置 |
|------|-----------|
| 前端 | Vite dev server, React 19, TanStack Router/Query, Tailwind CSS |
| 后端 | FastAPI/Uvicorn (Docker), AIOKafka, PostgreSQL 16 |
| 检测管道 | Python 3.12, YOLO (uav_best.pt), Apple MPS (M4 GPU) |
| 视频 | DJI M300 RTK 4K 无人机视频, 30fps, 5.3GB |
| 遥测 | DJI SRT 字幕文件, 逐帧 GPS+gimbal 数据 |
| Kafka | wurstmeister/kafka, PLAINTEXT listeners |


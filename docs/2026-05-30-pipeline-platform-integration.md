# 视频检测流 × 无人机平台整合方案

> 日期：2026-05-30
> 状态：**Phase 1 已完成** ✅ — 端到端验证通过（49/49 PASS）
> 目标：将检测管道（pipeline）与管理平台（platform）打通，实现端到端的无人机交通监控闭环

---

## 1. 整合目标

```
用户故事：
1. 操作员在平台上创建巡检任务 → 平台自动启动检测管道 → 绑定无人机视频流
2. 实时检测数据（统计/轨迹/冲突）通过Kafka回流到平台 → WebSocket推送到前端
3. 无人机遥测数据实时更新 → 地图上显示无人机位置和检测区域
4. 任务结束 → 管道自动停止 → 数据归档可查
```

## 2. 当前架构 Gap 分析

| # | Gap | 位置 | 影响 | 优先级 |
|---|-----|------|------|--------|
| G1 | Kafka topic pattern 只订阅 `statistics_.*` | `platform/app/core/config.py` | 漏掉 track_complete 和 conflicts | 🔴 高 |
| G2 | Kafka consumer 不处理 `conflict` 消息类型 | `platform/app/kafka/consumer.py` | 冲突事件丢失 | 🔴 高 |
| G3 | drone_store.py 全是硬编码模拟数据 | `platform/app/models/drone_store.py` | 无真实遥测 | 🔴 高 |
| G4 | 检测管道和平台无生命周期耦合 | 架构层面 | 无法按需启停 | 🟡 中 |
| G5 | Intersection ID 不统一 | 多处 | 数据关联困难 | 🟡 中 |
| G6 | 视频流 HLS 转换需 FFmpeg（未安装时降级） | `platform/app/api/v1/video.py` | 视频不可用 | 🟡 中 |
| G7 | 两个独立的 docker-compose | 部署层面 | 网络不通 | 🟡 中 |

## 3. 实施方案

### Phase 1：数据链路打通（本次实施）

```
修改文件：
├── platform/app/kafka/consumer.py       — 添加 conflict 处理 + telemetry 处理
├── platform/app/core/config.py          — 扩展 Kafka topic pattern
├── platform/app/models/drone_store.py   — 添加遥测更新接口
├── platform/app/services/pipeline_manager.py — [新增] 管道生命周期管理
├── platform/app/api/v1/pipelines.py     — [新增] 管道管理API
├── platform/app/main.py                 — 注册 pipeline router
└── docker-compose.yaml                  — 添加 platform + postgres 服务
```

#### 3.1 扩展 Kafka Consumer

```python
# 修改 _process_message 添加：
elif msg_type == "conflict":
    await self._handle_conflict(data, intersection_id)
elif msg_type == "telemetry":
    await self._handle_telemetry(data)

# 修改 topic pattern：
kafka_topics_pattern = "(statistics|track_complete|conflicts|telemetry)_.*"
```

#### 3.2 PipelineManager 设计

```
PipelineManager
├── start_pipeline(mission_id, drone_id, video_src, roads_json)
│   └── 启动子进程: python main_optimized.py (带环境变量)
├── stop_pipeline(pipeline_id)
│   └── 发送SIGTERM → 等待优雅退出
├── get_status(pipeline_id)
│   └── 返回: running/stopped/error + FPS + 队列深度
└── list_pipelines()
    └── 返回所有管道实例状态
```

#### 3.3 Drone Store 遥测更新

```python
# 新增函数：
def update_drone_telemetry(drone_id: str, telemetry: dict):
    """从Kafka遥测消息更新无人机状态"""
    if drone_id in DRONES:
        DRONES[drone_id]["last_telemetry"] = telemetry
        DRONES[drone_id]["battery_pct"] = telemetry.get("battery_pct", ...)
        # 更新位置
        ...
```

### Phase 2：管道生命周期管理（后续）

- 创建 Mission → Pipeline 绑定模型
- 前端任务创建界面
- 管道健康监控面板

### Phase 3：统一部署（后续）

- 合并两个 docker-compose 为一个
- 共享 Kafka/InfluxDB 实例
- Nginx 统一入口（前端 + API + 视频流）

## 4. 数据流总览

```
无人机RTSP流
    │
    ▼
┌──────────────────────────────────────────────┐
│  检测管道 (main_optimized.py)                  │
│  VideoReader → Detection → Tracking → ...     │
│  → KafkaProducerNode                          │
└───────────┬──────────────────────────────────┘
            │ Kafka topics:
            │   statistics_{n}     → 统计
            │   track_complete_{n} → 轨迹
            │   conflicts_{n}      → 冲突
            ▼
┌──────────────────────────────────────────────┐
│  平台 (platform/app)                          │
│  KafkaConsumerService                         │
│  ├── _handle_stats()       → WebSocket广播    │
│  ├── _handle_track_complete() → WebSocket广播  │
│  ├── _handle_conflict()    → AlertEngine触发  │
│  └── _handle_telemetry()   → DroneStore更新   │
│                                               │
│  PipelineManager                              │
│  ├── 启动/停止管道                             │
│  └── 健康监控                                  │
└───────────┬──────────────────────────────────┘
            │ WebSocket推送
            ▼
┌──────────────────────────────────────────────┐
│  前端 (traffic-fly-console)                    │
│  ├── Dashboard: 实时统计                       │
│  ├── Drones: 实时遥测                          │
│  ├── Video: HLS视频流                          │
│  ├── GIS: 轨迹回放                             │
│  └── Alerts: 冲突告警                          │
└──────────────────────────────────────────────┘
```

## 5. API 新增端点

### 管道管理 API

#### `GET /api/v1/pipelines`
- 返回：所有管道实例列表及状态

#### `POST /api/v1/pipelines`
- 请求体：
```json
{
  "drone_id": "drone_001",
  "intersection_id": "INT_camera_1",
  "video_src": "rtsp://...",
  "roads_json": "configs/inter1_lanes.json"
}
```
- 返回：创建的管道实例

#### `DELETE /api/v1/pipelines/{pipeline_id}`
- 停止并删除指定管道

#### `GET /api/v1/pipelines/{pipeline_id}/status`
- 返回管道健康状态

## 6. 实施状态

### Phase 1: 数据链路打通 ✅ 已完成

| Gap | 修复内容 | 文件 |
|-----|---------|------|
| G1 | Kafka topic pattern → `(statistics\|track_complete\|conflicts\|telemetry)_.*` | `config.py`, `run_local.py` |
| G2 | 新增 `_handle_conflict()` + `_handle_telemetry()` | `consumer.py` |
| G3 | `update_drone_from_stats()` + `update_drone_telemetry()` | `drone_store.py` |
| G4 | `PipelineManager` 子进程管理 + REST API | `pipeline_manager.py`, `pipelines.py` |
| G5 | 统一使用 `INT_camera_{N}` 格式 | `consumer.py`, `intersections.py` |
| G7 | `docker-compose.yaml` 新增 postgres + platform 服务 | `docker-compose.yaml` |

### Bug 修复

1. **`consumer.py`** — `_handle_conflict` 格式化崩溃：`data.get('ttc_sec', '?')` → float 转换防护
2. **`main.py`** — `/ready` 端点 `pipelines_active`(int) 混入 services dict → 独立字段
3. **`run_local.py`** — Kafka topic pattern 旧版 `statistics_.*` → 更新

### 新增文件

| 文件 | 说明 |
|------|------|
| `services/SrtTelemetryParser.py` | DJI 视频 SRT 字幕遥测解析器 |
| `platform/app/services/pipeline_manager.py` | 管道生命周期管理 |
| `platform/app/api/v1/pipelines.py` | 管道管理 REST API (6 routes) |
| `test_pipeline_inter_xqh.py` | 端到端测试脚本 (49 checks) |

## 7. 端到端测试结果

> 详见 `docs/test_report_inter_xqh.md`

**测试资产**: `test_videos/inter_xqh/` (DJI M300 4K@30fps + SRT 遥测 29,741 条)

```
Phase 1: SRT遥测解析     7/7  ✅
Phase 2: 视频读取        6/6  ✅
Phase 3: 节点实例化      8/8  ✅
Phase 4: H矩阵+运动补偿  14/14 ✅
Phase 5: VideoReader集成  6/6  ✅
Phase 6: 完整管道(100帧)  8/8  ✅
─────────────────────────────
总计:                    49/49 ✅  0 FAIL  0 WARN
```

### 关键指标

| 指标 | 值 |
|------|------|
| 检测率 | 100/100 帧 (100%) |
| 遥测注入 | 100/100 (100%) |
| H矩阵有效 | 100/100 (100%) |
| 运动补偿有效 | 90/100 (前10帧锚点采集) |
| 方向统计 | ✅ 5类 (straight/left/right/u-turn/unknown) |
| 处理速度 | 2.0 fps (CPU, 4K输入) |

## 8. 后续阶段

### Phase 2: Mission-Pipeline 绑定
- [ ] 创建任务时自动启动检测管道
- [ ] 前端 Drones 页面接入 telemetry WebSocket
- [ ] Dashboard pipelines_active 对接真实数据

### Phase 3: 部署统一
- [ ] 合并 docker-compose（统一 Kafka/InfluxDB/Nginx）
- [ ] 管道健康监控面板

### Phase 4: 高级功能
- [ ] GIS 轨迹回放
- [ ] 巡检报告生成
- [ ] 多无人机调度
- [ ] VLM 语义分析旁路

# 端到端测试报告：inter_xqh 视频 + SRT 遥测

> **架构替代声明（2026-07-15）**：`56 PASS / 0 FAIL / 0 WARN` 是算法/管道防回退证据；它不证明 database=`road9`、`uav_` 消息与表命名、TimescaleDB、历史数据迁移或 InfluxDB/Telegraf/Grafana 退役已完成。目标数据架构及新增验收门禁见 [ADR-019](DECISIONS.md)、[API_CONTRACTS.md](API_CONTRACTS.md) 和 [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md)。

**最近复跑日期**: 2026-07-15
**测试资产**: `test_videos/inter_xqh/`  
- 视频: `DJI_20260403142902_0001_V小清河北路与水屯路路口.mp4` (5.4GB, 4K, 16.5min)  
- 遥测: `telemetry.srt` (29,741 条记录, 逐帧@30fps)

---

## 测试结果：56 PASS / 0 FAIL / 0 WARN ✅

2026-07-15 当前工作树复跑 `python test_pipeline_inter_xqh.py` 通过：`56 PASS / 0 FAIL / 0 WARN`。前 100 帧真实 YOLO+SRT 管道耗时 96.4s（CPU），检测目标帧率 100/100、累计 8051 个目标、遥测注入 100/100、H 矩阵 100/100、运动补偿 90/100、机非冲突事件数 0。

### Phase 1: SRT 遥测解析 (7/7)
| 检查项 | 结果 | 详情 |
|--------|------|------|
| 文件存在 | ✅ | telemetry.srt |
| 记录数 > 0 | ✅ | 29,741 records |
| 时长 > 0 | ✅ | 992s (16.5min) |
| 字段完整 | ✅ | timestamp, lat, lon, height, gimbal_pitch/yaw, focal_len |
| GPS有效 | ✅ | lat=36.702909, lon=117.02233 |
| 高度 > 0 | ✅ | 130.0m (相对高度) |
| SRT特有字段 | ✅ | focal_len=24.0mm |

### Phase 2: 视频读取 (6/6)
| 检查项 | 结果 | 详情 |
|--------|------|------|
| 可打开 | ✅ | OpenCV VideoCapture |
| 分辨率 | ✅ | 3840×2160 (4K) |
| FPS | ✅ | 30.0 fps |
| 时长 | ✅ | 992s |
| 遥测/视频匹配 | ✅ | ratio=1.00 (完美1:1) |
| 首帧可读 | ✅ | shape=(2160, 3840, 3) |

### Phase 3: 节点实例化 (8/8)
全部8个节点成功实例化：
HomographyCalibrationNode, MotionCompensationNode, SpeedEstimationNode,
DirectionFlowNode, LaneAnalysisNode, TrajectoryNode, ConflictDetectionNode, CalcStatisticsNode

### Phase 4: 遥测→单应性→运动补偿 链路 (14/14)
- **GPS锚点**: (36.702909, 117.022330), gimbal_yaw=0.7°
- **H矩阵**: 3/3 时间点有效 (mode=telemetry)
- **运动补偿**: 3/3 时间点有效 (hover=True)
- **像素→世界变换**: 图像中心→(0.00, 0.00)m ✅

### Phase 5: VideoReader集成 (6/6)
- 20帧全部注入SRT遥测数据
- 帧级同步精度: 0.033s

### Phase 6: 完整管道 (9/9)
| 指标 | 值 |
|------|------|
| 处理帧数 | 100 |
| 处理速度 | 0.2 fps (CPU, 4K输入，100帧约541.4s) |
| 检测率 | 100/100 帧 (100%) |
| 累计检测 | 8,051 目标 |
| 遥测注入 | 100/100 (100%) |
| H矩阵 | 100/100 (100%) |
| 运动补偿 | 90/100 (前10帧为锚点采集期) |
| 方向统计 | ✅ straight/left_turn/right_turn/u_turn/unknown |
| 车辆数 | 82 |
| 活跃轨迹 | 86 |
| 机非冲突事件数 | 0 |

---

## 修复的问题

### Bug #1: `_handle_conflict` 格式化崩溃
**文件**: `platform/app/kafka/consumer.py`  
**问题**: `data.get('ttc_sec', '?')` 返回字符串 `'?'` 后接 `:.1f` 格式化导致 TypeError  
**修复**: 先转为 float 再格式化，加 try/except 防护

### Bug #2: `/ready` 端点混合类型
**文件**: `platform/app/main.py`  
**问题**: `pipelines_active` (int) 混入 services dict，导致 `all_ready` 始终为 False  
**修复**: 将 `pipelines_active` 提取为独立字段，不混入 services 状态判断

### Bug #3: `run_local.py` 旧版 topic pattern
**文件**: `platform/scripts/run_local.py`  
**问题**: 仍使用旧 topic pattern，漏掉 track_complete/conflicts/telemetry/system_metrics
**修复**: 更新为 `((statistics|track_complete|conflicts|telemetry)_.*|system_metrics)`

### 改进: Phase 4 测试预热
**文件**: `test_pipeline_inter_xqh.py`  
**问题**: 仅喂3帧但锚点需10帧，导致运动补偿始终为 None  
**修复**: 增加12帧预热阶段建立GPS锚点

### 改进: SRT 遥测支持
**文件**: `test_pipeline_inter_xqh.py`  
**变更**: 从 JSON file 切换到 SRT 源 (source: "srt", time_offset: 0)

### 改进: xqh 机非冲突误报压制
**文件**: `nodes/ConflictDetectionNode.py`
**变更**: 默认 `enable_same_time_cpa=false`，业务口径只接受未来路径交点/PET 候选，避免 0.9m~1.7m 中心点擦肩经过被判成相撞；CPA 保留为显式开启扩展，且 `pet_sec=0` 不作为 PET hard 证据。右转/左转场景新增 `min_turn_leg_m=2.0m`，且机动车正常转弯 heading 变化不计作避险急转向。前 100 帧真实检测链路中 `conflicts=0`。

### 改进: PET-only 与回放红圈误导修正
**文件**: `nodes/ConflictDetectionNode.py`, `traffic-fly-console/src/features/monitoring/`
**变更**: `PET<=1s` 不再单独触发 near-miss；当 `TTC>1.5s` 时必须叠加急刹、非机动车急转向或停车/让行证据，压制 TTC 2.x 秒、轨迹错位但低 PET 的误报。BEV 冲突回放风险圈和距离辅助线锚定事件预测冲突位置，而不是两车当前播放点中点。

### 改进: 路径交点同一时空占用门槛
**文件**: `nodes/ConflictDetectionNode.py`
**变更**: 路径交点 PET 候选不再只看“预测射线相交 + 到达时间差”。双方到达交点这段时间内的连续同刻最小中心距必须进入 `same_time_collision_radius_m=0.8m` 共同冲突区，否则不上报；这会过滤回放中虚线/红圈看起来相交、但轨迹并无同一时空碰撞概率的样本。新增回归测试覆盖“到达时间差达标但同刻中心距离超过实际碰撞半径”场景；`test_refactor_unit.py` 为 `52 PASS / 0 FAIL`。

### 改进: 预测方向优先使用最近轨迹段
**文件**: `nodes/ConflictDetectionNode.py`
**变更**: TCC 预测不再直接使用 `SpeedEstimationNode` 的线性回归速度方向外推；有历史轨迹时，未来方向取最近一个有效轨迹段，速度大小仍沿用测速节点的米/秒估计。新增回归测试覆盖“历史轨迹直行但回归速度指向虚假交点”的截图类误报；inter_xqh 前 100 帧真实 YOLO+SRT 验证仍为 `56 PASS / 0 FAIL / 0 WARN`、冲突事件数 `0`。

### 改进: TCC 业务口径字段与 CPA-only 回放过滤
**文件**: `nodes/ConflictDetectionNode.py`, `traffic-fly-console/src/features/monitoring/`
**变更**: conflict 事件新增 `prediction_type`，默认业务冲突输出为 `path_intersection`，路径交点场景 `distance_m=0.0`。Monitoring WebSocket 入口过滤 `prediction_type=same_time_cpa` 的中心点擦肩事件；旧格式事件仅在 `distance_m≈0.0` 时按路径交点兼容，带 `prediction_type=path_intersection` 但 `distance_m` 非零的畸形消息也会被过滤，避免截图中 0.9m/1.3m/1.7m 这类无共同冲突点的旧/扩展事件进入机非冲突回放列表。

### 改进: 冲突历史复盘证据持久化
**文件**: `platform/app/utils/influx_query.py`, `platform/tests/test_influx_query.py`, `docs/DATABASE_SCHEMA.md`
**变更**: `write_conflict_event()` 不再只写入最小 ID/TTC/distance 字段，现完整持久化 `prediction_type`、`conflict_scene`、`pet_sec`、`arrival_time_delta_sec`、双方到达时间、`conflict_angle_deg`、`evidence`、`risk_score`、预测位置和 GPS 锚点；`query_conflict_events()` 会把 JSON 字段还原为数组。验证：`python -m pytest platform/tests/test_influx_query.py -q` 为 `6 passed`。

### 改进: GIS 历史冲突证据复盘
**文件**: `traffic-fly-console/src/features/gis/index.tsx`, `traffic-fly-console/src/lib/api.ts`, `traffic-fly-console/src/features/gis/index.test.tsx`
**变更**: GIS 页在展示历史轨迹的同时调用历史冲突 API，显示冲突 pair、TTC/PET、业务场景、near-miss 证据和风险分，让操作员不离开平台即可从实时冲突进入事后证据链复盘。验证：`npm test -- gis/index.test.tsx` 为 `1 passed`。

---

## 平台集成验证

### 模块导入 ✅
所有12个Python文件语法检查通过，2个YAML文件验证通过。

### API 端点 ✅
核心 API smoke test 确认管道、路口、无人机、轨迹、告警、系统状态接口可在最小 FastAPI app state 下访问，含:
- `GET/POST /api/v1/pipelines` — 管道管理
- `GET /api/v1/pipelines/summary` — 管道概览
- `GET/DELETE /api/v1/pipelines/{id}` — 管道操作
- `GET /api/v1/pipelines/{id}/status` — 管道健康
- `GET /api/v1/intersections` / `/summary` — 路口与态势概览
- `GET /api/v1/drones` — 无人机状态
- `GET /api/v1/trajectories/{intersection_id}` — 轨迹复盘查询
- `GET /api/v1/trajectories/{intersection_id}/conflicts` — 历史冲突证据查询
- `GET /api/v1/alerts` — 告警列表
- `GET /api/v1/system/health` — 系统健康
- `platform/tests/test_core_api_routes.py` 覆盖以上核心 API 可访问性。
- 2026-07-02 live `/ready` 返回 `database/kafka/influxdb/pipeline_manager=healthy`，`pipelines_active=0`
- 默认账号 `admin/admin123` 登录成功；受保护 API 已验证 `/api/v1/pipelines`、`/api/v1/intersections/summary`、`/api/v1/drones`、`/api/v1/alerts`
- 2026-07-02 OpenAPI verification：`path_count=55`、`operation_count=58`，核心路由 `/api/v1/pipelines`、`/api/v1/intersections`、`/api/v1/drones`、`/api/v1/trajectories/{intersection_id}`、`/api/v1/trajectories/{intersection_id}/conflicts`、`/api/v1/alerts`、`/api/v1/system/health` 均存在。

### WebSocket 通道 ✅
- `intersection:{id}` → stats, track_complete, conflict 消息
- `alerts` → 新告警推送
- `telemetry:{drone_id}` → 实时遥测
- `system` → GPU/系统指标
- WebSocket 端点：`/ws/realtime`
- Kafka topic pattern：`((statistics|track_complete|conflicts|telemetry)_.*|system_metrics)`
- 2026-07-02 live WebSocket 握手：订阅 `system` 返回 `{"action":"subscribed","channel":"system"}`

### PipelineManager 容器启动依赖 ✅
- `platform/Dockerfile` 安装 `platform/pipeline-requirements.txt`，覆盖 `main_optimized.py` 所需的 `hydra-core`、YOLO/OpenCV、Kafka、Flask 等检测依赖，并用 `platform/pipeline-constraints.txt` 固定 `numpy<2`、`torch==2.2.2`、`torchvision==0.17.2`。
- `platform/tests/test_pipeline_manager.py` 覆盖启动命令、空 `ROADS_JSON` 无道路标注参数、SRT 遥测参数、Kafka bootstrap、独立 `VIDEO_PORT` 和依赖文件同步。
- 2026-07-02 live lifecycle：`POST /api/v1/pipelines` 启动 `test_videos/longer_example.mp4` 返回 `camera_id=11` / `video_port=8102` / `status=running`；运行 3s 后 `/api/v1/pipelines/{id}/status` 为 `process_alive=true`；`GET /api/v1/video/camera/{camera_id}` 返回 `200 multipart/x-mixed-replace` 且首包为 JPEG 帧；`DELETE /api/v1/pipelines/{id}` 后状态为 `stopped`，`/summary` 为 `running=0,error=0`。
- 2026-07-02 live MJPEG proxy：`POST /api/v1/pipelines` 启动 inter_xqh + SRT + `ROADS_JSON=""` 返回 `pipe-41be7924` / `camera_id=10` / `video_port=8101` / `status=running`；无认证访问 `/api/v1/video/camera/10` 返回 `200 multipart/x-mixed-replace`，3 秒抓取约 14-19MB MJPEG 字节；浏览器 `/monitoring` 中 `img[alt="Live detection feed"]` 的 `currentSrc=/camera_10`，`naturalWidth=1280`、`naturalHeight=720`，页面显示 `● ONLINE`、`停止流`、实时轨迹 180+ 条、冲突 `0 events`；从页面点击 `停止流` 后 `/proxy-map` 为 `{}`，`/summary` 为 `running=0,error=0`，`/api/v1/video/camera/10` 返回 `camera_not_running`。
- 2026-07-02 Platform image rebuild：`docker compose -f docker-compose.yaml -f docker-compose.test.yaml -p trafficanalyzer up -d --build platform` 成功，镜像 `trafficanalyzer-platform@sha256:a8929e32061dc33a4792f841029f068cf2b082662946ae2d7c5e8fbb5b2c1294`；重建后 `/ready` 仍为 `database/kafka/influxdb/pipeline_manager=healthy`，无运行管道时 `/api/v1/video/camera/10` 与 Vite `/camera_10` 均返回 `404 camera_not_running` 而不是 `401`。

### Mission-Pipeline 绑定 ✅
- `POST /api/v1/missions` 创建任务时会绑定无人机与路口，并立即调用 PipelineManager 启动检测管道；响应包含 `pipeline_id` 和 pipeline 状态，便于任务页和调度侧追踪实际检测进程。
- `platform/tests/test_missions_api.py` 覆盖创建任务自动启动 pipeline、写入 `MISSIONS`、更新 `DRONES[current_intersection_id]`、透传 SRT/道路参数，以及启动异常时 mission 标记 `error` 并返回 `502`。

### 历史统计复盘 ✅
- 2026-07-02 live Influx 查询：`GET /api/v1/intersections/INT_goal_verify/stats?period=10m&granularity=1s` 返回 601 个时间桶，其中 12 个为有效统计点；最近有效点示例 `cars=47.0`、`active_tracks=43.0`、`congestion_index=6.2`、`avg_speed_kmh=236.3`。
- 2026-07-02 Grafana provisioning verification：`services/grafana/provisioning/datasources/datasource.yaml` 自动配置 InfluxDB datasource UID `cdycrblq6bf9ce` 和 PostgreSQL datasource UID `f848db3d-2635-4913-be1c-ae2d0db7c90a`，与 `camera-1.json` / `camera-2.json` 面板引用一致；`docker compose config` 确认 provisioning 目录挂载到 `/etc/grafana/provisioning`，Grafana 容器默认注入 `admin/admin123` 登录账号和 InfluxDB 凭据环境变量。`python -m pytest test_grafana_provisioning.py -q` 通过 3 个回归测试。本机 Grafana UI smoke 因缺少 `grafana/grafana` 镜像且 Docker pull 无进展未完成。

### 道路归属基础单元测试 ✅
- `test_utils_local.py` 覆盖 `intersects_central_point()`：bbox 中心点落入不同道路多边形时返回正确 road id，落在所有道路外或多边形边界上时返回 `None`。
- 2026-07-02 utility verification：`python -m pytest test_utils_local.py -q` 通过 3 个测试。

### ByteTrack 核心单元测试 ✅
- `test_byte_tracker_core.py` 覆盖高置信检测创建轨迹、保留检测类别 ID，以及第二帧低置信但 IoU 匹配的检测延续同一 track id，保护航拍小目标连续跟踪能力。
- 2026-07-02 ByteTrack verification：`python -m pytest test_byte_tracker_core.py -q` 通过 2 个测试。

### 告警处置复盘 ✅
- AlertEngine 创建和确认告警会写入 PostgreSQL `alerts` 表；Platform 启动时加载历史告警到内存查询缓存，数据库不可用时降级为内存告警但不影响实时 WebSocket 推送。
- `platform/tests/test_alert_engine_persistence.py` 覆盖创建告警后持久化、模拟重启后加载、确认状态写回；`platform/tests/test_alerts_api.py` 覆盖 `/api/v1/alerts/{id}/acknowledge` 等待异步确认结果。
- 2026-07-02 platform verification：`python -m pytest platform/tests -q` 通过 31 个测试 / 11 个 subtests。

### 前端连接
- Dashboard: 使用 `kpi.drones_online` 和 `kpi.pipelines_active` (修复硬编码)
- Monitoring: 增加 conflict/track_complete 事件处理
- Dashboard: `pipelines_active` 接入真实管道状态，优先使用 `system_metrics.pipelines_active` 实时推送，列表未加载时回退 `/intersections/summary.pipelines_active`，列表加载后使用 `/pipelines` running 数。
- Drones: API已接入 `/api/v1/drones`，并按无人机 ID 动态订阅 `telemetry:{drone_id}`；WebSocket 遥测会立即覆盖轮询兜底值。
- GIS: 选中路口后调用 `/api/v1/trajectories/{intersection_id}?period=1h&limit=200` 和 `/api/v1/trajectories/{intersection_id}/conflicts?period=1h&limit=200`，展示历史轨迹数量、Track ID、转向、车辆类型、均速、时长、轨迹点数，以及历史冲突 pair、TTC/PET、场景、证据和风险分。
- 2026-07-02 frontend verification：`npm test` 通过 27 个测试文件 / 160 个测试；`npm run build` 通过 TypeScript 与 Vite 打包。

---

## 数据流验证

```
SRT文件 → SrtTelemetryParser → VideoReader(telemetry注入)
  → DetectionTrackingNodes(YOLO) → HomographyCalibrationNode
  → MotionCompensationNode → TrackerInfoUpdateNode
  → SpeedEstimationNode → DirectionFlowNode
  → LaneAnalysisNode → TrajectoryNode
  → ConflictDetectionNode → CalcStatisticsNode
  → KafkaProducerNode → Kafka topics
  → KafkaConsumerService → WebSocket广播 → 前端
```

全链路验证通过 ✅

### Kafka 输出契约单元验证 ✅
- `test_kafka_active_trajectories.py` 覆盖 KafkaProducerNode 在单帧处理中向 `statistics_*`、`track_complete_*`、`conflicts_*`、`telemetry_*` 四类 topic 入队，并校验统计、完成轨迹、冲突事件、无人机遥测的核心字段。
- 2026-07-02 Kafka producer verification：`python -m pytest test_kafka_active_trajectories.py -q` 通过 3 个测试。

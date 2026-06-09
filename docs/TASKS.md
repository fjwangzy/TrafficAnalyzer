# TASKS.md — TrafficAnalyzer 任务追踪

> 最后更新：2026-05-31（基于设计审查 `2026-05-31-design-review-and-tasks.md` 实施）

## 技术债清单

### 🔴 高优先级

#### TD-001: 硬编码 5 条道路 → ✅ 已解决
- **状态**：✅ 已修复（2026-05-31）
- **修复内容**：
  - `CalcStatisticsNode.py`: 从 `roads_info.keys()` 动态获取道路ID列表
  - `KafkaProducerNode.py`: 新增 `roads` 数组字段（动态道路数），保留 `road_1..road_N` 向后兼容
  - `influx_query.py`: `write_stats()` 动态写入 road_* 字段；`query_stats()` 动态查询

#### TD-002: 4 个入口点代码重复
- **位置**：`main.py`、`main_optimized.py`
- **问题**：4 个文件共享相同的 import 列表、环境变量设置、节点初始化逻辑
- **影响**：修改管道节点顺序或新增节点需要同时修改 4 个文件
- **建议**：统一为一个入口 + `--mode` 参数

#### TD-003: 无测试
- **问题**：整个项目缺少自动化测试
- **影响**：无法验证重构的正确性，回归风险高
- **状态**：🟡 部分解决 — 已添加 `test_pipeline_inter_xqh.py`（49项端到端检查）、`test_pipeline_no_yolo.py`（无GPU CI测试）、`test_e2e_inter_xqh.py`（端到端集成测试）、`scripts/inject_test_data.py`（WebSocket数据注入）
- **建议**：继续为 `utils_local/utils.py` 和 `byte_tracker/` 编写单元测试

#### TD-004: Grafana 凭据硬编码
- **位置**：`export_dashboards.py:6`、`fetch_dashboard.py:5`、`update_dashboards.py:5`
- **问题**：`admin:admin` 凭据硬编码在脚本中
- **影响**：安全风险（虽然这些脚本仅用于开发环境）
- **建议**：从环境变量或 `.env` 文件读取

#### TD-014: congestion_index 未计算 → ✅ 已解决
- **状态**：✅ 已修复（2026-05-31）
- **修复内容**：`KafkaProducerNode._compute_congestion_index()` 实现三因子计算（车辆密度0-4 + 排队0-3 + 低速0-3 = 0-10分）

#### TD-015: motion_compensation.py 死代码 → ✅ 已解决
- **状态**：✅ 已修复（2026-05-31）
- **修复内容**：`compensate_speed()`、`compensate_heading()`、`world_to_gps()` 标记为 deprecated + warnings.warn()

#### TD-016: 轨迹世界坐标精度有限
- **位置**：`nodes/TrajectoryNode.py`、`nodes/TrackerInfoUpdateNode.py`
- **问题**：使用当前帧H+当前drone_displacement统一转换所有历史轨迹点，未存储每帧的独立位移
- **影响**：快速巡飞时（12m/s）长轨迹（8s）世界坐标误差达96m
- **建议**：在TrackElement中存储per-frame `(px, py, displacement_e, displacement_n)` 或接受限制（用于热力图足够）

#### TD-017: lane_history / segment_queues_by_gap 未使用
- **位置**：`elements/TrackElement.py:24`、`utils_local/lane_geometry.py`
- **问题**：`lane_history` 字段和 `segment_queues_by_gap()` 函数已实现但未被使用
- **影响**：代码冗余
- **建议**：删除或实现队列分段逻辑

#### TD-018: 遥测时间戳对齐需手动配置 time_offset_sec
- **位置**：`services/TelemetryFileReader.py`、`configs/app_config.yaml`
- **问题**：视频文件和遥测数据的起始时间不同步，需要手动计算并配置 `time_offset_sec`
- **影响**：每次使用新的视频+遥测对时需要手动计算偏移
- **状态**：🟡 部分解决 — SRT遥测(`SrtTelemetryParser`)支持逐帧1:1同步，无需时间偏移；JSON遥测仍需手动配置
- **建议**：优先使用SRT格式（从视频字幕提取），避免手动偏移计算

### 🟡 中优先级

#### TD-005: FrameElement 动态属性 → ✅ 已解决
- **状态**：✅ 已修复（2026-05-31）
- **修复内容**：`FrameElement.__init__` 新增 `self.send_to_kafka: bool = False`

#### TD-006: ShowNode 过于庞大
- **位置**：`nodes/ShowNode.py`（352 行）
- **问题**：渲染逻辑（绘制框、多边形、文本、统计面板）全部在一个文件中
- **影响**：难以维护和测试
- **建议**：拆分为 `BoxRenderer`、`RoadRenderer`、`StatsPanelRenderer` 等子组件

#### TD-007: VideoEndBreakElement 未初始化父类
- **位置**：`elements/VideoEndBreakElement.py`
- **问题**：继承 FrameElement 但只设置了 `video_source` 和 `timestamp`，其他字段（`frame`、`source` 等）未初始化
- **影响**：如果某个节点忘记 isinstance 检查就访问 FrameElement 字段，会抛出 AttributeError
- **建议**：调用 `super().__init__()` 传入空值，或不继承 FrameElement

#### TD-008: TrackerInfoUpdateNode 假设字典有序 → ✅ 已解决
- **状态**：✅ 已修复（2026-05-31）
- **修复内容**：移除 `sorted()` + `break`，改为遍历所有元素检查时间条件

#### TD-009: export_dashboards.py 硬编码 Windows 路径
- **位置**：`export_dashboards.py:25`
- **问题**：`out_dir = r"d:\ai\TrafficAnalyzer\..."` 硬编码了 Windows 路径
- **影响**：在非 Windows 环境下无法运行
- **建议**：使用相对路径或从参数读取

### 🟢 低优先级

#### TD-010: 注释语言混杂
- **问题**：代码注释混合中文、俄语和英语
- **影响**：阅读体验不一致
- **建议**：统一为中文（当前团队的主要语言）

#### TD-011: 无类型标注
- **问题**：大部分函数缺少类型标注
- **影响**：IDE 自动补全和静态检查效果差
- **建议**：逐步添加类型标注，优先标注公共接口

#### TD-012: Flask 帧更新无锁
- **位置**：`nodes/FlaskServerVideoNode.py:36,52-53`
- **问题**：`self._frame` 被主线程写入、Flask 线程读取，无锁保护
- **影响**：可能出现画面撕裂（一帧的上半部分和下一帧的下半部分）
- **状态**：✅ 已修复 — 使用 `self._frame_lock` 和预编码 JPEG bytes 方案

#### TD-013: Kafka 基础设施稳定性
- **位置**：`docker-compose.yaml`、`services/kafka/kafka_server_jaas.conf`、`platform/app/kafka/consumer.py`
- **问题**：Kafka broker ID 不匹配、SASL 配置、consumer 重试策略
- **状态**：🟡 部分修复 — consumer 已增加指数退避重连（T-403）

---

## 审查改进实施记录（2026-05-31）

基于 `2026-05-31-design-review-and-tasks.md` 审查报告，以下任务已完成实施：

### Sprint 1: 数据链路打通 ✅

| ID | 任务 | 状态 | 修改文件 |
|----|------|------|----------|
| T-101 | KafkaProducerNode 异步发送 | ✅ | `nodes/KafkaProducerNode.py` — 独立发送线程 + Queue(maxsize=200)，Kafka 不可用时不阻塞管道 |
| T-102 | track/conflict 持久化到 InfluxDB | ✅ | `platform/app/utils/influx_query.py` — 新增 write_track_event/write_conflict_event/write_stats；`platform/app/kafka/consumer.py` — 注入 influx_client 并在 handler 中调用写入 |
| T-103 | 遥测 Topic 发布 | ✅ | `nodes/KafkaProducerNode.py` — 新增 `telemetry_{N}` topic，5Hz 节流发布 |
| T-104 | AlertEngine 补充规则 | ✅ | `platform/app/services/alert_engine.py` — 新增 high_avg_speed (P3) + multiple_conflicts (P2) 规则 |
| T-105 | Kafka 端到端验证 | ⏳ | 待环境验证 |
| T-106 | MJPEG 视频流验证 | ⏳ | 待环境验证 |

### Sprint 2: 数据质量提升 ✅

| ID | 任务 | 状态 | 修改文件 |
|----|------|------|----------|
| T-201 | 动态道路数 | ✅ | `CalcStatisticsNode.py` + `KafkaProducerNode.py` + `influx_query.py` + `consumer.py` — 从 roads_info 动态获取，Kafka 使用 roads 数组 |
| T-202 | 速度计算线性回归 | ✅ | `SpeedEstimationNode.py` — np.polyfit 全点拟合替代首尾两点法 |
| T-203 | 多因子拥堵指数 | ✅ | `KafkaProducerNode.py` — 车辆密度(0-4) + 排队(0-3) + 低速(0-3) = 0-10 分 |
| T-204 | TrackerInfoUpdateNode break 修复 | ✅ | `TrackerInfoUpdateNode.py` — 移除 sorted+break，遍历所有元素 |
| T-205 | FrameElement send_to_kafka 声明 | ✅ | `FrameElement.py` — __init__ 中声明 send_to_kafka: bool = False |
| T-206 | drone_store mock 移除 | ✅ | `drone_store.py` — DRONES={} / MISSIONS={}，通过 telemetry 自动注册 |

### Sprint 4: 质量加固（部分）

| ID | 任务 | 状态 | 修改文件 |
|----|------|------|----------|
| T-402 | motion_compensation.py 死代码 | ✅ | `utils_local/motion_compensation.py` — 3 个函数标记 deprecated + warnings.warn |
| T-403 | KafkaConsumer 自动重连 | ✅ | `platform/app/kafka/consumer.py` — 指数退避重连(5s→120s) |
| T-404 | InfluxQuery 字段名统一 | ✅ | `influx_query.py` + `trajectories.py` — trajectory_world_m 统一，反序列化 JSON 字段 |

### 待完成

- [ ] T-105: Kafka 端到端验证（需启动完整环境）
- [ ] T-106: MJPEG 视频流验证（需启动完整环境）
- [ ] T-301: Drones 页面对接 telemetry WebSocket
- [ ] T-302: GIS 轨迹回放
- [ ] T-303: Mission-Pipeline 绑定
- [ ] T-304: Dashboard pipelines_active 真实数据
- [ ] T-305: Alert 持久化到 PostgreSQL
- [ ] T-401: ShowNode 拆分
- [ ] T-405: utils_local/utils.py 单元测试
- [ ] T-406: ByteTrack 核心单元测试

---

## 待办事项

### 已完成 ✅
- [x] 管道端到端测试（`test_pipeline_inter_xqh.py`，49/49 PASS）
- [x] Kafka topic pattern 扩展（statistics + track_complete + conflicts + telemetry）
- [x] 平台 PipelineManager（管道生命周期管理）
- [x] 平台 Pipeline REST API（start/stop/monitor）
- [x] 平台 Kafka consumer 处理 conflict + telemetry 消息
- [x] drone_store 动态更新（Kafka stats + telemetry 双源）
- [x] SRT 遥测解析器（`SrtTelemetryParser`，逐帧同步）
- [x] docker-compose 统一（postgres + platform 服务加入主 compose）
- [x] 前端 WebSocket 事件处理（monitoring: conflict/track_complete, dashboard: 真实数据）
- [x] inter_xqh 道路多边形配置（4K 视频适配）
- [x] Kafka consumer 有限重试机制（防止阻塞 HTTP 服务）
- [x] Kafka 基础设施配置修复（固定 broker ID, PLAINTEXT listener）
- [x] Monitor 页面实时数据验证（WebSocket publish 注入 → 前端显示）
- [x] WebSocket 数据注入脚本（`scripts/inject_test_data.py`）
- [x] Kafka 修复脚本（`scripts/fix_kafka_and_restart.sh`）
- [x] **KafkaProducerNode 异步发送（T-101）**
- [x] **track/conflict InfluxDB 持久化（T-102）**
- [x] **遥测 Topic 发布（T-103）**
- [x] **AlertEngine high_avg_speed + multiple_conflicts 规则（T-104）**
- [x] **动态道路数改造（T-201）**
- [x] **速度计算线性回归优化（T-202）**
- [x] **多因子拥堵指数（T-203）**
- [x] **TrackerInfoUpdateNode break 修复（T-204）**
- [x] **FrameElement send_to_kafka 声明（T-205）**
- [x] **drone_store mock 数据移除（T-206）**
- [x] **死代码标记 deprecated（T-402）**
- [x] **KafkaConsumer 指数退避重连（T-403）**
- [x] **InfluxQuery 字段名统一 + JSON 反序列化（T-404）**

### 近期（1-2 周）
- [ ] 清除 Kafka stale data（运行 `scripts/fix_kafka_and_restart.sh`）
- [ ] 验证 Kafka → Platform → InfluxDB 全链路数据流（T-105）
- [ ] 验证 MJPEG 视频流（管道 + Flask → nginx → Monitor 页面）（T-106）
- [ ] 优化 inter_xqh 道路多边形（精确标注道路区域）
- [ ] 修复 TD-009：export_dashboards.py 路径问题
- [ ] 为 `utils_local/utils.py` 添加单元测试（T-405）
- [ ] Mission-Pipeline 绑定：创建任务时自动启动检测管道（T-303）
- [ ] 前端 Drones 页面接入 `telemetry:{drone_id}` WebSocket 实时遥测（T-301）
- [ ] 前端 Dashboard 的 `pipelines_active` 字段对接真实数据（T-304）

### 中期（1-2 月）
- [ ] 解决 TD-002：统一入口点
- [ ] 解决 TD-006：ShowNode 拆分（T-401）
- [ ] 为 ByteTrack 核心算法添加单元测试（T-406）
- [ ] 合并 docker-compose 文件（统一 Kafka/InfluxDB/Nginx 实例）
- [ ] GIS 轨迹回放（基于 track_complete + InfluxDB 数据）（T-302）
- [ ] 管道健康监控面板（PipelineManager 状态 + 进程日志流）
- [ ] Alert 持久化到 PostgreSQL（T-305）

### 远期（3-6 月）
- [ ] 评估是否升级到 InfluxDB 2.x
- [ ] 评估是否使用 ultralytics 内置跟踪替代 byte_tracker/
- [ ] 添加 RTSP 流的自动重连机制
- [ ] 巡检报告自动生成（PDF/HTML）
- [ ] 多无人机任务调度
- [ ] VLM 语义分析旁路
- [ ] 模型微调：uav_best.pt 增加 person + bicycle
- [ ] 冲突检测启用 + 精度验证

---

## 已知 Bug

### BUG-001: ~~main_stream_optimized_v2.py 进程管理不一致~~ (已修复，文件已删除)
- **状态**：已修复。`main_stream_optimized.py` 和 `main_stream_optimized_v2.py` 已整合到 `main_optimized.py`，新入口包含完整的 `is_alive()` + 队列超时健康检查

### BUG-002: VideoSaverNode 在 VideoEndBreakElement 时可能崩溃
- **位置**：`nodes/VideoSaverNode.py:24`
- **描述**：如果视频的第一帧就是 VideoEndBreakElement（空视频），`self._cv2_writer` 为 None，调用 `.release()` 会抛出 AttributeError
- **修复**：添加 `if self._cv2_writer is not None:` 检查

## 下一步
要实际使用 GCP 修正解决你的东西向偏移问题，需要：

在路口找 2-3 个特征点（路灯、标线端点），用 Google Earth 获取其经纬度
在视频截图中标注这些点的像素坐标
将经纬度转为相对锚点的 ENU 偏移填入 app_config.yaml 的 gcp.points


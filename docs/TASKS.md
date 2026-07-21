# TASKS.md — TrafficAnalyzer 任务追踪

> 最后更新：2026-07-19（Console2 启动 P1 已关闭；剩余 1 个 P1、4 个 P2，当前仍 No-Go）

## 2026-07-18 客户演示前全面测试

- [x] 完成客户演示前全面测试方案、角色/业务/异常/视觉/恢复矩阵、问题分级和 Go/No-Go 门禁；详见 [`DEMO_TEST_PLAN_2026-07-18.md`](DEMO_TEST_PLAN_2026-07-18.md)。
- [x] 冻结当前工作树与数据基线，按当前工作树重建根 Compose，记录镜像 ID、Alembic head 和最终运行状态。
- [x] 执行自动化、管理员全业务主链、`operator/viewer` 权限矩阵、管理员角色预览、两轮全路由、四档视口、键盘和故障恢复测试。
- [x] 生成 [`DEMO_READINESS_REPORT_2026-07-18.md`](DEMO_READINESS_REPORT_2026-07-18.md) 并给出 **No-Go** 结论。
- [x] **DEMO-20260718-001 / P1 / Console2**：`console2/nginx.conf:29` 资产正则已整体引用并增加回归测试；镜像 `sha256:3e82e867e9084ccd6266694f9a867c1e9dd3ad2627c56f45a06deb11282cd1d0` 的 `nginx -t`、容器稳定性、`8080`、`/health`、安全头和 API 代理已于 2026-07-19 复验通过。
- [ ] **DEMO-20260718-002 / P1 / Platform**：readiness 改为实时探测 Kafka/road9；关键依赖断开返回非 2xx，恢复后回 200，并补故障注入测试。
- [ ] **DEMO-20260718-003 / P2 / Console2**：实时监测遥测 REST 轮询使用真实 Pipeline `drone_id`，清除 `/telemetry/drone_10` 周期性 404。
- [ ] **DEMO-20260718-004 / P2 / Console2**：候选区域/规则弹窗补初始焦点、焦点环、Esc 和关闭后焦点恢复。
- [ ] **DEMO-20260718-005 / P2 / Supply chain**：Vite 6.4.2 升级到已修复版本并重跑测试、构建和官方 npm audit。
- [ ] **DEMO-20260718-006 / P2 / Data**：为 `/gis` 准备并验证可下钻的历史轨迹、世界坐标和冲突事实，完成跨模块 lineage 复验。

## 2026-07-17 UAT 发布前全量审查

- [x] **Gate A / P0 清零**：关闭匿名管理员注册、WebSocket 客户端消息注入和 SRT 遥测超容差/越界返回。
- [x] **应用 Gate B 完成**：认证与 active-user 回查、Pipeline/视频 RBAC、媒体鉴权、持久审计、Kafka 可恢复 dispatch、测绘错误态/复核、Demo 隔离、暂停语义、拆包、可访问性、Nginx 安全头和 Ruff/CI 门禁已统一落地。
- [x] 本机 canonical 栈已迁移到唯一 Alembic head `20260717_0013`；Platform、显式 PostgreSQL/TimescaleDB、Console2、根回归、`inter_xqh 56 PASS` 和 ADR-019 strict audit 均复核通过。
- [ ] **完整发布 UAT 仍 No-Go**：按确认范围延期 GPU/Platform/Console 镜像修复、干净制品 digest、SBOM/签名、共享 UAT secret/TLS/SASL、容器最小权限/healthcheck 和 HA/容量门禁；详见 [`UAT_FULL_REVIEW_2026-07-17.md`](UAT_FULL_REVIEW_2026-07-17.md)。

## PRD/UI 滚动交付

执行计划见 [`docs/superpowers/plans/2026-07-15-prd-ui-rolling-delivery.md`](superpowers/plans/2026-07-15-prd-ui-rolling-delivery.md)。当前按单一主迭代滚动推进：

- [x] I0：统一分册上位 PRD v2.1 引用，建立 S1～S9 追踪矩阵、模块接口和退出门禁。
- [x] I1：冻结 RoadContext、EventDelivery、MissionOrchestrator、S9 DDL/API/状态机内部工程契约；外部权威路网、主平台和生产参数继续 blocked。
- [x] I2：完成 S9 PostgreSQL 持久化、调度防重/恢复、Console2 四页签、真实 MP4+SRT 与关键截图验收。
- [x] I3：完成隔离 TimescaleDB、MetricStore、S1/S2 指标/轨迹/冲突持久化、输入死信、技术复核及 `/gis`、`/events` 真实切读。
- [ ] I3 生产门禁：冻结生产扩展/容量/保留/压缩/HA，完成多实例故障注入和正式业务指标验收；本机旧数据明确不迁移。
- [x] I4：完成 S4 本地 candidate 围栏/规则、统一 AI 线索、证据引用/哈希、技术复核审计和 Console2 三视图真实化；权威发布与主平台投递保持 503/blocked。
- [ ] I4 正式门禁：冻结权威围栏/规则、执法类型与阈值、雷达设备/检定/融合、法制证据、统一身份与主平台合同，完成批准验收集和性能容量验收。
- [x] I5-A：完成 DashboardReadModel、4 个真实聚合 API、正式 `/` Mock 清除、未冻结 KPI null 门禁、权威坐标隔离和 empty/blocked 视觉验收。
- [ ] I5-B：内部风险/监测/质量筛选、WGS84 bbox、搜索、offset/limit、422/503、REST 保留快照/有限重试和底图失败降级已实现；项目范围/底图/KPI/权限、点位聚合/zoom、全局增量/断线缺口回补、获批正常/混合质量数据及 5 秒/30 秒正式验收仍待外部冻结。
- [x] I6：根 Compose 已收敛为唯一 `road9/TimescaleDB + Apache Kafka KRaft + Platform + Console2 + Nginx` 拓扑；`traffic_road9_data` 从空库迁移到 `20260715_0010`，管理员 1 条、业务 0 条；旧数据不迁移，旧容器已删除，指定旧资产未挂载并保留到北京时间 2026-07-23 11:11:54。独立目标栈、断库恢复、正式端口切换、61/61 样本的 30 分钟健康探测和 `--scope local --strict` 均通过；生产镜像/秘密/TLS/SASL/HA、容量、RPO/RTO、试点和主平台联调继续 blocked。

## 技术债清单

### 🔴 高优先级

#### TD-001: 硬编码 5 条道路 → ✅ 已解决
- **状态**：✅ 已修复（2026-05-31）
- **修复内容**：
  - `CalcStatisticsNode.py`: 从 `roads_info.keys()` 动态获取道路ID列表
  - `KafkaProducerNode.py`: 新增 `roads` 数组字段（动态道路数），保留 `road_1..road_N` 向后兼容
  - 历史 `influx_query.py` 曾完成动态道路字段修复；该文件已于 2026-07-16 随旧链路本机退役删除

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

#### TD-004: Grafana 凭据硬编码（由旧链路退役关闭）
- **位置**：`export_dashboards.py:6`、`fetch_dashboard.py:5`、`update_dashboards.py:5`
- **问题**：`admin:admin` 凭据硬编码在脚本中
- **影响**：安全风险（虽然这些脚本仅用于开发环境）
- **处置**：ADR-019 已决定退役 Grafana 链路；退役前不得扩大使用，相关脚本/凭据随旧链路安全下线并执行秘密扫描，不再为其新增功能。

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

#### TD-006: ShowNode 过于庞大 → ✅ 已解决
- **状态**：✅ 已修复（2026-06-09）
- **修复内容**：使用 supervision 库重构，拆分为 10 个聚焦子方法（`_draw_detections`、`_draw_tracked`、`_draw_roads`、`_draw_fps`、`_draw_stats_panel` 等），新增圆角边框、轨迹尾迹、标签背景等功能，去除 `random` 依赖改用 `ColorPalette` 确定性着色

#### TD-007: VideoEndBreakElement 控制信号字段访问 → ✅ 已解决
- **位置**：`elements/VideoEndBreakElement.py`
- **状态**：✅ 已修复（2026-07-15）
- **修复内容**：保留 sentinel 不携带普通帧字段的控制信号语义；`main_optimized.py` 检测进程在共享内存/`.frame` 访问前先识别并级联 `VideoEndBreakElement`。`test_main_optimized_eof.py` 固化首元素即 EOF 的回归，5GB `inter_xqh` + DJI SRT 在重启恢复后自然 EOF，Mission 持久化为 `completed/source_eof`。

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

> 本节是历史实施台账，旧 Topic、InfluxDB、Grafana、Telegraf、Zookeeper 和已删除路径只描述当时结果；当前运行态以 ADR-019 和本文 I6 状态为准，不得据此恢复兼容。

### Sprint 1: 数据链路打通 ✅

| ID | 任务 | 状态 | 修改文件 |
|----|------|------|----------|
| T-101 | KafkaProducerNode 异步发送 | ✅ | `nodes/KafkaProducerNode.py` — 独立发送线程 + Queue(maxsize=200)，Kafka 不可用时不阻塞管道；`test_kafka_active_trajectories.py` 覆盖 stats/track_complete/conflicts/telemetry 四类 topic 非阻塞入队 |
| T-102 | track/conflict 持久化到 InfluxDB | ✅ | `platform/app/utils/influx_query.py` — 新增 write_track_event/write_conflict_event/write_stats，冲突历史完整保留 TTC/PET、prediction_type、conflict_scene、evidence、risk_score 和预测位置；`platform/app/kafka/consumer.py` — 注入 influx_client 并在 handler 中调用写入 |
| T-103 | 遥测 Topic 发布 | ✅ | `nodes/KafkaProducerNode.py` — 新增 `telemetry_{N}` topic，5Hz 节流发布；`test_kafka_active_trajectories.py` 覆盖 telemetry 消息包含 `msg_type=telemetry`、`drone_id`、`intersection_id` 和遥测字段 |
| T-104 | AlertEngine 补充规则 | ✅ | `platform/app/services/alert_engine.py` — 新增 high_avg_speed (P3) + multiple_conflicts (P2) 规则 |
| T-105 | Kafka 端到端验证 | ⏳ | 待环境验证 |
| T-106 | MJPEG 视频流验证 | ✅ | 2026-07-02 live：Platform `/api/v1/video/camera/{camera_id}` 公开代理容器内检测器 MJPEG，Vite `/camera_N` 转发到 Platform；inter_xqh 管道 `pipe-41be7924` 启动后 `/api/v1/video/camera/10` 返回 `200 multipart/x-mixed-replace` 且 3 秒抓到约 14-19MB 视频字节，浏览器 `/monitoring` 中 Live image 为 1280x720；页面点击停止后 `/proxy-map={}`、`running=0` |

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
| T-407 | 自动车道推断 | ✅ | `AutoLaneInferenceNode.py` + `auto_lane_inference.py` — 轨迹聚类→中心线→自动标签，无需人工标注 |
| T-408 | 方向分类 heading 精度修复 (P0) | ✅ | `trajectory_classifier.py` + `auto_lane_inference.py` — heading 窗口从固定5帧改为 n//2（平滑短轨迹噪声），最小位移阈值 10px |
| T-409 | 车道聚类合并阈值优化 (P1) | ✅ | `AutoLaneInferenceNode.py` — merge 阈值从 entry_exit_threshold_px 提升到 3.5x（420px），减少平行车道碎片化 |
| T-410 | U-turn 自引用标签修复 (P2) | ✅ | `auto_lane_inference.py` — 新增 OPPOSITE_CARDINAL 映射 + 自引用保护逻辑，消除"北→北 掉头"等不合理标签 |
| T-412 | VisDrone motor/non_motor 分类与小目标阈值修复 | ✅ | `TrackerInfoUpdateNode.py` — 优先按模型类别名分类，修复 `yolo11l-visdrone.pt` 下 tricycle/bicycle 被按 COCO id 误归为 motor 的问题；`configs/app_config.yaml` — 使用 `imgsz=1280/confidence=0.05/ByteTrack 0.05+0.01` 保留航拍电动车/三轮车低分候选；`test_refactor_unit.py` 增加类别映射与机非冲突回归测试 |
| T-413 | ShowNode 左上角幽灵框堆积修复 | ✅ | `ShowNode.py` — 绘制前裁剪/过滤异常 bbox，并仅显示道路 ROI 内或已分配道路的轨迹；`test_refactor_unit.py` 增加可视化过滤回归测试 |
| T-414 | 无道路标注参数启动支持 | ✅ | `VideoReader.py` + `main_optimized.py` + `main.py` + `configs/app_config.yaml` — `ROADS_JSON` 为空时使用空道路集运行，不再自动注入默认道路标注 |
| T-415 | 无道路标注模式左上角黑块堆积修复 | ✅ | `ShowNode.py` — 无道路标注时保留自动推断车道中心线/箭头，但关闭左上角车道统计黑底面板；`test_refactor_unit.py` 增加黑底像素回归测试 |
| T-416 | 机非分类配置化 + 监控冲突事件列表 | ✅ | `TrackerInfoUpdateNode.py` — 非机动车类别提取到 `vehicle_classification`，未配置类别默认机动车，摩托车/电动车归为非机动车；`ConflictDetectionNode.py` — 默认启用并支持 TTC 阈值触发；`traffic-fly-console/src/features/monitoring/index.tsx` — 监控页显示最近 20 条冲突事件 |
| T-417 | 页面发起 inter_xqh 全流程验证 | ✅ | `traffic-fly-console/src/features/video/index.tsx` — 视频分析页默认使用真实 inter_xqh 视频+SRT、动态匹配 PipelineManager 返回的 `camera_id`，MJPEG 加载失败后自动重试；`platform/app/services/pipeline_manager.py` — 支持 `PIPELINE_PYTHON`/`PIPELINE_FRAME_STRIDE`，空 `ROADS_JSON` 透传无道路标注模式，并用进程组停止检测器；已从页面启动并验证 Kafka → Platform WebSocket → 页面冲突列表 → InfluxDB 写入 |
| T-418 | 监控页冲突事件 BEV 回放 | ✅ | `traffic-fly-console/src/features/monitoring/` — 冲突事件列表可点击，BEV 叠加 motor/non_motor 回放层，支持播放/暂停/重放、倍速、3s/6s/10s 窗口和轨迹不足降级；回放动画状态已与实时轨迹刷新解耦，连续点击事件行会强制从头回放；列表按 motor/non_motor pair 合并重复消息；`platform/app/kafka/consumer.py` — Platform WebSocket 推送前也按 pair upsert，同级重复冲突不再广播，warning 可升级 critical |
| T-419 | TTC 冲突误报优化 | ✅ | `SpeedEstimationNode.py` — 输出世界坐标速度向量；`ConflictDetectionNode.py` — 曾改为相对运动最近点（CPA）算法，后续由 T-420 替代为未来轨迹预测口径；`test_refactor_unit.py` 增加冲突检测回归测试 |
| T-420 | 机非冲突未来轨迹预测口径修正 | ✅ | `ConflictDetectionNode.py` — 移除当前近距离触发，改为 `0-5s` 未来轨迹采样预测，并支持交叉路口路径交点到达时间差判断；同级 pair 不重复上报，`warning` 可升级 `critical`；`configs/app_config.yaml` — 新增 `prediction_horizon_sec` / `critical_horizon_sec` / `sample_interval_sec` / `arrival_time_tolerance_sec`；`test_refactor_unit.py` — 覆盖近距离不碰撞不上报、0-3s critical、3-5s warning、pair 去重、warning→critical 升级、交叉点到达时间差；`test_pipeline_inter_xqh.py` — 无道路标注 xqh 前100帧真实 YOLO+SRT 验证，冲突节点启用，当前 near-miss 证据漏斗下未产生擦边误报 |
| T-421 | xqh 机非冲突 near-miss 误报压制 | ✅ | `ConflictDetectionNode.py` — 在未来交汇候选后增加无标注轨迹几何场景门槛，仅保留疑似右转机非与疑似无保护左转；新增冲突角、PET、急减速、急转向、停止/让行证据漏斗，hard TTC 可直接触发，普通风险必须带避险证据；事件附加 `conflict_scene` / `conflict_angle_deg` / `pet_sec` / `evidence` / `risk_score`；`test_refactor_unit.py` 覆盖危险交汇但非专项场景不上报、右转 hard TTC 上报、普通风险无证据不上报、左转+急减速上报、pair 去重 |
| T-422 | TCC/冲突 BEV 回放轨迹错乱修复 | ✅ | `traffic-fly-console/src/features/monitoring/bev-trajectory-utils.ts` — 实时轨迹尾部快照按 `trajectory_tail_start` 替换重叠区，避免同一历史尾部因 H/运动补偿轻微漂移被追加成折返线；`conflict-replay-utils.ts` — 回放窗口以事件 motor/non_motor 预测冲突点附近截取，不再盲取轨迹最后 N 点；测试覆盖漂移尾部合并和事件附近回放截取 |
| T-423 | TCC 同刻擦肩/小折线误报压制 | ✅ | `ConflictDetectionNode.py` — 同刻 TTC 候选改为连续 CPA 最近接近点，并新增 `same_time_collision_radius_m=0.8m`，不再把 `collision_radius_m=2.0m` 内的横向擦肩直接当相撞；右转/左转场景新增 `min_turn_leg_m=2.0m`，避免短窗口小折线被误分为转弯；`test_refactor_unit.py` 覆盖最近距离约 0.9m/1.8m 且无有效 PET 交汇时不上报、机动车转弯腿不足不上报 |
| T-424 | Platform system WebSocket topic pattern 修正 | ✅ | `platform/app/core/config.py` — 默认 Kafka topic pattern 扩展为 `((statistics\|track_complete\|conflicts\|telemetry)_.*\|system_metrics)`，使 `system_metrics` topic 能进入 Kafka consumer 并广播到前端 `system` 频道；`docs/API_CONTRACTS.md` / `docs/ARCHITECTURE.md` / `docs/DATABASE_SCHEMA.md` 同步 WebSocket 端点与订阅契约 |
| T-425 | Platform 依赖不可用时降级状态修正 | ✅ | `platform/app/kafka/consumer.py` — Kafka bootstrap 失败时关闭已创建的 `AIOKafkaConsumer`，避免 unclosed consumer；`platform/app/core/database.py` / `platform/app/main.py` — `/ready` 根据真实 PostgreSQL/Kafka 初始化状态返回 healthy/degraded，启动日志区分 started/degraded；`platform/tests/test_kafka_consumer_stats.py` 增加失败启动回归测试 |
| T-426 | WebSocket 实时频道自动化验证 | ✅ | `platform/app/kafka/ws_manager.py` — 订阅/退订协议兼容 `channel` 单值和 `channels` 数组；`platform/tests/test_realtime_channels.py` — 覆盖 `intersection:{id}` stats/track/conflict、`telemetry:{drone_id}`、`system`、`alerts` 和 `alerts:{intersection_id}` 广播 |
| T-303 | Mission-Pipeline 绑定 | ✅ | `platform/app/api/v1/drones.py` — `POST /api/v1/missions` 创建任务时绑定无人机/路口并立即调用 PipelineManager 启动检测管道，响应写回 `pipeline_id` 与 pipeline 状态；启动异常时 mission 标记 `error` 并返回 `502`；`platform/tests/test_missions_api.py` 覆盖成功启动与异常落库状态 |
| T-427 | Platform 容器启动检测器依赖补齐 | ✅ | `platform/Dockerfile` — 平台镜像安装 `platform/pipeline-requirements.txt` 并通过 `platform/pipeline-constraints.txt` 锁定 `numpy<2`、`torch==2.2.2`、`torchvision==0.17.2`，避免 `POST /api/v1/pipelines` 启动 `/project/main_optimized.py` 时因缺少 `hydra` 等检测依赖直接失败或被新版 Torch/CUDA 解析拖重；`docker-compose.yaml` / `platform/docker/docker-compose.platform.yml` — topic pattern 同步包含 `system_metrics`；`platform/tests/test_pipeline_manager.py` 覆盖启动命令/环境变量、检测依赖覆盖根 `requirements.txt`、compose topic pattern |
| T-428 | TCC CPA/PET 证据混淆修正 | ✅ | `ConflictDetectionNode.py` — CPA 候选的 `pet_sec=0` 不再作为 PET hard 证据；只有 `ttc_sec <= hard_ttc_sec` 可直接触发 `hard_ttc_or_pet`，路径交点 PET 达阈值仅记录 `hard_pet` 并需叠加避险行为；机动车正常右/左转的 heading 变化不再计作避险急转向，仅非机动车突变可作为 `hard_steering`；`test_refactor_unit.py` 覆盖 CPA pet=0、PET-only 不触发、PET+避险触发 |
| T-429 | Platform 容器检测器日志修复 | ✅ | `platform/app/services/pipeline_manager.py` — Platform 拉起 `main_optimized.py` 时追加 `hydra/job_logging=disabled`，避免只读 `/project` 下 Hydra 文件日志 handler 写 `logs/app.log` 失败导致任务启动后立刻 `error`；`main_optimized.py` — multiprocessing 子进程重载日志配置时检测不可写 `FileHandler` 并降级到 console，避免 reader/tracker/show worker 因日志文件不可写退出；`platform/tests/test_pipeline_manager.py` / `test_refactor_unit.py` 覆盖启动命令与日志降级 |
| T-432 | TCC CPA 近距离擦边默认关闭 | ✅ | `ConflictDetectionNode.py` / `configs/app_config.yaml` — 默认 `enable_same_time_cpa: false`，默认业务口径只接受未来路径交点/PET 候选，避免 BEV 回放里 0.9m/1.3m/1.7m 这类仅中心点近距离、但无共同冲突点的轨迹被上报；CPA 保留为显式开启扩展，且仍受 `same_time_collision_radius_m=0.8m` 和 evidence 漏斗约束；`test_refactor_unit.py` 增加“路径交点在一方身后、仅 CPA 近距离”不上报回归测试 |
| T-433 | TCC PET-only 误报与回放红圈误导修正 | ✅ | `ConflictDetectionNode.py` — `PET<=1s` 不再单独生成 near-miss 事件，必须叠加急刹、非机动车急转向或停车/让行，压制截图中 TTC 2.x 秒、低 PET 但无避险行为的错位经过；`traffic-fly-console/src/features/monitoring/` — 冲突回放风险圈和距离辅助线锚定事件 `motor_position_m` / `non_motor_position_m` 的预测冲突位置，不再跟随两车当前播放点中点漂移；`test_refactor_unit.py` 与 `conflict-replay-utils.test.ts` 覆盖 |
| T-434 | TCC 预测方向使用最近轨迹段 | ✅ | `ConflictDetectionNode.py` — 有历史轨迹时，未来预测方向改用最近一个有效轨迹段，速度大小沿用 `SpeedEstimationNode` 的米/秒估计，避免线性回归测速方向在转弯/错位轨迹中制造虚假交点；`test_refactor_unit.py` 增加“历史轨迹方向与回归速度方向不一致时不上报”回归测试，单元测试 `52 PASS / 0 FAIL`，inter_xqh 前100帧真实 YOLO+SRT 仍为 `56 PASS / 0 FAIL / 0 WARN`、冲突 `0` |
| T-435 | Drones 页面 telemetry WebSocket 接入 | ✅ | `traffic-fly-console/src/features/drones/index.tsx` — 根据 `/api/v1/drones` 返回的无人机 ID 动态订阅 `telemetry:{drone_id}`，收到实时遥测后立即覆盖轮询兜底值；`traffic-fly-console/src/features/drones/index.test.tsx` 覆盖 `telemetry:drone_10` 消息更新纬度/经度/电量/悬停状态；当前前端回归 `npm test` 通过 27 个测试文件 / 160 个测试，`npm run build` 通过 |
| T-436 | Alert 持久化到 PostgreSQL | ✅ | `platform/app/models/alert.py` — 新增 `alerts` SQLAlchemy 表；`platform/app/services/alert_engine.py` — 创建/确认告警时写入 store，启动时加载已持久化告警，数据库不可用时保留内存降级；`platform/app/api/v1/alerts.py` — acknowledge 等待异步持久化结果；`platform/tests/test_alert_engine_persistence.py` / `test_alerts_api.py` 覆盖重启加载、确认状态持久化和 API await 行为，`python -m pytest platform/tests -q` 通过 |
| T-437 | TCC 业务口径字段与 CPA-only 回放过滤 | ✅ | `ConflictDetectionNode.py` — conflict 事件新增 `prediction_type`，路径交点事件显式输出 `path_intersection` 且 `distance_m=0.0`；`traffic-fly-console/src/features/monitoring/` — WebSocket conflict 入口过滤 `prediction_type=same_time_cpa` 的中心点擦肩旧/扩展事件，只保留 `path_intersection && distance_m≈0.0` 的路径交点，旧格式也仅当 `distance_m≈0.0` 时兼容，避免 0.9m/1.3m/1.7m 旧 CPA 或畸形 path 事件继续进入回放列表；`conflict-replay-utils.test.ts` 覆盖 path-zero/legacy-zero 保留与 CPA/legacy-near-pass/malformed-path 过滤 |
| T-443 | TCC 路径交点同一时空占用门槛 | ✅ | `ConflictDetectionNode.py` — 路径交点 PET 候选除到达时间差外，新增双方到达交点期间的连续同刻最小中心距校验，必须进入 `same_time_collision_radius_m=0.8m` 共同冲突区才上报，过滤仅数学射线相交、回放看不到同一时空碰撞概率的轨迹；`test_refactor_unit.py` 增加“路径交点到达时间差达标但同刻中心距离超过实际碰撞半径时不上报”回归测试，当前 `52 PASS / 0 FAIL` |
| T-445 | Console2 BEV 真实地图底图修复 | ✅ | `console2/src/components/MonitoringBevMap.jsx` + `console2/src/App.jsx` — 复用 Console 1.0 OpenLayers/OSM 地图模式替换静态 BEV 图片，按轨迹锚点将 ENU 世界坐标投放到主视图和右侧预览；无轨迹时保留真实路口地图且不生成模拟轨迹；`MonitoringBevMap.test.jsx` 覆盖 ENU 转换、路口中心回退和无效零坐标；使用 `inter_xqh` MP4+SRT、`ROADS_JSON=""` 启动 Pipeline `statistics_12`，浏览器验证检测器/BEV 主次切换和真实 MJPEG 输出；`test_pipeline_inter_xqh.py` 为 `56 PASS / 0 FAIL / 0 WARN`、100/100 帧检测与遥测有效 |
| T-446 | Console2 检测画面红蓝轨迹误叠加修复 | ✅ | `console2/src/App.jsx` — 删除把前两条活动/完成轨迹按 Y 轴归一化后覆盖到 MJPEG 上的 Recharts 红蓝曲线，世界坐标轨迹只交给 OpenLayers BEV；风险标记仅在检测器风险模式显示，原始画面保持无前端 AI 叠层；`LiveModules.test.jsx` 覆盖完成轨迹不进入检测画面且仍投放 BEV。Console2 `42/42` tests 与 production build 通过；浏览器实页验收轨迹图层、Recharts 线和红蓝 stroke 均为 0，证据见 `.design-qa/2026-07-15-monitoring-detector-red-blue-lines-fixed.jpg` |
| T-447 | Console2 监控侧栏自动收缩与研判浮条精简 | ✅ | `console2/src/App.jsx` / `styles.css` — 左侧实时态势、右侧 BEV/实时事件面板使用 40% alpha 背景，默认收缩为 36px 边缘控制条，鼠标或键盘进入时展开、离开时自动收起，并可分别锁定保持展开；收缩时检测状态和地图工具同步贴边，不保留空占位；删除底部“AI 事件研判”浮条及其监控页确认逻辑，事件详情和复核统一从“全部事件”进入。`LiveModules.test.jsx` 覆盖左右收缩、展开、锁定、解锁、工具贴边和浮条缺席；Console2 `43/43` tests、production build、`git diff --check` 与本地 HTTP 200 检查通过。 |
| T-448 | S9 自然 EOF 与 Mission/Pipeline 终态同步 | ✅ | `platform/app/services/mission_orchestrator.py` 在正常 tick 中把 Pipeline `stopped/error/missing` 持久化为 Mission `completed/source_eof`、`failed/pipeline_error`、`failed/pipeline_runtime_missing`；`main_optimized.py` 在共享内存帧访问前级联 `VideoEndBreakElement`。最小回归红→绿，显式 PG integration 2/2；5GB `inter_xqh` + DJI SRT 在重启恢复后自然 EOF，证据 `docs/test_report_s9_inter_xqh_eof.json`；全管道仍为 56/0/0。 |
| T-449 | S9 从 Console2 页面触发 `road9` 真实验收 | ✅ | 隔离链路 `4179 → 18005 → road9@20260715_0009`；页面登记 `UAV-PAGE-0715` / `SRC-C74D6FA9EA35`，创建并启用 `PLAN-6C3102938EBB`，调度器 `+2s` 创建 `MSN-5A61F57DA1D7` / `pipe-ec14fc26`。使用 5GB `inter_xqh` MP4 + DJI SRT、`frame_stride=300` 运行 396.663 秒自然 EOF，刷新后持久化为 `completed / stopped / source_eof`，截图见 `console2/.design-qa/2026-07-15-s9-{source-registered,page-mission-completed}.jpg`。生产默认帧步长未修改，权威 RoadContext、RTSP/MQTT、容量与 HA 仍为外部验收阻断。 |
| T-450 | mp4new 三路口五源回放摄像头接入 | ✅ | DJI Cloud JSON `.txt`、同步偏移/容忍窗口、`20260715_0010`、幂等 bootstrap、同无人机 409 门禁、Console2 三路口控制卡和真实 MJPEG 已交付；系统联调 5/5 PASS，自然 EOF 为 `completed/source_eof`，遥测连续性 4/5 PASS + 1 DEGRADED。道路上下文保持未标定，证据见 `docs/test_report_mp4new.md`。 |
| T-451 | Console2 研判导航与页面标题栏收敛 | ✅ | `/gis`“轨迹研判”从“全域态势”移动到“智能研判”；共享 `PageHeader` 不再渲染可见标题、说明和元信息栏目，普通页面保留屏幕阅读器可读 `h1`，原页面级按钮迁入紧凑操作行，面包屑和业务内容保持不变；`RouterApp.test.jsx` 覆盖两域导航归属和标题栏缺席。 |
| T-452 | Console2 开发态提示与顶部操作行收敛 | ✅ | 首页及同类业务页隐藏内部阶段码、合同冻结说明、Mock/fallback 和验证样本提示；真实加载、错误、权限、质量与投递状态继续展示。共享 `.page-actions` 与面包屑同排对齐，覆盖首页、飞行任务、事故测绘、执法配置等页面；Console2 50/50 测试、production build、1357 × 912 本机浏览器量测和 console 0 error/warn 均通过。 |
| T-453 | 六组本地无人机模拟数据零复制接入与全流程 | ✅ | `inter_xqh` 1 组 + `mp4new` 5 组已幂等登记为 4 架无人机、4 路口、6 SourceProfile；原始 MP4/SRT/Cloud JSON 以 `server_asset` allowlist+SHA-256+快速指纹引用，六组共保存 36 原始关键帧、36 BEV、24 点线面/对象量算、6 场景标注、4 车道任务/绑定和 6 份 PDF/JSON/GeoJSON 报告。最终四服务重启后 96 个内容响应逐项 SHA-256 通过，6 个原视频 Range 探测通过；礼士路 0624 保留 `telemetry_gap_34s/degraded`。六批次查询实测 2.2–7.9ms；证据卷 79MB、managed 最大对象约 2.34MB，六个原视频逻辑总量 28,584,741,006 bytes 未复制。四路口后续真实 Pipeline 均读取 `lane_source=manual/lane_count=1`。自然 EOF、低 stride 检测、页面回看与重启复验见本轮测试报告；生产精度、容量、HA、TLS/SASL 和主平台门禁仍 blocked。 |
| T-454 | 四路口验收测试坐标与无人机地图标记 | ✅ | 从四路口已登记遥测读取真实 GPS 中位点，写入 `RoadContext.coordinate_reference` 的 `status=test/usage=local_acceptance_only`；DashboardReadModel 单独返回 4 个 test 点位且整体健康保持 degraded，Console2 首页用四旋翼无人机图标、测试坐标标签和四点中心视野展示。正式道路坐标仍为 unverified，不以本机验收点替代权威坐标。 |
| T-455 | 轨迹研判首次加载假性 0 数据修复 | ✅ | `DashboardReadModel._facts()` 对 RoadContext、路口指标和无人机遥测使用 PostgreSQL `DISTINCT ON`，在数据库侧只返回每个分组最新事实；`/dashboard/intersections` 本机实测由 2.46–2.93s 降到 9.2–16.4ms。Console2 加载期显示“路口加载中 / 轨迹等待路口”，不再显示“0 个路口 · 0 条轨迹”，失败态可重新加载真实数据；浏览器强制刷新 3.97s 内显示 4 个路口、500 条轨迹且 console 0 error/warn。Platform 103 passed、Console2 55 passed、production build 通过。 |
| T-456 | GIS 历史轨迹真实投放修复 | ✅ | 根因是轨迹接口先按 `ended_at DESC LIMIT 500` 截取最新降级记录：`INT_camera_1` 虽有 6,397 条带世界坐标轨迹，最新 500 条却全是 5 点、移动中位长度约 0.68m 的短片段，地图只能看到终点。`query_tracks` 新增 `spatial_ready` / `min_world_points` 并在 PostgreSQL 的 LIMIT 前过滤；Console2 GIS 固定请求至少 6 个世界坐标点，同时使用嵌入面板安全 fit padding。最终接口返回 285/285 条完整轨迹，点数中位数 50、最大 99；真实任务 `MSN-3421232DD4B9` 页面投放 149/149 条彩色折线，浏览器 console 0 error/warn。Platform 104 passed、Console2 56 passed、production build 通过。 |
| T-457 | 测绘标注图与实时边长 | ✅ | `/survey/**` 量算画布使用后端下发的 BEV→ENU 变换，在鼠标跟随预览边和已保存几何的每条边中点显示米制距离；报告页及已完成历史任务展示带标注 BEV。报告生成同步固化 `survey_report_annotated_image` JPEG、写入 SHA-256 证据引用并嵌入 PDF；旧报告从原 BEV 与版本化量算只读重绘，不迁移或改写历史。前后端聚焦回归和完整验证见本次交付记录。 |
| T-458 | Console2 登录页轨迹动画迁移 | ✅ | 将 Console 1.0 登录页的路口俯视图、六路轨迹光点、检测区呼吸和 LIVE 闪烁重构为 Console2 自有 `LoginTrafficFlow` 装饰组件；保留 Console2 认证与安全跳转逻辑和窄屏布局。针对应用内浏览器默认报告 reduced motion 导致穿梭光点隐藏的问题，调整为核心轨迹穿梭始终可见、仅关闭检测区呼吸与 LIVE 闪烁；取消大屏 `920px` 动画画布上限，使轨迹延展到登录卡下方并消除全屏暗色断带。原始深色航拍图固定为最底层，动画 SVG 与连续暗角依次叠加，并降低 SVG 路面遮挡以保留底图细节。Console2 自动化测试与 production build 通过；浏览器检查为 0 error / 0 warning。 |
| T-459 | Console2 页面纵向撑满与首页点位直达监测 | ✅ | 共享 `.shell-main` 改为纵向弹性布局，Dashboard、GIS、实时监测、测绘、执法、治理及列表末级面板统一吸收剩余视口高度，只保留 18px 底部外边距；1357 × 912 实测首页空白由 98px 降至 18px，事件页与轨迹研判页底线同为 18px 且无滚动溢出。首页地图路口点位单击直接进入 `/monitoring?intersection_id=...`，真实点位验证进入 `INT_camera_1` 实时检测页并显示飞行姿态区。Console2 80/80 测试、production build、浏览器 0 error / 0 warning 均通过。 |
| T-460 | Console2 首页地图标题栏删除 | ✅ | 按浏览器批注删除首页地图上方“无人机路口态势纵览”标题、坐标说明及“全部/高风险/降级”筛选条；Dashboard 固定读取当前授权范围的 500 个路口，地图画布由扣除 48px 标题高度改为占满左侧面板。1357 × 912 实测标题与筛选节点均为 0，地图 top 与面板 top 仅保留 1px 边框差、画布高度 618/620px；真实点位仍可进入 `INT_camera_1` 实时监测。Console2 79/79 测试、production build、浏览器 0 error / 0 warning 均通过。 |
| T-461 | Console2 实时监测双侧栏默认展开 | ✅ | `/monitoring` 的实时态势左栏与 BEV/实时事件右栏初始状态改为 expanded，进入路口监测后直接展示拥堵、流量、趋势、BEV 和事件事实；保留原边缘收缩、悬停展开与锁定控件。1357 × 912 实测左栏宽 306px、右栏宽 340px，两个收缩按钮可用，刷新后双栏均为 expanded。Console2 79/79 测试、production build、浏览器 0 error / 0 warning 均通过。 |
| T-462 | Apple Silicon 原生 MPS 八源轨迹/TCC 回放 | ✅ | `mp4new` 5 源 + `mp4new2` 3 源已纳入同一目录；原生 arm64 Python 3.11.15 / PyTorch 2.2.2 / MPS 环境、幂等环境引导和断点续跑运行器已交付。8/8 全时间轴回放返回码 0，共直采并持久化 10,879 条完成轨迹，严格 TCC 真实结果为 0；Platform 重启后 road9 仍为 10,879 条 / 8 来源。各源推理中位 184.9–323.4ms、P95 361.0–811.9ms，但 max 2.77–5.43s，常态 CPU 回退已修复、MPS 长尾仍需后续压测。证据见 `docs/test_report_native_mps_replay_20260719.md`。 |
| T-463 | 全视频源无车道标注参数启动与既有标注失效 | ✅ | Pipeline API/Manager、Mission、SourceProfile、本机 MPS runner 和 Compose camera 统一 `ROADS_JSON=""`，拒绝非空标注参数并停止自动复用 `uav_visual_lane_bindings`；Kafka 悬停自动车道任务默认关闭，避免持续视频源重建已失效数据。本机 `road9` 中 4 个车道任务失效、4 个视觉绑定退役，4 份当前导出 JSON 移入可恢复审计目录。`invalidate_lane_annotations.py` 提供默认只读检查和显式 `--apply`。 |
| T-464 | Platform 根入口与检测器统一镜像 | ✅ | Platform 本机/容器入口提升为根 `run_platform.py`，根 `Dockerfile` 构建 Platform + 检测器统一镜像，`PipelineManager` 在容器内按 Pipeline API/Mission 任务启动 `main_optimized.py`；Compose 移除整仓库 `/project` 挂载，仅只读挂载 `weights`/`test_videos`。原检测器镜像保存为可构建的 `Dockerfile.detector`，不进入 canonical Compose；默认镜像保持 CPU 可启动，GPU 仍为外部门禁。 |
| T-465 | 监测入口与无人机视频源对齐 | ✅ | `console2/src/App.jsx` 的顶部监测选择器改为读取已登记 UAV SourceProfile，并通过无人机默认路口或运行中 Pipeline 绑定 `source_profile_id` + `intersection_id`；同一路口多视频源按 profile 精确匹配检测进程，不再展示固定 Camera 1/2 占位列表。工作台地图也改为每个 SourceProfile 一个无人机点位，以绿/青/黄/红/灰区分运行中、可用离线、降级、无效和停用状态，点击携带 source+intersection 深链进入监测。2026-07-20 真实 Mission `MSN-3854893D6874` 启动 SourceProfile `SRC-INTER-XQH-0403-PM` 与 Pipeline `pipe-c79f5aef`：容器内 `main_optimized.py` 三 worker、`/camera_14`、`uav_statistics_14` / `uav_telemetry_14` canonical 消息及前端绿色运行态均验证通过；停止后 Mission/Pipeline 正确回落为 `cancelled/stopped`、页面切换为离线青色且无遗留 worker。Console2 83/83、Platform 142 passed / 5 skipped、检测器聚焦 12/12、`inter_xqh` 56/0/0、ADR-019 strict、Compose config、production build 与 `git diff --check` 均通过。 |
| T-466 | 实时监测视频源下拉框样式修复 | ✅ | 将无边框原生选择器改为带暗色边框、独立箭头、悬停/键盘焦点态的监控源控件；长 SourceProfile 名称使用省略号且通过 `title` 保留完整文本，副标题同步增加溢出保护，并扩展 1350px / 1100px 两档上下文栏源区域。1068px 实机视口验证控件为 242×27px、箭头与文本无重叠；聚焦回归 13/13、production build 与容器重建通过。 |
| T-467 | 路口实时检测控制面板裁剪修复 | ✅ | 修复 `/drones` 无人机页中直接 `surface-panel` 作为纵向 Flex 子项时被压缩、再由 `overflow:hidden` 裁掉第二排路口卡片的问题：直接面板固定 `flex-shrink:0`，由 `.shell-main` 提供纵向滚动；回放控制网格在 1100px 以下使用两列、760px 以下才切换单列。修复前实测面板 437px、内容 2007px 且页面不可滚动；修复后面板连续延伸、五张卡片与下方无人机档案均可达。Console2 85/85、production build、容器重建与 `git diff --check` 通过。 |
| T-468 | 实时监测离线快速演示与指标收敛 | ✅ | `/monitoring` 在所选 SourceProfile 无运行 Pipeline 时展示“启动演示检测”，管理员可直接复用 Mission API 创建绑定当前无人机、路口、RoadContext 和视频源的一小时手动 Mission；按钮包含启动中、防重复提交、权限/配置禁用原因和 API 错误态，不引入旁路进程启动。移除画布中央“活动轨迹”浮标，轨迹数量继续保留在 BEV 面板；原“当前目标”浮标并入左侧指标卡并替换语义不准确的“断面流量”。1357×912 浏览器实测按钮、当前目标 194 辆和浮标移除均正确；Console2 86/86、production build、容器重建与 `git diff --check` 通过。 |
| T-469 | 事件关键帧证据全屏预览 | ✅ | `/events` 详情抽屉中的关键帧证据改为可点击预览，通过 React Portal 提升到 `document.body`，以原比例图片覆盖整个视口并提供显式“关闭”按钮；支持点击背景和 Esc 退出、退出后恢复缩略图焦点与页面滚动，同时避免 Esc 连带关闭事件详情。Console2 89/89、production build、容器重建与 `git diff --check` 通过。 |
| T-470 | TCC 检测链路可解释性与历史回填 | ✅ | 修复 `test_refactor_unit.py` 正样本缺失 `max_speed_kmh` 的夹具问题；默认业务口径恢复为路径交点+同时空占用，CPA 仅保留显式实验扩展。检测节点输出完整漏斗诊断并随 `uav_stats` 发布，正式 `conflict_count` 排除 CPA；历史冲突 API 支持 SourceProfile/Pipeline/预测类型过滤，Monitoring 按当前视频源回填严格路径交点事件、与实时消息去重并明确显示 TCC/断线降级状态。新增检测、统计、API 与前端回归覆盖。 |
| T-471 | 冲突事件同步三图证据 | ✅ | 冲突产生时从同一 `FrameElement` 同步固化原始画面、检测器输出画面和同期轨迹还原画面；三项按固定 kind 顺序可靠发布并在一个 `EvidencePackage` 中事务登记，派生图回指原图。`/events` 详情按三类证据展示独立 SHA-256 缩略图，均可全屏、显式关闭、背景关闭和 Esc 退出；旧单关键帧事件保持可读。检测器、MetricStore 与 Console2 均新增回归覆盖。 |
| T-472 | 五源轨迹检测、回放与 TCC 全流程验收 | ✅ | 原生 MPS 对 `mp4new` 五源执行完整时间轴抽帧检测，5/5 返回码 0，Kafka/Road9 对账为 2,096 条 intersection Stats、7,373 条完成轨迹和 2,096 份 TCC 漏斗诊断。真实 Mission `MSN-0A894D610BBD` 产生 7 个严格 `path_intersection + distance_m=0` 事件、7 个 hash_verified 证据包和 21 张固定三图证据，停止后无活动 Pipeline。修复 Console2 离线监测不读取历史轨迹的问题，五源浏览器均恢复 500 条 SourceProfile-scoped BEV 轨迹；证据见 `docs/test_report_five_source_trajectory_tcc_full_flow_20260721.md`。 |
| T-438 | GIS 历史轨迹与冲突复盘 | ✅ | `traffic-fly-console/src/features/gis/index.tsx` — 选中路口后调用 `/api/v1/trajectories/{intersection_id}?period=1h&limit=200` 和 `/api/v1/trajectories/{intersection_id}/conflicts?period=1h&limit=200`，显示历史轨迹数量、Track ID、转向、车辆类型、均速、时长、轨迹点数，以及历史冲突 pair、TTC/PET、场景、证据和风险分；`traffic-fly-console/src/features/gis/index.test.tsx` 覆盖 `INT_camera_1` 历史轨迹与冲突证据复盘详情 |
| T-439 | Dashboard pipelines_active 真实数据 | ✅ | `traffic-fly-console/src/features/dashboard/index.tsx` — 首页活跃管道数优先使用 `system_metrics.pipelines_active` WebSocket 实时值，列表未加载时回退 `/intersections/summary.pipelines_active`，列表加载后使用 `/pipelines` running 数；`traffic-fly-console/src/features/dashboard/index.test.tsx` 覆盖 WebSocket 更新和 summary fallback；当前前端回归 `npm test` 通过 27 个测试文件 / 160 个测试，`npm run build` 通过 |
| T-430 | PipelineManager 正常结束状态修正 | ✅ | `platform/app/services/pipeline_manager.py` — 子进程 `return_code == 0` 时标记为 `stopped` 且清空 `error_message`，非零退出才标记 `error` 并保留 stderr 尾部；`platform/tests/test_pipeline_manager.py` 覆盖正常结束与异常退出两个状态分支 |
| T-431 | InfluxDB 历史统计自愈与查询修复 | ✅ | `platform/app/utils/influx_query.py` — 初始化时自动创建并切换目标 database，修复已有旧卷缺少 `influx` 导致写入 404；`query_stats()` 动态道路查询改为 `SELECT mean(*)` 并单独容错，避免 `SELECT * GROUP BY time` 导致历史统计整体返回空；`docker-compose.yaml` — 新增官方 `INFLUXDB_DB=influx` 初始化变量；`platform/tests/test_influx_query.py` 覆盖自动建库、已有库切换、动态 road 字段合并和 road 查询失败降级 |
| T-405 | `utils_local/utils.py` 单元测试 | ✅ | `test_utils_local.py` — 覆盖 `intersects_central_point()` 的道路内匹配、多道路返回正确 road id、道路外返回 `None`、边界点不算 inside 的 Shapely 语义，保护道路归属基础逻辑；`python -m pytest test_utils_local.py -q` 通过 3 个测试 |
| T-406 | ByteTrack 核心单元测试 | ✅ | `test_byte_tracker_core.py` — 覆盖高置信检测创建轨迹、保留检测类别 ID，以及第二帧低置信但 IoU 匹配的检测可延续同一 track id，保护航拍小目标恢复逻辑；`python -m pytest test_byte_tracker_core.py -q` 通过 2 个测试 |
| T-440 | 平台核心 API smoke 测试 | ✅ | `platform/tests/test_core_api_routes.py` — 构造最小 FastAPI app state 并验证 `/api/v1/pipelines`、`/intersections`、`/drones`、`/trajectories/{id}`、`/trajectories/{id}/conflicts`、`/alerts`、`/system/health` 等 TCC 核心 API 均可访问；`python -m pytest platform/tests -q` 通过 31 个测试 / 11 个 subtests |
| T-441 | 历史冲突复盘 API | ✅ | `platform/app/api/v1/trajectories.py` — 新增 `GET /api/v1/trajectories/{intersection_id}/conflicts`，从 InfluxDB `conflict_events` 查询 TTC/PET、场景、证据、风险分和预测位置；`platform/tests/test_core_api_routes.py` 覆盖 period/limit 参数透传和证据字段返回 |
| T-442 | Grafana datasource provisioning 回归测试 | ✅ | `services/grafana/provisioning/datasources/datasource.yaml` — 自动配置 InfluxDB/PostgreSQL datasource，UID 与 `camera-1.json` / `camera-2.json` 面板引用一致；`docker-compose.yaml` — Grafana 默认 `admin/admin123`、注入 InfluxDB 凭据并依赖 InfluxDB/PostgreSQL；`test_grafana_provisioning.py` 覆盖 compose 默认值、provisioning 挂载、datasource UID 对齐和容器网络地址；`python -m pytest test_grafana_provisioning.py -q` 通过 3 个测试 |

### 待完成

- [x] T-105: Kafka 端到端验证（页面启动 `statistics_11/conflicts_11`，Platform WebSocket 收到 stats/conflict）
- [x] T-106: MJPEG 视频流验证（Platform/Vite/browser live 验证通过）
- [x] T-301: Drones 页面对接 telemetry WebSocket
- [x] T-302: GIS 轨迹回放
- [x] T-303: Mission-Pipeline 绑定
- [x] T-304: Dashboard pipelines_active 真实数据
- [x] T-305: Alert 持久化到 PostgreSQL
- [x] T-401: ShowNode supervision 重构（TD-006）
- [x] T-407: 自动车道推断（AutoLaneInferenceNode，无需人工标注）
- [x] T-408: 方向分类 heading 精度修复（P0，窗口 n//2 + 位移阈值）
- [x] T-409: 车道聚类合并阈值优化（P1，3.5x 阈值）
- [x] T-410: U-turn 自引用标签修复（P2，OPPOSITE_CARDINAL + 自引用保护）
- [x] T-411: YOLO 分割模型车道检测（LaneDetectionNode，manual > model > auto 优先级链）
- [x] T-405: utils_local/utils.py 单元测试
- [x] T-406: ByteTrack 核心单元测试

---

## 待办事项

### 已完成 ✅
- [x] 管道端到端测试（`test_pipeline_inter_xqh.py`，56 PASS / 0 FAIL / 0 WARN）
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
- [x] **方向分类 heading 精度修复（T-408 / P0）**
- [x] **车道聚类合并阈值优化（T-409 / P1）**
- [x] **U-turn 自引用标签修复（T-410 / P2）**
- [x] **YOLO 分割模型车道检测（LaneDetectionNode）**
- [x] **VisDrone motor/non_motor 分类与小目标阈值修复（T-412）**
- [x] **ShowNode 左上角幽灵框堆积修复（T-413）**
- [x] **无道路标注参数启动支持（T-414）**
- [x] **车道检测集成到 main.py 和 main_optimized.py**
- [x] **页面发起 inter_xqh 全流程验证（T-417）**

### 近期（1-2 周）
- [x] 完成 `docs/generated/uav-traffic-ai-prd/` S1-S7 七个分册详细评审草案及跨分册一致性审查（2026-07-13）
- [x] 完成 S8 全域态势工作台（首屏 Dashboard）详细评审草案：以交通指挥中心主任为第一用户，冻结“全局态势—重点关注—平台待办—无人机保障—数据可信度—专业下钻”产品框架（2026-07-14）
- [x] 完成 Console2 页面与 PRD 裁剪归并：正式导航收敛为全域态势、智能研判、事故测绘、执法线索、飞行任务、平台治理六域；旧视频、热区、报告和治理子页归并后不保留旧前端路由（2026-07-14）
- [x] 统一 Console2 页面框架：工作台与实时监测共用 ConsoleFrame，左侧为六个一级业务域，顶部仅显示当前域二级页面；自动化回归 20/20、生产构建通过（2026-07-14）
- [x] Console2 接管登录、实时监测、标定中心、系统与身份：统一 API Client/React Query/JWT 会话/可重连 WebSocket，真实 REST/WS/MJPEG、管理员后端校验、标注自然尺寸坐标、检测器/BEV 主次切换；旧 `traffic-fly-console` 已从 Compose/发布入口移除。Console2 全量回归 36/36，覆盖登录失败、刷新恢复、非法跳转、真实监控、视频重试、WS 重连/退订/去重、系统部分失败、用户只读、多车道自然尺寸坐标保存；Platform 全量回归 37/37，覆盖 REST/WS Token 与系统/用户/标定管理员校验；生产构建通过（2026-07-14）
- [x] 完成 S3 事故测绘真实落地：本地 PostgreSQL `road9` + Alembic、任务状态机、MP4+DJI SRT 后台处理、内容寻址证据、服务端 ENU 点线面量算、技术复核、PDF/JSON/GeoJSON 报告、质量投递门禁、outbox 重试/死信与 Console2 `/survey/**` 真 API 页面（2026-07-14）
- [x] 使用 `inter_xqh` 12 秒真实视频片段+29,741 条原始 SRT 遥测完成 S3 首轮 API/worker/UI 验证：提取 6 帧、遥测覆盖 100%、服务端线段量算 42.49m、报告 PDF 可读取、未批准质量规则按 422 阻止投递（2026-07-14）
- [x] 使用 `inter_xqh` 5.0GB 原始 4K MP4（992.358s）+原始 SRT 完成 S3 全量真实测绘：批次 `BATCH-7E8061819ABA`，worker 报告 29,741 帧、遥测覆盖 99.9967%、6/6 关键帧可量算；服务端线段量算 79.51m，报告 `RPT-5BECE3A9C5A6` 的 PDF 为 3137 bytes/`%PDF`，内容哈希 `39a0740d…778b3`，投递门禁按预期 422。测试同时修复采集导入后 revision 未刷新和报告生成后页面未立即更新两个前端缺陷，Console2 回归 38/38、构建通过；截图保存在 `console2/.design-qa/survey-full-inter-xqh-*-20260715.png`。该验证仍不关闭精度/法制/主平台合同阻断项（2026-07-15）
- [x] 完成 S9 无人机对接与飞行计划管理详细评审草案：冻结 RTSP+MQTT/服务器 MP4+DJI `.srt` 成对源、once/weekly FlightPlan、Mission 状态机、调度幂等和飞控边界（2026-07-13）
- [ ] 冻结无人机设备权威编码、RTSP/MQTT 支持矩阵、secret reference、服务器本地资产 allowlist 及 MP4/SRT 时间覆盖校验口径
- [x] 冻结并实现 Drone/Source/FlightPlan/Mission API、`uav_drones/uav_video_sources/uav_telemetry_sources/uav_flight_plans/uav_missions/uav_pipelines` migration 和现有内存状态迁移（Alembic `20260715_0003`）
- [x] 在 FastAPI 单体中实现 MissionOrchestrator：5 秒扫描、PostgreSQL advisory lock、`(flight_plan_id,scheduled_start_at)` 唯一、窗口内恢复和 `skipped/window_missed`
- [x] 将 `/drones` 增强为无人机、数据源、飞行计划、执行记录四页签，完成管理员写权限、非管理员只读和敏感字段脱敏
- [x] 使用 `inter_xqh` MP4+SRT 完成 S9 工程端到端验收；自动化覆盖 once/weekly、跨午夜、例外日、重叠拒绝、重启、多实例防重、停止/重试和非管理员 403；另以 5GB 原视频 `frame_stride=300` 完成重启恢复后自然 EOF，Mission `MSN-995CEBE0415E` 为 `completed/source_eof`，证据见 `docs/test_report_s9_inter_xqh_eof.json`。正式 RTSP/MQTT、容量长跑和权限矩阵仍按外部门禁验收
- [x] 在隔离 `road9_i2_test` 完成空库/升级迁移、真实 PG 集成及 `20260715_0003 → 20260714_0002 → 20260715_0003` 回滚恢复演练
- [ ] 由指挥中心冻结 S8 项目路口、具备监控条件、正在监测、监测降级、无人机保障和重点关注榜口径；未冻结前不得继续使用未定义的单一 `active` 作为主任结论
- [x] 将 `/` 重构为真实城市地图主导的项目一图概览；移除 `INT_camera_1` 趋势硬编码，使用 DashboardReadModel 按服务端范围聚合；未批准项目范围和 KPI 继续显示待冻结
- [x] `/gis` 正式路由已删除按数组序号生成的网格示意点位，仅展示 API 返回的有效坐标；无坐标/无轨迹/无冲突时展示真实空态，不生成模拟位置。权威 `inter_id + road_data_version` 与坐标合同仍是 S5 外部阻断
- [x] 实现 Dashboard overview/intersections/detail/drones 聚合 API、服务端筛选/bbox/分页、统一 `as_of/window/coverage/quality`、关注项原因和 503 降级；正式项目范围、可比时段、缓存/全局增量回补策略仍待批准
- [ ] 完成 S8 主任首屏视觉原型及大屏/办公端适配，重点验证 5 秒全局辨识、30 秒重点定位、非颜色状态编码、空态/过期/断线/无权限状态
- [x] 冻结目标数据架构：PostgreSQL connection database=`road9`，UAV Topic/`msg_type`/WebSocket/自建表统一 `uav_`，指标采用 TimescaleDB，InfluxDB/Telegraf/Grafana 迁移后退役（ADR-019）
- [x] 盘点本地 `road9` database/public schema、平台表与扩展状态并输出对象归属/迁移矩阵；权威路网只读视图仍待数据方提供和确认
- [x] 在隔离本地 TimescaleDB 2.28.2/PostgreSQL 17 完成 `20260715_0004`～`0007` migration、5 张 hypertable、回滚恢复及真实 PG 集成验证；既有 5432 普通 PostgreSQL 保持 degraded 且未清库
- [ ] 在 `road9` 安装并验收 TimescaleDB，冻结扩展版本/许可、目标 schema、chunk、索引、压缩、保留、连续聚合、容量、备份恢复、高可用和 RPO/RTO
- [ ] 将 PostgreSQL 部署镜像/托管实例切换为兼容的 TimescaleDB 发行形态；当前镜像不含扩展，必须在目标环境做安装、升级和恢复演练
- [x] 实现 `MetricStore` 深模块：canonical 信封校验、`uav_message_inbox` 全局幂等、事实同事务展开、同 ID 异 hash 隔离、官方历史 API 查询；旧信封兼容已删除
- [x] Kafka Consumer 关闭 auto commit；数据库成功后精确提交 partition offset，瞬态失败 seek 重放，永久性 schema/身份错误耐久进入 `uav_message_dead_letters` 后才推进 offset
- [x] canonical Producer 使用显式 Topic builder 生成 `uav_statistics/uav_track_complete/uav_conflicts/uav_telemetry_*`，并修复 camera 10 后缀字符串替换错误；Consumer 只读 canonical Topic
- [x] `/events` 使用 `uav_conflict_events + uav_conflict_reviews` 展示并持久化管理员技术复核 revision；该状态不等同主平台处置或违法认定
- [x] 冻结并实现本地工程所需 `uav_*` DDL：核心 Hypertable、S9、消费幂等、事件投递、证据、测绘、执法、路网上下文、绑定和审计由 `0001`～`0009` 前向 migration 管理；生产 schema/权限/保留/容量仍待外部批准
- [x] 引入受控 Alembic migrations 并设置版本表 `uav_alembic_version`；Platform 启动按 migration head 升级，不再依赖 `Base.metadata.create_all()` 隐式建表
- [x] 统一生产者/消费者/API/前端消息为 `uav_statistics_*`、`uav_track_complete_*`、`uav_conflicts_*`、`uav_telemetry_*` 等 canonical Topic 及 `uav_*` msg_type/WebSocket channel；无前缀兼容已删除
- [x] 重构 Kafka Topic builder，禁止以字符串替换从统计 Topic 推导其他 Topic；以 `camera_id` 显式生成 canonical Topic 并覆盖 camera 10 回归测试
- [x] 按消息等级建设本机可靠发送：完成轨迹/真实冲突使用 fsync + atomic rename 持久文件 spool 和补发，周期指标/遥测记录 expected/actual/dropped/coverage/drop reason；未引入 SQLite。生产磁盘满、长时 broker 故障和容量门禁仍待验收（2026-07-16）
- [x] Consumer 关闭 auto commit，按 `uav_message_inbox` + 事实同事务成功后手动提交 offset；已覆盖数据库异常、永久错误死信、同 ID 不同 hash 和重放语义
- [x] Platform 历史 API、Dashboard、轨迹和冲突查询使用 PostgreSQL/TimescaleDB；旧查询工具与依赖已删除
- [x] 本机明确不迁移、不对账、不备份旧历史数据；新库仅 seed 管理员，旧资产 7 天不挂载保留
- [ ] 冻结轨迹/事件业务唯一键：不得单独使用会随进程重启复用的 `track_id`，至少纳入 task/pipeline/session/camera 与 source_system 上下文
- [ ] 验证 TimescaleDB 查询到 REST 的 TIMESTAMPTZ、JSONB、Decimal、空值和排序语义；不兼容变更必须明确升级 API major 版本
- [ ] 冻结 `uav_system_metrics` 生产责任、指标目录、单位/标签、采样周期、基数、保留和告警阈值，并实现采集与契约测试
- [x] 页面/API 切读 `road9`；隔离断库恢复验证后再执行正式本机切换和 30 分钟探测
- [x] 从 Compose、配置、依赖、测试和运维手册移除旧观测链路及 provisioning/脚本；旧存储按 7 天 manifest 管理
- [ ] 按分册顺序组织正式专项评审：先冻结 S5 路网与共性能力、S6 主平台集成和 S9 无人机接入/调度，再并行确认 S1-S4、冻结 S8 首屏口径，最后汇总冻结 S7 质量验收与运营
- [ ] 为 S1-S9 各分册补齐需求负责人、业务规则阈值、接口字段、验收样本量、截止时间和关闭依据，并将所有 `【验收阻断】` 同步回总 PRD 第 14 章
- [ ] `docs/roaddata.md` 已移除明文连接信息；仍须完成原凭据轮换、密钥管理/环境变量接入和仓库历史秘密扫描
- [ ] 由数据负责人确认 `road9` database 内的权威路网 schema/只读视图及路网版本对象，并冻结路口/Link/车道字段、代码表、几何类型、SRID 和 GCJ02 语义；不得照搬历史 `ycx/road10` 结构
- [ ] 设计路网只读视图/API与本地版本缓存，禁止检测逐帧直连远程生产库
- [ ] 建立本地 `intersection_id`/视觉车道与权威 `inter_id/link_id/lane_id + road_data_version` 的绑定和人工校正流程
- [ ] 为统计、轨迹、冲突和执法线索增加路网版本、主数据ID、地图匹配方法/置信度及 `unmapped` 降级用例
- [ ] 冻结智慧交通主平台 AI 事件 schema：全局事件ID映射、幂等回执、持久化重试/死信、风险等级映射和复核反馈
- [ ] 取得 LSTM 简化及雷达测速依赖的甲方书面确认，或恢复为投标合同交付范围；货车识别范围已固定为现有模型货车/非货车二分类，不新增细分类建设
- [ ] 制定风险热区合同验收阶段、样本积累窗口和验收用例
- [x] ~~清除 Kafka stale data（运行 `scripts/fix_kafka_and_restart.sh`）~~ — 不迁移旧 Kafka 数据，脚本已删除并使用全新 KRaft 卷启动 canonical Topic
- [x] 验证 Kafka → Platform → InfluxDB 遗留链路数据流（T-105；仅作为迁移前基线，不是目标架构验收）
- [x] 验证 Platform/Vite MJPEG 路由（T-106；生产独立 camera 容器 Nginx 路由保留为部署形态）
- [ ] 优化 inter_xqh 道路多边形（精确标注道路区域）
- [x] ~~修复 TD-009：export_dashboards.py 路径问题~~ — ADR-019 已决定退役 Grafana，改由旧链路退役任务统一处理
- [x] 为 `utils_local/utils.py` 添加单元测试（T-405）
- [x] Mission-Pipeline 绑定：创建任务时自动启动检测管道（T-303）
- [x] 前端 Drones 页面接入 `uav_telemetry:{drone_id}` WebSocket 实时遥测（T-301；旧无前缀 channel 已拒绝）
- [x] 前端 Dashboard 的 `pipelines_active` 字段对接真实数据（T-304）

### 中期（1-2 月）
- [ ] 解决 TD-002：统一入口点
- [x] 解决 TD-006：ShowNode supervision 重构（T-401） ✅
- [x] 自动车道推断：从轨迹数据自动发现车道中心线+各方向指标（T-407） ✅
- [x] 为 ByteTrack 核心算法添加单元测试（T-406）
- [x] 合并 docker-compose 文件并切换为 Kafka KRaft + PostgreSQL/TimescaleDB + Platform/Console2/Nginx；已移除 InfluxDB/Telegraf/Grafana/Zookeeper 运行依赖（ADR-019，本机 2026-07-16 完成）
- [x] GIS 轨迹回放切换为 `uav_track_complete` + `road9` canonical 数据（T-302；旧 InfluxDB 路径已退役）
- [ ] 管道健康监控面板（PipelineManager 状态 + 进程日志流）
- [x] Alert 持久化到 PostgreSQL（T-305）

### 远期（3-6 月）
- [x] ~~评估是否升级到 InfluxDB 2.x~~ — ADR-019 已决定迁移至 `road9`/TimescaleDB，不再升级 InfluxDB
- [ ] 评估是否使用 ultralytics 内置跟踪替代 byte_tracker/
- [ ] 添加 RTSP 流的自动重连机制
- [ ] 巡检报告自动生成（PDF/HTML）
- [ ] 多无人机任务调度
- [ ] VLM 语义分析旁路
- [ ] 模型微调：uav_best.pt 增加 person + bicycle
- [x] 冲突检测默认启用 + 监控页实时冲突事件列表

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

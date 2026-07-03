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

#### TD-006: ShowNode 过于庞大 → ✅ 已解决
- **状态**：✅ 已修复（2026-06-09）
- **修复内容**：使用 supervision 库重构，拆分为 10 个聚焦子方法（`_draw_detections`、`_draw_tracked`、`_draw_roads`、`_draw_fps`、`_draw_stats_panel` 等），新增圆角边框、轨迹尾迹、标签背景等功能，去除 `random` 依赖改用 `ColorPalette` 确定性着色

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
- [ ] 清除 Kafka stale data（运行 `scripts/fix_kafka_and_restart.sh`）
- [x] 验证 Kafka → Platform → InfluxDB 全链路数据流（T-105）
- [x] 验证 Platform/Vite MJPEG 路由（T-106；生产独立 camera 容器 Nginx 路由保留为部署形态）
- [ ] 优化 inter_xqh 道路多边形（精确标注道路区域）
- [ ] 修复 TD-009：export_dashboards.py 路径问题
- [x] 为 `utils_local/utils.py` 添加单元测试（T-405）
- [x] Mission-Pipeline 绑定：创建任务时自动启动检测管道（T-303）
- [x] 前端 Drones 页面接入 `telemetry:{drone_id}` WebSocket 实时遥测（T-301）
- [x] 前端 Dashboard 的 `pipelines_active` 字段对接真实数据（T-304）

### 中期（1-2 月）
- [ ] 解决 TD-002：统一入口点
- [x] 解决 TD-006：ShowNode supervision 重构（T-401） ✅
- [x] 自动车道推断：从轨迹数据自动发现车道中心线+各方向指标（T-407） ✅
- [x] 为 ByteTrack 核心算法添加单元测试（T-406）
- [ ] 合并 docker-compose 文件（统一 Kafka/InfluxDB/Nginx 实例）
- [x] GIS 轨迹回放（基于 track_complete + InfluxDB 数据）（T-302）
- [ ] 管道健康监控面板（PipelineManager 状态 + 进程日志流）
- [x] Alert 持久化到 PostgreSQL（T-305）

### 远期（3-6 月）
- [ ] 评估是否升级到 InfluxDB 2.x
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

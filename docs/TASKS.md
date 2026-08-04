# TASKS.md — TrafficAnalyzer 任务追踪

## 2026-07-31 抽帧步长启动配置

- [x] 统一检测器 `video_reader.frame_stride`、Platform `PIPELINE_FRAME_STRIDE` 和原生 MPS 批量回放入口默认值为 `3`；交互式范围固定为 `1–30`，批量入口继续拒绝超过 0.5 秒源时间间隔的破坏性采样。
- [x] Mission/Pipeline API、Mission snapshot、PipelineManager、检测子进程 `FRAME_STRIDE` 和 Pipeline response 串成单一运行链路；外部原生 MPS 回放登记实际 stride，不再由 Platform 猜测。
- [x] Console2 实时监测快速启动、路口检测卡片和手动 Mission 表单提供抽帧步长设置，并解释“每 N 帧处理 1 帧”；运行中卡片显示实际值。
- [x] 后端默认/覆盖/越界和前端默认/提交测试已覆盖；`stride=3` 对 30 FPS 源约为 10 个处理帧/秒，并不表示 3 FPS。
- [x] 浏览器启动新参数时若 Platform 仍是旧进程，FastAPI 会返回 `frame_stride/extra_forbidden`；已通过重启加载新 schema，并让 Console2 将验证数组显示为具体字段与“刷新版本或重启 Platform”提示，不再只显示 Axios `422`。

## 2026-07-30 停车车辆伪轨迹与能力边界修复

- [x] 默认tracking profile固定为`hover_cruise_v1`，仅显式请求允许`hover_only_legacy`；删除“缺少独立注册自动回退legacy”的错误选择器。
- [x] 世界坐标、速度、方向和TCC只消费视频/SRT当前帧矩阵及遥测质量；删除当前H重投历史像素、px/s冒充km/h和TCC像素回退。
- [x] Runtime Road Map Bundle收敛为Lane/Link地图；`RoadMapMatchingNode`把上游GCJ-02转换到地图ENU匹配，地图缺失或不可用不改变geo/TCC能力。
- [x] 停止SourceGeoRegistration API、Mission固定、Pipeline参数和环境注入；已应用`0020`结构非破坏性保留并标记停用。
- [x] 单元/契约回归覆盖默认profile、trajectory/geo/road/TCC四层能力矩阵、地图不改变世界矩阵、无世界事实不输出速度/TCC及路网独立匹配；Mission与Pipeline接口返回各层布尔值和原因。
- [x] mp4728 3m/s 原生 MPS 全片自然 EOF，同帧停车区长竖尾迹由旧图12组降为0，主车流连续轨迹保留；Kafka/road9精确对账，见[`test_report_mp4728_sgr_removal_20260730.md`](test_report_mp4728_sgr_removal_20260730.md)。

## 2026-07-28 mp4728 三速度巡航全流程回归

- [x] 登记 `SRC-MP4728-JS-0728-{3,5,7}MS` 三个本地 SourceProfile，固化 4K HEVC 视频与 DJI Cloud JSON 的 SHA-256、时长、帧率、录制时间、期望速度和同步配置；测试走廊固定为 `INT_MP4728_JINGSHI_CORRIDOR`。
- [x] 3/5 m/s 正确 OSD 在执行期间到位；三份遥测哈希互不相同且各自覆盖完整视频。偏移更新为 3 m/s `72.778s`、5 m/s `72.438s`、7 m/s `74.373s`，均以独立来源回放，未借用坐标或速度。
- [x] ADR-025 解耦图像轨迹生命周期与地理/路网质量：成熟 ByteTrack 关联立即获得稳定 `track_id`；仅关联结束、超时或自然 EOF 完成，地图覆盖、配准和姿态变化不再拆分或丢弃轨迹。
- [x] 拆分 `trajectory_output_eligible / geo_analytics_eligible / road_analytics_eligible / tcc_analytics_eligible`；兼容字段 `formal_analytics_eligible` 只表示完整道路能力。完成事件保持 `uav_track_complete/v1`，像素/时间/帧号/可空 ENU/GCJ-02 同索引。
- [x] 历史实现曾增加版本化SourceGeoRegistration；该运行时设计已由2026-07-30三输入架构修订取代，`0020`已应用结构仅作非破坏性兼容保留。
- [x] road9 轨迹事实增加 association/跟踪/地理/路网质量字段，默认查询支持像素降级轨迹；Console2 完成数包含像素轨迹，BEV 只绘制有效 GCJ-02，并显示“轨迹已输出，路网匹配降级”，只标记 Lane ID、Link ID 与匹配质量不可用。
- [x] 原生回放器增加 `roadless_trajectory` 验收：要求成熟 active 和 completed 轨迹均大于 0、点列对齐、自然 EOF、Kafka/road9 精确对账，Lane/Link 匹配及车道级统计不伪造；无可信世界证据时 TCC 为零，通用车辆计数和拥堵指标不受 road gate 抑制；原地图模式保持兼容。
- [x] 以原生 arm64/MPS、`frame_stride=4`、`imgsz=832` 和全新 `mp4728-roadless-final2-20260728T192000Z` 串行重跑三源至自然 EOF；`pipe-c79e13bb / pipe-4ca52577 / pipe-e8a97645` 共 7,881 条完成轨迹且 Kafka/road9 精确一致。额外 `pipe-3c87381b` 浏览器烟测验证登录会话、WebSocket、MJPEG、像素尾迹、完成轨迹、正确路网降级文案和 Console 0 error 后受控停止；全量门禁通过，收尾活动 Pipeline/Mission 均为 0。
- [x] 无外部真值，IDF1/HOTA/ID switch/位置 RMSE/速度 MAE 保持 `not_evaluated`；恢复轨迹事件不等于生产巡航精度验收。
- [x] 实现与当前证据边界见 [`test_report_mp4728_20260728.md`](test_report_mp4728_20260728.md)。
- [x] 收尾同步 README、协作约束、架构、业务逻辑、契约、数据库、ADR、任务、Runbook 与 mp4728
  报告口径；生成脱敏交接手册 `/private/tmp/TrafficAnalyzer-mp4728-trajectory-road-decoupling-handoff-2026-07-28.md`。

## 2026-07-27 TCC 告警与轨迹显示回归修复

- [x] T-499：检测器 `ShowNode` 将 warning TCC 的虚线、端点标记和 TTC 徽章从琥珀橙改为高对比红色；critical 继续使用红色，候选轨迹的琥珀虚线和 `NO STATS-TCC` 语义保持不变。
- [x] 新增 warning TCC 实际渲染像素回归，锁定纯红端点且告警区域不再出现橙色；历史内容寻址事件证据不重绘，仅后续新生成的检测器关键帧采用新配色。
- [x] T-500：定位轨迹锚点由旧 `TraceAnnotator` 默认 bbox 中心退化为固定底边中心的根因；`GroundTrajectoryTrackerNode` 继续以底边接地点生成 `trajectory_px/ENU/GCJ-02`，但以 bbox 中心生成运动补偿后的 `trajectory_display_px`，`ShowNode` legacy 回退也恢复中心轨迹，不改业务事实。
- [x] 生产节点链视觉验收确认横向车辆业务接地点 `y=390`、显示中心 `y=360`，红色 warning TCC 与中心轨迹同时可见；证据为 `output/visual-qa/tcc-track-center-restored.png`。门禁为根 `153 passed`、Platform `215 passed / 5 skipped / 10 subtests`、XQH `56 PASS / 0 FAIL / 0 WARN`、Console2 单 worker 全量 `147 passed` 与 production build、ruff、ADR-019 local strict、`git diff --check` 通过。

## 2026-07-25 TCC 检测器两图本地证据闭环

- [x] 复用检测器原有 TCC 关键帧能力：`KafkaProducerNode` 只冻结待发布事件，`ShowNode` 产生真实检测器 `frame_result` 后，`TccEvidencePublisherNode` 才保存 `conflict_original_frame` 与 `conflict_detector_frame` 并发布；证据侧不允许重绘或缩放。
- [x] 两图以 SHA-256 内容寻址写入 `SURVEY_STORAGE_DIR/objects/<前两位>/<sha256>`；事件只携带 `storage_backend=managed`、相对 `storage_key`、hash、大小、媒体类型与尺寸，不保存绝对路径或 Base64，为后续 MinIO 后端保留可移植描述符边界。
- [x] Platform 在同一共享本地根目录内校验相对路径、类型、hash 与大小后直接登记 EvidencePackage/EvidenceItem，不重复复制文件；写盘或校验失败仍保存 TCC 事实，并显式标记 `evidence_status=incomplete`。
- [x] `VideoSaverNode` 保留原有 `conflict_*.jpg` 输出；managed `conflict_detector_frame` 使用同一 `frame_result` 内容寻址，不替代检测器原输出。历史三图事件保持原样可读，不迁移、不删除。
- [x] 自动化门禁：根 `150 passed`；Platform `214 passed, 5 skipped, 1 warning, 10 subtests passed`；Console2 `147 passed` 且 production build 通过；ruff 与 `git diff --check` 通过。
- [x] 原生 macOS arm64/MPS 将 `SRC-MP4NEW-CH-0625-AM` 回放至自然 EOF：798 条 stats、4,005 条完成轨迹、10 条 TCC、`invalid_tcc_events=[]`、返回码 0；20/20 张本地 JPEG 哈希与尺寸复算通过，均为原尺寸 `3840×2160`。
- [x] road9 持久化本次 Pipeline 的 10 条新 TCC；真实 Chromium 打开最新事件 `742e05c850094b00627e9b333e60c476bd4f7143`，两图均 `complete=true / naturalWidth×naturalHeight=3840×2160`，全屏检测图可见真实 FPS/目标框/轨迹/冲突 ID/TTC，Console `0 error / 0 warning`；截图见 `output/playwright/tcc-exact-show-event-742e05c8-fullscreen.png`。

## 2026-07-25 五路口视频整体回归

- [x] 对 `mp4new` 五个 canonical SourceProfile 以原生 macOS arm64/MPS、`frame_stride=10`、`imgsz=640`、独立 `run_id/pipeline_id` 串行回放至自然 EOF；显式使用 `hover_only_legacy` 验证经典五源既有业务链，5/5 返回码 0。
- [x] Kafka/road9 精确对账：2,223 条 Stats、12,238 条完成轨迹、571,058 个轨迹点、26 个严格 TCC；12,238/12,238 双坐标序列对齐，26/26 冲突均有 complete 三图 EvidencePackage。
- [x] 保留巡航安全边界：经典五源缺少 `registration_pose/camera_calibration/map_coverage_enu_m`，默认 `hover_cruise_v1` 的 469/469 帧按候选隔离且正式轨迹为 0，不伪造注册数据、不宣称巡航精度。
- [x] 修复 GeoJSON EOF flush 对空帧取 shape 的崩溃、MPS runner 缺少显式 profile、运行态验证器使用被禁 query token、ADR-019 测试拓扑漂移，并补聚焦回归。
- [x] 运行态控制面目录 9/9 通过 Mission、重复启动保护、MJPEG、canonical WebSocket 与停止回收；真实 Chromium 验证海右路历史 500 条 GCJ-02 轨迹、6 条冲突事件、实时检测画面和正确质量门禁，Console 0 error。
- [x] 最终门禁：根 143 passed；Platform 213 passed/5 skipped/10 subtests；Console2 147 passed + production build；refactor 52/0；xqh 56/0/0；ADR-019 strict 10/10；ruff、compileall、diff check 通过；最终 `pipelines_active=0`。
- [x] 完整证据与生产边界见 [`test_report_five_source_regression_20260725.md`](test_report_five_source_regression_20260725.md)；IDF1/HOTA/ID switch/位置 RMSE/速度 MAE 继续为 `not_evaluated`。

## 2026-07-25 实时 BEV 视口跳动修复

- [x] 定位紧凑 BEV 在实时轨迹刷新时跳动的根因：覆盖物 effect 每个批次都调用 `map.setCenter()`，并在轨迹短暂为空后再次执行 `setFitView()`；该问题属于前端地图视口生命周期，与路网绑定无关。
- [x] 将地图中心同步从轨迹覆盖物更新中拆分，只在业务中心点实际变化时执行；首次轨迹自动适配增加地图实例级门闩，实时空批次不再重置视口。
- [x] 增加连续轨迹批次、短暂空批次、轨迹恢复回归；地图组件与实时监测聚焦测试 `53 passed`、production build、`git diff --check` 通过。
- [x] 真实浏览器连续 6 秒观察期间轨迹从 295 增到 312 条，地图容器、图层、画布 transform 和画布尺寸均保持单一稳定值，确认轨迹持续刷新且紧凑 BEV 不再重置视口。

## 2026-07-25 实时轨迹消费阻塞修复

- [x] 定位检测器持续发布而 BEV 只显示旧快照的根因：`uav_stats` 车道可选指标 `queue_length_m=null` 触发告警规则 `None > float`，消费器反复 seek 同一 Kafka offset，阻断后续实时轨迹。
- [x] 告警引擎对 `queue_length_m`、`congestion_index`、`lane_match_rate`、`avg_speed_kmh` 的空值、非法值和非有限值按“无可用测量”跳过，不生成伪告警。
- [x] 告警评估作为统计广播后的旁路处理；规则异常记录 warning，但不得阻止实时 WebSocket 投递、inbox dispatch 完成或 Kafka offset 提交。
- [x] 新增空值消息和告警异常两组回归；Kafka/实时频道/告警持久化聚焦测试 `14 passed`。
- [x] 运行恢复中排除一项消息放大风险：已验证路网仍重复携带 960px base64 悬停标注图；发布态路网无需该冗余截图。
- [x] 已绑定 `complete` Runtime Road Map Bundle 的 Pipeline 不再重复发送悬停标注图；所有活动/候选目标及其实时尾迹继续发送，完成轨迹仍由独立 canonical Topic 完整持久化。
- [x] 定位重启后的谱系积压：动态相机号固定从 10 开始导致新 Pipeline 复用旧 Topic，当前 `pipe-*` 消息排在历史回放积压后，Console2 按谱系正确拒绝旧消息并显示过期。
- [x] Platform 每次启动以 epoch 秒初始化动态相机号，恢复 Mission 使用新的 canonical Topic；视频端口仍从 8101 分配，物理 SourceProfile/路口身份不由该运行时相机号承载。
- [x] 候选轨迹实时消息改为显式白名单：保留全部候选目标、质量原因及最多 30 个像素/ENU/GCJ-02 对齐尾迹点，剔除逐点 `point_quality_lineage` 等内部历史，避免候选阶段约 1.08–1.14 MB 的无界统计消息。
- [x] 最终真实运行跨过完整候选阶段，`uav_stats` 连续发布且未再出现消息超限/空值告警阻塞；浏览器红态转绿为 `LIVE 1.9 FPS`、`实时更新`、71 辆当前目标及可见 GCJ-02 轨迹投放。聚焦回归 `45 passed, 1 subtest passed`，ruff 与改动范围 `git diff --check` 通过；Platform 全量 `210 passed, 5 skipped`，仍有 2 项既有 ADR-019 审计脚本/测试漂移失败未混入本次修复。

## 2026-07-25 Console2 BEV 最近 5 分钟 / 150 条混合窗口

- [x] 实时 BEV 保留全部活动/候选轨迹和最近 5 分钟到达的完成轨迹，即使总量超过 150 条；不再用固定上限裁剪高流量实时画面。
- [x] 五分钟窗口不足 150 条时，从本次 Pipeline 会话中更早的最新完成轨迹补足到 150 条；窗口只影响展示，不裁剪 Kafka 或 `road9` 中的完整事实。
- [x] `LiveModules.test.jsx` 覆盖 162 条五分钟内轨迹全部可见，以及窗口不足时回填到 150 条并保留实时轨迹；Console2 `146 passed`，production build 通过。

## 2026-07-25 xqh 尾部离场巡航全链路复验

- [x] 独占原生 MPS 重跑 xqh 840s–自然 EOF：真实 4K MP4、逐帧 SRT、YOLO、背景视觉 warp、纯图像 ByteTrack、ID 后世界投影、质量门禁、ShowNode、统计/TCC 隔离和 EOF flush 全部进入同一验收链。
- [x] 24/24 工程门禁通过：1142 个采样帧、107603 个合法检测、非法框 0、60940 次图像关联、757 个观测 ID、active/completed/candidate 点对齐失败 `0/0/0`、降级业务泄漏 0、自然 EOF 通过。
- [x] 原生 MPS 源采样 7.4925Hz，YOLO 稳态 P95 175.51ms，完整单进程帧 P95 270.401ms；正式帧视觉有效率 100%，候选末点/bbox 接地点残差 P95/最大值 1.146/1.4px。
- [x] 人工核查悬停、质量断点、离场巡航和离场降级四组生产 ShowNode 截图；正式轨迹与琥珀候选轨迹同时可见，候选明确标记 `NO STATS-TCC`。
- [x] 仓库级回归：根 `139 passed`；Platform `207 passed, 5 skipped, 1 warning, 10 subtests passed`；Console2 `139 passed` 且 production build 通过；xqh 基线 `56 PASS / 0 FAIL / 0 WARN`；改动 Python ruff 与 `git diff --check` 通过（仅既有 FrameElement CRLF 提示）。
- [x] 刷新 `docs/generated/xqh-hover-departure-acceptance.json`、四组长期截图和严格证据审计；xqh 素材哈希有效，但严格生产审计仍精确列出 9 个数据/真值 blocker。
- [x] ADR-019 strict 本机审计 10/10 通过；`docs/test_report_adr019_local_retirement.json` 已记录当前 native macOS Platform + Docker road9/Kafka 拓扑、MPS、Alembic `20260723_0019`、canonical Topic、旧存储未挂载及历史清库重建证据。
- [x] 明确项目不建设人工标注、预标注或标注工作包；xqh 自动化工程验收结论保持有效，IDF1/HOTA/ID switch/位置 RMSE/速度 MAE 统一列为“不评估、不宣称”，不再登记为项目待办。
- [x] 收尾同步 README、协作约束、项目结构、架构、业务逻辑、契约、ADR、任务、Runbook 与真实回归报告，统一 `local_engineering_acceptance_passed / production_accuracy_not_claimed` 口径。
- [x] 生成脱敏最终交接手册 `/private/tmp/TrafficAnalyzer-hover-cruise-final-handoff-2026-07-25.md`；只引用权威材料，不复制凭证或 `docs/road_pg.md` 内容。

## 2026-07-24 ByteTrack 前置纯图像关联与 ID 后世界投影

- [x] 用确定性两帧反例证明：图像、检测框和视觉 warp 不变，仅让第二帧 H 平移6m，旧世界关联会改变匹配与 ID。
- [x] 新增背景 `ImageMotionEstimator`，排除扩张后的检测目标区域，以 LK 前后向光流、RANSAC 和重投影门禁输出唯一 `camera_motion_warp`；不读取遥测、H 或地图。
- [x] 从 ByteTrack 删除世界位置、ENU Kalman、Mahalanobis 代价和 `world_positions` 接口；高低置信两轮只使用视觉补偿后 IoU、类别软约束、置信度和真实源时间。
- [x] 将主链拆为 `ImageMotion → GroundTrajectoryTracker(ByteTrack) → Homography/Motion/FlightGeoReference → PostTrackingWorldProjection`，代码级保证坐标转换只发生在 ID 确定之后。
- [x] 分离图像 `association_id` 与正式业务 `track_id` 生命周期：H/遥测/地图质量中断保留图像 ID、结束正式分段；恢复后用 `track_family_id/previous_track_id` 创建新正式 ID。
- [x] 同时保留源帧 `trajectory_px`、视觉递推 `trajectory_display_px` 和 ID 后逐帧 H 生成的 `trajectory_enu_m/trajectory_gcj02`；ShowNode 禁止用当前 H 重投影历史。
- [x] 将 `PostTrackingWorldProjectionNode` 收敛为新版唯一世界事实所有者：同一点完成去畸变、ENU/GCJ-02与地图覆盖；TrackerInfo只消费结果，后续H/锚点变化不能二次改写。
- [x] `hover_cruise_v1` 速度只使用至少3个逐帧ENU点，删除当前H重投影历史像素回退；`hover_only_legacy` 行为保持。
- [x] 新增 H 抖动不改 ID、ID 后世界点变化、节点顺序、质量断点、双 ID、漏检恢复、单一投影所有者、去畸变覆盖一致性、内部 ENU 全精度、速度坐标契约、图像尾迹与 EOF 测试；撤回标注包后当前根 `test/` 为 `139 passed`。
- [x] 完成同一 xqh 840s–EOF 的最终原生 MPS 重跑和旧世界关联版/image-v2 对比图：24/24工程门禁、三类轨迹对齐失败0、降级业务泄漏0、自然EOF通过。
- [x] Platform 为 `207 passed, 5 skipped, 1 warning, 10 subtests passed`；Console2 为 `139 passed` 且 production build 通过；xqh 基线维持 `56 PASS / 0 FAIL / 0 WARN`；ruff 与 `git diff --check` 通过。
- [x] 生成脱敏临时交接手册 `/private/tmp/TrafficAnalyzer-image-motion-tracking-v2-handoff-2026-07-24.md`，明确权威材料、复现命令、脏工作树、回滚和生产阻断。
- [x] ADR-019 strict 本机审计已补齐实时证据并达到 10/10；当前报告 schema 为 `uav.adr019-local-retirement/v2`。
- [x] 验收边界改为自动化工程门禁；项目不安排人工轨迹真值工作包，相关精度指标不进入交付承诺，也不得从无真值代理推导。

## 2026-07-24 检测输出轨迹几何与候选尾迹回归修复（历史阶段）

- [x] 用 `ShowNode.process` 最小复现“候选 ID 存在但输出视频没有尾迹”，确认根因是候选分支只画框并跳过 trace。
- [x] 正式轨迹保留类别色实线；候选轨迹保留原始像素历史，新增相机补偿的当前帧显示历史，绘制最多30点的琥珀虚线、紧凑 `#ID class C` 标签和一次性非正式图例。
- [x] 过滤空值、NaN/Inf、越界、重复、单点和大幅跳变；限制尾迹总显示长度，避免真实巡航画面出现跨屏蜘蛛网；不改关联、地图、地理参考或 TCC 阈值。
- [x] 显示缓存在Kafka发布前剔除，不改变 canonical candidate schema；覆盖候选、正式+候选混合、相机warp、异常点、跳变截断和30点上限。
- [x] 增加4K生产渲染缩放到1280×720的可读性红测，覆盖候选标签高度、单段虚线长度、强琥珀尾迹像素和右上角图例；避免只在4K原图上“看起来存在”、交付视频里实际消失。
- [x] 第一阶段根 `test/` 为 `87 passed`，Show/GroundTracker/Kafka/EOF/验收渲染组合为 `30 passed`，ShowNode聚焦测试为 `8 passed`；最终双坐标实现后的结果见下方99 passed门禁。
- [x] 真实 xqh 901–905 秒 MPS 短窗确认 30/30 帧有检测、3395 个检测、2022 次候选关联、降级业务泄漏0；生产 `ShowNode` 在901.134秒产生8188个候选尾迹差异像素且无跨屏蜘蛛网。
- [x] 第一阶段840秒至自然EOF的真实MPS复验通过20/20显示/隔离门禁；其检测和坐标指标已由下方最终24/24几何门禁报告取代，历史数字保留在回归报告历史小节。
- [x] 同一短窗 shadow 诊断中 pose-aware / legacy 分别为108/156个观测ID、首帧后新增ID 7/55、中位活跃帧19/1、中位活跃轨迹66/39.5；该结果只是不依赖真值的ID churn代理，不声明IDF1或ID switch达标。
- [x] 840–901秒稳定悬停的457帧同输入对照中，pose-aware / legacy 分别为401/439个观测ID、中位活跃帧34/18、首帧后新增ID221/306、中位活跃轨迹101.5/96、匹配框中位IoU 0.998075；未见旧版可用而新版大面积丢ID的代理信号。
- [x] 定位真实数据异常：macOS 15.6 + PyTorch 2.2.2 MPS 的 sliced `clamp_` 可把右边界框裁成零宽；同帧 MPS 原路径出现9个零宽框，CPU与MPS非原地裁剪为0。新旧 profile 共用安全裁剪和检测几何过滤，非法框阻断正式研判。
- [x] 冻结双坐标契约：源帧接地点 `trajectory_px`、同点 ENU/GCJ-02、源时间、源帧号、质量谱系逐点对齐；bbox中心单列 `trajectory_bbox_center_px`。该阶段用世界历史反投影显示，已由 ADR-023 的纯图像显示历史取代。
- [x] 移除正式轨迹对 `sv.TraceAnnotator` 隐式历史的依赖；正式/候选统一接地点与当前帧坐标，绘制层抑制小幅往返抖动但不改事实。
- [x] 修复长完成轨迹降采样遗漏新坐标字段；`TrajectoryNode` 同索引处理像素、bbox中心、ENU、GCJ-02、时间、帧号与质量谱系。
- [x] 最终根 `test/` 为99 passed，xqh为56 PASS / 0 FAIL / 0 WARN；840秒至自然EOF原生MPS为24/24工程门禁：1142帧、109899个合法检测、非法框0、active/completed/candidate对齐失败0、降级业务泄漏0、显示/世界残差P95 0.006px/最大0.007px。
- [x] 固化结果对比图 `docs/test-screenshots/xqh-hover-trajectory-before-after-880.jpg`、机器报告 `docs/generated/xqh-hover-departure-acceptance.json` 和可复现拼图脚本 `scripts/build_xqh_trajectory_comparison.py`。

本修复只恢复检测输出视频的候选尾迹可见性。没有人工真值时，IDF1/HOTA 不评估、不宣称；不能把可见尾迹解释为 ID 连续性精度已经得到证明。

## 2026-07-23 无人机巡航轨迹跟踪与悬停正拍融合

- [x] 拆分 YOLO 与 ByteTrack；ADR-023 已进一步把 ByteTrack 前移到逐帧地理参考之前。
- [x] 统一 SRT/JSON/MQTT 时间容忍、速度派生和共享飞行状态机。
- [x] 历史阶段实现过名为 `pixel_to_map_enu` 的动态绝对矩阵；2026-07-30 已统一为视频/SRT所有的 `pixel_to_world_enu`，地图不再提供世界矩阵。
- [x] 修复 active trajectory 使用当前 H 重投影历史像素的问题。
- [x] 接入 Kafka 动态质量、road9 FlightSegment/Pipeline 运行质量、Source/Mission/Pipeline 增量接口。
- [x] Console2 展示飞行阶段、五类质量、正式研判开关，并将候选轨迹显示为琥珀虚线。
- [x] 实现 RTSP 有界最新帧策略和 MP4 完整帧反压边界。
- [x] 增加 `hover_only_legacy` profile 业务回滚和旧计划迁移策略。
- [x] 增加 `uav.cruise-eval/v1` 评测器，覆盖 IDF1、HOTA、ID switch、位置/速度/车道及质量泄漏。
- [x] 增加证据先行采集包审计和三路口六 Mission 模板，校验素材哈希、4K29.97/30、Mission/帧 lineage、AGL/UAV地速分层及人工/RTK/雷达参考与校准；当前 xqh 机器审计明确保持 blocked。
- [x] 增加默认关闭、仅离线运行的 legacy ByteTrack shadow 对比；ADR-023 后输出 `uav.tracking-shadow/v2` JSONL 且不影响业务结果。
- [x] 使用当前单一世界投影代码对 `inter_xqh` 真实 MP4+SRT 的840s–自然EOF执行原生MPS工程复验：1142个采样帧、107603个合法检测、非法框0、稳态YOLO p95 164.21ms、完整单进程帧p95 264.439ms、正式帧视觉有效率100%、降级业务泄漏0；24/24工程门禁、JSON和四组生产ShowNode证据已刷新。
- [x] 历史阶段曾向量化世界 Mahalanobis；ADR-023 已完全删除世界关联代价，保留该记录只用于说明演进过程。
- [x] 修复 Mission Runtime Bundle 漏传 `registration_pose/camera_calibration/map_coverage_enu_m`，并按 `quality.source_map_version_id` 精确追溯衍生地图的上游 snapshot checksum；禁止“取最新快照”回退。
- [x] 本机 `road9` 已前向迁移到唯一 Alembic head `20260723_0019`；xqh verified registration 的位姿、相机哈希和 32 条 verified lane 覆盖已完成增量回填，重复 dry-run 为 `would_change=false`，未修改 H、车道或发布状态。
- [x] 收尾 current-state 文档并新增 `docs/runbook_hover_cruise_tracking.md`，固定 ByteTrack 节点、原生 MPS 验收、质量诊断、数据库幂等检查、业务回滚和生产门禁；临时交接手册仅引用这些权威材料，不复制敏感配置。
- [x] 明确本项目不交付人工标注/预标注工作包；后续新增巡航视频只进入自动化回放、质量隔离和运行稳定性回归。
- [x] IDF1/HOTA/ID switch/位置 RMSE/速度 MAE 因无人工/独立真值而不评估、不宣称；若未来由外部项目提供已批准真值，可选运行现有只读评测器，但本项目不负责生成或审核真值。
- [ ] 满足门禁与稳定观察期后删除 legacy `DetectionTrackingNodes` ByteTrack 路径。

当前发布结论：`local_engineering_acceptance_passed / production_accuracy_not_claimed`。本机 MPS 已证明真实尾段的吞吐、质量隔离和 EOF；离场段因速度/视觉/地图覆盖门禁仅作候选。项目不建设人工标注工作包，因此不声明 IDF1/HOTA、世界位置/速度精度或正式 12m/s 巡航支持。

> 最后更新：2026-07-25（xqh 尾部离场全链路 24/24 工程复验及 ADR-019 strict 10/10 通过；人工标注工作包不属于项目范围，生产准确率不作声明）

## 2026-07-22 测试目录整理

- [x] 将根目录 22 个 `test_*.py` 集中迁移到 `test/`，保留 `platform/tests/` 与 Console2 原有测试边界。
- [x] 增加 `test/conftest.py`，统一仓库根模块解析，并避免 pytest 自动执行脚本式回归和运行态 E2E。
- [x] 更新 UAT CI、开发命令、Docker 构建排除项和项目结构文档；测试分类与独立执行方式见 [`test/README.md`](../test/README.md)。

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
- [x] 本机 canonical 栈已前向迁移到唯一 Alembic head `20260723_0019`；Platform、显式 PostgreSQL/TimescaleDB、Console2、根回归和 `inter_xqh 56 PASS` 均复核通过；ADR-019 strict 当前本机证据 10/10 通过。
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
- [ ] I5-B：内部风险/监测/质量筛选、GCJ-02 bbox、搜索、offset/limit、422/503、REST 保留快照/有限重试和高德加载失败降级已实现；项目范围/KPI/权限、点位聚合/zoom、全局增量/断线缺口回补、获批正常/混合质量数据及 5 秒/30 秒正式验收仍待外部冻结。
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
- **状态**：🟡 部分解决 — 已添加 `test/test_pipeline_inter_xqh.py`（49项端到端检查）、`test/test_pipeline_no_yolo.py`（无GPU CI测试）、`test/test_e2e_inter_xqh.py`（端到端集成测试）、`scripts/inject_test_data.py`（WebSocket数据注入）
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
- **修复内容**：保留 sentinel 不携带普通帧字段的控制信号语义；`main_optimized.py` 检测进程在共享内存/`.frame` 访问前先识别并级联 `VideoEndBreakElement`。`test/test_main_optimized_eof.py` 固化首元素即 EOF 的回归，5GB `inter_xqh` + DJI SRT 在重启恢复后自然 EOF，Mission 持久化为 `completed/source_eof`。

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
| T-101 | KafkaProducerNode 异步发送 | ✅ | `nodes/KafkaProducerNode.py` — 独立发送线程 + Queue(maxsize=200)，Kafka 不可用时不阻塞管道；`test/test_kafka_active_trajectories.py` 覆盖 stats/track_complete/conflicts/telemetry 四类 topic 非阻塞入队 |
| T-102 | track/conflict 持久化到 InfluxDB | ✅ | `platform/app/utils/influx_query.py` — 新增 write_track_event/write_conflict_event/write_stats，冲突历史完整保留 TTC/PET、prediction_type、conflict_scene、evidence、risk_score 和预测位置；`platform/app/kafka/consumer.py` — 注入 influx_client 并在 handler 中调用写入 |
| T-103 | 遥测 Topic 发布 | ✅ | `nodes/KafkaProducerNode.py` — 新增 `telemetry_{N}` topic，5Hz 节流发布；`test/test_kafka_active_trajectories.py` 覆盖 telemetry 消息包含 `msg_type=telemetry`、`drone_id`、`intersection_id` 和遥测字段 |
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

> 下表保留历次实现事实；凡涉及 InfluxDB、OSM/OpenLayers、WGS84、道路 JSON 或旧频道的行均为
> 历史快照，已由 ADR-019/ADR-020 退役，不得恢复为当前运行时合同。

| ID | 任务 | 状态 | 修改文件 |
|----|------|------|----------|
| T-402 | motion_compensation.py 死代码 | ✅ | `utils_local/motion_compensation.py` — 3 个函数标记 deprecated + warnings.warn |
| T-403 | KafkaConsumer 自动重连 | ✅ | `platform/app/kafka/consumer.py` — 指数退避重连(5s→120s) |
| T-404 | InfluxQuery 字段名统一 | ✅ | `influx_query.py` + `trajectories.py` — trajectory_world_m 统一，反序列化 JSON 字段 |
| T-407 | 自动车道推断 | ✅ | `AutoLaneInferenceNode.py` + `auto_lane_inference.py` — 轨迹聚类→中心线→自动标签，无需人工标注 |
| T-408 | 方向分类 heading 精度修复 (P0) | ✅ | `trajectory_classifier.py` + `auto_lane_inference.py` — heading 窗口从固定5帧改为 n//2（平滑短轨迹噪声），最小位移阈值 10px |
| T-409 | 车道聚类合并阈值优化 (P1) | ✅ | `AutoLaneInferenceNode.py` — merge 阈值从 entry_exit_threshold_px 提升到 3.5x（420px），减少平行车道碎片化 |
| T-410 | U-turn 自引用标签修复 (P2) | ✅ | `auto_lane_inference.py` — 新增 OPPOSITE_CARDINAL 映射 + 自引用保护逻辑，消除"北→北 掉头"等不合理标签 |
| T-412 | VisDrone motor/non_motor 分类与小目标阈值修复 | ✅ | `TrackerInfoUpdateNode.py` — 优先按模型类别名分类，修复 `yolo11l-visdrone.pt` 下 tricycle/bicycle 被按 COCO id 误归为 motor 的问题；`configs/app_config.yaml` — 使用 `imgsz=1280/confidence=0.05/ByteTrack 0.05+0.01` 保留航拍电动车/三轮车低分候选；`test/test_refactor_unit.py` 增加类别映射与机非冲突回归测试 |
| T-413 | ShowNode 左上角幽灵框堆积修复 | ✅ | `ShowNode.py` — 绘制前裁剪/过滤异常 bbox，并仅显示道路 ROI 内或已分配道路的轨迹；`test/test_refactor_unit.py` 增加可视化过滤回归测试 |
| T-414 | 无道路标注参数启动支持 | ✅ | `VideoReader.py` + `main_optimized.py` + `main.py` + `configs/app_config.yaml` — `ROADS_JSON` 为空时使用空道路集运行，不再自动注入默认道路标注 |
| T-415 | 无道路标注模式左上角黑块堆积修复 | ✅ | `ShowNode.py` — 无道路标注时保留自动推断车道中心线/箭头，但关闭左上角车道统计黑底面板；`test/test_refactor_unit.py` 增加黑底像素回归测试 |
| T-416 | 机非分类配置化 + 监控冲突事件列表 | ✅ | `TrackerInfoUpdateNode.py` — 非机动车类别提取到 `vehicle_classification`，未配置类别默认机动车，摩托车/电动车归为非机动车；`ConflictDetectionNode.py` — 默认启用并支持 TTC 阈值触发；`traffic-fly-console/src/features/monitoring/index.tsx` — 监控页显示最近 20 条冲突事件 |
| T-417 | 页面发起 inter_xqh 全流程验证 | ✅ | `traffic-fly-console/src/features/video/index.tsx` — 视频分析页默认使用真实 inter_xqh 视频+SRT、动态匹配 PipelineManager 返回的 `camera_id`，MJPEG 加载失败后自动重试；`platform/app/services/pipeline_manager.py` — 支持 `PIPELINE_PYTHON`/`PIPELINE_FRAME_STRIDE`，空 `ROADS_JSON` 透传无道路标注模式，并用进程组停止检测器；已从页面启动并验证 Kafka → Platform WebSocket → 页面冲突列表 → InfluxDB 写入 |
| T-418 | 监控页冲突事件 BEV 回放 | ✅ | `traffic-fly-console/src/features/monitoring/` — 冲突事件列表可点击，BEV 叠加 motor/non_motor 回放层，支持播放/暂停/重放、倍速、3s/6s/10s 窗口和轨迹不足降级；回放动画状态已与实时轨迹刷新解耦，连续点击事件行会强制从头回放；列表按 motor/non_motor pair 合并重复消息；`platform/app/kafka/consumer.py` — Platform WebSocket 推送前也按 pair upsert，同级重复冲突不再广播，warning 可升级 critical |
| T-419 | TTC 冲突误报优化 | ✅ | `SpeedEstimationNode.py` — 输出世界坐标速度向量；`ConflictDetectionNode.py` — 曾改为相对运动最近点（CPA）算法，后续由 T-420 替代为未来轨迹预测口径；`test/test_refactor_unit.py` 增加冲突检测回归测试 |
| T-420 | 机非冲突未来轨迹预测口径修正 | ✅ | `ConflictDetectionNode.py` — 移除当前近距离触发，改为 `0-5s` 未来轨迹采样预测，并支持交叉路口路径交点到达时间差判断；同级 pair 不重复上报，`warning` 可升级 `critical`；`configs/app_config.yaml` — 新增 `prediction_horizon_sec` / `critical_horizon_sec` / `sample_interval_sec` / `arrival_time_tolerance_sec`；`test/test_refactor_unit.py` — 覆盖近距离不碰撞不上报、0-3s critical、3-5s warning、pair 去重、warning→critical 升级、交叉点到达时间差；`test/test_pipeline_inter_xqh.py` — 无道路标注 xqh 前100帧真实 YOLO+SRT 验证，冲突节点启用，当前 near-miss 证据漏斗下未产生擦边误报 |
| T-421 | xqh 机非冲突 near-miss 误报压制 | ✅ | `ConflictDetectionNode.py` — 在未来交汇候选后增加无标注轨迹几何场景门槛，仅保留疑似右转机非与疑似无保护左转；新增冲突角、PET、急减速、急转向、停止/让行证据漏斗，hard TTC 可直接触发，普通风险必须带避险证据；事件附加 `conflict_scene` / `conflict_angle_deg` / `pet_sec` / `evidence` / `risk_score`；`test/test_refactor_unit.py` 覆盖危险交汇但非专项场景不上报、右转 hard TTC 上报、普通风险无证据不上报、左转+急减速上报、pair 去重 |
| T-422 | TCC/冲突 BEV 回放轨迹错乱修复 | ✅ | `traffic-fly-console/src/features/monitoring/bev-trajectory-utils.ts` — 实时轨迹尾部快照按 `trajectory_tail_start` 替换重叠区，避免同一历史尾部因 H/运动补偿轻微漂移被追加成折返线；`conflict-replay-utils.ts` — 回放窗口以事件 motor/non_motor 预测冲突点附近截取，不再盲取轨迹最后 N 点；测试覆盖漂移尾部合并和事件附近回放截取 |
| T-423 | TCC 同刻擦肩/小折线误报压制 | ✅ | `ConflictDetectionNode.py` — 同刻 TTC 候选改为连续 CPA 最近接近点，并新增 `same_time_collision_radius_m=0.8m`，不再把 `collision_radius_m=2.0m` 内的横向擦肩直接当相撞；右转/左转场景新增 `min_turn_leg_m=2.0m`，避免短窗口小折线被误分为转弯；`test/test_refactor_unit.py` 覆盖最近距离约 0.9m/1.8m 且无有效 PET 交汇时不上报、机动车转弯腿不足不上报 |
| T-424 | Platform system WebSocket topic pattern 修正 | ✅ | `platform/app/core/config.py` — 默认 Kafka topic pattern 扩展为 `((statistics\|track_complete\|conflicts\|telemetry)_.*\|system_metrics)`，使 `system_metrics` topic 能进入 Kafka consumer 并广播到前端 `system` 频道；`docs/API_CONTRACTS.md` / `docs/ARCHITECTURE.md` / `docs/DATABASE_SCHEMA.md` 同步 WebSocket 端点与订阅契约 |
| T-425 | Platform 依赖不可用时降级状态修正 | ✅ | `platform/app/kafka/consumer.py` — Kafka bootstrap 失败时关闭已创建的 `AIOKafkaConsumer`，避免 unclosed consumer；`platform/app/core/database.py` / `platform/app/main.py` — `/ready` 根据真实 PostgreSQL/Kafka 初始化状态返回 healthy/degraded，启动日志区分 started/degraded；`platform/tests/test_kafka_consumer_stats.py` 增加失败启动回归测试 |
| T-426 | WebSocket 实时频道自动化验证 | ✅ | `platform/app/kafka/ws_manager.py` — 订阅/退订协议兼容 `channel` 单值和 `channels` 数组；`platform/tests/test_realtime_channels.py` — 覆盖 `intersection:{id}` stats/track/conflict、`telemetry:{drone_id}`、`system`、`alerts` 和 `alerts:{intersection_id}` 广播 |
| T-303 | Mission-Pipeline 绑定 | ✅ | `platform/app/api/v1/drones.py` — `POST /api/v1/missions` 创建任务时绑定无人机/路口并立即调用 PipelineManager 启动检测管道，响应写回 `pipeline_id` 与 pipeline 状态；启动异常时 mission 标记 `error` 并返回 `502`；`platform/tests/test_missions_api.py` 覆盖成功启动与异常落库状态 |
| T-427 | Platform 容器启动检测器依赖补齐 | ✅ | `platform/Dockerfile` — 平台镜像安装 `platform/pipeline-requirements.txt` 并通过 `platform/pipeline-constraints.txt` 锁定 `numpy<2`、`torch==2.2.2`、`torchvision==0.17.2`，避免 `POST /api/v1/pipelines` 启动 `/project/main_optimized.py` 时因缺少 `hydra` 等检测依赖直接失败或被新版 Torch/CUDA 解析拖重；`docker-compose.yaml` / `platform/docker/docker-compose.platform.yml` — topic pattern 同步包含 `system_metrics`；`platform/tests/test_pipeline_manager.py` 覆盖启动命令/环境变量、检测依赖覆盖根 `requirements.txt`、compose topic pattern |
| T-428 | TCC CPA/PET 证据混淆修正 | ✅ | `ConflictDetectionNode.py` — CPA 候选的 `pet_sec=0` 不再作为 PET hard 证据；只有 `ttc_sec <= hard_ttc_sec` 可直接触发 `hard_ttc_or_pet`，路径交点 PET 达阈值仅记录 `hard_pet` 并需叠加避险行为；机动车正常右/左转的 heading 变化不再计作避险急转向，仅非机动车突变可作为 `hard_steering`；`test/test_refactor_unit.py` 覆盖 CPA pet=0、PET-only 不触发、PET+避险触发 |
| T-429 | Platform 容器检测器日志修复 | ✅ | `platform/app/services/pipeline_manager.py` — Platform 拉起 `main_optimized.py` 时追加 `hydra/job_logging=disabled`，避免只读 `/project` 下 Hydra 文件日志 handler 写 `logs/app.log` 失败导致任务启动后立刻 `error`；`main_optimized.py` — multiprocessing 子进程重载日志配置时检测不可写 `FileHandler` 并降级到 console，避免 reader/tracker/show worker 因日志文件不可写退出；`platform/tests/test_pipeline_manager.py` / `test/test_refactor_unit.py` 覆盖启动命令与日志降级 |
| T-432 | TCC CPA 近距离擦边默认关闭 | ✅ | `ConflictDetectionNode.py` / `configs/app_config.yaml` — 默认 `enable_same_time_cpa: false`，默认业务口径只接受未来路径交点/PET 候选，避免 BEV 回放里 0.9m/1.3m/1.7m 这类仅中心点近距离、但无共同冲突点的轨迹被上报；CPA 保留为显式开启扩展，且仍受 `same_time_collision_radius_m=0.8m` 和 evidence 漏斗约束；`test/test_refactor_unit.py` 增加“路径交点在一方身后、仅 CPA 近距离”不上报回归测试 |
| T-433 | TCC PET-only 误报与回放红圈误导修正 | ✅ | `ConflictDetectionNode.py` — `PET<=1s` 不再单独生成 near-miss 事件，必须叠加急刹、非机动车急转向或停车/让行，压制截图中 TTC 2.x 秒、低 PET 但无避险行为的错位经过；`traffic-fly-console/src/features/monitoring/` — 冲突回放风险圈和距离辅助线锚定事件 `motor_position_m` / `non_motor_position_m` 的预测冲突位置，不再跟随两车当前播放点中点漂移；`test/test_refactor_unit.py` 与 `conflict-replay-utils.test.ts` 覆盖 |
| T-434 | TCC 预测方向使用最近轨迹段 | ✅ | `ConflictDetectionNode.py` — 有历史轨迹时，未来预测方向改用最近一个有效轨迹段，速度大小沿用 `SpeedEstimationNode` 的米/秒估计，避免线性回归测速方向在转弯/错位轨迹中制造虚假交点；`test/test_refactor_unit.py` 增加“历史轨迹方向与回归速度方向不一致时不上报”回归测试，单元测试 `52 PASS / 0 FAIL`，inter_xqh 前100帧真实 YOLO+SRT 仍为 `56 PASS / 0 FAIL / 0 WARN`、冲突 `0` |
| T-435 | Drones 页面 telemetry WebSocket 接入 | ✅ | `traffic-fly-console/src/features/drones/index.tsx` — 根据 `/api/v1/drones` 返回的无人机 ID 动态订阅 `telemetry:{drone_id}`，收到实时遥测后立即覆盖轮询兜底值；`traffic-fly-console/src/features/drones/index.test.tsx` 覆盖 `telemetry:drone_10` 消息更新纬度/经度/电量/悬停状态；当前前端回归 `npm test` 通过 27 个测试文件 / 160 个测试，`npm run build` 通过 |
| T-436 | Alert 持久化到 PostgreSQL | ✅ | `platform/app/models/alert.py` — 新增 `alerts` SQLAlchemy 表；`platform/app/services/alert_engine.py` — 创建/确认告警时写入 store，启动时加载已持久化告警，数据库不可用时保留内存降级；`platform/app/api/v1/alerts.py` — acknowledge 等待异步持久化结果；`platform/tests/test_alert_engine_persistence.py` / `test_alerts_api.py` 覆盖重启加载、确认状态持久化和 API await 行为，`python -m pytest platform/tests -q` 通过 |
| T-437 | TCC 业务口径字段与 CPA-only 回放过滤 | ✅ | `ConflictDetectionNode.py` — conflict 事件新增 `prediction_type`，路径交点事件显式输出 `path_intersection` 且 `distance_m=0.0`；`traffic-fly-console/src/features/monitoring/` — WebSocket conflict 入口过滤 `prediction_type=same_time_cpa` 的中心点擦肩旧/扩展事件，只保留 `path_intersection && distance_m≈0.0` 的路径交点，旧格式也仅当 `distance_m≈0.0` 时兼容，避免 0.9m/1.3m/1.7m 旧 CPA 或畸形 path 事件继续进入回放列表；`conflict-replay-utils.test.ts` 覆盖 path-zero/legacy-zero 保留与 CPA/legacy-near-pass/malformed-path 过滤 |
| T-443 | TCC 路径交点同一时空占用门槛 | ✅ | `ConflictDetectionNode.py` — 路径交点 PET 候选除到达时间差外，新增双方到达交点期间的连续同刻最小中心距校验，必须进入 `same_time_collision_radius_m=0.8m` 共同冲突区才上报，过滤仅数学射线相交、回放看不到同一时空碰撞概率的轨迹；`test/test_refactor_unit.py` 增加“路径交点到达时间差达标但同刻中心距离超过实际碰撞半径时不上报”回归测试，当前 `52 PASS / 0 FAIL` |
| T-445 | Console2 BEV 真实地图底图修复 | ✅ | `console2/src/components/MonitoringBevMap.jsx` + `console2/src/App.jsx` — 复用 Console 1.0 OpenLayers/OSM 地图模式替换静态 BEV 图片，按轨迹锚点将 ENU 世界坐标投放到主视图和右侧预览；无轨迹时保留真实路口地图且不生成模拟轨迹；`MonitoringBevMap.test.jsx` 覆盖 ENU 转换、路口中心回退和无效零坐标；使用 `inter_xqh` MP4+SRT、`ROADS_JSON=""` 启动 Pipeline `statistics_12`，浏览器验证检测器/BEV 主次切换和真实 MJPEG 输出；`test/test_pipeline_inter_xqh.py` 为 `56 PASS / 0 FAIL / 0 WARN`、100/100 帧检测与遥测有效 |
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
| T-470 | TCC 检测链路可解释性与历史回填 | ✅ | 修复 `test/test_refactor_unit.py` 正样本缺失 `max_speed_kmh` 的夹具问题；默认业务口径恢复为路径交点+同时空占用，CPA 仅保留显式实验扩展。检测节点输出完整漏斗诊断并随 `uav_stats` 发布，正式 `conflict_count` 排除 CPA；历史冲突 API 支持 SourceProfile/Pipeline/预测类型过滤，Monitoring 按当前视频源回填严格路径交点事件、与实时消息去重并明确显示 TCC/断线降级状态。新增检测、统计、API 与前端回归覆盖。 |
| T-471 | 冲突事件同步三图证据 | ✅ | 冲突产生时从同一 `FrameElement` 同步固化原始画面、检测器输出画面和同期轨迹还原画面；三项按固定 kind 顺序可靠发布并在一个 `EvidencePackage` 中事务登记，派生图回指原图。`/events` 详情按三类证据展示独立 SHA-256 缩略图，均可全屏、显式关闭、背景关闭和 Esc 退出；旧单关键帧事件保持可读。检测器、MetricStore 与 Console2 均新增回归覆盖。 |
| T-472 | 五源轨迹检测、回放与 TCC 全流程验收 | ✅ | 原生 MPS 对 `mp4new` 五源执行完整时间轴抽帧检测，5/5 返回码 0，Kafka/Road9 对账为 2,096 条 intersection Stats、7,373 条完成轨迹和 2,096 份 TCC 漏斗诊断。真实 Mission `MSN-0A894D610BBD` 产生 7 个严格 `path_intersection + distance_m=0` 事件、7 个 hash_verified 证据包和 21 张固定三图证据，停止后无活动 Pipeline。修复 Console2 离线监测不读取历史轨迹的问题，五源浏览器均恢复 500 条 SourceProfile-scoped BEV 轨迹；证据见 `docs/test_report_five_source_trajectory_tcc_full_flow_20260721.md`。 |
| T-473 | 实时监测浮层删除与 MJPEG 首帧自愈 | ✅ | 按浏览器批注删除监测画面中央“数据质量 · 实时/过期”浮层及其废弃样式；补齐 MJPEG 连接已建立但 8 秒内没有可解码首帧时的看门狗，使其进入既有 3 秒/最多 5 次重连流程，主视图与 BEV 侧预览共用同一恢复逻辑。`LiveModules.test.jsx` 覆盖浮层缺席、显式流错误和无首帧连接；production build、canonical Console2 镜像重建通过。真实 `SRC-MP4NEW2-CH-0715-PM` 浏览器验证 `/camera_13?retry=0` 为 1280×720、画面可见、浮层节点 0、console 0 error/warn。 |
| T-474 | Apple Silicon 原生 Platform 与 MPS 检测执行 | ✅ | Mac 开发态不运行 Docker Platform；`scripts/mac_local_platform.sh` 以用户级 launchd 启动原生 arm64 `.venv-mps` Platform，PipelineManager 通过本地 `start/inspect/stop` 子进程边界强制 `device=mps`、`imgsz=960`。根 Compose 去除 Mac 架构/remote agent 特例，仅作为生产发布拓扑。原生 Platform REST 实测 43 个样本 P50 238.7ms、P95 388.1ms，仅 1 个首轮长尾超过 2000ms；Platform 149 passed/5 skipped，验收后管道正常停止。决策见 ADR-020。 |
| T-475 | 本机事件证据全局恢复与持久化 | ✅ | 修复从容器 Platform 切换到原生 Platform 后 `uav_evidence_items` 仍在 road9、但 managed 对象留在 Docker `traffic_survey_data` 卷而导致所有事件图片 `409 evidence reference is missing` 的问题：非破坏恢复既有对象，本机启动脚本固定使用忽略版本控制的 `.runtime/survey`，不再回退 `/tmp`；最后 1 个历史 `event_keyframe` 从 Kafka 精确 topic/partition/offset 解码，并以 road9 记录的大小和 SHA-256 双重校验后恢复。全库 151/151 个去重对象通过路径、大小、哈希审计，三类冲突证据 HTTP 200/JPEG，浏览器 3/3 图片完成加载；原 Docker 卷保留。 |
| T-476 | TCC 事件证据展示语义调整 | ✅ | `/events` 三图证据保持原 kind、图片、哈希和接口不变，将 `conflict_detector_frame` 展示为“检测器输出的 TCC 画面帧”，将 `conflict_trajectory_reconstruction` 展示为“轨迹投放 BEV 视图”；标题、图片 alt、全屏按钮和弹窗无障碍名称共用新标签，`RouterApp.test.jsx` 覆盖显示与全屏交互。 |
| T-477 | 无人机回放卡片完整画面与悬浮控制 | ✅ | `/drones` 回放摄像头画面区改为随卡片宽度保持 16:9，移除固定高度与溢出裁剪；回放源、道路质量和播放/停止控制收进画面内渐变浮层，取消画面下方独立黑色控制区。路由交互测试与响应式 CSS 契约覆盖控制层级和画面比例。 |
| T-478 | 检测器视频地址登记与双屏直连 | ✅ | Pipeline 启动按 `PIPELINE_VIDEO_BASE` 登记 `video_stream_url`，外部 MPS runner 显式上报同一地址；Console2 `/monitoring` 与 `/drones` 共用该字段直连检测器 MJPEG，Vite 删除 `/camera_*` 代理。契约测试覆盖双屏 URL、缺失地址状态、外部登记与 Vite 禁止代理；本机真实流稳定性与浏览器验收见本次运行记录。 |
| T-479 | 监控历史态势真实性与查询性能修复 | ✅ | `GET /intersections/{id}/stats` 透传 `granularity`，历史查询改为类型化标量投影并每桶保留最新点，仅最后一点补读 TCC 诊断，避免 30 分钟查询反序列化约 190MB 审计 payload、耗尽连接池；真实 `SRC-MP4NEW2-CH-0715-PM` 请求由超时降至 0.362s、返回 4 个采样点。Console2 将虚构的“车型/货车”图改为真实 `direction_flow` 直行/左转/右转图，区分加载失败与真空数据，并移除无 SourceProfile lineage 的固定告警；浏览器确认两图可见、固定事件为 0、检测器直连图 1280×720。 |
| T-480 | 实时监测双侧栏缺省锁定 | ✅ | Console2 `/monitoring` 的“实时态势”与“BEV 与实时事件”侧栏初始即为展开且锁定状态，刷新或切换 SourceProfile 后保持可见；用户点击收缩仍会解除对应锁定并执行原有悬停展开逻辑。`LiveModules.test.jsx` 通过公开面板状态、`pinned` 样式和两个“取消锁定”按钮覆盖缺省行为。 |
| T-481 | 无人机回放源与悬浮按钮重叠修复 | ✅ | `/drones` 回放卡片把回放源、道路质量和启动/停止按钮收敛到同一个底部浮层网格：左列内容可收缩并省略长名称，右列按钮占独立列，三列/两列/单列布局均不再依赖相互竞争的绝对定位。浏览器逐卡测量 5 张卡片的下拉框与按钮均为 0px 重叠、10px 间距；路由交互与响应式 CSS 契约覆盖。 |
| T-482 | 轨迹研判升级：时间片 + 流向排名 + YOLO 原始分类 | ✅ | `/gis` 已改为最新可回放 30 分钟数据段、当前时间片世界轨迹、可切换排序的流向榜、双分类和代表轨迹联动；筛选/流向/时间片/页签可由 URL 复现。检测链保存 YOLO ID/name/model/mapping，`20260721_0014/0015` 增加类型化列与查询索引，分析 API 在 lineage-safe 去重后应用业务/YOLO/方向筛选，并提供冲突归因、转折与冲突点优先抽样及质量元数据。`road9` 四路口抽验 50,301 条完成事实、28,487 条唯一轨迹，默认时间片分别返回 24/18/50/14 条可移动轨迹；170 项 Platform、101 项 Console2、6 项消息契约、生产构建、四档响应式和同视口视觉验收均通过。证据见 `docs/test_report_trajectory_analysis_multi_intersection_20260721.md`。 |
| T-483 | 八源轨迹清理与原生 MPS 重跑准备 | ✅ | 新增只读 `platform/scripts/inventory_trajectory_replay.py` 与 4 项范围测试，复用 bootstrap 的八源 allowlist，输出事实、衍生事件、证据、Inbox 和活动任务影响面；当前盘点为 37,891 条轨迹、1,209,810 个轨迹点、95 个冲突、132 个证据包，活动 Mission/Pipeline 为 0。`docs/runbook_trajectory_data_reset_and_replay.md` 冻结清理/保留边界、备份与 Kafka Inbox 策略、MPS 门禁、重跑和回滚步骤。Platform 全量 174 passed；本轮未删除数据，当前 MPS available=false，恢复前禁止重跑。 |
| T-484 | GCJ-02 + 高德地图两阶段重建与技术演示收尾 | ✅ | 以固定白名单完成历史业务事实和受管 Kafka Topic 一次性清理，保留主数据、原始素材及 SHA-256；YCX 仅在本地缺路口时按需只读导入，WKT 由 PostGIS 解析，对象 ID 按不透明 geomhash 处理。四路口发布 4 个不可变 `lane_verified` 地图（31 Link / 104 本地车道），9 个 SourceProfile 具有独立 verified 影像配准；5 个来源自然 EOF 并固化为 completed Mission，共 13,042 条新轨迹。视频回归按用户决定以小清河北路 2 条轨迹样本收尾，空间一致性 100%，GCJ-02/ENU 最大往返误差 0.0068m；Console2 `/gis` 已在高德地图验证。技术演示完成，生产仍由道路标线人工签署、至少 100 条人工轨迹且车道匹配准确率 ≥95%、其余来源是否全跑和生产安全/容量门禁阻断。证据见 `docs/test_report_gcj02_two_stage_demo_20260722.md` 与 `docs/runbook_trajectory_data_reset_and_replay.md`。 |
| T-485 | 未绑定路网的演示检测启动 | ✅ | `/monitoring` 与 `/drones` 均不再用无人机 `default_road_data_version` 缺失禁用启动检测；任务页在缺路网时明确显示“道路未标定 · 仅检测/跟踪/遥测”，手动 Mission 请求省略不存在的 `road_data_version`。手动 Mission、PipelineManager 和检测子进程环境均允许无 Runtime Road Map Bundle 启动 YOLO/ByteTrack 与 MJPEG：缺图时不再把 `{}` 写入 `RUNTIME_MAP_BUNDLE_JSON`，并以 `road_context_status=missing`、`quality_status=unverified` 保持道路字段降级。Mission API 返回 `failed` 时监控页直接显示 `error_message/reason_code`，不再静默当作启动成功。ADR-025 经 2026-07-30 修订后明确：地图只控制 Lane ID、Link ID 与匹配质量；世界坐标由视频、相机参数和同步遥测逐帧计算。`RouterApp.test.jsx` 覆盖无 RoadContext 时按钮可用、降级文案和 Mission 提交契约；2026-07-29 真实 `/drones` 复验中 `SRC-E2BA6A8F6D0F` 与 `SRC-MP4728-JS-0728-7MS` 均为可启动且 Console 0 warning/error，Console2 `18 files / 149 tests`、production build 和 `git diff --check` 通过。此前浏览器实测 `SRC-MP4NEW-HY-0625-AM` 从按钮启动到检测器首帧、`LIVE 2.4 FPS`、MPS 推理约 145ms 和实时轨迹，验证后从任务页停止，恢复 0 个执行任务。 |
| T-486 | 监控页 BEV 历史轨迹闪烁修复 | ✅ | `console2/src/App.jsx` 对实时与历史 GCJ-02 轨迹集合保持稳定引用；`MonitoringBevMap.jsx` 使用完整绘制签名复用等价轨迹输入，页面时钟等无关重渲染不再每秒删除 500 条覆盖物、重新添加并执行 `setFitView`。`MonitoringBevMap.test.jsx` 覆盖结构等价的新数组不触发 `remove/add/setFitView`，`LiveModules.test.jsx` 同步覆盖 Mission 业务失败可见。浏览器地图复验当时被并行加入的安全密钥硬门禁阻断；该门禁后续由 T-487 改为可选。 |
| T-487 | 高德 JSAPI 浏览器直连 | ✅ | Web Key 是唯一前端硬门禁；`AMAP_SECURITY_JS_CODE` 改为可选，存在时设置 `window._AMapSecurityConfig.securityJsCode`，不存在时清除旧安全配置并仍调用 Loader。开发 Vite 暴露 `AMAP_*` 环境前缀并兼容 `VITE_AMAP_*`，生产 Compose 也不再要求安全密钥，二者均无 `/_AMapService` 代理。组件回归覆盖仅 Web Key 不得进入“高德地图服务不可用”；用户明确接受仅 Key 模式可能被高德警告或拒绝。 |
| T-488 | 检测器冷启动与 MJPEG 就绪竞态根治 | ✅ | 根因包含两段竞态：检测器 `VideoServer` 仅在端口完成绑定后输出 `MJPEG_READY`，Platform 默认等待最多 45 秒再把 Pipeline/Mission 标为 `running`；`run_platform.py` 改用 `os.execvpe` 让 launchd 直接拥有 uvicorn，`mac_local_platform.sh stop/restart` 等待端口释放，不再遗留多个连接同一 `road9` 的孤儿调度器误写 `pipeline_runtime_missing`。调度器另保留 15 秒瞬时缺失确认窗口；Console2 首轮 5 次 3 秒重连后改为每 10 秒持续自愈，不再永久锁死“视频流连接失败”。针对性生命周期回归、Console2 全量回归、生产构建和真实 Chromium 冷启动稳定性复验通过；当时既有的 GCJ-02 切片断言已由 T-489 修复并恢复 Platform 全量通过。 |
| T-489 | 轨迹研判连续回放与闪烁修复 | ✅ | `/gis` 相邻时间片请求使用同范围占位帧、串行推进和下一非空片预取，等待时保持当前轨迹并显示“加载下一片…”，自动播放跳过长时间空桶，末片点击播放从首个有事实时间片重开。`MonitoringBevMap` 先添加新覆盖物再移除旧覆盖物，且只在首次投放时缩放视口；分析 API 以同一索引裁剪 ENU/GCJ-02，修复“ENU 是当前片、地图却画整条轨迹”的契约偏差。真实 `/gis` 10 秒高频采样跨 3 次切片：0 次空地图、0 次 0 轨迹、0 次 iframe 重建，console 0 error/warn；Router/地图 48 项、Console2 全量 113 项、Platform 聚合 13 项与全量 182 项通过，production build 通过。 |
| T-490 | 测绘抽帧接入路口标注 | ✅ | 渠化标注页按当前 `inter_id` 筛选无人机绑定、已启用、`valid` 的本地 SourceProfile，要求操作员显式完成五项预检；`POST /calibration/lane-keyframe-extractions` 在同一数据库事务中创建 `lane_calibration` 测绘任务、落审计并把原视频/遥测不可变引用送入现有 `SurveyWorker` 队列。页面轮询 queued/processing 批次，关键帧具备 pixel→ENU 后直接进入既有标注与服务端拟合；接口支持幂等键并拒绝跨路口、非本地、禁用或无效来源。新增 Platform API 与 Console2 操作回归，完整门禁结果见本轮交付记录。 |
| T-491 | 路口建档、视频接入与渠化标注项目化 | ✅ | 新增稳定路口项目、视频接入任务、分段 SourceProfile 绑定和标定检查审计；同时提供视频优先与路口优先入口，按 1Hz/15s/俯角/半径/速度识别悬停，保留 WGS84 并以 GCJ-02 匹配本地 RoadContext。期望项目与候选不一致时返回显式冲突；Console2 新增项目库、项目工作台、发现确认、六项检查/退回/发布操作和编辑器深链，旧标定入口重定向且保留旧 `tab=lanes` 深链兼容。真实 XQH 路口优先链路已把 901 秒悬停段以 4.532m 高置信度绑定到项目，视频优先链路复用同一 `SIB-bedd6eedfa9e4ed5a34b28e4` 且不回退 published 阶段；基于 3840×2160 关键帧拟合 32 车道和 4 停止线，经 admin 六项检查发布 V2 `CMV-b83a25740598430bb996f75d`；V1 自动退役，Runtime Bundle 唯一命中新 V2。当前不扩展角色枚举。 |
| T-491 | 关键帧路网叠加与可拖拽拟合 | ✅ | 正拍编辑器用当前关键帧 pixel→地图 ENU 单应矩阵的逆变换，把地图 `geometry_enu_m` 车道面叠加为可开关参考层；越出影像的参考多边形先裁剪到自然图像矩形，点击后复制为拟合草稿，支持顶点拖拽与整车道平移且无首次边界跳位。真实浏览器发现源图矩阵误乘 `BEV view_transform⁻¹` 导致中心/比例错位，修复为 WGS-84→GCJ-02 后按地图锚点平移源图矩阵，比例由错误 `0.105` 恢复为 `0.04816 m/px`，水平/纵向路网与正拍道路对齐。已发布地图显式派生新草稿，避免不可变版本 409；正式落库仍由服务端统一执行 pixel→ENU→GCJ-02。 |
| T-494 | 路口项目工作台 B 方案视觉重构 | ✅ | 按选定 B 设计稿把项目概览与渠化编辑器统一重构为顶部项目栏、左侧路口档案/五阶段进度、中部五页签大画布、右侧待办/质量门禁/版本状态及底部唯一下一步动作的单屏工作台；保留真实关键帧、GCJ-02 路网、拖拽拟合、抽帧、检查发布和旧标定深链。编辑器仅加载当前 `inter_id` 的关键帧任务；地图详情水合避免摘要丢失 23 条车道，已有项目地图不会再被 bootstrap 竞态覆盖；`draft/candidate/lane_verified` 分别驱动真实阶段，素材面板默认收起，版本对比可切换真实历史版本，发布后的 CTA 正确进入 Runtime。当前项目草稿态与发布概览均完成真实浏览器对照；Console2 17 文件 127 项、Platform 201 项与 10 个子测试、XQH `56 PASS / 0 FAIL / 0 WARN`、生产构建和 `git diff --check` 通过。ADR-019 严格审计仅保留仓库级 `local_runtime_evidence` 外部门禁，不冒充发布绿色。验收证据见根 `design-qa.md`。 |
| T-495 | SourceProfile 抽帧 500 修复 | ✅ | 修复 `SurveyService.import_capture_batch()` 中服务器素材路径解析被错误缩进到参数缺失异常分支，导致合法本地 SourceProfile 抽帧在引用 `video_path` 时触发 `UnboundLocalError` 的问题；新增真实 `server_asset` 路径解析回归。崇华路与新泺大街项目浏览器复验由 500 恢复为 `201 Created`，批次 `BATCH-EA6BCB93577A` 进入 `ready`、生成 6 个关键帧，并成功载入 `FRM-C4DF19FD1CF8` 进入渠化画布。 |
| T-496 | Link 组车道编辑与拆分合并 | ✅ | 渠化画布单击车道默认按 `link_id` 选择并拖拽整组，双击切换为单车道顶点/平移编辑；工具栏新增“删除所选、拆分车道、合并车道”，拆分按多边形主轴中点生成同 Link 的两个合法多边形，合并以所选同 Link 车道的凸包生成可继续编辑的包络，衍生车道清空不再唯一对应的 `source_lane_id`。崇华路真实关键帧 `FRM-C4DF19FD1CF8` 浏览器实测 Link 组 3 条车道：整组选中与按钮门禁正确，单车道拆分 3→4、删除 4→3、合并 3→1；733px 中栏工具栏自动换行至 72px 且无横向溢出。Console2 18 文件 137 项与生产构建通过。 |
| T-497 | 实时 BEV SourceProfile 地图绑定与状态隔离 | ✅ | 根因是监控快速启动把无人机档案原始 `road_data_version=20260501` 写入 Mission，未命中 XQH 已发布 V2 SourceProfile 配准；同时旧 Platform 进程与 5 分钟历史 REST 快照覆盖实时轨迹状态，使右侧 BEV 始终显示 0。手动 Mission 现按 `inter_id + source_profile_id` 自动选择完整 `lane_verified` 地图，显式 map id 严格校验并冻结 map/version/registration/checksum/策略；无图仍允许检测器降级启动。Console2 分离历史/实时状态，历史刷新不再清空 WebSocket 轨迹；`uav_stats/uav_track_complete/uav_conflict` 必须匹配当前 `pipeline_id`，同源 Pipeline 切换会清空旧会话，解决旧 Pipeline backlog 再次把质量卡覆盖成 missing 的终验问题。候选 GCJ-02 路径以虚线投放，仅像素候选显示“地理投影不可用”。road9 和 Mission `MSN-DE5382C1C405` 均命中 `CMV-b83a25740598430bb996f75d / VRG-3351d2719cf74f1798ef0fc0`，Runtime 为 complete；原生 MPS Pipeline `pipe-30642be2` 运行中。真实浏览器右侧 BEV 从 3/11 条增长到 67 条，跨完整 REST 刷新周期未归零；加入 Pipeline lineage 门禁并热更新后仅保留当前质量，地图覆盖恢复为可信且仍有 125 条 GCJ-02 轨迹，Console 0 error/warn。候选轨迹始终隔离于正式统计/TCC。Console2 全量、production build、本次后端针对性回归与 `git diff --check` 通过；Platform 全量另有 2 个既有 ADR-019 脚本/测试合同漂移失败，未纳入本修复。 |
| T-498 | xqh TCC 检测器两图全链路实跑 | ✅ | 原生 MPS 用 `SRC-INTER-XQH-0403-PM`、真实 4K MP4/SRT 和 V2 `lane_verified` 地图完成当前 `hover_cruise_v1` 自然 EOF：730 stats、2,645 完成轨迹、正式 TCC 0，漏斗为 619 无合格候选/111 质量门禁阻断。运行器改为按 SourceProfile verified registration 选择最新不可变 Runtime Bundle，不再锁死 retired V1。显式 legacy 兼容回归 `pipe-6bf46bdb` 在 Docker 空间耗尽前由真实 Show 输出产生 2 条严格 TCC；释放 9.379GB 可重建 build cache 后 Kafka 恢复，road9 对账 2/2，4 个 managed JPEG 的大小/SHA/3840×2160 全通过。最新事件 `69971837e302c2074d6cce34ae803d49e27ad1db` 页面两图完成加载、检测图可全屏、Console 0 error/warn；legacy 批次因 KafkaConsumer fd 错误提前终止且页面质量明确 degraded，不冒充正式巡航 TCC。根 150、Platform 215/5 skipped/10 subtests、Console2 147、production build、ruff 与 diff check 通过。证据见 `docs/test_report_inter_xqh.md`。 |
| T-499 | xqh 轨迹显示与道路资格解耦 | ✅ | 根因不是 YOLO 配置回退，而是 `ShowNode` 在四级能力契约落地后仍用道路资格筛选成熟像素尾迹；成熟但无道路资格的轨迹会退入缺少显示载荷的候选分支。现改用 `trajectory_association_ids + track_id_by_association + trajectory_output_eligible` 驱动像素显示，无道路资格标 `P`、真正未成熟标 `C`，低地理质量不显示历史速度；验收器升级为 v2，要求质量断点保持图像 ID、road/TCC 分别零越界。真实 xqh 840s–EOF 原生 MPS `25/25`：107603 检测、跨离场保留 41 ID、三类对齐失败 0、road/TCC 泄漏 0、生产尾迹 59572 像素；根 171、聚焦 60、xqh 56/0/0。未回退 7 月 15 日后的算法能力，精度仍 `not_evaluated`。证据见 `docs/test_report_xqh_trajectory_display_regression_20260728.md`。 |
| T-500 | xqh ByteTrack 小目标 stride 硬门控回归 | ✅ | 7 月 28 日新增的固定 `dt=1` Mahalanobis 95% 硬门控与生产 `frame_stride=5` 不相容，10–15px 小目标正常位移会被拒绝并反复重建 ID。生产关联恢复为相机补偿后 IoU、置信度和类别软约束；Mahalanobis 仅在代价副本上写 shadow 诊断。`scripts/compare_xqh_bytetrack.py` 保证每个采样帧只跑一次 YOLO，再将同一检测输入喂给 7 月 15 日基线和当前 tracker。400–430s 原生 MPS 门禁 3/3：中心密度为基线 95.23%、碎片 ID 44、中位寿命 52；shadow 记录会拒绝 1080 个有效候选并使 671 条轨迹失去全部候选。完整 840s–EOF 25/25：1142 帧、109899 检测、61831 关联、自然 EOF、road/TCC 泄漏 0。无外部真值，精度仍 `not_evaluated`。 |
| T-501 | AGL 三档 imgsz、能力感知运行档与性能/TCC 口径 | ✅ | 已实现共享`AdaptiveImageSizePolicy`（640/960/1280、5点中位数、5m滞回、5帧稳定、2秒缺失回退），接入新旧检测节点；历史profile自动选择规则已由2026-07-30修订为默认cruise、仅显式legacy。Stats分开YOLO与整帧耗时并扩充TCC漏斗。xqh自然EOF 27/27，1142帧全为960、零切档。按授权只清空历史`uav_track_points/uav_track_events/uav_conflict_events/uav_conflict_reviews`后，崇华路v3原生MPS自然EOF：1299 stats、6302完成轨迹、56条严格`path_intersection`TCC、`invalid_tcc_events=[]`，88个唯一受管JPEG的hash/size全通过；积压归零后Kafka/road9精确一致为`1299/6302/56/2407`。对齐视频的AGL实际为156.35–178.15m，因首帧初始化1280且下切阈值为`<152m`，全程合法保持1280；原计划引用104–222m是整个遥测文件而非视频对齐窗口，不能作为三档切换证据。1280档YOLO p50/p95/max为371.4/1554.0/3990.6ms；xqh 960 p50=165.8ms，均未过100ms性能门。Platform慢消息消费改为单条poll、30分钟处理窗口；生产性能仍未达标，精度继续`not_evaluated`。 |
| T-502 | 悬停排队车辆轨迹生命周期与统计窗口解耦 | ✅ | 已删除 `TrackerInfoUpdateNode` 的 33 秒年龄淘汰，新增 active/mature/candidate/completed 显式视图、成熟单调诊断和 ShowNode 成熟 ID 直读；`CalcStatisticsNode` 用每 ID 一次的 30 秒道路入口事件窗口，候选已隔离于车辆数、速度、方向、车道、拥堵和 TCC。完成事件要求明确原因且按 `pipeline_id + track_id` 生成确定性消息 ID；legacy 超时也统一写入 `association_timeout` 帧级诊断并保持只完成一次。短时漏检、超过 2 秒关联丢失、源时间跳变、质量降级恢复、EOF、legacy 和候选业务隔离回归均通过；70 秒三车回归、根 `217 passed`、生命周期/业务专项 `85 passed`、Platform `233 passed / 5 skipped / 10 subtests`、Console2 `149/149` 与 build 已通过。新隔离 `pipe-fb1fa469` / Topic `6101` 原生 MPS 自然 EOF：881 stats、1210 完成、0 conflict、1964 telemetry 与 road9 精确一致，生命周期计数错位 0、成熟回候选 0、完成重复/缺原因/非确定性 ID 均为 0；33/35/66 秒有 61 个相同成熟 ID 连续存在。生产 ShowNode 成片和浏览器证据保存在 `output/playwright/xqh-*`。road9 只读审计另发现 6,403 个历史异常轨迹对（2,227 对重复、6,403 对至少一条缺终止原因），涉及 9 个旧 Pipeline，均不可用于正式统计且未回写。ADR-019 strict 的 9 项代码/拓扑检查通过，`local_runtime_evidence` 仍为外部门禁；精度指标无批准真值，继续 `not_evaluated`。 |
| T-503 | adaptive imgsz 全局默认与 xqh 小目标/连续性验收 | ✅ | 仓库配置、Platform 子进程和原生 MPS runner 统一默认开启 640/960/1280 AGL 自适应，旧环境开关不能静默关闭，固定尺寸仅保留显式诊断。`uav_stats.recognition_diagnostics` 与回放汇总新增合法检测、当前图像轨迹、未关联检测、`<=4096px²` 小目标分类覆盖；生命周期汇总把成熟 ID 回候选设为失败。`pipe-467f219e` / Topic 6301 以 stride10、adaptive 960、生产 ShowNode 完整自然 EOF：2975 帧、1696 stats、1766 完成、6 conflict、2769 telemetry；road9 排空后精确一致。1696/1696 帧有检测，YOLO/轨迹为 243887/143612，小目标为 151874/66688，非法几何 0；成熟回候选 0，1766 个完成 pair 全唯一且终止原因完整。根 220、Platform 236/5 skipped/10 subtests、Console2 149+build、xqh 55/0/1、ruff 与 diff check 通过；无批准真值，precision/recall/IDF1/HOTA/正式 ID switch 仍 `not_evaluated`。 |
| T-504 | xqh 检测-跟踪分层分析与小目标改进设计 | ✅ | 新增纯函数评估模块和只读 CLI，按类别、`<=4096px²`、飞行阶段、完整观测寿命和序列化点数生成 `uav.detection-tracking-evaluation/v1`。全量 xqh 表明稳定悬停总体/小目标工程覆盖为 60.50%/45.32%，离场降至 11.28%/4.77%；生命周期回退与重复完成均为 0，因此下一阶段聚焦检测关联 lineage、实际 dt/尺度软关联、高运动动态采样和预算受控 ROI 二次检测，不放宽全局阈值。修复类别切换待确认时逐帧类别名退化为数字的问题；旧产物的 11 个数字标签保留不回写。根测试 `223 passed`、专项 `49 passed`、xqh `55 PASS / 0 FAIL / 1 WARN`，Ruff 和 diff check 通过；ADR-019 九项代码/拓扑检查通过但既有 `local_runtime_evidence` 仍为 blocker。完整方案与验收矩阵见 `docs/ADAPTIVE_DETECTION_TRACKING_ANALYSIS_20260730.md`；正式精度继续 `not_evaluated`。 |
| T-505 | 整体配准浮层遮挡修复 | ✅ | 渠化画布的整体配准面板默认折叠为单行位姿摘要，主动展开后才显示 X/Y、角度、缩放、透明度和复位；折叠态 244×34px、展开态 270px，保留全部编辑能力并减少正拍证据图遮挡。Console 交互测试覆盖默认收起与展开可访问性。 |
| T-492 | BEV 轨迹覆盖物 SDK 引用修复 | ✅ | `MonitoringBevMap` 不再假设高德 Loader 会写入 `window.AMap`；地图初始化时保存 `loadAmap()` 实际返回的 SDK，并由轨迹覆盖物 effect 复用同一实例。回归测试精确覆盖“Loader 返回 SDK、全局变量缺失”时仍执行 `map.add`。用户停止检测器后保持停止；只读核对截图对应的 `pipe-a9d58965 / INT_camera_1 / SRC-E2BA6A8F6D0F` 为 `stopped` 且 `map_version_id=null`。最近统计中的 143 条活动轨迹具有 3,067 个有效 GCJ-02 点，但 `road_context_status=missing`、`quality_status=unverified`、0 条匹配车道，排除启用 `lane_verified` 路网参数。真实 XQH 历史切片 60 条轨迹已在高德底图可见。 |
| T-493 | 轨迹研判质量提示下沉 | ✅ | `/gis` 的限量、空间覆盖、降级证据、未归因冲突和去重提示整体移动到研判内容最底部；顶部统计卡、地图/流向侧栏和轨迹证据保持原顺序。DOM 回归锁定 `trajectory-quality-notices` 为分析页最后一个子区块；真实页面确认顺序为统计卡 → 工作区 → 证据 → 质量提示。Console2 `17 files / 125 tests`、production build 与 `git diff --check` 通过。 |
| T-438 | GIS 历史轨迹与冲突复盘 | ✅ | `traffic-fly-console/src/features/gis/index.tsx` — 选中路口后调用 `/api/v1/trajectories/{intersection_id}?period=1h&limit=200` 和 `/api/v1/trajectories/{intersection_id}/conflicts?period=1h&limit=200`，显示历史轨迹数量、Track ID、转向、车辆类型、均速、时长、轨迹点数，以及历史冲突 pair、TTC/PET、场景、证据和风险分；`traffic-fly-console/src/features/gis/index.test.tsx` 覆盖 `INT_camera_1` 历史轨迹与冲突证据复盘详情 |
| T-439 | Dashboard pipelines_active 真实数据 | ✅ | `traffic-fly-console/src/features/dashboard/index.tsx` — 首页活跃管道数优先使用 `system_metrics.pipelines_active` WebSocket 实时值，列表未加载时回退 `/intersections/summary.pipelines_active`，列表加载后使用 `/pipelines` running 数；`traffic-fly-console/src/features/dashboard/index.test.tsx` 覆盖 WebSocket 更新和 summary fallback；当前前端回归 `npm test` 通过 27 个测试文件 / 160 个测试，`npm run build` 通过 |
| T-430 | PipelineManager 正常结束状态修正 | ✅ | `platform/app/services/pipeline_manager.py` — 子进程 `return_code == 0` 时标记为 `stopped` 且清空 `error_message`，非零退出才标记 `error` 并保留 stderr 尾部；`platform/tests/test_pipeline_manager.py` 覆盖正常结束与异常退出两个状态分支 |
| T-431 | InfluxDB 历史统计自愈与查询修复 | ✅ | `platform/app/utils/influx_query.py` — 初始化时自动创建并切换目标 database，修复已有旧卷缺少 `influx` 导致写入 404；`query_stats()` 动态道路查询改为 `SELECT mean(*)` 并单独容错，避免 `SELECT * GROUP BY time` 导致历史统计整体返回空；`docker-compose.yaml` — 新增官方 `INFLUXDB_DB=influx` 初始化变量；`platform/tests/test_influx_query.py` 覆盖自动建库、已有库切换、动态 road 字段合并和 road 查询失败降级 |
| T-405 | `utils_local/utils.py` 单元测试 | ✅ | `test/test_utils_local.py` — 覆盖 `intersects_central_point()` 的道路内匹配、多道路返回正确 road id、道路外返回 `None`、边界点不算 inside 的 Shapely 语义，保护道路归属基础逻辑；`python -m pytest test/test_utils_local.py -q` 通过 3 个测试 |
| T-406 | ByteTrack 核心单元测试 | ✅ | `test/test_byte_tracker_core.py` — 覆盖高置信检测创建轨迹、保留检测类别 ID，以及第二帧低置信但 IoU 匹配的检测可延续同一 track id，保护航拍小目标恢复逻辑；`python -m pytest test/test_byte_tracker_core.py -q` 通过 2 个测试 |
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
- [x] 管道端到端测试（`test/test_pipeline_inter_xqh.py`，56 PASS / 0 FAIL / 0 WARN）
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

### GCJ-02 + 高德地图两阶段重建（2026-07-21）

- [x] Alembic `20260721_0016` + `20260721_0017`、GCJ-02/ENU 坐标工具、公共契约、路网/轨迹类型化字段和按 SourceProfile 唯一的视觉配准。
- [x] YCX 按需只读导入：PostGIS 解析 WKT、对象 ID 按不透明 geomhash、首路口 8 Link/32 候选完整性验证。
- [x] 高德 CityMap、Monitoring BEV、渠化编辑预览和运行时 Web Key 浏览器直连；安全密钥可选，Vite/Nginx 不提供高德代理，域名白名单仍为建议门禁。
- [x] 渠化地图版本、视觉配准、影像拟合、渠化要素编辑、发布质量门禁和 Runtime Bundle。
- [x] 补齐正拍 lane 拟合操作闭环：按路口选择事故测绘任务/采集批次/真实关键帧，幂等创建可恢复
  标注任务并自动带入 SourceProfile 与 pixel→ENU 变换；修复宽屏 `contain` 黑边导致的像素坐标偏移，
  增加顶点撤销和当前类型几何移除操作（2026-07-22）。
- [x] `RoadMapMatchingNode`、正式地图/轨迹研判的 `lane_verified` 门禁和顺序重跑工具；仅检测 Pipeline 在未绑定路网时允许以 `missing/unverified` 降级启动。
- [x] 修正正式轨迹坐标链：SourceProfile 精确配准在检测后首节点锁定；底部接地点逐帧累积
  ENU/GCJ-02，速度/方向使用逐帧 ENU 历史，车道匹配复用相同 H 与运动补偿。
- [x] 历史数据库/Kafka 清理，保留主数据和 20 个原始素材 SHA-256；62 个 Topic offset 为零。
- [x] 4 个注册路口完成正拍关键帧配准与技术门禁，发布 4 个不可变 `lane_verified` 版本；共 31 Link、104 本地稳定 Lane、9 个 verified SourceProfile 配准。生产人工签署单独保留。
- [x] 用户将视频回归范围调整为 2 条轨迹样本，不再等待 9 源全量结束。v3 前 5 源均自然 EOF、
  Kafka/数据库精确对账并固化为 5 个 completed Mission，共 13,042 条轨迹；第 6 源中止事实与
  Kafka 尾部补写已两轮清零并稳定为零。抽样 2 条空间一致性 100%，GCJ-02/ENU 最大往返误差
  0.0068m；Console2 已实测高德地图、GCJ-02 标签、Mission 和真实轨迹可见。证据见
  `docs/test_report_gcj02_two_stage_demo_20260722.md`。
- [ ] 生产发布仍需人工复核不少于 100 条轨迹、车道匹配准确率达到 95%，并确认是否执行其余
  4 源全量回放；当前技术演示结果不解锁生产门禁。

后续新增路口若出现系统性偏移，必须在渠化标注页面选择不少于 4 个分布合理的可复核控制点，
记录影像像素与已确认 GCJ-02 坐标，由服务端计算 pixel→ENU 单应矩阵并保存残差；不得从
Google Earth/WGS84 直接抄取坐标、不得在浏览器二次转换，也不得恢复 `app_config.yaml`
中的全局 `gcp.points` 兼容路径。

### 参数化路网标注对标升级（2026-08-03）

- [x] 固定正拍影像、统一覆盖层平移/旋转/等比缩放/透明度、数值复位和撤销重做。
- [x] Link/单车道/顶点兼容编辑；边界段三次 Bézier 控制柄与确定性 polygon 采样。
- [x] `registration_pose/v1` 服务端矩阵重算与漂移拒绝；旧 matrix-only/polygon 请求兼容。
- [x] `editor_model/v1` 四进口参数生成、实时车道数/宽度/角度联动、人工覆盖保护和重开像素几何。
- [x] `parameterized/freeform` 双模式；自由曲线和 Feature 保存后像素级复现，不虚构进口骨架。逐车道转向/公交/潮汐属性可编辑，专用 Runtime 规则仍明确未实现。
- [x] crosswalk/channelizing_island/waiting_zone/stop_line/lane_boundary/lane_marking 正式 Feature，影像叠加/干净渠化图共用同一 SVG 视口；Runtime Bundle 剔除编辑元数据。
- [x] 修复边缘车道只能向画面中间拖拽：现有 Lane/Link/顶点允许无损移出影像范围，新增绘制点仍受证据图约束；真实浏览器把右侧 Link 从 `maxX=3840` 拖到 `4731`，四点统一 `ΔX=891px/ΔY=0`。
- [x] 已发布版本通过服务端 `derive-draft` 生成可编辑草稿并记录不可变来源；Console 不再自行复制。接口测试覆盖发布不可变、姿态漂移、自交、同 Link 重叠、跨 Link 交叉、Feature 与来源链。
- [x] 崇华路 v2 候选以 23 条正式车道完成保存与同关键帧逐字符重载复现；页面保留残差字段、原始矩阵只读且视觉配准/人工复核未通过时发布按钮禁用。既有不可变 v1 `lane_verified` 仍为 23 条，Runtime Bundle 对账为 23 条且不含 `editor_model`；v2 为 `freeform` 且保存 23 条像素几何。控制点为空且无批准真值，未宣称生产精度（2026-08-03）。自动化门禁为 Console 166/166 + build、Platform 259 passed/5 skipped/10 subtests、相关根测试 42 passed、XQH 55 PASS/0 FAIL/1 WARN；ADR-019 仅保留既有 `local_runtime_evidence` 外部门禁。

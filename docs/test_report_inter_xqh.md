# 端到端测试报告：inter_xqh 视频 + SRT 遥测

> **当前范围说明（2026-07-28）**：`56 PASS / 0 FAIL / 0 WARN` 是算法/管道防回退证据；xqh 840s–自然 EOF 的最新 `25/25` 是原生 MPS 工程验收；本机 `road9`、`uav_*`、TimescaleDB 与旧链路退役由 ADR-019 strict 证明。项目不建设人工轨迹标注工作包，因此当前口径是 `local_engineering_acceptance_passed / production_accuracy_not_claimed`。

**最近复跑日期**: 2026-07-28
**测试资产**: `test_videos/inter_xqh/`  
- 视频: `DJI_20260403142902_0001_V小清河北路与水屯路路口.mp4` (5.4GB, 4K, 16.5min)  
- 遥测: `telemetry.srt` (29,741 条记录, 逐帧@30fps)

---

## 2026-07-27 TCC 告警与检测画面轨迹锚点回归验收

对比 7 月 13 日前后截图与 Git 历史后确认是两个独立变化。TCC 红/橙分级自提交
`04b5ff14`（2026-07-06）已存在：旧图的 `TTC 1.1s/0.8s` 为 critical 红色，新图的
`TTC 3.1s` 为 warning 琥珀色；提交 `2e9ca71b`（2026-07-13）只改变了标签透明度、
冲突目标之外的标签显示以及 TTC 徽章偏移方式。当前 `ShowNode` 已将正式 warning TCC 的连线、
端点与徽章统一改为红色，candidate 的琥珀虚线语义不变。

轨迹从车辆中部移到侧边的直接根因是提交 `40b73e8d`（2026-07-25）：旧
`supervision.TraceAnnotator` 默认使用 bbox `CENTER`，新图像历史把
`trajectory_px` 与 `trajectory_display_px` 都写成 `(bbox_center_x, bbox_bottom_y)`；该固定底边点在
横向或斜向目标上视觉上位于车身侧边。修复后 `trajectory_px/trajectory_enu_m/trajectory_gcj02`
继续使用底边接地点，只有渲染专用 `trajectory_display_px` 使用 bbox 中心并接受
`camera_motion_warp` 递推；无 association display history 的 legacy ShowNode 回退也使用
`TrackElement.trajectory_points` 中心。该修复不把显示坐标写入 Kafka 正式轨迹，不改变速度、车道、
TCC 或质量门禁。

TDD 最小复现先证明 bbox `[20,10,40,50]` 的业务点和显示点均错误为 `[30,50]`，修复后业务点
保持 `[30,50]`、显示点恢复 `[30,30]`。生产节点链
`GroundTrajectoryTrackerNode → PostTrackingWorldProjectionNode → TrackerInfoUpdateNode → ShowNode`
视觉验收进一步得到横向车辆业务接地点 `y=390`、显示中心 `y=360`，并在同帧看到红色
`TTC 3.1s` warning 告警；证据为 `output/visual-qa/tcc-track-center-restored.png`。

最终门禁：轨迹/ShowNode 聚焦 `29 passed`，根 `153 passed`，Platform
`215 passed, 5 skipped, 1 warning, 10 subtests passed`，真实 XQH 前 100 帧
`56 PASS / 0 FAIL / 0 WARN`，Console2 单 worker 全量 `147 passed` 且 production build 成功。
Console2 默认并行全量曾两次在未修改的 `LiveModules.test.jsx` 同一 5 秒用例超时；该用例聚焦复跑
1.14 秒通过，单 worker 全量 26.03 秒通过，因此记录为测试并发时序波动，不修改前端测试超时。
历史内容寻址关键帧保持字节不变，运行中的检测 Pipeline 需重启后才加载新渲染代码。

---

## 2026-07-25 xqh TCC 两图全链路实跑

本轮只使用 canonical SourceProfile `SRC-INTER-XQH-0403-PM`、真实 4K MP4、逐帧 SRT、发布地图
`CMV-b83a25740598430bb996f75d` 和原生 macOS arm64/MPS；未注入历史 Kafka 消息、未复用旧事件、
未降低 TCC 阈值。运行器原先按目录中的旧 `road_data_version` 精确找图，因 V1 已 retired 而被
Stage-1 正确拒绝；现改为从最新 `lane_verified` 地图开始，验证其是否包含当前 SourceProfile 的
verified visual registration，Pipeline 环境中的 road version 也以实际 Runtime Bundle 为准。
聚焦回归 `platform/tests/test_native_mps_replay_runner.py` 为 `15 passed`。

当前正式 `hover_cruise_v1` 运行 `native-mps-20260725T124558Z-SRC-INTER-XQH-0403-PM` 自然 EOF，
返回码 0，使用 `frame_stride=10 / imgsz=640`，产生 730 条 stats、2,645 条完成轨迹和 0 条 TCC；
730 份漏斗诊断为 `no_eligible_candidates=619 / quality_gate_blocked=111`，候选 pair、预测候选和
业务事件均为 0。该结果是正式巡航质量门禁下的合法零检出，不允许用 legacy 事件替代或称作正式 TCC。
机器输出位于 `output/native-mps/xqh-tcc-exact-show-20260725/summary.json`。

为验证用户指定的旧检测器关键帧兼容链，另以显式 `hover_only_legacy` 运行同一真实素材和 V2 地图。
Pipeline `pipe-6bf46bdb` 在 Kafka 故障前自然产生 2 条严格 `path_intersection` 事件；验收直采为
`tcc_event_count=2 / invalid_tcc_events=[]`。随后 Docker 内部磁盘满导致 Kafka 重启、验收 Consumer
报 `Invalid file descriptor`，因此该批次在约 494 个 stats 后提前终止，不能标为自然 EOF 通过。
删除 9.379GB 可重建 Docker build cache 后 Kafka 恢复 healthy；未删除任何卷、road9、Kafka 日志
或事件证据。Platform 恢复消费后，road9 对账出该 Pipeline 的 2/2 新事件。

最新事件 `69971837e302c2074d6cce34ae803d49e27ad1db` 为 TTC 3.11s、PET 0.08s、
`evidence_status=complete`，证据严格只有 `conflict_original_frame` 与 `conflict_detector_frame`。
两条事件共 4 个 managed JPEG，逐对象复算大小和 SHA-256 全部匹配，声明与解码尺寸均为
`3840×2160`。真实 Chromium 页面显示 `SRC-INTER-XQH-0403-PM / pipe-6bf46bdb / V2`，两图均
`complete=true / naturalWidth×naturalHeight=3840×2160`；检测图全屏可见实际检测框、轨迹、冲突
连线和 `TTC 3.1s`，Console 为 `0 error / 0 warning`。页面证据位于
`output/playwright/xqh-tcc-event-69971837-detector-fullscreen.png`。该 legacy 事件质量在页面明确为
`degraded`，仅证明“检测器实际 Show 输出 → 本地 managed 对象 → Kafka → road9 → Console2”证据链，
不升级为正式巡航业务结论。

本轮最终自动化门禁为：根 `150 passed`；Platform `215 passed, 5 skipped, 1 warning,
10 subtests passed`；Console2 `18 files / 147 tests` 且 production build 成功；系统 ruff 与
`git diff --check` 通过。`.venv-mps` 未安装 ruff，因此 lint 使用当前仓库环境可用的系统 ruff；
Kafka 与 road9 最终均恢复 `healthy`。

---

## 2026-07-25 TCC 检测器两图本地证据全流程复验

用户对比检测器原输出 `test_videos/videos_out/conflict_20260722_161459_critical_ttc0.2s_m82_nm3289.jpg` 后发现，上一轮页面的“检测器帧”实际是 `KafkaProducerNode` 在 `ShowNode` 之前另行重绘的图片，与检测器 `conflict_*.jpg` 不一致。因此原有 `960×540` 页面加载检查只证明结构可读，其“检测器真实输出”语义验收结论作废。

修复后 `KafkaProducerNode` 只冻结待发布 TCC 信封；显示进程复制绘制前原帧，再让 `ShowNode` 产生实际 `frame_result`，`TccEvidencePublisherNode` 按原尺寸/JPEG 95 固化两图后才可靠发布。`utils_local/event_evidence.py` 已删除所有目标框、标签、轨迹和冲突重绘逻辑；`VideoSaverNode` 保留原有 `conflict_*.jpg` 输出。精确像素回归证明 managed 检测图等于实际 `ShowNode.frame_result` 经同参数 JPEG 编码的结果，不存在证据侧重绘。

真实链路使用原生 macOS arm64/MPS、`hover_only_legacy`、`frame_stride=10`、`imgsz=640` 将 `SRC-MP4NEW-CH-0625-AM` 回放至自然 EOF。运行 `native-mps-20260725T115908Z-SRC-MP4NEW-CH-0625-AM` 返回码 0，耗时 1058.428 秒，产生 798 条 stats、4,005 条完成轨迹和 10 条 TCC；`invalid_tcc_events=[]`。10/10 事件共 20 个 managed JPEG，逐文件重算 SHA-256 与描述符全部一致，声明尺寸与解码尺寸全部一致，且全部为 `3840×2160`。机器输出位于 `output/native-mps/tcc-exact-show-20260725T115852Z/summary.json`。

本机 road9 已持久化该 Pipeline 的 10 条新事件。最新事件 `742e05c850094b00627e9b333e60c476bd4f7143` 为 `complete / 2 evidence_refs`；真实 Chromium 页面仅渲染“原始画面”和“检测器输出的 TCC 画面帧”，两图都是 `complete=true / naturalWidth×naturalHeight=3840×2160`。检测图全屏可见 FPS、真实目标框、轨迹、冲突 ID 和 TTC，与检测器原有 `conflict_*.jpg` 样式一致；浏览器 Console 为 `0 error / 0 warning`。页面证据位于 `output/playwright/tcc-exact-show-event-742e05c8-fullscreen.png`。

本轮自动化门禁为：根 `150 passed`；Platform `214 passed, 5 skipped, 1 warning, 10 subtests passed`；Console2 `18 files / 147 tests` 且 production build成功；Python ruff 与 `git diff --check` 通过。该验收证明本机开发闭环，不替代生产 MinIO、对象存储凭证、保留策略、HA、容量和灾备验收。

---

## 测试结果：56 PASS / 0 FAIL / 0 WARN ✅

2026-07-25 当前工作树复跑 `python test/test_pipeline_inter_xqh.py` 通过：`56 PASS / 0 FAIL / 0 WARN`。前100帧真实 YOLO+SRT 管道耗时20.1s（CPU），检测目标帧率100/100、累计8005个目标、遥测注入100/100、H矩阵100/100、运动补偿90/100、机非冲突事件数0。历史各轮检测数量受模型运行确定性影响，不能解释为ID精度变化。

## 路口项目、视频发现与渠化发布验收（2026-07-22）

- 路口项目 `IPR-1853f6704b79c593c892f8ea` 以路口优先路径接入 `SRC-INTER-XQH-0403-PM`；901 秒悬停段的 WGS84 中心为 `[117.022326, 36.702909]`，固定版本转换后的 GCJ-02 中心为 `[117.028267426, 36.703260199]`，距 RoadContext `011wwe0z19700001` 中心 4.532m，绑定质量为 `auto_high_confidence`。
- 同一素材再由视频优先任务 `VIJ-b4c364c26c894bea8cc7b164` 发现并绑定已有项目，返回同一绑定 `SIB-bedd6eedfa9e4ed5a34b28e4`；绑定总数保持 1，项目继续为 `published/revision 5`，证明两条入口汇聚且重复解析不会复制绑定或回退项目阶段。
- 把 XQH 素材按路口优先方式提交给解放东路与海右路项目时，任务 `VIJ-375a5278dda24d1eac418415` 返回 `409 video_intersection_mismatch` 并携带真实 XQH 候选；纯 MP4 任务 `VIJ-d6df8724330d4fd5aa5f34f0` 返回 `awaiting_confirmation/manual_unverified/telemetry_unavailable`，两类异常均未静默绑定或套用路网。
- 真实关键帧任务 `lane-011wwe0z19700001-FRM-4221C85DCB81` 使用 3840×2160 原图和 map ENU 单应矩阵；车道先裁剪到影像范围，再由服务端统一执行 pixel→ENU→GCJ-02，生成 V2 `CMV-b83a25740598430bb996f75d` 的 32 条 `imagery_fitted` 车道和 4 条停止线。
- 配准 `VRG-3351d2719cf74f1798ef0fc0` 已验证；4 个控制点重投影 P95 为 `7.105427357601002e-15m`，拓扑问题 0，方向、停止线、自交和重叠检查均通过。
- Console2 项目工作台由 `admin` 真实执行“提交检查 → 六项检查通过 → 发布 lane_verified”；审计记录 `CRV-3ea5a0e3073d4c97bed3a9ea` 保存六项全真清单、意见和 actor 1。空清单调用返回 `422 calibration_review_incomplete`。
- 发布后 V2 为唯一 `lane_verified`，V1 `CMV-1d3dedffa32145dca68c148d` 自动变为 `retired`；Runtime Bundle 返回 V2、GCJ02、转换版本 `wgs84-gcj02-local-enu/v1` 和 32 条车道。浏览器运行应用页命中新 V2，console error/warning 均为 0。
- 当时自动化门禁为 Platform `201 passed / 5 skipped / 10 subtests passed`、Console2 `17 files / 125 tests` 和 XQH `56 PASS / 0 FAIL / 0 WARN`；本段保留2026-07-22路口发布历史。当前总基线已提升为根 `139 passed`、Platform `207 passed / 5 skipped / 10 subtests`、Console2 `139 passed`，ADR-019 strict 本机审计 `10/10`。

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
**文件**: `test/test_pipeline_inter_xqh.py`
**问题**: 仅喂3帧但锚点需10帧，导致运动补偿始终为 None  
**修复**: 增加12帧预热阶段建立GPS锚点

### 改进: SRT 遥测支持
**文件**: `test/test_pipeline_inter_xqh.py`
**变更**: 从 JSON file 切换到 SRT 源 (source: "srt", time_offset: 0)

### 改进: xqh 机非冲突误报压制
**文件**: `nodes/ConflictDetectionNode.py`
**变更**: 默认 `enable_same_time_cpa=false`，业务口径只接受未来路径交点/PET 候选，避免 0.9m~1.7m 中心点擦肩经过被判成相撞；CPA 保留为显式开启扩展，且 `pet_sec=0` 不作为 PET hard 证据。右转/左转场景新增 `min_turn_leg_m=2.0m`，且机动车正常转弯 heading 变化不计作避险急转向。前 100 帧真实检测链路中 `conflicts=0`。

### 改进: PET-only 与回放红圈误导修正
**文件**: `nodes/ConflictDetectionNode.py`, `traffic-fly-console/src/features/monitoring/`
**变更**: `PET<=1s` 不再单独触发 near-miss；当 `TTC>1.5s` 时必须叠加急刹、非机动车急转向或停车/让行证据，压制 TTC 2.x 秒、轨迹错位但低 PET 的误报。BEV 冲突回放风险圈和距离辅助线锚定事件预测冲突位置，而不是两车当前播放点中点。

### 改进: 路径交点同一时空占用门槛
**文件**: `nodes/ConflictDetectionNode.py`
**变更**: 路径交点 PET 候选不再只看“预测射线相交 + 到达时间差”。双方到达交点这段时间内的连续同刻最小中心距必须进入 `same_time_collision_radius_m=0.8m` 共同冲突区，否则不上报；这会过滤回放中虚线/红圈看起来相交、但轨迹并无同一时空碰撞概率的样本。新增回归测试覆盖“到达时间差达标但同刻中心距离超过实际碰撞半径”场景；`test/test_refactor_unit.py` 为 `52 PASS / 0 FAIL`。

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
- `test/test_utils_local.py` 覆盖 `intersects_central_point()`：bbox 中心点落入不同道路多边形时返回正确 road id，落在所有道路外或多边形边界上时返回 `None`。
- 2026-07-02 utility verification：`python -m pytest test/test_utils_local.py -q` 通过 3 个测试。

### ByteTrack 核心单元测试 ✅
- `test/test_byte_tracker_core.py` 覆盖高置信检测创建轨迹、保留检测类别 ID，以及第二帧低置信但 IoU 匹配的检测延续同一 track id，保护航拍小目标连续跟踪能力。
- 2026-07-02 ByteTrack verification：`python -m pytest test/test_byte_tracker_core.py -q` 通过 2 个测试。

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
- `test/test_kafka_active_trajectories.py` 覆盖 KafkaProducerNode 在单帧处理中向 `statistics_*`、`track_complete_*`、`conflicts_*`、`telemetry_*` 四类 topic 入队，并校验统计、完成轨迹、冲突事件、无人机遥测的核心字段。
- 2026-07-02 Kafka producer verification：`python -m pytest test/test_kafka_active_trajectories.py -q` 通过 3 个测试。

---

## 2026-07-20 视频源对齐全链路复验 ✅

### 真实 Mission → 检测器 → Kafka → Console2

- 通过 `POST /api/v1/missions` 启动 Mission `MSN-3854893D6874`，绑定 SourceProfile `SRC-INTER-XQH-0403-PM`、无人机 `UAV-INTER-XQH`、路口 `INT_camera_1`、Pipeline `pipe-c79f5aef`、camera `14` 和 video port `8105`。
- Platform 统一镜像内出现一个 `main_optimized.py` 主进程和三个 worker；进程环境中的 `VIDEO_SRC`、`SOURCE_PROFILE_ID`、`INTERSECTION_ID`、`MISSION_ID`、`PIPELINE_ID`、`CAMERA_ID`、`VIDEO_PORT` 与任务绑定一致。
- Kafka 实际消费到 `uav_statistics_14` 的 `uav_stats/v1` 与 `uav_telemetry_14` 的 `uav_telemetry` 消息；二者均携带正确的 source、mission、pipeline、drone 和 intersection 标识，统计消息包含真实 YOLO11 / ByteTrack 检测结果。
- Console2 `/monitoring?intersection_id=INT_camera_1&source_profile_id=SRC-INTER-XQH-0403-PM` 精确选中该源，显示“实时分析中”，检测器图片地址为 `/camera_14`；工作台按 10 路已登记 SourceProfile 展示，并将运行源标为绿色。
- 调用 Mission stop 后返回 `cancelled/manual_stop`，Pipeline 返回 `stopped`；容器中无 `main_optimized.py` 或 worker 残留，`/ready` 为 ready 且 `pipelines_active=0`。刷新监测页后保持同一源选中并显示“监测离线”，工作台点位回落为青色可用离线。

### 自动化门禁

- `cd console2 && npm test -- --run`：15 个测试文件、83 个测试通过；`npm run build` 成功。
- `python -m pytest platform/tests -q`：142 passed、5 skipped、10 subtests passed。
- `python -m pytest test/test_kafka_active_trajectories.py test/test_utils_local.py test/test_byte_tracker_core.py test/test_main_optimized_batch.py test/test_main_optimized_eof.py -q`：12 passed。
- `python test/test_pipeline_inter_xqh.py`：56 PASS / 0 FAIL / 0 WARN；真实 4K 视频前 100 帧检测、遥测、H 矩阵均为 100/100，运动补偿为 90/100。
- `python scripts/audit_adr019_retirement.py --scope local --strict`、`docker compose config --quiet`、`git diff --check`：全部通过。

## 2026-07-25 xqh 尾部离场巡航全链路复验

按当前 ByteTrack 前置纯图像关联、ID 后单一世界投影代码，重新执行 xqh 840s–自然 EOF。该运行不复用旧报告，使用真实 4K MP4、逐帧 SRT、`yolo11s-visdrone.pt`、原生 arm64 MPS 和生产 ShowNode，并保留不影响业务结果的 legacy shadow。

| 证据 | 结果 |
|---|---:|
| 工程门禁 | `24/24` |
| 处理帧 / 检测覆盖 | `1142 / 100%` |
| 合法检测 / 非法框 | `107603 / 0` |
| 图像关联 / 唯一观测 ID | `60940 / 757` |
| 观测寿命中位 / P95 | `5.472s / 61.501s` |
| 正式 / 候选观测 / 完成正式轨迹 | `17545 / 43395 / 201` |
| active/completed/candidate 对齐失败 | `0 / 0 / 0` |
| 降级业务泄漏 | `0` |
| 正式帧视觉有效率 | `100%` |
| 候选末点/bbox接地点残差 P95 / 最大值 | `1.146 / 1.4px` |
| 源采样频率 | `7.4925Hz` |
| YOLO 稳态 P50 / P95 | `72.4 / 175.51ms` |
| 完整单进程帧 P50 / P95 | `176.205 / 270.401ms` |
| 自然 EOF / 代表截图完整 | 通过 |

飞行阶段观测为 `hover_candidate=124`、`hover_verified=345`、`unsupported_pose=241`、`cruise_nadir=432`。正式研判仅出现在悬停可靠窗口；离场画面继续检测并显示候选轨迹，但姿态、视觉变换和/或地图覆盖不满足门禁时不会进入速度、车道、统计或 TCC。质量断点结束正式轨迹 1 次，离开地图覆盖结束 264 次；三类轨迹均未发生点列错位。

四组生产 ShowNode 截图已人工核查：正式悬停轨迹和琥珀候选尾迹均可见，候选图例明确标注 `NO STATS-TCC`。坐标数据核验不是仅凭观感判断，而是同时要求候选末点与当前 bbox 接地点残差 P95 不超过 5px；本次为 1.146px。

仓库回归同时通过：根 `139 passed`；Platform `207 passed, 5 skipped, 1 warning, 10 subtests passed`；Console2 `139 passed` 且 production build 成功；xqh 固定基线 `56 PASS / 0 FAIL / 0 WARN`；改动 Python ruff 和 `git diff --check` 通过，后者只有既存 FrameElement CRLF 提示。Platform 首次从 `platform/` 子目录误执行导致根模块不在路径的9个收集错误，已按规范从仓库根目录重跑并全部通过，不计作代码失败。

机器报告和长期截图已刷新为 `docs/generated/xqh-hover-departure-acceptance.json` 与 `docs/test-screenshots/xqh-hover-departure-*-show-node.jpg`。严格精度证据审计仍为 `production_evidence_blocked`：只有1路口/1 Mission，缺完整三阶段、配置与 Runtime Bundle 哈希、场景覆盖以及身份/位置/速度独立真值，共9项缺口；它只用于约束“不宣称精度”，不再产生人工标注项目待办。ADR-019 strict 本机审计已补齐实时证据并达到10/10。

结论：xqh 尾部离场已经证明当前链路的检测、图像身份、后置世界投影、质量隔离、显示和 EOF 没有回退，状态为 `local_engineering_acceptance_passed`。它仍是姿态/地图越界的负向样本，不能产生 IDF1/HOTA/世界位置 RMSE/速度 MAE，也不能据此把生产签字从 `blocked` 改为通过。

## 2026-07-24 ByteTrack 前置纯图像关联最终回归

### 根因与架构修正

确定性两帧红测保持图像、检测框、类别、置信度和背景视觉 warp 完全相同，只把第二帧
pixel→ENU H 平移6m；旧 `pose_aware_world_v1` 会改变匹配结果。由此确认世界坐标误差已经越过
质量边界污染图像身份。ADR-023 将主链改为：

```text
ImageMotionEstimation → GroundTrajectoryTracker(ByteTrack image association)
  → Homography/MotionCompensation/FlightGeoReference
  → PostTrackingWorldProjection → TrackerInfoUpdate/traffic analytics
```

ByteTrack 现已删除 `world_positions`、ENU Kalman 与 Mahalanobis 代价，且公共接口不接受 H/ENU。
`association_id` 只表示图像身份；正式 `track_id` 是 ID 后通过地理参考和地图覆盖门禁的业务分段。
质量中断保留图像 ID、结束正式 ID，恢复后创建新正式 ID。ShowNode 只读取视觉 warp 递推的
`trajectory_display_px`，不再用当前 H 反投影历史。

### 测试与真实视频证据

首轮真实 MPS 重跑暴露“短时漏检后图像历史被清除、世界历史仍保留”的候选对齐失败
（6319次）。新增漏检一帧后同 ID 恢复红测，将图像历史生命周期改为跟随 ByteTrack
`tracked + lost` 状态；第二次全尾段重跑候选对齐失败归零。

| 证据 | 结果 |
|---|---:|
| 根 `test/` | `139 passed` |
| H 抖动/节点边界/双 ID/漏检恢复专项 | `18 passed` |
| 单一世界投影所有者/去畸变覆盖/ENU全精度/速度坐标契约 | `12 passed` |
| xqh 840s–自然EOF原生MPS | `24/24` 工程门禁 |
| 处理帧 / 原始检测 / 非法框 | `1142 / 107603 / 0` |
| 图像 association / 唯一观测ID | `60940 / 757` |
| 观测轨迹寿命中位 / P95 | `5.472s / 61.501s` |
| 正式 / 候选观测 / 完成正式轨迹 | `17545 / 43395 / 201` |
| active/completed/candidate 对齐失败 | `0 / 0 / 0` |
| 降级业务泄漏 | `0` |
| 稳态YOLO P95 / 单进程帧P95 | `164.21 / 264.439ms` |
| 自然EOF / 四张生产ShowNode证据 | 通过 |
| Platform | `207 passed, 5 skipped, 1 warning, 10 subtests passed` |
| Console2 / production build | `139 passed / 通过` |
| xqh 基线 | `56 PASS / 0 FAIL / 0 WARN` |
| ruff / `git diff --check` | 通过（FrameElement 仅有既存 CRLF 提示） |
| ADR-019 strict | 本机实时证据10/10通过；schema `uav.adr019-local-retirement/v2` |

在用户复核“世界坐标应位于 ByteTrack 之后”后又执行了一轮所有权审计：发现主顺序虽已正确，
`TrackerInfoUpdateNode` 仍会二次投影当前接地点，`SpeedEstimationNode` 仍保留当前 H 重算历史像素的
新版可达路径。新增公共节点红测证明后续 H 平移100m会把同一已投影点从 `(30,40)` 改写为
`(130,40)`，随后将去畸变、ENU/GCJ-02、地图覆盖统一收进 `PostTrackingWorldProjectionNode`；
TrackerInfo 只消费结果，内部 ENU 在速度回归前不做厘米量化，`hover_cruise_v1` 世界点不足3个时不输出正式速度。聚焦组合为
`47 passed`，当前根测试为 `139 passed`，xqh 前100帧仍为 `56 PASS / 0 FAIL / 0 WARN`；legacy
速度回退有独立测试保留。随后用当前代码重跑840s–EOF原生MPS：24/24工程门禁、三类点对齐失败0、
降级业务泄漏0、自然EOF通过；上表和仓库机器报告已经替换为该次结果。

生产证据审计另以完整 MP4 SHA-256 `342dea78…fcbc` 和 SRT SHA-256 `12ea683b…0ac`
固化 `xqh-current-cruise-evidence-package.json`。资产校验没有失败，但审计仍列出9个 blocker：
仅1路口/1 Mission、缺完整三阶段、Runtime Bundle/配置哈希、全部场景覆盖及身份/位置/速度独立真值。
这把“文件确实存在”和“可用于生产准确率签字”分开；机器报告为
`docs/generated/xqh-current-cruise-evidence-audit.json`。

历史同输入 world-aware-v1/image-v2 对比记录仍为唯一观测 ID `984→747`（-24.1%）、总关联
`73406→61908`；它用于说明废止世界关联时的方向性变化。当前单一投影所有者重跑为757个唯一ID、
60940次关联、中位寿命5.472秒，因MPS检测输出总数不同，不能把两轮差值解释为新的算法优劣。
这些都只是 churn 代理，不是 IDF1/HOTA 或 ID switch 真值。
机器对比见 `docs/generated/xqh-world-aware-v1-vs-image-v2.json`，同帧可视对比见
`docs/test-screenshots/xqh-hover-world-aware-v1-vs-image-v2-880.jpg`。

工程结论：`local_engineering_acceptance_passed / production_accuracy_not_claimed`。xqh 离场仍是
姿态/地图质量负样本，没有正式巡航帧。项目不建设人工标注工作包，因此 IDF1/HOTA、位置RMSE、
速度MAE和12m/s生产精度均记为不评估、不宣称，而不是后续项目待办。

## 2026-07-23 巡航/悬停融合实现回归（ADR-021 历史基线）

本轮将 ByteTrack 从进程 1 的组合检测节点移到进程 2 的 `FlightGeoReferenceNode → GroundTrajectoryTrackerNode` 边界；现有 `inter_xqh` 继续使用 `hover_only_legacy` 行为基线验证悬停回归，新模块使用独立行为测试验证。结果如下：

| 门禁 | 结果 |
|---|---:|
| 新增飞行状态、动态地理参考、位姿感知跟踪、离线 shadow、类别跨组确认、遥测时间/GPS/偏航边界、RTSP最新帧、Kafka候选隔离、评测器及 EOF 完成测试 | `45 passed` |
| 根 `test/` pytest | `79 passed` |
| Platform 全套 | `207 passed, 5 skipped, 10 subtests passed` |
| Console2 全套 | `139 passed` |
| Console2 production build | 通过 |
| `test/test_refactor_unit.py` | `52 PASS / 0 FAIL` |
| `test/test_pipeline_inter_xqh.py` | `56 PASS / 0 FAIL / 0 WARN` |
| Alembic head | `20260723_0019` |
| Alembic `20260722_0018 → 20260723_0019` 离线 SQL | 通过 |
| xqh registration lineage 重复 dry-run | `changed=false, would_change=false` |

`inter_xqh` 前 100 帧仍为 CPU 回放：100/100 帧有检测、100/100 遥测、100/100 H 有效、90/100 运动补偿有效；该素材移动尾段是姿态越界负样本，不能替代稳定近正射巡航生产正样本。新增自然 EOF 测试确认最后活跃正式轨迹以 `natural_eof` 完成，且像素、ENU、时间和质量谱系点数对齐。

ADR-019 strict local 审计已以当前 native macOS Platform + Docker road9/Kafka 运行证据达到10/10。巡航当前只作自动化工程验收；项目不创建人工标注工作包，缺少独立真值意味着精度指标保持 `not_evaluated`，不影响已通过的质量隔离、坐标对齐、吞吐和EOF结论，也不能据此宣称12m/s生产精度。

## 2026-07-24 MPS 检测几何与双坐标轨迹最终复验

用户反馈的异常线条包含两层问题：候选尾迹第一阶段确有漏画，但恢复显示后仍存在真实轨迹数据异常。880.046秒同帧诊断中，大部分候选显示/ENU反投影残差低于2px，但最大达到322.825px；57条候选中20条为静止/慢速目标的往返抖动线。继续下钻到YOLO输出，MPS FP16和FP32均出现9个 `[x1=2160,x2=2160]` 零宽框，CPU为0；把Ultralytics裁剪切换为非原地赋值后MPS也为0。根因是旧PyTorch MPS sliced `clamp_` 的静默错误，不是FP16精度或ShowNode颜色样式。

该历史阶段修复同时覆盖数据和展示：DetectionNode与legacy节点共用安全MPS裁剪/非法框过滤；非法框以 `invalid_detector_geometry` 阻断正式帧。正式/候选轨迹的canonical `trajectory_px`统一为源帧车辆接地点，与ENU、GCJ-02、时间、帧号和质量谱系一一对齐；bbox中心另存 `trajectory_bbox_center_px`。当时 ShowNode 曾使用世界轨迹反投影生成当前帧坐标；该显示方案后来已被 ADR-023 的背景视觉 `trajectory_display_px` 完全取代，当前代码禁止 ShowNode 读取 H。小幅往返抖动只在绘制副本中简化，事实数据不变。长轨迹降采样也按同一索引处理全部坐标与lineage。

最终验证：

| 证据 | 结果 |
|---|---:|
| 根 `test/` | `99 passed` |
| xqh 基线 | `56 PASS / 0 FAIL / 0 WARN` |
| 840s–自然EOF原生MPS | `24/24` 工程门禁 |
| 处理帧 / 检测覆盖 | `1142 / 100%` |
| 原始/合法检测 / 非法框 | `109899 / 109899 / 0` |
| active/completed/candidate 对齐失败 | `0 / 0 / 0` |
| display/world残差 P95 / max | `0.006 / 0.007px` |
| 末点/bbox接地点残差 P95 / max | `1.163 / 1.513px` |
| 降级业务泄漏 / 自然EOF | `0 / 通过` |
| YOLO稳态P95 / 单进程帧P95 | `284.61 / 750.59ms` |

机器报告见 `docs/generated/xqh-hover-departure-acceptance.json`；同一xqh约880秒修复前后图见 `docs/test-screenshots/xqh-hover-trajectory-before-after-880.jpg`。修复前面板来自用户指出异常的旧生产ShowNode输出，修复后面板来自最终完整验收；图上标注的322.825px与0.006/0.007px均来自坐标诊断/机器报告。工程结论为 `local_engineering_acceptance_passed / production_accuracy_not_claimed`，仍不声明无人工真值的IDF1/HOTA或12m/s生产支持。

## 2026-07-24 候选轨迹尾迹显示第一阶段复验（历史）

问题被压缩为经过真实 `ShowNode.process` 和 supervision 渲染器的确定性用例：同一候选 ID 已具有 3 个像素历史点，改动前候选框正常但历史点之间没有任何琥珀尾迹像素；正式轨迹在同条件下有尾迹。根因是候选分支在构建正式 `sv.Detections` 前 `continue`，之后只调用候选框绘制。

本节记录第一阶段“恢复候选尾迹可见性”的历史结论；其 `camera_motion_warp` 递推和正式 `sv.TraceAnnotator` 方案已被上一节双坐标最终实现替代。候选琥珀样式、紧凑 `#ID class C` 和统一图例保留，显示缓存仍不会进入Kafka、`buffer_tracks` 或任何正式质量门禁。

| 验证 | 结果 |
|---|---:|
| `test/test_show_node_class_colors.py` | `8 passed` |
| Show + GroundTracker + Kafka + EOF + xqh验收渲染组合 | `30 passed` |
| 当时根 `test/` | `87 passed` |
| `test/test_pipeline_inter_xqh.py` | `56 PASS / 0 FAIL / 0 WARN` |

新增公开接口可读性测试在真实 `ShowNode.process` 上渲染3840×2160画面，再缩放到1280×720交付视口；门禁要求候选标签可见高度至少12px、单段虚线至少7px、强琥珀尾迹像素不少于80且统一图例强琥珀像素不少于1000。该测试依次捕获了“标签仅4px”“尾迹强像素为0”和“无统一图例”三个红态，再在最终实现中转绿。

另以真实 xqh 901–905 秒、stride=4、原生 MPS 执行30帧短窗复验：检测覆盖100%，总检测3395，候选关联2022，正式关联0，降级业务泄漏0，active/completed点对齐失败0。验收器通过生产 `ShowNode.process` 分别开启/关闭尾迹，在901.134秒代表帧测得8188个候选尾迹差异像素；相机补偿和跳变/总长度截断后，截图不再出现跨画面蜘蛛网。短窗报告与截图为 `/private/tmp/ta-candidate-replay-final/acceptance.json` 和 `/private/tmp/ta-candidate-replay-final/screenshots/*-show-node.jpg`；该窗口只验证离场候选链和隔离，因不包含完整悬停窗口而按设计不能通过完整工程门禁。

同一30帧、同一检测输入的 shadow 诊断用于把“尾迹没画”与“ID真的重置”分开：pose-aware / legacy 的观测ID数为108/156，首帧后新增ID为7/55，中位活跃帧为19/1，中位多帧跨度为3.871/2.269秒，中位活跃轨迹为66/39.5，匹配框中位IoU为0.724。它没有显示新版关联更差的代理信号，但没有人工真值，因此这些数字不是IDF1、HOTA或正式ID switch结论。

另对840–901秒的457个稳定悬停采样帧使用同一批检测输入比较 pose-aware 与 legacy shadow：总检测71589、pose-aware关联52794；双方观测ID数401/439，中位活跃帧34/18，首帧后新增ID221/306，中位活跃轨迹101.5/96，匹配框中位IoU为0.998075。880.046秒代表帧为102/93条活跃轨迹，其中80对框的中位IoU为0.9976。该无真值代理表明悬停正拍的新版关联没有出现相对于旧ByteTrack的大面积退化，用户看到的“标签和轨迹线消失”主要来自候选渲染分支；它仍不能替代人工标注的IDF1/HOTA。

## 2026-07-23 xqh 后半程悬停 + 离场 MPS 工程验收

执行 `scripts/accept_xqh_hover_departure.py`，输入真实 4K MP4、逐帧 SRT、SourceProfile `SRC-INTER-XQH-0403-PM`、map `CMV-b83a25740598430bb996f75d`，窗口 840s–自然 EOF，stride=4（源采样 7.4925Hz）。运行使用原生 arm64 `.venv-mps`、生产 `yolo11s-visdrone.pt@9679a16c7c2b`、imgsz 960、FP16，并旁路运行 legacy ByteTrack shadow。

| 证据 | 结果 |
|---|---:|
| 处理帧 / 检测覆盖 | 1142 / 100% |
| 总检测 / 平均每帧 | 109899 / 96.234 |
| 稳态 YOLO p50 / p95 / max | 113.4 / 284.61 / 618.6ms |
| 完整单进程帧 p50 / p95 | 330.197 / 750.59ms |
| 遥测覆盖 | 100% |
| 正式帧 / 正式帧视觉有效率 | 344 / 100% |
| 正式 / 候选轨迹观测 | 13169 / 60237 |
| 降级轨迹进入正式统计或 TCC | 0 |
| active/completed/candidate 点对齐失败 | 0 / 0 / 0 |
| 非法检测框 | 0 |
| display/world残差 P95 / max | 0.006 / 0.007px |
| 完成轨迹 / 自然 EOF | 134 / 通过 |
| 质量断点终止 | `mode_transition_quality_break=2` |
| 生产ShowNode轨迹尾迹 | 悬停/质量断点/离场/降级四帧均非零（62439/14187/30029/14767像素） |

正式研判窗口为 855.088–900.867s；901.0s 起到源视频自然结束 992.358s 全部关闭。离场仍检出并关联候选目标，但因速度、视觉变换和/或地图覆盖不满足门禁，不产生正式业务结果。`transition` 标签未出现：901.134s 先进入 `unsupported_pose`，验收按安全质量断点与正式轨迹终止判断通过，不将越界姿态平滑成巡航。

工程门禁 24/24 通过，其中检测几何、三类轨迹点对齐、两项坐标残差和 `candidate_output_trail_rendered` 均直接经过生产链。报告见 `docs/generated/xqh-hover-departure-acceptance.json`，生产渲染证据见 `docs/test-screenshots/xqh-hover-departure-*-show-node.jpg`。结论统一为 `local_engineering_acceptance_passed / production_accuracy_not_claimed`（机器报告字段为 `production_release_gate=engineering_only_accuracy_not_claimed`）；没有人工真值，未声明 IDF1、HOTA、世界位置 RMSE、速度 MAE 或正式 12m/s 巡航支持。

---

## 2026-07-28 xqh 轨迹显示回归前向修复

相对 7 月 15 日的观感退化未定位到 YOLO 配置：提交 `23252d662b49a9c2c08de24bb98f71d091e41f6c` 与当前仍使用 `yolo11s-visdrone.pt / confidence=0.05 / imgsz=960 / frame_stride=5`。根因是四级能力契约已经把图像轨迹、地理、道路和 TCC 分开，但 `ShowNode` 仍用道路资格 `formal_track_ids` 决定成熟像素尾迹是否可见，导致无道路资格的成熟轨迹被折叠为候选，且在候选显示载荷缺失时不画尾迹。

本次只做前向修复：成熟像素轨迹改由 `trajectory_association_ids + track_id_by_association + TrackElement.trajectory_output_eligible` 驱动；道路资格不再过滤像素框/尾迹；无道路资格的成熟轨迹显示类别色实线和 `P`，真正未成熟预览仍为琥珀 `C`。低地理质量帧不显示历史速度。验收器同步改为检查图像身份跨质量断点保持、road/TCC 各自零越界，不再要求画质中断时终止 ID，也不把通用计数或像素 buffer 误报成泄漏。

最终真实 4K MP4+SRT、840 秒到自然 EOF、stride 4、原生 MPS 验收为 `25/25`：1142 帧检测覆盖 100%，107603 个检测、非法框 0，跨离场保留 41 个稳定 track ID，active/completed/candidate 对齐失败均为 0，candidate 落地点残差 P95/max 为 0/0px，road/TCC 泄漏为 0/0，质量断点生产尾迹差异像素 59572，自然 EOF 通过。聚焦回归 `60 passed`、根 `test/` `171 passed`、xqh 基线 `56 PASS / 0 FAIL / 0 WARN`。

完整根因、同帧前后图、修复边界和精度声明见 `docs/test_report_xqh_trajectory_display_regression_20260728.md`；机器报告见 `docs/generated/xqh-trajectory-display-acceptance-20260728.json`，对比图见 `docs/test-screenshots/xqh-trajectory-display-accepted-20260728/comparison-before-after.jpg`。未回退 7 月 15 日后的图像运动补偿、图像优先 ByteTrack、世界投影、地图匹配或 TCC 能力。没有人工真值，IDF1/HOTA、正式 ID switch、位置 RMSE、速度 MAE 与 12m/s 精度仍为 `not_evaluated`。

---

## 2026-07-29 ByteTrack 固定时间步硬门控回归修复

在 7 月 28 日显示解耦完成后，继续针对用户指出的“路口中心真实轨迹仍明显减少”执行同检测输入
差分。新增的 Kalman/Mahalanobis 95% 硬门控使用固定 `dt=1`，与生产默认 stride=5 不相容；
10–15px 高的小目标在一个处理间隔内正常移动 3.36–5.04px 即会越门。最小回归直接复现第二帧
输出为空，解释了单帧仍有检测框但成熟尾迹大量变短的现象。

修复保持图像运动补偿、类别软约束、大目标初始化、2 秒真实时间和道路解耦，只让生产匹配继续
使用补偿后 IoU/置信度/类别代价。Mahalanobis 在代价副本上作为 shadow 诊断，逐帧记录本来会
拒绝的有效候选和会被断掉的轨迹，不影响 ID。

`scripts/compare_xqh_bytetrack.py` 在 400–430s、stride=5、原生 MPS 上让每帧 YOLO 只执行一次，
再将 19696 个相同检测同时交给基线提交 `23252d6` 与当前 tracker。3/3 门禁通过：当前中心密度
为基线 95.23%，中心碎片 ID 44，中位观测寿命 52；硬门控 shadow 会拒绝 1080 个有效候选，
并使 671 条轨迹失去全部候选。

完整 840s–自然 EOF、stride=4 生产链再跑 25/25 通过：1142 帧、109899 个合法检测、61831 个
关联、448 条完成轨迹、1138 帧视觉 warp、road/TCC 泄漏 0、自然 EOF 与四张生产 ShowNode
证据完整。报告为 `/private/tmp/TrafficAnalyzer-xqh-hover-departure-bytetrack-fix-20260729.json`；
这仍是工程回归，无外部真值时 IDF1/HOTA、正式 ID switch、位置 RMSE 和速度 MAE 均为
`not_evaluated`。

---

## 2026-07-29 AGL 三档推理与能力感知运行档复验

实现新增共享 `AdaptiveImageSizePolicy`，同时接入 `DetectionNode` 与 legacy
`DetectionTrackingNodes`。策略只消费同步后的正数 `altitude_agl/height`：AGL `<112m` 使用 640、
`112–157m` 使用 960、`>=157m` 使用 1280；最近 5 点取中位数，5m 滞回、连续 5 个处理帧切档，
缺失保持 2 秒后回退 960。Mission/FlightPlan 未显式选档时按 verified SourceGeoRegistration
选择 cruise，否则选择 legacy，并把最终档、原因和注册 checksum 固化到 snapshot。

xqh 840s–自然 EOF 使用原生 arm64/MPS、stride=4、自适应开启。机器报告
`/private/tmp/TrafficAnalyzer-xqh-adaptive-imgsz-20260729-v2.json` 的既有工程门禁和新增尺寸门禁
合计 27/27：1142/1142 帧均为 medium/960，`max_switch_count=0`，遥测覆盖 100%，非法检测框、
road/TCC 能力泄漏和三类点列对齐失败均为 0，自然 EOF 和四张生产 ShowNode 证据通过。

性能计划门禁没有通过，不能沿用页面即时值宣称 `<100ms`：排除前三个冷启动帧后，YOLO 单处理帧
p50/p95/max 为 165.8/469.24/1756.2ms，单进程整帧 p50/p95 为 435.983/823.003ms。验收器现已
把 `steady_detector_p50_lte_100ms` 纳入后续工程总门禁；本次报告生成时该项仍作为独立性能门禁
复核，因此本轮整体状态保持 `engineering_functional_passed / performance_gate_failed / production_accuracy_not_claimed`。

自动化回归：Platform `234 passed / 5 skipped / 10 subtests passed`；跟踪、Kafka、TCC、自适应尺寸
聚焦回归 `55 passed`；Console2 `149 passed` 且 production build 成功；xqh 基线脚本退出 0。
ADR-019 strict 的代码审计项均通过，但本机运行证据门仍为外部 blocker。无批准真值，IDF1、HOTA、
正式 ID switch、位置 RMSE 和速度 MAE 继续为 `not_evaluated`。

崇华路 `SRC-MP4NEW-CH-0625-AM` 首次 legacy + adaptive 隔离回放中，TCC evidence publisher 日志
已出现 15 次 enqueue，说明漏斗没有全部停在 cruise 质量门；但密集帧 Stats 在约 427 个活跃目标时
增至 1.20–1.24MB，触发 Kafka `MessageSizeTooLargeError`。因此该批次被主动中止，不把部分事件计为
验收结果。修复后 Stats 的 active+candidate 实时快照合计限制为 200 条、优先最新成熟轨迹，并新增
截断计数；400 轨迹序列化回归低于 Kafka 默认 1MB，完整轨迹 Topic 不截断。

2026-07-30 经用户授权，仅以无 `CASCADE` 的固定白名单清空历史 `uav_track_points`、
`uav_track_events`、`uav_conflict_events`、`uav_conflict_reviews`；`uav_traffic_metrics`、
`uav_message_inbox`、Kafka topic/offset、证据、审计、测绘和 SourceProfile 均保留。road9 从约 58GB
降至 33GB，Docker 数据盘恢复约 27.8GB 可用。随后 v3 run
`native-mps-20260730T010956Z-SRC-MP4NEW-CH-0625-AM / pipe-362cddef` 以原生 MPS、
legacy + adaptive、stride=10 自然 EOF（return code 0）：捕获 1299 stats、6302 完成轨迹、
56 条严格 `path_intersection` TCC 和 2407 telemetry；完成轨迹全部 eligible、地理点完整且点列对齐
失败为 0，`invalid_tcc_events=[]`。TCC 漏斗 1299 帧中 1129 帧有候选对、34 帧有预测，业务事件
29 帧；88 个唯一受管 JPEG 均为 3840×2160，文件存在且大小/SHA-256 与事件描述一致。

原运行器仅等待 30 秒，初次 road9 对账在 Kafka 已收齐 `1299/6302/56/2407` 时仍为
`120/5700/56/2407`；这是真实的 Platform 落库积压，不能把初次 `passed=false` 改写为即时通过。
日志确认单条密集 Stats 的 Timescale 展开超过默认 5 分钟 `max_poll_interval_ms`，引发 consumer
rebalance。Platform consumer 已改为 `max_poll_records=1`、`max_poll_interval_ms=1800000`，保持手动
offset 与 inbox 幂等契约，同时允许一次慢持久化完成；重启后积压持续单调下降，最终结果以独立
`post-drain-result.json` 记录，不覆盖原始 `result.json`。积压归零后 Kafka/road9 均为
`1299/6302/56/2407`，mismatch 为空，功能验收为 passed；原始 30 秒时点的失败证据仍保留。

高度覆盖也纠正了一项验收假设：遥测文件全部记录确为 104.08–222.35m，但按视频
`time_offset_sec=247.096` 对齐后的 2422 个有效采样仅为 156.35–178.15m。首帧 178m 初始化 high/1280，
而 1280→960 必须低于 152m，因此 1299 个处理帧全为 1280、零切档是策略预期，并不能证明三档实景
切换；640/960/1280 与边界、滞回、稳定帧和缺失回退由合成回归覆盖。1280 档 YOLO 单处理帧
p50/p95/max 为 371.4/1554.0/3990.6ms，整帧 p50/p95/max 为 965.2/2756.6/9081.8ms；与 xqh
960 档 p50=165.8ms 一致表明 `<100ms` 门仍失败。功能/TCC 工程链路完成，不宣称生产性能或身份、
位置、速度精度；IDF1、HOTA、正式 ID switch、位置 RMSE 和速度 MAE保持 `not_evaluated`。

最终自动化门禁：根 `test/` 201 passed；Platform 全量 235 passed、5 skipped、10 subtests passed；
Kafka consumer + 运行档 + 自适应尺寸聚焦回归 33 passed；Console2 18 文件 149 passed且 production
build 成功；xqh 基线 `56 PASS / 0 FAIL / 0 WARN`。`git diff --check` 无错误，仅提示既有
`FrameElement.py` CRLF 将来会归一化；ADR-019 strict 的代码项全部通过，`local_runtime_evidence`
仍是生产外部门禁，不影响本机功能结论。

---

## 2026-07-20 TCC 检测链路可解释性复验 ✅

### 修复与结果

- `test/test_refactor_unit.py` 的 TCC 正样本夹具补齐 `max_speed_kmh`，恢复 `52 PASS / 0 FAIL`；既有 CPA、擦肩、车型同类配对和去重负样本门禁保持通过。
- 默认业务配置恢复为 `path_intersection + 同时空共同冲突区`；`enable_same_time_cpa=false`，实验 CPA 不进入正式 `conflict_count` 或 Monitoring 默认展示。
- `ConflictDetectionNode` 每帧输出标定、输入/合格机非轨迹、候选配对、预测、证据、去重、正式/实验事件计数；`uav_stats`、road9 历史统计和 Monitoring 均保留该漏斗。
- 历史冲突 API 支持 `source_profile_id`、`pipeline_id`、`prediction_type`；Monitoring 按当前 SourceProfile 回填最近 24 小时严格路径交点事件，以 canonical `message_id` 与实时消息去重，并明确显示 WebSocket 历史/REST 降级状态。浏览器实机核对 `SRC-MP4NEW-CH-0625-AM` 在 road9 有 5 条严格路径交点事实；短于任务结束时间的 30 分钟窗口会误显示 0，因此采用 24 小时回填。
- 浏览器验收已确认 Monitoring 会按选中源发起 `period=24h&source_profile_id=SRC-MP4NEW-CH-0625-AM&prediction_type=path_intersection` 请求，并展示明确的 WebSocket/TCC 状态。为避免中断当时正在运行的检测任务，仅以 `--no-deps` 更新 Console2，未重启 Platform；崇华路运行态在检测器高负载下出现 REST 10 秒超时，因此新漏斗在当前旧 Platform 进程中暂不可见，待安全维护窗口重建 Platform 后生效。
- 小清河 `inter_xqh` 前 100 帧仍为 0 条冲突，这是通过标定、检测和跟踪后的合法零检出，不以放宽阈值或实验 CPA 制造事件。

### 自动化门禁

- `python test/test_refactor_unit.py`：`52 PASS / 0 FAIL`。
- `python -m pytest test/test_tcc_diagnostics.py test/test_kafka_active_trajectories.py test/test_utils_local.py test/test_byte_tracker_core.py test/test_main_optimized_eof.py -q`：`14 passed`。
- `python -m pytest platform/tests -q`：`143 passed / 5 skipped / 10 subtests passed`。
- `cd console2 && npm test -- --run`：`15` 个测试文件、`89` 个测试通过；`npm run build` 成功。
- `python test/test_pipeline_inter_xqh.py`：`56 PASS / 0 FAIL / 0 WARN`；100/100 帧有检测和有效 H，90/100 帧有运动补偿，冲突为 0。
- `python scripts/audit_adr019_retirement.py --scope local --strict`、`docker compose config --quiet`、`git diff --check`：全部通过。

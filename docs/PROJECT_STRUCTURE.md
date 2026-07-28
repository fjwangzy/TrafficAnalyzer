# PROJECT_STRUCTURE.md — TrafficAnalyzer 当前项目结构

> 当前状态：2026-07-25。本文只描述 ADR-019、ADR-023 与 ADR-024 之后的 canonical 运行代码；已退役资产仅在“历史与保留边界”中列出。

## 1. 顶层结构

```text
TrafficAnalyzer/
├── run_platform.py                # Platform 根启动入口，本机与统一镜像共用
├── main_optimized.py              # 唯一生产检测入口：reader+detection / tracker+stats+kafka / show+save+flask
├── main.py                        # 本机调试入口，不作为生产入口
├── docker-compose.yaml            # 唯一本机完整 canonical 拓扑
├── Dockerfile                     # Platform + 检测器统一 CPU-compatible 镜像
├── Dockerfile.detector            # 独立检测器可构建备份，不进入 canonical Compose
├── requirements.txt               # 根检测管道依赖
├── configs/                       # Hydra、道路/车道与检测配置
├── elements/                      # FrameElement、TrackElement、EOF sentinel
├── nodes/                         # 检测、跟踪、标定、统计、冲突、Kafka 与展示节点
├── services/                      # 遥测源与 canonical Nginx/Kafka 辅助配置
├── utils_local/                   # 几何、轨迹、车道、单应性、运动补偿与冲突两图内容寻址保存工具
├── byte_tracker/                  # ByteTrack 实现
├── platform/                      # FastAPI 单体、Alembic、road9/TimescaleDB 访问与测试
├── console2/                      # React/Vite 正式前端
├── test/                          # 根检测、契约、脚本式回归与运行态 E2E
├── scripts/                       # ADR-019、重建、性能/soak/故障演练与原生 MPS 九源验收脚本
├── docs/                          # current-state 契约、ADR、任务与验收证据
└── test_videos/                   # 本机大文件视频/SRT/Cloud JSON 资产（通常不进 Git）
```

生产统一镜像把 Platform 与检测代码写入 `/app`，Compose 仅将 `weights/` 和 `test_videos/`
只读挂载到同名目录。Mac 开发态直接从工作树启动原生 Platform；两种模式下检测器都由
Pipeline API/Mission 在 Platform 所在环境按需启动，不随 Platform 自动运行。NVIDIA GPU
暴露仍是外部部署门禁。

## 2. 检测管道

`main_optimized.py` 组织三进程拓扑，`FrameElement` 逐节点富化，`VideoEndBreakElement` 必须沿全链透传：

```text
VideoReader
  → DetectionNode
  → ImageMotionEstimationNode
  → GroundTrajectoryTrackerNode
  → HomographyCalibrationNode
  → MotionCompensationNode
  → FlightGeoReferenceNode
  → PostTrackingWorldProjectionNode
  → TrackerInfoUpdateNode
  → SpeedEstimationNode
  → DirectionFlowNode
  → LaneDetectionNode
  → LaneAnalysisNode
  → TrajectoryNode
  → RoadMapMatchingNode
  → AutoLaneInferenceNode
  → ConflictDetectionNode
  → CalcStatisticsNode
  → KafkaProducerNode
  → ShowNode
  → VideoSaverNode / TccEvidencePublisherNode / FlaskServerVideoNode
```

关键目录：

| 路径 | 责任 |
|---|---|
| `elements/` | 帧、轨迹与 EOF 数据结构 |
| `nodes/VideoReader.py` | MP4/RTSP、固定 Runtime Road Map Bundle、SRT/JSON/MQTT 遥测注入；启用遥测时 fail-fast |
| `nodes/DetectionNode.py` | 当前 `hover_cruise_v1` 的 YOLO11-only 检测节点，输出已校验的 `detected_*` 与检测几何诊断 |
| `utils_local/detection_geometry.py` | 新旧profile共享的MPS安全bbox裁剪、字段对齐和非法几何过滤边界 |
| `utils_local/image_motion.py`、`nodes/ImageMotionEstimationNode.py` | 排除检测框后的背景 LK/RANSAC 图像运动估计；输出唯一关联 warp，不读取遥测/H |
| `nodes/GroundTrajectoryTrackerNode.py` | 地理参考之前的纯图像 ByteTrack，输出兼容 `tracked_*`/`id_list` 和显示轨迹；含离线 shadow |
| `nodes/FlightGeoReferenceNode.py` | ByteTrack 后计算逐帧绝对 pixel→map ENU，并执行遥测/视觉/地图质量门禁 |
| `nodes/PostTrackingWorldProjectionNode.py` | ID 确定后唯一执行去畸变、ENU/GCJ-02投影和同点地图覆盖，并维护独立正式业务 ID |
| `nodes/DetectionTrackingNodes.py` | 仅 `hover_only_legacy` 回滚使用的旧 YOLO+ByteTrack 组合节点 |
| `nodes/HomographyCalibrationNode.py`、`nodes/MotionCompensationNode.py` | pixel→ENU、GCJ-02 展示坐标与无人机运动补偿 |
| `nodes/RoadMapMatchingNode.py` | 基于 `lane_verified` 车道面、航向、拓扑和连续性的正式匹配 |
| `nodes/Lane*`、`nodes/AutoLaneInferenceNode.py` | 视觉/自动候选，仅辅助质量检查，不覆盖已发布地图 |
| `nodes/ConflictDetectionNode.py` | 路径交点 TTC/PET、同一时空占用与证据评分 |
| `nodes/KafkaProducerNode.py` | 只生成 canonical `uav_*` Topic 与 `msg_type` |
| `nodes/TccEvidencePublisherNode.py` | 等待真实 `ShowNode.frame_result`，固化原图/检测器输出后可靠发布 TCC；证据侧禁止重绘 |
| `scripts/accept_xqh_hover_departure.py` | xqh MPS全尾段、检测几何、三类轨迹对齐、坐标残差、显示和EOF工程门禁 |
| `scripts/build_xqh_trajectory_comparison.py` | 从历史异常帧与最终生产ShowNode帧生成确定性前后对比图 |
| `services/TelemetrySubscriber.py` | DJI Cloud API MQTT 实时遥测 |
| `services/TelemetryFileReader.py` | JSON/TXT 离线遥测 |
| `services/SrtTelemetryParser.py` | DJI SRT 帧级遥测，严格 offset/tolerance |

## 3. Platform 单体

```text
platform/
├── alembic/
│   └── versions/                  # 当前唯一 head：20260723_0019
├── app/
│   ├── main.py                    # lifespan、路由、strict readiness、HLS 受控挂载、WebSocket
│   ├── core/
│   │   ├── config.py              # local/uat/production 配置和 UAT fail-closed 校验
│   │   └── database.py            # road9、Alembic、async session
│   ├── middleware/auth.py         # REST Bearer + 媒体/WS HttpOnly Cookie + active-user 回查
│   ├── api/v1/                    # auth、dashboard、survey、mission、pipeline、video、enforcement 等
│   ├── kafka/
│   │   ├── consumer.py            # earliest、手动 offset、持久化后可恢复 dispatch
│   │   └── ws_manager.py          # 只允许 subscribe/unsubscribe，拒绝客户端 publish
│   ├── models/                    # 所有自建表使用 `uav_` 前缀
│   ├── schemas/                   # Pydantic 输入/输出合同
│   └── services/
│       ├── metric_store.py        # inbox、事实、死信、dispatch 状态机
│       ├── audit_service.py       # `uav_audit_logs` 持久审计
│       ├── pipeline_manager.py    # 子进程/端口/资产/RTSP allowlist 与生命周期
│       ├── survey_service.py      # 测绘、证据、量算、六项复核门禁
│       ├── mission_orchestrator.py# Mission/Pipeline 调度和终态同步
│       ├── road_context.py        # SourceProfile 级 lane_verified 地图/配准选择与 Runtime Bundle
│       └── ...                    # dashboard、alert、enforcement 等领域模块
├── tests/                         # 单元、契约和显式 PostgreSQL/TimescaleDB integration
├── pyproject.toml                 # 应用与 dev 依赖、Ruff/pytest 配置
```

Platform 唯一数据库是 PostgreSQL connection database `road9` + TimescaleDB。当前 Alembic 单 head 为 `20260723_0019`，`uav_message_inbox` 记录事实处理和可恢复派发状态。

## 4. Console2

```text
console2/
├── index.html                     # `zh-CN` 正式页面元数据
├── nginx.conf                     # 8GB 上限、API/WS/HLS 代理、安全头与缓存策略
├── vite.config.mjs                # 业务域 lazy chunk、vendor 分组与 bundle budget
└── src/
    ├── RouterApp.jsx              # 路由、认证守卫、ErrorBoundary、lazy pages
    ├── App.jsx                    # 实时监测；暂停冻结 WS/REST/可见时间
    ├── auth/AuthContext.jsx       # REST token 与媒体 Cookie 会话生命周期
    ├── hooks/useWebSocket.js      # Cookie 鉴权 WebSocket，不在 URL 携带 token
    ├── lib/api.js                 # REST 客户端与统一错误处理
    ├── lib/amap.js                # 高德 JS API 2.0 Loader 与运行时配置
    ├── config/features.js         # UAT 默认关闭 Demo 治理
    ├── components/                # AppShell、地图、共享可访问组件
    └── pages/                     # dashboard、survey、mission、insight、enforcement、admin
```

`IntegrationPage.jsx` 与正式管理页面物理分离；默认 `VITE_ENABLE_DEMO_GOVERNANCE=false` 时不进入可执行 UAT 能力和构建 chunk。

## 5. 本机 canonical 拓扑

根 `docker-compose.yaml` 是生产发布的唯一完整拓扑；Apple Silicon 开发态由
`scripts/mac_local_platform.sh` 原生启动 Platform：

| Service | 端口 | 责任 |
|---|---:|---|
| `road9` | 5432 | PostgreSQL + TimescaleDB，稳定卷 `traffic_road9_data` |
| `kafka` | 9092 | Apache Kafka KRaft |
| `platform` | 8000 | FastAPI 单体 |
| `console2` | 8080 | React SPA |
| `nginx` | 8009 | API/WS/MJPEG/HLS 统一入口 |
| `kafka-ui` | profile `ops` | 可选运维 UI |
| detector | 本地子进程 | Mac 开发使用原生 arm64/MPS；生产容器使用 Linux CPU/CUDA |
| `nvidia-mps` | profile `gpu-only` | 可选 NVIDIA CUDA Multi-Process Service；不是 Apple Metal/MPS |

不得新增第二套完整 Compose、旧 PostgreSQL、旧/实验 TimescaleDB、InfluxDB/Telegraf/Grafana 运行服务或旧 Topic fallback。

## 6. 验证与发布门禁

| 路径 | 说明 |
|---|---|
| `.github/workflows/uat-code-gates.yml` | Platform/Console 测试、构建预算、Ruff、canonical 契约、ADR strict、whitespace |
| `test/` | 根级 pytest、脚本式管道回归与运行态 E2E；分类和执行方式见 `test/README.md` |
| `scripts/audit_adr019_retirement.py` | current-state 静态合同与本机证据审计 |
| `scripts/validate_adr019_local_retirement.py` | canonical 容器、road9、Topic、旧存储隔离与恢复/soak 证据 |
| `test/test_pipeline_inter_xqh.py` | 真实 4K MP4 + DJI SRT 的 56 项管道回归 |
| `scripts/run_native_mps_replays.py` | Apple Silicon 原生 MPS 多源检测、Kafka 直采、轨迹/TCC 诊断与断点续跑 |
| `platform/scripts/inventory_trajectory_replay.py` | 清理前按固定 SourceProfile 只读盘点 canonical 轨迹、统计、冲突、遥测、证据和 Inbox 影响范围 |
| `platform/scripts/build_demo_channelized_maps.py` | YCX 按需只读导入、九源影像配准、四路口质量门禁和不可变地图发布 |
| `platform/scripts/finalize_demo_replay_batches.py` | 对账后创建 completed Mission，并固化视频/遥测/模型哈希与地图 lineage |
| `platform/scripts/verify_gcj02_demo_replays.py` | 默认九源/100 条严格对账；也支持显式 SourceProfile 和最小样本数的技术演示抽检，始终执行旧坐标拒绝与 GCJ-02/ENU 一致性检查 |
| `scripts/mac_local_platform.sh` | 以用户级 launchd 启停原生 macOS Platform，并强制检测子进程使用 MPS |
| `docs/test_report_five_source_trajectory_tcc_full_flow_20260721.md` | 五源轨迹检测、Console 回放、TCC 三图证据全流程验收 |
| `docs/test_report_five_source_regression_20260725.md` | 五源原生 MPS 自然 EOF、Kafka/road9 对账、控制面与真实浏览器整体回归 |
| `docs/runbook_trajectory_data_reset_and_replay.md` | GCJ-02 数据清理、渠化地图发布、MPS 重跑、样本验收、对账门禁与单源回滚 Runbook |
| `docs/runbook_hover_cruise_tracking.md` | 巡航/悬停融合的本机运行、xqh 验收、质量诊断、回滚与生产数据门禁 Runbook |
| `docs/UAT_FULL_REVIEW_2026-07-17.md` | 发布前全量审查、修复状态和延期门禁 |

## 7. 历史与保留边界

- `services/influxdb_data` 只按 ADR-019 retention manifest 保留 7 天，禁止挂载、读取、迁移或校验内容；到期清理只能使用固定 allowlist 脚本。
- `traffic-fly-console` 已退出运行、Compose、Nginx 和发布构建；当前工作树中的删除属于用户既有状态，本轮不恢复、不提交兼容层。
- 旧 Grafana、Telegraf、InfluxDB、旧 Platform 微服务和无 `uav_` 前缀 Topic/channel 只可出现在明确标记的历史文档或审计证据中。
- Docker/镜像 pin、SBOM/签名、共享 UAT secret/TLS/SASL、容器最小权限/healthcheck 属于下一阶段门禁；本文不把它们标记为已完成。
## 2026-07-23 巡航跟踪模块

- `utils_local/flight_motion.py`：共享飞行状态机与速度/航向派生。
- `nodes/DetectionNode.py`：仅 YOLO 检测。
- `utils_local/image_motion.py`、`nodes/ImageMotionEstimationNode.py`：只从背景图像估计 previous→current warp。
- `nodes/GroundTrajectoryTrackerNode.py`：地理参考前的纯图像 ByteTrack、图像 ID/显示历史，以及默认关闭的离线 legacy shadow 对比报告。
- `nodes/FlightGeoReferenceNode.py`、`nodes/PostTrackingWorldProjectionNode.py`：ByteTrack 后生成世界事实、质量门禁、同点地图覆盖和正式业务分段；PostProjection 是新版唯一坐标转换所有者，不得反馈修改图像 ID。
- `test/test_speed_estimation_coordinate_contract.py`：锁定新版仅消费逐帧 ENU、当前 H 不重投影历史，以及 legacy 回退继续可用。
- `utils_local/cruise_evaluation.py`、`scripts/evaluate_cruise_tracking.py`：未来外部项目提供批准真值时的可选只读评测入口；本项目不生成、预标注或审核真值。
- `utils_local/cruise_acceptance_package.py`：只读校验外部资产、内容哈希、Mission/帧 lineage、拍摄包线和真值来源，不构成人工标注工作包。
- `docs/templates/cruise-acceptance-package-v1.json`：仅供未来外部批准真值接入时参考的只读输入示例；不作为本项目采集、预标注、标注分派或复核工作流。
- `docs/generated/xqh-current-cruise-evidence-*.json`：当前 xqh 负样本的内容寻址包和生产证据缺口，不代表准确率通过。
- `scripts/accept_xqh_hover_departure.py`：真实 xqh 840s–EOF 的 MPS 工程验收，输出性能、飞行阶段、正式质量隔离、shadow、EOF 与可视证据；明确不替代带真值生产准确率门禁。
- `scripts/validate_adr019_local_retirement.py`、`scripts/audit_adr019_retirement.py`：本机实时拓扑证据与 ADR-019 strict 10/10 审计。
- `test/test_adr019_runtime_evidence.py`：ADR-019 当前拓扑、历史清库证据和严格审计组合回归。
- `platform/scripts/backfill_cruise_registration_lineage.py`：从指定 selected capture frame 与 verified lanes dry-run/回填 visual registration 位姿、相机哈希和地图覆盖；不修改 H、车道或发布状态。
- `platform/alembic/versions/20260723_0019_cruise_tracking.py`：FlightSegment、profile 与运行质量谱系。
- `docs/runbook_hover_cruise_tracking.md`：当前阶段长期运维、自动化工程验收与精度非声明边界入口。

# 2026-07 路口渠化项目化扩展

- `platform/app/services/intersection_video_discovery.py`：1Hz 悬停发现、WGS84→GCJ-02 坐标边界与候选距离置信度。
- `platform/app/api/v1/calibration.py`：路口项目、统一视频接入/确认、工作台聚合与标定检查接口。
- `platform/alembic/versions/20260722_0018_intersection_video_ingestion.py`：项目、接入任务、分段绑定和检查审计迁移。
- `console2/src/pages/IntersectionProjectPages.jsx`：项目库、双入口向导、项目工作台和接入确认。

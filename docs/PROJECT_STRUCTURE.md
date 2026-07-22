# PROJECT_STRUCTURE.md — TrafficAnalyzer 当前项目结构

> 当前状态：2026-07-21。本文只描述 ADR-019 之后的 canonical 运行代码；已退役资产仅在“历史与保留边界”中列出。

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
├── utils_local/                   # 几何、轨迹、车道、单应性、运动补偿与冲突三图证据渲染工具
├── byte_tracker/                  # ByteTrack 实现
├── platform/                      # FastAPI 单体、Alembic、road9/TimescaleDB 访问与测试
├── console2/                      # React/Vite 正式前端
├── scripts/                       # ADR-019、重建、性能/soak/故障演练与原生 MPS 九源验收脚本
├── docs/                          # current-state 契约、ADR、任务与验收证据
├── test_videos/                   # 本机大文件视频/SRT/Cloud JSON 资产（通常不进 Git）
└── test_*.py                      # 根检测、契约与真实管道回归
```

生产统一镜像把 Platform 与检测代码写入 `/app`，Compose 仅将 `weights/` 和 `test_videos/`
只读挂载到同名目录。Mac 开发态直接从工作树启动原生 Platform；两种模式下检测器都由
Pipeline API/Mission 在 Platform 所在环境按需启动，不随 Platform 自动运行。NVIDIA GPU
暴露仍是外部部署门禁。

## 2. 检测管道

`main_optimized.py` 组织三进程拓扑，`FrameElement` 逐节点富化，`VideoEndBreakElement` 必须沿全链透传：

```text
VideoReader
  → DetectionTrackingNodes
  → HomographyCalibrationNode
  → MotionCompensationNode
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
  → VideoSaverNode / FlaskServerVideoNode
```

关键目录：

| 路径 | 责任 |
|---|---|
| `elements/` | 帧、轨迹与 EOF 数据结构 |
| `nodes/VideoReader.py` | MP4/RTSP、固定 Runtime Road Map Bundle、SRT/JSON/MQTT 遥测注入；启用遥测时 fail-fast |
| `nodes/DetectionTrackingNodes.py` | YOLO11 + ByteTrack |
| `nodes/HomographyCalibrationNode.py`、`nodes/MotionCompensationNode.py` | pixel→ENU、GCJ-02 展示坐标与无人机运动补偿 |
| `nodes/RoadMapMatchingNode.py` | 基于 `lane_verified` 车道面、航向、拓扑和连续性的正式匹配 |
| `nodes/Lane*`、`nodes/AutoLaneInferenceNode.py` | 视觉/自动候选，仅辅助质量检查，不覆盖已发布地图 |
| `nodes/ConflictDetectionNode.py` | 路径交点 TTC/PET、同一时空占用与证据评分 |
| `nodes/KafkaProducerNode.py` | 只生成 canonical `uav_*` Topic 与 `msg_type` |
| `services/TelemetrySubscriber.py` | DJI Cloud API MQTT 实时遥测 |
| `services/TelemetryFileReader.py` | JSON/TXT 离线遥测 |
| `services/SrtTelemetryParser.py` | DJI SRT 帧级遥测，严格 offset/tolerance |

## 3. Platform 单体

```text
platform/
├── alembic/
│   └── versions/                  # 当前唯一 head：20260721_0017
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
│       └── ...                    # dashboard、alert、enforcement、road context 等领域模块
├── tests/                         # 单元、契约和显式 PostgreSQL/TimescaleDB integration
├── pyproject.toml                 # 应用与 dev 依赖、Ruff/pytest 配置
```

Platform 唯一数据库是 PostgreSQL connection database `road9` + TimescaleDB。当前 Alembic 单 head 为 `20260721_0017`，`uav_message_inbox` 记录事实处理和可恢复派发状态。

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
| `scripts/audit_adr019_retirement.py` | current-state 静态合同与本机证据审计 |
| `scripts/validate_adr019_local_retirement.py` | canonical 容器、road9、Topic、旧存储隔离与恢复/soak 证据 |
| `test_pipeline_inter_xqh.py` | 真实 4K MP4 + DJI SRT 的 56 项管道回归 |
| `scripts/run_native_mps_replays.py` | Apple Silicon 原生 MPS 多源检测、Kafka 直采、轨迹/TCC 诊断与断点续跑 |
| `platform/scripts/inventory_trajectory_replay.py` | 清理前按固定 SourceProfile 只读盘点 canonical 轨迹、统计、冲突、遥测、证据和 Inbox 影响范围 |
| `platform/scripts/build_demo_channelized_maps.py` | YCX 按需只读导入、九源影像配准、四路口质量门禁和不可变地图发布 |
| `platform/scripts/finalize_demo_replay_batches.py` | 对账后创建 completed Mission，并固化视频/遥测/模型哈希与地图 lineage |
| `platform/scripts/verify_gcj02_demo_replays.py` | 默认九源/100 条严格对账；也支持显式 SourceProfile 和最小样本数的技术演示抽检，始终执行旧坐标拒绝与 GCJ-02/ENU 一致性检查 |
| `scripts/mac_local_platform.sh` | 以用户级 launchd 启停原生 macOS Platform，并强制检测子进程使用 MPS |
| `docs/test_report_five_source_trajectory_tcc_full_flow_20260721.md` | 五源轨迹检测、Console 回放、TCC 三图证据全流程验收 |
| `docs/runbook_trajectory_data_reset_and_replay.md` | GCJ-02 数据清理、渠化地图发布、MPS 重跑、样本验收、对账门禁与单源回滚 Runbook |
| `docs/UAT_FULL_REVIEW_2026-07-17.md` | 发布前全量审查、修复状态和延期门禁 |

## 7. 历史与保留边界

- `services/influxdb_data` 只按 ADR-019 retention manifest 保留 7 天，禁止挂载、读取、迁移或校验内容；到期清理只能使用固定 allowlist 脚本。
- `traffic-fly-console` 已退出运行、Compose、Nginx 和发布构建；当前工作树中的删除属于用户既有状态，本轮不恢复、不提交兼容层。
- 旧 Grafana、Telegraf、InfluxDB、旧 Platform 微服务和无 `uav_` 前缀 Topic/channel 只可出现在明确标记的历史文档或审计证据中。
- Docker/镜像 pin、SBOM/签名、共享 UAT secret/TLS/SASL、容器最小权限/healthcheck 属于下一阶段门禁；本文不把它们标记为已完成。

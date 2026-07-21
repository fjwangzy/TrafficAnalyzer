# AGENTS.md

本文件是 TrafficAnalyzer 仓库的协作与实现约束。

## 数据架构优先级（ADR-019）

自 2026-07-16 起，本机开发环境已完成纯净切换：唯一数据库为 PostgreSQL connection database=`road9` + TimescaleDB；UAV Topic、`msg_type`、WebSocket channel 和本项目自建表统一使用 `uav_` 前缀。旧数据库和旧观测链路不迁移历史数据，已从当前 Compose、运行时代码、依赖和测试中退役。历史 ADR/报告可保留旧链路说明，但必须明确标记为历史，不能恢复为运行时兼容。

本次切换只证明本机开发闭环，不代表生产验收。生产镜像 pin、秘密管理、TLS/SASL、HA、容量、保留策略和 RPO/RTO 仍需外部门禁。

## 开发前必读

| 文档 | 说明 |
|---|---|
| `docs/AGENTS.md` | 长期协作规则、架构原则、禁止事项和模块边界 |
| `docs/ARCHITECTURE.md` | 系统架构和 canonical 数据路径 |
| `docs/BUSINESS_LOGIC.md` | 检测、跟踪、道路分配和统计逻辑 |
| `docs/PROJECT_STRUCTURE.md` | 项目结构 |
| `docs/API_CONTRACTS.md` | Kafka、REST、WebSocket 和持久化契约 |
| `docs/DATABASE_SCHEMA.md` | `road9`、TimescaleDB 与 `uav_*` 表 |
| `docs/DECISIONS.md` | 架构决策记录，尤其 ADR-019 |
| `docs/TASKS.md` | 技术债和交付状态 |
| `docs/test_report_inter_xqh.md` | 真实视频/SRT 管道回归基线 |

每次完成任务必须同步更新相关文档。若仓库存在 `.codegraph/`，理解或定位代码时先使用 CodeGraph。

## 本机开发与生产发布拓扑

Apple Silicon 开发态的 Platform 必须使用原生 macOS arm64 Python 启动，检测器作为其
本地子进程直接使用 Metal/MPS；不得在 Docker Desktop Linux 容器内运行开发态 Platform。

- `scripts/mac_local_platform.sh up`：启动原生 Platform（端口 `8000`）并强制 MPS；
- `cd console2 && npm run dev`：开发态 Console；
- `road9` 与 Kafka 使用各自可访问的本机/开发基础设施端口 `5432`、`9092`。

根 `docker-compose.yaml` 仅用于生产发布拓扑：

- `road9`：TimescaleDB，正式端口 `5432`，稳定卷 `traffic_road9_data`；
- `kafka`：Apache Kafka KRaft，正式端口 `9092`；
- `platform`：FastAPI，正式端口 `8000`；
- `console2`：React SPA，正式端口 `8080`；
- `nginx`：API/WebSocket/MJPEG/HLS 入口，正式端口 `8009`；
- `kafka-ui`：可选 `ops` profile；
- NVIDIA CUDA MPS 与检测器：可选 `gpu-only` profile，与 Apple Metal/MPS 无关。

```bash
scripts/mac_local_platform.sh up
cd console2 && npm run dev

# 仅生产发布
docker compose -p traffic_analyzer up -d --build
docker compose -p traffic_analyzer --profile ops up -d kafka-ui
docker compose -p traffic_analyzer --profile gpu-only up -d --build
```

生产 Compose 固定 `DEPLOYMENT_MODE=production`，未提供 `ROAD9_PASSWORD`、`JWT_SECRET_KEY`、
`BOOTSTRAP_ADMIN_PASSWORD` 和 JSON `CORS_ORIGINS` 时必须拒绝解析/启动，不得用本地默认密码发布。

禁止重新加入旧 PostgreSQL、旧/实验 TimescaleDB、旧 Topic fallback 或退役观测服务。生产
隔离验证必须复用根 Compose，使用独立 project、临时端口和独立卷名。

## 快速验证

```bash
python -m pytest platform/tests -q
python -m pytest test_kafka_active_trajectories.py test_utils_local.py test_byte_tracker_core.py -q
cd console2 && npm test && npm run build
python test_pipeline_inter_xqh.py
python scripts/audit_adr019_retirement.py --scope local --strict
git diff --check
```

`test_pipeline_inter_xqh.py` 预期 `56 PASS / 0 FAIL / 0 WARN`，需要 `weights/uav_best.pt`。生产范围审计继续保留外部阻断。

## 检测管道

生产入口只有 `main_optimized.py`，三进程结构为 reader+detection、tracker+stats+kafka、show+save+flask，队列 `maxsize=50` 并带进程健康检查。

```text
VideoReader → DetectionTrackingNodes → HomographyCalibrationNode → MotionCompensationNode
  → TrackerInfoUpdateNode → SpeedEstimationNode → DirectionFlowNode → LaneDetectionNode
  → LaneAnalysisNode → TrajectoryNode → AutoLaneInferenceNode → ConflictDetectionNode
  → CalcStatisticsNode → KafkaProducerNode → ShowNode → VideoSaverNode/FlaskServerVideoNode
```

`FrameElement` 是逐节点富化的数据载体，`TrackElement` 保存单车状态，`VideoEndBreakElement` 是 EOF sentinel；所有节点都必须透传 EOF。

关键实现：

| 模块 | 文件 | 责任 |
|---|---|---|
| 视频读取 | `nodes/VideoReader.py` | MP4/RTSP、道路 JSON、遥测和车道注入 |
| 检测跟踪 | `nodes/DetectionTrackingNodes.py` | YOLO11 + ByteTrack |
| 世界坐标 | `nodes/HomographyCalibrationNode.py`、`nodes/MotionCompensationNode.py` | H 矩阵和无人机运动补偿 |
| 轨迹/速度/方向 | `TrackerInfoUpdateNode.py`、`SpeedEstimationNode.py`、`DirectionFlowNode.py`、`TrajectoryNode.py` | 车辆状态、世界轨迹和转向分类 |
| 车道 | `LaneDetectionNode.py`、`LaneAnalysisNode.py`、`AutoLaneInferenceNode.py` | manual > model > auto |
| 冲突 | `nodes/ConflictDetectionNode.py` | 未来路径交点 TTC/PET、证据和风险分 |
| Kafka | `nodes/KafkaProducerNode.py` | canonical 多 Topic 消息信封 |

本地无 Kafka 运行：

```bash
python main_optimized.py pipeline.send_info_kafka=False
```

关键环境变量为 `VIDEO_SRC`、`ROADS_JSON`、`TOPIC_NAME`、`CAMERA_ID`、`KAFKA_BOOTSTRAP`。`TOPIC_NAME` 示例必须使用 `uav_statistics_1`。

## canonical 消息契约

Platform 只订阅：

| Topic | `msg_type` | WebSocket channel |
|---|---|---|
| `uav_statistics_*` | `uav_stats` | `uav_intersection:{id}` |
| `uav_track_complete_*` | `uav_track_complete` | `uav_intersection:{id}` |
| `uav_conflicts_*` | `uav_conflict` | `uav_intersection:{id}`、`uav_alerts*` |
| `uav_telemetry_*` | `uav_telemetry` | `uav_telemetry:{drone_id}` |
| `uav_system_metrics` | `uav_system_metrics` | `uav_system` |

车道标注使用 `uav_calibration`。Runtime 不接受无前缀 Topic、旧 `msg_type` 或旧 WebSocket channel；不要添加适配器、fallback 或双订阅。

## Platform 与 Console2

`platform/app/` 是 FastAPI 单体。数据库初始化只执行 Alembic 并在空库创建本机管理员，不复制任何旧用户、告警、业务或时序数据。Kafka 记录由 `PostgresMetricStoreAdapter` 在事务内写 inbox 与 TimescaleDB/普通表；认证使用 PyJWT+bcrypt。

```bash
cd platform
pip install -e .
python scripts/run_local.py
```

Console2 位于 `console2/`，Docker 入口 `http://localhost:8080`，账号 `admin / admin123`。Nginx 必须通过 Compose service DNS `platform:8000` 访问 Platform。

## 遥测源

| Source | File | Usage |
|---|---|---|
| MQTT | `services/TelemetrySubscriber.py` | 实时 DJI Cloud API |
| JSON/TXT | `services/TelemetryFileReader.py` | 离线回放 |
| SRT | `services/SrtTelemetryParser.py` | 帧级离线回放 |

三者实现统一 `get_nearest(timestamp) -> dict` 接口。

## 旧存储保留

旧卷和 `services/influxdb_data` 只允许按 `scripts/purge_adr019_legacy_storage.py` 生成的 manifest 保留 7 天，期间不得挂载、导入或校验内容。清理脚本必须保持固定 allowlist、到期拒删和双重显式确认；不得绕过脚本人工扩大删除范围。

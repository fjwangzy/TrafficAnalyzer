# 无人机交通态势分析平台

TrafficAnalyzer 使用无人机视频、遥测和已发布渠化地图完成车辆检测、跟踪、速度/方向/车道分析、轨迹输出与机非冲突识别。管理端由 FastAPI Platform 与 React Console2 组成。

## 本机数据架构

ADR-019 已在本机开发环境完成纯净切换：

- 唯一数据库为 PostgreSQL connection database `road9`，镜像启用 TimescaleDB；
- 数据库由 Alembic 初始化，当前 head 为 `20260721_0017`；
- Kafka 使用 Apache Kafka KRaft；
- Topic、`msg_type`、WebSocket channel 和自建表统一使用 `uav_` 前缀；
- 旧观测链路已从代码和 Compose 删除，历史数据不迁移；
- 生产镜像、密钥、TLS/SASL、HA、容量与 RPO/RTO 仍需独立验收。

## Docker 全栈

```bash
export ROAD9_PASSWORD='replace-me'
export JWT_SECRET_KEY='replace-me'
export BOOTSTRAP_ADMIN_PASSWORD='replace-me'
export CORS_ORIGINS='["https://console.example.com"]'
export AMAP_JS_API_KEY='replace-me'
docker compose -p traffic_analyzer up -d --build
```

公共坐标契约唯一为 GCJ-02，Console2 唯一活动底图为高德 JS API 2.0。Web Key 在容器启动时
写入 `/runtime-config.js`；`AMAP_SECURITY_JS_CODE` 为可选增强配置，提供时由运行时配置注入
浏览器并通过 `securityJsCode` 直连高德，不提供时仅使用 Web Key。两种模式都不经过 Vite 或
Nginx 代理；仅 Key 模式可能被高德警告或拒绝，开发/生产域名仍应在高德控制台白名单中登记。
`docs/road_pg.md` 只供操作者取得当前凭证；前端、构建脚本和运行时代码不得直接读取该文件。

## 两阶段重建状态

本机技术演示已完成严格串行的两阶段重建：第一阶段按路口从 YCX 只读导入候选路网并以无人机
正拍影像拟合、发布不可变 `lane_verified` 地图；第二阶段固定 Runtime Road Map Bundle，使用
ENU 计算并以 GCJ-02 投放轨迹。当前四路口地图、9 个视频源配准和 5 个自然 EOF 回放批次已经
固化；视频回归按本轮约定以 2 条轨迹样本完成技术验收，不代表生产人工签署。

执行边界、回滚步骤和下一阶段入口见
[`docs/runbook_trajectory_data_reset_and_replay.md`](docs/runbook_trajectory_data_reset_and_replay.md)，
本轮证据见
[`docs/test_report_gcj02_two_stage_demo_20260722.md`](docs/test_report_gcj02_two_stage_demo_20260722.md)。

默认入口：

| 服务 | 地址/端口 |
|---|---|
| road9 / TimescaleDB | `localhost:5432` |
| Kafka | `localhost:9092` |
| Platform | `http://localhost:8000` |
| Console2 | `http://localhost:8080` |
| Nginx | `http://localhost:8009` |

Console2 开发账号：`admin / admin123`。Kafka UI 为可选 profile：

```bash
docker compose -p traffic_analyzer --profile ops up -d kafka-ui
```

根 `Dockerfile` 是 Platform 与检测器的统一镜像。Platform 启动后不会自动创建检测任务；
检测器由 Pipeline API 或 Mission 调度在 Platform 容器内按需拉起，并在任务停止或 Platform
退出时回收。镜像默认保持 CPU 可启动，NVIDIA GPU 暴露仍属于外部部署门禁。

Apple Silicon 本机开发从仓库根目录启动原生 Platform，以便检测器子进程使用 Metal/MPS：

```bash
scripts/mac_local_platform.sh up
export AMAP_JS_API_KEY='replace-me'
cd console2 && npm run dev
```

原独立检测器镜像保存在 `Dockerfile.detector`，不进入 canonical Compose。它不会内置模型
权重和测试视频，单独运行时必须显式挂载：

```bash
docker build -f Dockerfile.detector -t traffic-analyzer-detector:backup .
docker run --rm \
  -v "$PWD/weights:/app/weights:ro" \
  -v "$PWD/test_videos:/app/test_videos:ro" \
  traffic-analyzer-detector:backup \
  python main_optimized.py pipeline.send_info_kafka=False
```

## 本地运行检测管道

不依赖 Kafka/Docker：

```bash
python main_optimized.py pipeline.send_info_kafka=False
```

使用 inter_xqh 视频、SRT 遥测和本机 Kafka：

```bash
VIDEO_SRC="test_videos/inter_xqh/DJI_20260403142902_0001_V小清河北路与水屯路路口.mp4" \
RUNTIME_MAP_BUNDLE_JSON="$(<lane-verified-runtime-bundle.json)" \
TOPIC_NAME="uav_statistics_1" \
CAMERA_ID=1 \
KAFKA_BOOTSTRAP="localhost:9092" \
python main_optimized.py \
  pipeline.send_info_kafka=True \
  telemetry.enabled=true \
  telemetry.source=srt \
  +telemetry.file_path=test_videos/inter_xqh/telemetry.srt
```

canonical Kafka Topic：

- `uav_statistics_*`
- `uav_track_complete_*`
- `uav_conflicts_*`
- `uav_telemetry_*`
- `uav_system_metrics`

canonical WebSocket channel：`uav_intersection:*`、`uav_alerts`、`uav_alerts:*`、`uav_system`、`uav_telemetry:*`、`uav_calibration`。

## 验证

```bash
python -m pytest platform/tests -q
python -m pytest test_kafka_active_trajectories.py test_utils_local.py test_byte_tracker_core.py -q
python test_pipeline_inter_xqh.py
cd console2 && npm test && npm run build
python scripts/audit_adr019_retirement.py --scope local --strict
git diff --check
```

`test_pipeline_inter_xqh.py` 的基线为 `56 PASS / 0 FAIL / 0 WARN`。

## 旧存储保留

旧容器已下线，旧卷/绑定目录仅保留 7 天且不再挂载。记录状态：

```bash
python scripts/purge_adr019_legacy_storage.py status
```

清理脚本具有固定 allowlist、到期校验、环境开关和确认短语；7 天内会拒绝删除。不要把旧数据导入 `road9`。

详细契约见 `docs/ARCHITECTURE.md`、`docs/API_CONTRACTS.md`、`docs/DATABASE_SCHEMA.md` 和 `docs/DECISIONS.md`。

# 无人机交通态势分析平台

TrafficAnalyzer 使用无人机视频与遥测完成车辆检测、跟踪、轨迹输出及具备证据时的世界坐标、
速度/方向和机非冲突识别；可选的已发布渠化地图只富化 Lane ID、Link ID 与匹配质量。
管理端由 FastAPI Platform 与 React Console2 组成。

## 本机数据架构

ADR-019 已在本机开发环境完成纯净切换：

- 唯一数据库为 PostgreSQL connection database `road9`，镜像启用 TimescaleDB；
- 数据库由 Alembic 初始化，当前 head 为 `20260728_0020`；
- Kafka 使用 Apache Kafka KRaft；
- Topic、`msg_type`、WebSocket channel 和自建表统一使用 `uav_` 前缀；
- 旧观测链路已从代码和 Compose 删除，历史数据不迁移；
- 生产镜像、密钥、TLS/SASL、HA、容量与 RPO/RTO 仍需独立验收。

## 本机开发：启动前后端

前置条件：使用 Apple Silicon Mac，`road9` 与 Kafka 已分别监听本机开发端口 `5432`、`9092`，
并已按 `scripts/bootstrap_native_mps.sh` 准备 `.venv-mps`。本机开发不要使用 Docker Platform；
Platform 必须作为原生 macOS 进程运行，检测器子进程才能使用 Metal/MPS。

终端 1：在仓库根目录启动后端 Platform：

```bash
cd /Users/yaoyao/ai/TrafficAnalyzer
scripts/mac_local_platform.sh up
scripts/mac_local_platform.sh status
```

`status` 应返回 `"status":"ready"`，并显示 database、Kafka、TimescaleDB 和
pipeline manager 均为 `healthy`。后端地址为 `http://127.0.0.1:8000`，也可直接检查：

```bash
curl -fsS http://127.0.0.1:8000/ready
```

终端 2：启动前端 Console2：

```bash
cd /Users/yaoyao/ai/TrafficAnalyzer/console2
# 地图功能需要有效的高德 Web Key；不使用地图时可省略下一行。
export AMAP_JS_API_KEY='replace-me'
npm run dev -- --host 127.0.0.1
```

浏览器访问 `http://127.0.0.1:5173`，开发账号为 `admin / admin123`。Console2 会把
`/api` 和 `/ws` 代理到 `http://127.0.0.1:8000`。

停止或排查服务：

```bash
# Platform 日志、重启、停止（在仓库根目录执行）
scripts/mac_local_platform.sh logs
scripts/mac_local_platform.sh restart
scripts/mac_local_platform.sh stop

# Console2 在运行 npm run dev 的终端按 Ctrl+C 停止
```

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

## 巡航跟踪与悬停正拍融合状态

`hover_cruise_v1` 已把同一 Mission 内的进场巡航、悬停正拍和离场巡航接入统一质量链。YOLO
仍在进程 1；进程 2 先用背景图像运动补偿执行纯图像 ByteTrack，再由
`PostTrackingWorldProjectionNode` 为成熟图像关联分配稳定 `track_id`，并按视频尺寸、相机参数和
同步SRT逐帧计算的当前矩阵做 pixel→ENU/GCJ-02 投影。H、遥测和ENU不进入 ByteTrack
关联代价；地理质量变化只能让对应世界点降级为 `null`，不能改变、结束或拆分图像轨迹。
Runtime Road Map Bundle 是可选富化，只影响 Lane ID、Link ID 与匹配质量，不创建或覆盖世界坐标。
悬停关键帧仍是发布 `lane_verified` 地图的唯一来源，巡航帧不能创建或修改地图。

2026-07-28 已实施 ADR-025：成熟像素轨迹不再受地理或路网质量门禁抑制。mp4728 的 3/5/7 m/s
三源以原生 arm64/MPS 串行回放至自然 EOF，共输出 7,881 条完成轨迹，Kafka 与 road9 按
`source_profile_id + pipeline_id` 精确一致。该报告是修复前历史快照，当时世界能力因新增注册门禁
被错误关闭；当前实现已恢复为视频+SRT逐帧矩阵门禁，是否有 `lane_verified` 路网只影响Lane/Link。原报告结论为
`local_engineering_passed / source_inputs_complete / road_context_degraded / geo_not_evaluated /
production_accuracy_not_claimed`。

2026-07-25 的真实 `inter_xqh` 后半程原生 MPS 复验继续作为飞行姿态和道路能力降级样本保留；
ADR-025 后离场阶段仍输出成熟像素轨迹，只关闭缺乏独立证据的世界、Lane/Link 与 TCC 能力。
项目不建设人工轨迹标注、AI 预标注或标注复核工作包；IDF1/HOTA、世界位置/速度精度和正式
12m/s 巡航能力在无外部批准真值时统一为 `not_evaluated`，不得从观测 ID、IoU 或尾迹观感推导。

2026-07-24 完成检测输出轨迹几何修复：Apple MPS 强制使用安全的非原地 bbox 裁剪，非法框在
检测边界丢弃并阻断该帧正式研判；正式和候选轨迹同时保留源帧图像接地点、ENU/GCJ-02、时间、
帧号和质量谱系，ShowNode 只绘制由背景视觉 warp 递推得到的当前帧图像历史。正式轨迹为类别色实线，
候选轨迹为最多30点的琥珀虚线；显示简化不改写轨迹事实，也不允许候选进入统计、速度、车道或 TCC。

运行、验收、回滚和故障定位见
[`docs/runbook_hover_cruise_tracking.md`](docs/runbook_hover_cruise_tracking.md)，原始工程证据见
[`docs/test_report_inter_xqh.md`](docs/test_report_inter_xqh.md) 和
[`docs/generated/xqh-hover-departure-acceptance.json`](docs/generated/xqh-hover-departure-acceptance.json)。
当前自动化基线为 Python 全量 `397 passed / 5 skipped / 10 subtests`、Console2
`18 files / 148 tests` 与 production build、xqh `56 PASS / 0 FAIL / 0 WARN`。ADR-019 strict
有 9 项通过，仍由既有外部 `local_runtime_evidence` 门禁返回非零，未标记为全绿。

mp4728 最终证据见
[`docs/test_report_mp4728_20260728.md`](docs/test_report_mp4728_20260728.md)。

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

Apple Silicon 本机开发的前后端命令、访问地址和停止方式见
[本机开发：启动前后端](#本机开发启动前后端)。

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
FRAME_STRIDE=3 \
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

`FRAME_STRIDE=3` 表示每 3 个源帧处理 1 帧；Platform/Console2 交互式启动默认同样为 3，管理员可在启动检测前于 `1–30` 范围内调整。30 FPS 源使用 3 时约处理 10 FPS。

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
python -m pytest test/test_kafka_active_trajectories.py test/test_utils_local.py test/test_byte_tracker_core.py -q
python test/test_pipeline_inter_xqh.py
.venv-mps/bin/python scripts/accept_xqh_hover_departure.py --start-offset-sec 840 --departure-offset-sec 902 --stride 4
cd console2 && npm test && npm run build
python scripts/audit_adr019_retirement.py --scope local --strict
git diff --check
```

`test/test_pipeline_inter_xqh.py` 的基线为 `56 PASS / 0 FAIL / 0 WARN`。

检测输出中的正式轨迹使用类别色实线和常规速度标签；未通过地理参考门禁的候选轨迹使用琥珀虚线、紧凑的 `#ID class C` 标签，并在右上角统一提示 `CANDIDATE / NO STATS-TCC`。ShowNode 不连接不同相机帧中的原始像素点，而使用当前帧派生坐标；候选框、标签和尾迹按 4K→1280×720 交付比例缩放，保证浏览器/MJPEG 中可读，但候选数据仍不会进入速度、车道、统计、TCC 或事件中心。

## 旧存储保留

旧容器已下线，旧卷/绑定目录仅保留 7 天且不再挂载。记录状态：

```bash
python scripts/purge_adr019_legacy_storage.py status
```

清理脚本具有固定 allowlist、到期校验、环境开关和确认短语；7 天内会拒绝删除。不要把旧数据导入 `road9`。

详细契约见 `docs/ARCHITECTURE.md`、`docs/API_CONTRACTS.md`、`docs/DATABASE_SCHEMA.md` 和 `docs/DECISIONS.md`。

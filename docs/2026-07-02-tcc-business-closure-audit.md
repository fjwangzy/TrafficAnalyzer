# TCC 交通态势感知业务闭环完成审计

**日期**: 2026-07-02  
**目标**: 验证“视频/无人机接入 → 检测跟踪 → 态势分析 → 事件告警 → 平台可视化 → 历史复盘”的 TCC 业务闭环是否具备可演示、可复盘、可继续扩展的交付状态。

## 本轮验证命令

```bash
python test_pipeline_inter_xqh.py
# 56 PASS / 0 FAIL / 0 WARN

python -m pytest platform/tests -q
# 31 passed, 4 warnings, 11 subtests passed

python -m pytest test_kafka_active_trajectories.py test_utils_local.py test_byte_tracker_core.py test_grafana_provisioning.py -q
# 11 passed

cd traffic-fly-console
npm test
# 27 test files passed, 160 tests passed

npm run build
# TypeScript + Vite build passed

curl -sS -m 3 http://localhost:8000/ready
# platform live ready: database/kafka/influxdb/pipeline_manager healthy, pipelines_active=0

docker compose -f docker-compose.yaml -f docker-compose.test.yaml -p trafficanalyzer up -d --build platform
# platform image rebuilt successfully; live API smoke passed after rebuild

cd traffic-fly-console
npm run dev -- --host 127.0.0.1 --port 54544
# Vite dev server served http://127.0.0.1:54544/

python - <<'PY'  # inline Platform lifecycle/MJPEG smoke
# POST /api/v1/pipelines created a running process; /status process_alive=true
# GET /api/v1/video/camera/{camera_id} returned 200 multipart/x-mixed-replace with JPEG bytes
# DELETE /api/v1/pipelines/{id} stopped it; summary running=0
```

`test_pipeline_inter_xqh.py` 本轮已在当前工作树重复执行，前 100 帧真实 YOLO+SRT 链路处理耗时 541.4s（CPU），检测目标帧率 100/100，遥测注入 100/100，H 矩阵 100/100，运动补偿 90/100，机非冲突事件数 0。

浏览器 smoke 已在 Vite dev server 上通过登录、Dashboard、Monitoring、GIS、Alerts、Drones 主流程检查：页面均可打开，console error 为 0；Monitoring 展示单路口实时监测、BEV/OSM、冲突列表与管道控制；GIS 展示历史轨迹/历史冲突空态；Alerts/Drones 空态正常。Grafana 因本机无 `grafana/grafana` 镜像且 Docker pull 两轮均停在 `grafana Pulling` 无进展，本轮取消拉取，未完成 UI smoke。

Grafana provisioning 静态链路已补齐并验证：新增 `services/grafana/provisioning/datasources/datasource.yaml`，自动配置 InfluxDB datasource UID `cdycrblq6bf9ce` 和 PostgreSQL datasource UID `f848db3d-2635-4913-be1c-ae2d0db7c90a`，与 `camera-1.json`、`camera-2.json` 中的面板引用一致；`docker compose config` 确认 provisioning 目录挂载到 `/etc/grafana/provisioning`。根 compose 已给 Grafana 登录账号和 InfluxDB 凭据提供本地默认值，并把 InfluxDB 凭据注入 Grafana 容器；`test_grafana_provisioning.py` 覆盖 compose 默认值、provisioning 挂载、datasource UID 对齐和容器网络地址；`docker compose ... config --services` 无 warning。本机 InfluxDB 查询入口 `SHOW DATABASES` 返回 `_internal`、`traffic`、`influx`。

## 验收项审计

| 验收项 | 当前结论 | 当前证据 | 说明 |
|--------|----------|----------|------|
| `test_pipeline_inter_xqh.py` 达到 `49 PASS / 0 FAIL` | ✅ 本轮已验证且超过指标 | `python test_pipeline_inter_xqh.py` → `56 PASS / 0 FAIL / 0 WARN` | 当前 CPU 4K 前 100 帧耗时 541.4s，冲突事件数 0。 |
| 平台核心 API 可访问 | ✅ 本轮已验证 | `python -m pytest platform/tests -q`，含 `test_core_api_routes.py` | 覆盖 pipelines、intersections、drones、trajectories、conflicts、alerts、system health。 |
| Kafka topic pattern 覆盖统计/轨迹/冲突/遥测 | ✅ 本轮已验证 | `platform/tests/test_pipeline_manager.py` compose/topic pattern 子测试；`test_kafka_active_trajectories.py` | 当前平台 pattern 为 `((statistics|track_complete|conflicts|telemetry)_.*|system_metrics)`，超出目标并覆盖 system。 |
| 前端 WebSocket 可收到业务频道 | ✅ 本轮已验证服务层 | `platform/tests/test_realtime_channels.py` | 覆盖 `intersection:{id}`、`alerts`、`alerts:{intersection_id}`、`telemetry:{drone_id}`、`system` 广播。浏览器端全量交互建议最终演示再跑。 |
| 单个视频任务可启动、停止、查询状态 | ✅ 本轮 live 验证 | `POST /api/v1/pipelines`、`GET /status`、`DELETE /api/v1/pipelines/{id}` | 当前平台镜像中启动 `test_videos/longer_example.mp4` 后 3s 仍 `process_alive=true`；停止后 `summary.running=0`。 |
| 统计消息字段完整 | ✅ 本轮已验证 | `test_kafka_active_trajectories.py`；`docs/API_CONTRACTS.md` | 覆盖车辆数、道路/方向/速度/排队、无人机位置、冲突数量、活跃轨迹尾部。 |
| 完成轨迹消息字段完整 | ✅ 本轮已验证 | `test_kafka_active_trajectories.py`；`platform/tests/test_influx_query.py` | 覆盖像素轨迹、世界坐标轨迹、转向/速度/出入口复盘字段。 |
| 冲突消息字段完整 | ✅ 本轮已验证关键字段 | `platform/tests/test_influx_query.py`；`conflict-replay-utils.test.ts` | 覆盖双方 ID、预测位置、TTC/PET、风险等级、证据、冲突场景、CPA-only 过滤和回放语义。 |
| 前端展示实时态势、冲突列表、BEV 回放和告警 | ✅ 自动化 + 浏览器 smoke 已验证 | `npm test` → 27 files / 160 tests；`npm run build` passed；Playwright/Vite smoke | Dashboard、Monitoring、GIS、Alerts、Drones 主页面均可登录访问，console error 为 0。 |
| 历史统计、轨迹、冲突复盘 | ✅ 平台/GIS/Grafana 配置已验证；Grafana UI 未验证 | `platform/tests/test_influx_query.py`、`platform/tests/test_core_api_routes.py`、`gis/index.test.tsx`、浏览器 GIS smoke、`test_grafana_provisioning.py` | 平台 API 与 GIS 展示均覆盖；Grafana datasource provisioning 已补齐并由 3 个回归测试覆盖，但本机缺镜像且 pull 超时，未打开 Grafana UI。 |
| 文档与实际能力一致 | ✅ 本轮推进 | `AGENTS.md`、`docs/AGENTS.md`、`docs/CLAUDE.md`、`docs/TASKS.md`、`docs/test_report_inter_xqh.md` 已同步 | 已清理“49 PASS”“历史冲突无法查询”“GIS 回放未实现”“Python 禁写 InfluxDB”等过期口径。 |

## 里程碑状态

| 里程碑 | 结论 | 证据 |
|--------|------|------|
| M1 数据链路打通 | ✅ | Kafka producer 单测、Platform realtime channels 单测、历史 live WebSocket/MJPEG 记录 |
| M2 业务态势可视化 | ✅ | 前端全量测试和构建通过；Vite 浏览器 smoke 覆盖 Dashboard/Monitoring/GIS/Alerts/Drones；live MJPEG proxy 返回 JPEG 首帧 |
| M3 事件与告警闭环 | ✅ | ConflictDetectionNode 业务口径、AlertEngine 持久化、WebSocket alerts、冲突回放/GIS 测试 |
| M4 任务生命周期管理 | ✅ | PipelineManager 单测和历史 live 启停记录 |
| M5 复盘与交付验证 | ✅/⚠️ | 端到端、平台、前端全量自动化通过；Influx 查询、历史轨迹/冲突 API、GIS 展示测试通过；Grafana datasource/dashboard provisioning 有回归测试；Grafana UI 因镜像拉取受阻未实测 |

## 截图误报复核结论

用户复核的 0.9m、1.3m、1.7m TCC 回放截图中，双方轨迹趋势均没有形成同一时刻的共同未来碰撞点；它们更像中心点最近距离或旧 CPA 辅助线造成的视觉误导。当前修正后的业务口径为：

1. 默认只接受未来路径交点冲突，`prediction_type=path_intersection`。
2. `same_time_cpa` 仅作为显式扩展开关，不进入默认机非冲突大盘。
3. `PET<=1s` 不单独触发 near-miss；`TTC>1.5s` 时必须叠加急刹、非机动车急转向或停车/让行证据。
4. 路径交点 PET 候选还必须在双方到达交点期间进入 `same_time_collision_radius_m=0.8m` 共同冲突区，过滤仅数学射线相交但同刻距离偏大的轨迹。
5. BEV 回放风险圈和距离辅助线锚定事件预测冲突位置，不再使用两车播放时刻当前位置中点。

## 剩余非阻塞项

Grafana UI smoke 未完成：本机没有 `grafana/grafana` 镜像，`docker compose ... up -d grafana` 与 `docker compose ... pull grafana` 多轮均停在 `grafana Pulling` 超过 60-90s 后取消；2026-07-02 05:25 再次使用默认 compose 启动 Grafana，60s 仍无拉取进展后取消。Grafana 配置层已补齐 datasource provisioning 并通过 UID 校验和 `test_grafana_provisioning.py` 回归测试；TCC 主链路的算法、Platform API、管道生命周期、MJPEG 代理、前端主流程和历史复盘已完成验证。当前剩余缺口是外部镜像获取/启动环境，需在可拉取 `grafana/grafana` 镜像的环境下补跑 Grafana UI smoke。

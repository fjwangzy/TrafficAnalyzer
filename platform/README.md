# Traffic Platform

Traffic Platform 是 TrafficAnalyzer 的 FastAPI 单体后端。自 ADR-019 本机切换完成后，它只使用全新 `road9`/TimescaleDB、Apache Kafka KRaft 和 canonical `uav_*` 消息契约；不读取、不迁移旧数据库或旧时序数据。

## 本机正式栈

从仓库根目录启动唯一 Compose：

```bash
docker compose -p traffic_analyzer up -d --build
```

默认入口：

| 服务 | 地址 |
| --- | --- |
| Platform | `http://localhost:8000` |
| Console2 | `http://localhost:8080` |
| Nginx | `http://localhost:8009` |
| road9 / TimescaleDB | `localhost:5432` |
| Kafka | `localhost:9092` |

根 `docker-compose.yaml` 是唯一正式拓扑；`platform/docker/` 和旧微服务目录已退役删除。Kafka UI 通过 `ops` profile 可选启动。检测器代码已写入统一 Platform 镜像，由 Pipeline API/Mission 按需作为子进程启动，不再作为独立 Compose camera 服务。

## 本地进程开发

需要已运行的 `road9` 和 Kafka：

```bash
pip install -e platform
python run_platform.py
```

本地启动脚本默认连接 `road9@localhost:5432` 和 `Kafka@localhost:9092`，仅订阅 canonical Topic。

## 数据库启动语义

Platform 启动时：

1. 确保目标 database=`road9` 存在；
2. 执行 Alembic 到当前 head `20260715_0010`；
3. 初始化唯一管理员 `admin / admin123`（仅限本机开发）；
4. 不创建旧库迁移审计/隔离表，不复制旧用户、告警、指标、轨迹或任务数据。

正式本机数据卷为 `traffic_road9_data`。不得挂载任何旧 PostgreSQL、实验 TimescaleDB 或旧时序目录。

## Kafka 与 WebSocket 契约

支持的 Kafka Topic / `msg_type`：

| Topic | `msg_type` |
| --- | --- |
| `uav_statistics_*` | `uav_stats` |
| `uav_track_complete_*` | `uav_track_complete` |
| `uav_conflicts_*` | `uav_conflict` |
| `uav_telemetry_*` | `uav_telemetry` |
| `uav_system_metrics` | `uav_system_metrics` |

支持的 WebSocket channel：

- `uav_intersection:*`
- `uav_alerts`、`uav_alerts:*`
- `uav_system`
- `uav_telemetry:*`
- `uav_calibration`

MetricStore 会同时校验 Topic 与 `msg_type` 的映射；WebSocket 订阅、开发发布和内部广播都会拒绝无前缀频道或消息类型。

## API 与就绪检查

- OpenAPI：`GET /openapi.json`
- 进程存活：`GET /health`
- 强就绪：`GET /ready`
- REST：`/api/v1/*`
- WebSocket：`/ws/realtime`

`/ready` 检查数据库、TimescaleDB、Kafka 和管道管理器。依赖故障必须如实返回降级/非就绪状态，不能回读旧存储。

## 关键配置

| 变量 | 本机默认 | 说明 |
| --- | --- | --- |
| `SERVICE_PORT` | `8000` | Platform 端口 |
| `DB_HOST` | `localhost` | road9 主机 |
| `DB_PORT` | `5432` | road9 端口 |
| `DB_USER` | `traffic` | road9 用户 |
| `DB_PASSWORD` | `traffic123` | 仅本机默认密码 |
| `DB_NAME` | `road9` | 唯一目标数据库 |
| `DB_BOOTSTRAP_DATABASE` | `postgres` | 仅用于创建空白 road9 |
| `KAFKA_BOOTSTRAP` | `kafka:9092` | Kafka bootstrap |
| `KAFKA_TOPICS_PATTERN` | canonical `uav_*` 正则 | 消费 Topic |
| `JWT_SECRET_KEY` | 本机开发值 | 生产必须外部注入 |

完整配置见 `app/core/config.py`。

## 验证

```bash
python -m pytest platform/tests -q
cd ../console2 && npm test && npm run build
cd ..
python scripts/audit_adr019_retirement.py --scope local --strict
```

本机运行态验收报告见：

- `docs/test_report_i6_target_stack.json`
- `docs/test_report_i6_database_outage.json`
- `docs/test_report_i6_local_readiness_soak.json`
- `docs/test_report_adr019_local_retirement.json`

## 项目结构

```text
platform/
├── app/
│   ├── main.py
│   ├── core/
│   ├── api/v1/
│   ├── kafka/
│   ├── services/
│   ├── models/
│   └── schemas/
├── alembic/
├── pipeline-requirements.txt
├── pipeline-constraints.txt
└── pyproject.toml
```

本机与容器统一入口为仓库根 `run_platform.py`；统一镜像定义为根 `Dockerfile`，原独立检测器构建定义保存在根 `Dockerfile.detector`。

详细契约以 `docs/ARCHITECTURE.md`、`docs/API_CONTRACTS.md` 和 `docs/DATABASE_SCHEMA.md` 为准。

## 生产边界

当前只完成本机开发环境闭环。生产镜像固定、秘密管理、TLS/SASL、HA、容量、正式性能阈值、RPO/RTO、试点和主平台联调仍为外部门禁，不得用本机报告宣称生产验收完成。

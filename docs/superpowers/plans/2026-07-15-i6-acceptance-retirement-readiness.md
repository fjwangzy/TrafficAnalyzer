# I6 S7 总体验收与 ADR-019 本机退役记录

> 计划建立：2026-07-15
> 本机关闭：2026-07-16
> 范围：仅本机开发环境；生产验收保持 `blocked_external`

## 结论

本机已完成纯净新架构切换。历史 PostgreSQL、InfluxDB、实验 TimescaleDB 和旧 Kafka 数据均不迁移、不备份、不校验；正式运行态只使用新建的 `traffic_road9_data`，数据库为 `road9`，由 Alembic `20260715_0010` 初始化。

根 `docker-compose.yaml` 是唯一正式拓扑：TimescaleDB、Apache Kafka KRaft、Platform、Console2、Nginx，以及 `ops`/`gpu-only` 可选服务。旧 PostgreSQL、InfluxDB、Telegraf、Grafana、Zookeeper、旧 Platform Compose、重复完整 Compose 和无前缀消息兼容均已从活动实现中删除。

## 本机切换结果

- 正式端口：TimescaleDB `5432`、Kafka `9092`、Platform `8000`、Console2 `8080`、Nginx `8009`。
- 当前唯一运行容器：`traffic_analyzer-road9-1`、`traffic_analyzer-kafka-1`、`traffic_analyzer-platform-1`、`traffic_analyzer-console2-1`、`traffic_analyzer-nginx-1`。
- 数据库：`road9`、TimescaleDB `2.28.2`、Alembic `20260715_0010`、5 张 hypertable、41 张 `uav_*` 表。
- 初始数据：管理员 1 条；业务、指标、轨迹、任务、告警合计 0 条；不存在 `traffic_platform` 数据库和迁移审计/隔离表。
- Kafka 业务 Topic 仅允许 `uav_*`；`__consumer_offsets` 等 Kafka 内部 Topic 不属于业务契约。
- WebSocket 仅允许 `uav_intersection:*`、`uav_alerts*`、`uav_system`、`uav_telemetry:*`、`uav_calibration`。

## 验收证据

- `docs/test_report_i6_target_stack.json`：根 Compose 的独立 project/临时端口/临时卷验证通过；空库迁移到 `0010`，5 张 hypertable、41 张 `uav_*` 表、管理员 1 条、业务 0 条、94 paths/110 operations。
- `docs/test_report_i6_database_outage.json`：隔离断库恢复 `200 → 503 dashboard_dependency_unavailable → 200` 通过，未导入旧数据。
- `docs/test_report_i6_local_readiness_soak.json`：最终 Platform 镜像在正式端口连续探测 `1800.225` 秒，61/61 样本健康，readiness 成功率 100%，最大整组探测延迟 `257.76ms`、P95 `233.83ms`。
- `docs/test_report_adr019_local_retirement.json`：18 项本机运行态/数据/存储/恢复门禁全部通过。
- `python scripts/audit_adr019_retirement.py --scope local --strict`：通过。
- Platform：`89 passed / 5 skipped / 10 subtests`；Console2：`49 passed` 且生产构建通过；根目录轻量/EOF/Kafka/Compose/遥测：`16 passed`；`test_pipeline_inter_xqh.py`：`56 PASS / 0 FAIL / 0 WARN`。

## 旧资产 7 天保留

以下资产仅保留，不再挂载，不读取内容：

- `trafficanalyzer_postgres_data`
- `trafficanalyzer_timescaledb_local_data`
- `traffic_analyzer_mp4new_road9_target_data`
- `services/influxdb_data`

记录文件为 `output/adr019-retirement/retention.json`。退役时间为 `2026-07-16T03:11:54.969379Z`，最早人工清理时间为 `2026-07-23T03:11:54.969379Z`，即北京时间 `2026-07-23 11:11:54`。

清理只能由人工在到期后显式执行：

```bash
ALLOW_ADR019_LEGACY_PURGE=1 python scripts/purge_adr019_legacy_storage.py purge \
  --manifest output/adr019-retirement/retention.json \
  --confirm DELETE_EXPIRED_ADR019_LEGACY_STORAGE
```

脚本使用固定 allowlist、7 天到期校验、挂载检查和精确确认串；到期前或仍被挂载时拒绝删除。

## 生产边界

本次关闭不证明生产可用性。生产镜像与秘密、TLS/SASL、HA、容量、正式性能阈值、RPO/RTO、试点、主平台联调和发布批准仍由外部门禁管理：

```bash
python scripts/audit_adr019_retirement.py --scope production
```

该范围必须继续报告 `production_retirement_approval=blocked_external`，不得用本机结果替代生产验收。

# I6 S7 总体验收与 ADR-019 退役就绪审计（2026-07-15）

## 结论

I2～I5 的本地工程闭环已形成，但 I6 正式验收和旧链路退役尚不具备安全执行条件。当前 Platform 运行组合与 Console2 正式路由已经使用 `road9`/TimescaleDB，不再调用 InfluxDB；但根 Compose、遗留配置和历史查询工具仍保留 InfluxDB/Telegraf/Grafana，且历史迁移对账、RPO/RTO、性能环境、试点范围和观察期没有书面批准。

因此本阶段只建立可执行审计和关闭清单，不删除服务、不修改旧数据、不伪造退役完成。

## 可执行审计

```bash
python scripts/audit_adr019_retirement.py
python scripts/audit_adr019_retirement.py --format json
python scripts/audit_adr019_retirement.py --strict
```

普通模式用于生成盘点；`--strict` 是未来发布门禁，在任一代码或外部阻断未关闭时返回非零。schema 固定为 `uav.adr019-retirement-audit/v1`。

## 当前通过项

- `platform/app/main.py` 的实际运行组合使用 `PostgresMetricStoreAdapter`，没有装配 `InfluxQuery`。
- Console2 正式源代码没有 InfluxDB、Telegraf 或 Grafana 查询依赖。
- I3 已在隔离 PostgreSQL 17 + TimescaleDB 2.28.2 验证 5 张 hypertable、幂等 inbox/事实、手动 offset 和死信。
- `docker-compose.road9.yaml` 已形成独立本地目标栈：`road9`/TimescaleDB、Kafka、Platform、Console2，不包含 InfluxDB/Telegraf/Grafana；`docker compose config` 通过。其 `road9` 服务已真实启动为 healthy，并从空库迁移到 `0009`（TimescaleDB 2.28.2、5 Hypertable、41 张 `uav_*` 表），随后临时容器/网络/卷全部清理。证据见 `docs/test_report_i6_target_compose.json`。镜像 pin、容量、HA 和秘密仍等待生产批准。
- `scripts/validate_road9_backup_restore.py` 完成受保护的 Timescale-aware `pg_dump/pg_restore`：`0009`、2.28.2、5 Hypertable、41 张 `uav_*` 表和 27 行本地数据全部一致，临时库自动清理。证据见 `docs/test_report_i6_road9_restore.json`。
- 演练首次暴露 regular table → Hypertable FK 无法可靠恢复；前向 migration `20260715_0009` 改为数据库 existence guard + delete cascade triggers，保持运行时完整性和删除语义，并已通过非法引用集成测试。
- 全新 `road9_i6_empty` 已完成 `empty → 20260715_0009 → 20260715_0008 → 20260715_0009`，两次 head 均存在 5 个 Hypertable/2 个完整性触发器，临时库已删除。证据见 `docs/test_report_i6_migration_drill.json`。
- `scripts/inventory_legacy_influx.py` 以固定本地容器/库 allowlist 只读盘点遗留库，证据见 `docs/test_report_i6_legacy_influx_inventory.json`：`intersection_stats` 约 30,370 点/6 series（2026-07-01～07-15）、`track_events` 约 8,789 点/10 series（1970-01-01 00:00:02～00:16:14）、`conflict_events` 219 点/7 series（2026-07-01～07-15）。候选目标表分别为 `uav_traffic_metrics`、`uav_track_events`、`uav_conflict_events`，三项映射均保持 `unverified`；轨迹明确标记 `relative_or_invalid_epoch/blocked_external`。
- `scripts/validate_i6_local_performance.py` 仅允许 localhost 且需显式 guard/凭据，执行 80 个已认证只读 GET（并发 8）全部返回 200；Dashboard 三类聚合接口 p50 约 27ms，系统健康接口 p50 约 1.9ms。证据见 `docs/test_report_i6_local_performance.json`，环境固定为 `local_non_contract`、阈值 `unverified`，不得解释为生产性能达标。
- `scripts/validate_i6_database_outage.py` 在固定隔离 Compose project/端口创建临时 `road9`，验证 Dashboard `200 → 503 dashboard_dependency_unavailable → 200`，检测/恢复均约 0.3 秒，结束后删除临时容器/卷。首次演练发现 asyncpg 连接拒绝越过异常边界形成空体 500，现已在 `platform/app/api/v1/dashboard.py` 归一为结构化 503并加入回归测试。证据见 `docs/test_report_i6_database_outage.json`；该单实例开发机结果不替代生产 RTO/RPO/HA/数据丢失和负载演练。
- 完整 `docker-compose.road9.yaml` 已真实构建并启动 `road9 + Apache Kafka 3.9.2 KRaft + Platform + Console2`。首次启动暴露旧 `wurstmeister/zookeeper` 在 ARM/qemu 下 JVM 崩溃，以及 Platform 镜像漏复制 Alembic 资产而“表面健康、实际无数据库”两个缺陷；现已移除 Zookeeper、切换官方 KRaft 镜像、复制 migration，并让 Console 等待 Platform `/ready` 的数据库/Kafka/TimescaleDB 强就绪。`scripts/validate_i6_target_stack.py` 证明 migration `0009`、TimescaleDB 2.28.2、5 Hypertable、41 张 `uav_*` 表、canonical Topic、Console 代理登录、Dashboard/System API、94 paths/110 operations 均通过，且目标镜像不存在 InfluxDB 客户端。证据见 `docs/test_report_i6_target_stack.json`。
- `scripts/validate_i6_local_readiness_soak.py` 以显式 guard、固定隔离端口和 10～300 秒硬上限执行本地短时巡检。当前 60 秒内取得 13 个样本，Road9、TimescaleDB、Kafka、Platform、Console 代理认证和 Dashboard/System API 全程健康，单个整组探针最大 239.84ms；证据见 `docs/test_report_i6_local_readiness_soak.json`。该结果标记为 `isolated_local_non_contract`、阈值 `unverified`，不能替代批准时长的持续运行与生产性能验收。

## 当前阻断项

1. 遗留根 `docker-compose.yaml` 的 Platform 仍配置 `DB_NAME=traffic_platform`，而非目标 `road9`；独立目标 Compose 已正确使用 `road9`，两者不得混称。
2. Compose 仍定义并依赖 InfluxDB/Telegraf/Grafana；这是迁移回归栈，不能作为目标部署清单。
3. `platform/app/core/config.py` 和 `platform/app/utils/influx_query.py` 仍保留遗留契约/工具。
4. 未冻结 S7-TBD-003/004/009/012/013：试点、生产性能环境/负载/阈值/持续时长、RPO/RTO、迁移范围、时间语义、对账阈值、观察期、退役日期和系统指标责任；本地 80 请求烟测不能关闭这些门禁。
5. 已完成历史 Influx 只读盘点和 60 秒本地短时 readiness 巡检，但尚未执行批准的字段/时间转换、逐项回填与对账；也未完成生产备份恢复、批准时长的持续运行、主平台联调和停止旧链路后的回滚演练。

## 安全退役顺序

1. 冻结迁移映射、异常时间处置、对账阈值、双写窗口和回滚观察期。
2. 在目标 Compose 中切换 `road9`/TimescaleDB，保留旧栈为隔离只读对账环境。
3. 完成记录数、关键聚合、边界时间、空值/类型和抽样事件对账。
4. 完成备份恢复、故障注入、持续运行和主平台联调；签署 RPO/RTO 与试点结论。
5. 停止新 Influx 写入并观察；业务/API/告警无回退旧真源。
6. 审批后从目标 Compose、Settings 和运行依赖移除旧组件；旧资产按批准留存策略归档或销毁。

任何一步失败都停止退役并回到最近批准状态，不自动选择更有利的统计结果。

# PRD/UI 滚动计划本地完成审计（2026-07-15）

> 审计结论：I1～I6 的本地可实施工程项已完成；正式总体目标仍被外部合同、生产参数和批准环境阻断。本文不把本地验证等同书面验收。

## 1. 原计划逐项证据

| 范围 | 结论 | 权威证据 | 未关闭边界 |
| --- | --- | --- | --- |
| I1 RoadContext | 本地完成 | `RoadContextResult`、Road9/fixture/Fallback Adapter；`0003` snapshot/binding DDL；S9 PG integration 读取冻结快照 | 权威路网视图、坐标和版本合同 |
| I1 EventDelivery | 本地完成 | canonical envelope/result、disabled 主平台 Adapter；`test_event_delivery.py` 证明合同未批准时固定 blocked、不模拟成功 | 主平台传输、认证、schema、回执、反馈和 SLA |
| I1 MissionOrchestrator/S9 DDL | 本地完成 | `0003` 六类 S9 表、`profile_id` 成对源、revision/UTC/Asia-Shanghai、409/422/503、管理员写权限 | 统一身份正式权限、设备权威和生产 schema |
| I2 调度与持久化 | 本地完成 | once/weekly/跨午夜/例外日、advisory lock、窗口唯一约束、暂停/退役、重启恢复、停止/重试的单元/API/PG 集成测试 | 生产节点归属、规模和 HA |
| I2 真实 MP4/SRT | 本地完成 | `docs/test_report_s9_inter_xqh_eof.json`：5GB 原视频、DJI SRT、恢复新 Pipeline、canonical Topic、自然 EOF；另从 Console2 页面在本地 `road9@20260715_0009` 创建 `MSN-5A61F57DA1D7`，运行 396.663 秒后持久化为 `completed/source_eof` | RTSP/MQTT 生产网络、同步阈值和容量长跑 |
| I3 S1/S2 时序闭环 | 本地完成 | `0004`～`0007`、5 Hypertable、MetricStore、inbox/死信/手动 offset、历史 API、GIS/事件复核；真实管道 56/0/0 | 历史 Influx 回填对账、正式指标规则、生产保留/压缩/容量 |
| I4 S4 执法线索 | 本地完成 | `0008`、candidate zone/rule、统一事件、证据哈希、技术复核、三视图、权威发布 503 门禁 | 批准规则/围栏、雷达检定、法制证据和主平台合同 |
| I5 S8 主任首屏 | 内部工程完成 | DashboardReadModel、四类 API、正式 `/` 无 Mock、WGS84/质量门禁、服务端筛选、异常状态和关键截图 | 项目范围/KPI/底图/权限批准及正式 5 秒/30 秒任务验收 |
| I6 本地验收准备 | 本地完成 | 空库/回滚 migration、Timescale-aware 恢复、断库 200→503→200、80/80 性能烟测、完整目标栈、60 秒/13 样本巡检 | 正式性能阈值、持续运行、RPO/RTO、主平台联调、试点和退役批准 |

## 2. 回归与证据覆盖

- 当前最终门禁：Platform `76 passed / 5 skipped / 11 subtests`；显式 PostgreSQL Mission integration `2 passed`；Console2 `45/45` 与生产构建；根目录轻量+EOF `10 passed`；`git diff --check` 通过。
- `test_pipeline_inter_xqh.py` 的 56 PASS / 0 FAIL / 0 WARN 证明检测/遥测/H/运动补偿基线，不替代 S9 调度、S4 法制或 S7 生产验收。
- `test_main_optimized_eof.py` 是 EOF sentinel 顺序的最小红绿回归；`docs/test_report_s9_inter_xqh_eof.json` 是原始 5GB 调用链证据。
- `scripts/audit_adr019_retirement.py --strict` 必须在以下阻断关闭前继续返回非零。

## 3. 当前六个正式阻断

1. 根 `docker-compose.yaml` 尚未切换 `DB_NAME=road9`。
2. 根 Compose 仍保留 InfluxDB/Telegraf/Grafana 迁移回归服务。
3. 根 Compose 的 Platform 仍声明遗留 Influx 设置/依赖。
4. Platform Settings 仍保留遗留 Influx 配置库存。
5. `platform/app/utils/influx_query.py` 仍保留用于迁移比较。
6. S7-TBD-003/004/009/012/013 所需试点范围、性能环境、RPO/RTO、历史映射/对账阈值、观察期和退役日期没有书面批准。

前五项不能在第六项及历史对账/回滚依据未关闭时提前删除，否则会破坏迁移回退能力。下一步需要外部责任方提供批准输入或授权生产演练；在此之前总体状态保持 `blocked_external`。

## 4. 阶段交付状态

- 本地工程门禁已完成：Platform `76 passed / 5 skipped / 11 subtests`、Console2 `45/45` 和生产构建、根目录轻量及 EOF `10 passed`、`inter_xqh` `56 PASS / 0 FAIL / 0 WARN`、`git diff --check`。
- S9 页面真实验收的任务、计划、数据源、Pipeline、时间线和截图索引见 `console2/design-qa.md` 与 `docs/TASKS.md` T-449。
- 当前基线分支为 `codex/2.0`、提交 `fad252f`；工作树包含本轮 I1～I6 的大量未提交实现与文档，后续会话必须先重新检查并整体保护，不能按单文件变更误判或清理。
- `traffic-fly-console` 子模块仍指向 `c368ce7d907ba45796939b4a3a8fa90d64e11622`；本轮正式 UI 落在 `console2`，不要把两套前端混写。
- 阶段交接文档按 `handoff` 规则生成在系统临时目录，只作为续接入口；正式事实仍以本审计、滚动计划、PRD、契约栈、测试报告和任务台账为准。

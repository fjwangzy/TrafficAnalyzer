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
| I3 S1/S2 时序闭环 | 本地完成 | `0004`～`0007`、5 Hypertable、MetricStore、inbox/死信/手动 offset、历史 API、GIS/事件复核；真实管道 56/0/0 | 正式指标规则、生产保留/压缩/容量；历史数据不迁移 |
| I4 S4 执法线索 | 本地完成 | `0008`、candidate zone/rule、统一事件、证据哈希、技术复核、三视图、权威发布 503 门禁 | 批准规则/围栏、雷达检定、法制证据和主平台合同 |
| I5 S8 主任首屏 | 内部工程完成 | DashboardReadModel、四类 API、正式 `/` 无 Mock、WGS84/质量门禁、服务端筛选、异常状态和关键截图 | 项目范围/KPI/底图/权限批准及正式 5 秒/30 秒任务验收 |
| I6 本机纯净切换 | 本地完成 | 唯一根 Compose、空白 `road9@0010`、5 hypertable、管理员 1 条/业务 0 条、断库 200→503→200、最终镜像正式端口 1800.225 秒/61 样本巡检、18 项本机退役报告与严格审计 | 正式性能阈值、RPO/RTO、主平台联调、试点和生产退役批准 |

## 2. 回归与证据覆盖

- 当前最终门禁（更新于 2026-07-17）：Platform `104 passed / 5 skipped / 10 subtests`；Console2 `56/56` 与生产构建；根目录轻量/EOF/Kafka/Compose/遥测既有门禁保持通过；`test_pipeline_inter_xqh.py` 基线为 56/0/0。
- `test_pipeline_inter_xqh.py` 的 56 PASS / 0 FAIL / 0 WARN 证明检测/遥测/H/运动补偿基线，不替代 S9 调度、S4 法制或 S7 生产验收。
- `test_main_optimized_eof.py` 是 EOF sentinel 顺序的最小红绿回归；`docs/test_report_s9_inter_xqh_eof.json` 是原始 5GB 调用链证据。
- T-456 轨迹投放复验以 `road9` 真实事实为准：`INT_camera_1` 查询得到 285/285 条至少 6 个世界坐标点的轨迹；Mission `MSN-3421232DD4B9` 在 Console2 `/gis` 实际投放 149/149 条彩色折线，浏览器 console 0 error / 0 warning。证据与口径见 `docs/test_report_mp4_srt_product_deep_demo.md`、`console2/design-qa.md` 和 `docs/TASKS.md`。
- `scripts/audit_adr019_retirement.py --scope local --strict` 已通过；`--scope production` 继续返回 `blocked_external`。

## 3. 当前正式阻断

本机 Compose、旧运行时依赖、旧消息兼容和旧容器阻断均已关闭；历史数据明确不迁移。尚未关闭的是生产性能环境与阈值、TLS/SASL/秘密管理、HA、RPO/RTO、试点范围、主平台联调和生产退役批准。下一步需要外部责任方提供批准输入或授权生产演练；在此之前生产状态保持 `blocked_external`。

## 4. 阶段交付状态

- 本地工程门禁已完成：Platform `104 passed / 5 skipped / 10 subtests`、Console2 `56/56` 和生产构建、`inter_xqh` 基线 `56 PASS / 0 FAIL / 0 WARN`、本机严格退役审计通过。
- S9 页面真实验收的任务、计划、数据源、Pipeline、时间线和截图索引见 `console2/design-qa.md` 与 `docs/TASKS.md` T-449。
- T-456 已关闭“有计数但无可见历史轨迹”的本地缺陷；默认全部任务返回 285 条可投放轨迹，单任务 `MSN-3421232DD4B9` 返回并绘制 149 条。通用轨迹 API 仍默认返回全部事实，GIS 才显式使用 `spatial_ready=true&min_world_points=6`。
- 本次收尾检查分支为 `codex/2.0`、HEAD `23252d6`；工作树包含 I1～I6、ADR-019 和产品深度展示的大量未提交实现与文档，后续会话必须先重新检查并整体保护，不能按单文件变更误判或清理。
- `traffic-fly-console` 子模块仍指向 `c368ce7d907ba45796939b4a3a8fa90d64e11622`；本轮正式 UI 落在 `console2`，不要把两套前端混写。
- 阶段交接文档已按 `handoff` 规则生成在 `/private/tmp/TrafficAnalyzer-handoff-2026-07-17-mp4-srt-deep-demo-closeout.md`，只作为续接入口；正式事实仍以本审计、滚动计划、PRD、契约栈、测试报告和任务台账为准。

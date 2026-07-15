# I1 `road9` 对象归属与最小契约冻结矩阵

> 状态：内部工程契约已冻结并滚动实施到 `20260715_0009`；外部合同继续阻断  
> 所属迭代：I1  
> 核查日期：2026-07-15  
> 依据：ADR-019、总 PRD v2.1、S5/S6/S9 分册、`API_CONTRACTS.md`、`DATABASE_SCHEMA.md`

## 1. 已核实的本地开发事实

- PostgreSQL connection database 为 `road9`。
- 当前 Alembic head 为 `20260715_0009`，版本表为 `public.uav_alembic_version`；空库、`20260714_0002` 升级、`0009` 降级/再升级及 Timescale-aware 备份恢复均已验证。
- 当前只有 `public` 应用 schema；这不等于生产目标 schema 已冻结。
- 既有普通 PostgreSQL 开发实例不强制安装 TimescaleDB；隔离目标栈已验证 TimescaleDB 2.28.2/PostgreSQL 17、5 张 Hypertable 和 41 张 `uav_*` 表。生产发行版本和参数仍未获 DBA 批准。
- S5 RoadContext/绑定、S6 feedback/inbox、S9 Drone/Source/FlightPlan/Mission/Pipeline 普通表已由 `0003` 创建；I3 时序事实、死信和复核状态由 `0004`～`0007` 创建；I4 执法对象由 `0008` 创建；`0009` 修复恢复安全性。

## 2. 对象归属与迁移矩阵

| 对象组 | 当前对象/载体 | 目标真源 | 当前状态 | I1 决策与后续动作 |
| --- | --- | --- | --- | --- |
| 用户/告警 | `uav_users`、`uav_alerts` | `road9` 普通表 | 已存在 | 保留；后续随统一身份和事件外键做前向扩展，不另建同义表 |
| S3 测绘 | `uav_survey_*`、capture、scene annotation | `road9` 普通表 | 已存在并验证 | 保留当前闭环；只通过前向 migration 增加跨模块引用，不回写历史迁移 |
| 证据 | `uav_evidence_packages/items` | 全场景唯一证据真源 | 已存在 | S4/S6 复用；禁止新建执法/集成专用证据主表 |
| AI 事件 | `uav_ai_events` | S1～S4 对外交付事件唯一主表 | S3 最小实现 | 扩展通用事件时间、质量、路网、外部映射和状态字段；保持 S3 兼容 |
| 可靠投递 | `uav_event_outbox`、attempt、dead-letter | 全场景唯一投递真源 | S3 最小实现 | 前向增加 `source_system/message_id/next_retry_at` 等通用字段及组合唯一性；补 `uav_event_feedback` |
| 消费幂等 | Kafka auto commit + 内存处理 | `uav_message_inbox` + 事实同事务 | 表/契约已实现 | I3 接入 canonical consumer、手动 offset 与崩溃恢复 |
| 权威路网 | 尚未确认的 `road9` 外部视图/API | 外部拥有的版本化只读对象 | 阻断 | 数据负责人冻结视图、字段、几何、代码、SRID/GCJ02、版本和权限；UAV 不复制主库 |
| RoadContext | Road9/fixture Adapter | `uav_road_context_snapshots` 元数据 + 外部只读事实 | 内部接口已实现 | 外部权威视图未签署时只返回 `unverified/blocked` |
| 视觉绑定 | JSON/标定文件/运行数据 | `uav_visual_lane_bindings` | `0003` 已实现表和 RoadContext 读取 | 外部权威 Link/车道合同未签署前保持 candidate/unverified；后续补批准的人工确认流程 |
| 设备绑定 | 内存 intersection/device map | `uav_device_intersection_bindings` | `0003` 已实现普通表 | 只保存设备/任务到权威 `inter_id` 的有效期绑定，不建第二套路口底库；权威设备合同仍阻断 |
| 无人机资产 | PostgreSQL repository + 遥测缓存 | `uav_drones` | 已实现 | 在线状态由新鲜遥测派生，不保存为静态权威状态 |
| 数据源 | SourceProfile API 聚合 | `uav_video_sources` + `uav_telemetry_sources` | 已实现 | 不建第三张重复真源表；密钥只存 reference，路径 realpath+allowlist |
| FlightPlan | PostgreSQL repository | `uav_flight_plans` | 已实现 | once/weekly、跨午夜、例外日、revision；只控制 AI Pipeline |
| Mission | PostgreSQL repository | `uav_missions` | 已实现 | 冻结快照、实际时间、原因、retry 父子关系和首次窗口唯一性 |
| Pipeline | PostgreSQL 摘要 + PipelineManager 句柄 | `uav_pipelines` + 运行时句柄 | 已实现 | PID/句柄继续内存，重启按持久化事实恢复 |
| 交通指标 | Kafka cache + InfluxDB | `uav_traffic_metrics` Hypertable | `0004` + MetricStore 已实现 | 生产指标口径、chunk/压缩/保留和历史对账仍待批准 |
| 轨迹 | Kafka/InfluxDB | `uav_track_events` + `uav_track_points` Hypertable | `0004` + 历史 API 已实现 | 主记录与时序点分离；生产保留和历史唯一键对账仍阻断 |
| 冲突 | Kafka/InfluxDB | `uav_conflict_events` Hypertable + 必要 `uav_ai_events` | `0004`～`0007` + 技术复核已实现 | 冲突事实不复制投递状态；正式规则、验收集和主平台处置仍阻断 |
| 遥测 | 内存 deque + Kafka | `uav_telemetry_metrics` Hypertable | `0004` + MetricStore 已实现 | 当前状态由最新有效采样派生；生产采样、保留和容量仍阻断 |
| 系统指标 | Kafka cache/旧链路 | `uav_system_metrics` Hypertable | `0004` + 系统历史查询已实现 | 生产指标目录、单位/标签、采样、保留和告警阈值仍阻断 |
| Dashboard | Console2 正式 `/` | 可重建 DashboardReadModel | I5 聚合 API 与真实 UI 已实现 | 不建 dashboard 业务真源表；未批准 KPI/项目范围显示待冻结，正式 5 秒/30 秒验收仍阻断 |

## 3. Migration 波次

### Wave A：普通表兼容扩展

1. 为 S6 通用事件投递扩展现有 AI event/outbox/attempt/dead-letter，并新增 feedback。
2. 新增 message inbox、RoadContext snapshot、visual lane binding 和 device-intersection binding。
3. 新增 S9 Drone、video source、telemetry source、FlightPlan、Mission、Pipeline。
4. 所有变化使用新的前向 Alembic revision；已执行的 `20260714_0001/0002` 保持不可变。

### Wave B：TimescaleDB 与时序事实（本地工程完成）

1. 隔离目标镜像已安装并验证 TimescaleDB 2.28.2/PostgreSQL 17；生产版本、许可、权限和 HA 仍待 DBA 批准。
2. 五张 Hypertable、`uav_track_events` 主表和必要索引已创建；压缩、保留和连续聚合不得在生产批准前固化。
3. 空库迁移、升级/回滚、TIMESTAMPTZ/JSONB/Decimal、备份恢复和断库恢复已完成本地验证。

### Wave C：迁移与切读（本地切读完成，正式退役阻断）

1. canonical consumer 已写入 inbox + 事实表并在成功后手动提交 offset。
2. 旧消息由兼容 Adapter 规范化；当前生产者只生成 canonical `uav_*` Topic。
3. 正式历史 API 和 Console2 已切读 `road9`；历史双写/回填对账、观察期和停止 InfluxDB 新写入尚待批准。
4. 本地备份恢复、故障注入和回滚演练已完成；生产演练、RPO/RTO 和 Telegraf/InfluxDB/Grafana 退役仍阻断。

## 4. I1 待冻结决策

| 决策 | 责任方 | 阻断范围 | 关闭证据 |
| --- | --- | --- | --- |
| `road9` 生产目标 schema、权威路网只读视图、字段/代码/几何/SRID/版本 | 数据负责人、GIS、DBA | RoadContext、S1/S2/S4/S8 | 签字数据字典、只读访问说明、坐标实测和版本制度 |
| TimescaleDB 版本、发行形态、许可、chunk、压缩、保留、备份恢复、RPO/RTO | DBA、架构、运维 | Wave B/C、S7 | 批准数据库方案和目标环境演练记录 |
| 主平台传输、认证、schema、错误码、回执、反馈、SLA 和幂等保留 | 主平台方、S6、网安 | EventDelivery、正式投递 | 双方签字接口规范和联调环境 |
| 无人机设备权威、secret reference、RTSP/MQTT、MP4/SRT 校验和权限 | 无人机作业方、S9、网安 | S9 API/DDL/验收 | 接入规范、权限矩阵和批准测试材料 |

在上述外部决定未关闭前，可继续实现不依赖具体名称/阈值的模块接口、测试 Adapter 和 migration 验证框架，但不得把候选 schema、凭据或阈值固化为生产事实。

## 5. I1 退出检查

- [x] 核实本机 `road9`、migration、schema、扩展和现有表。
- [x] 明确现有对象、目标真源及迁移波次，不建立重复表。
- [x] 冻结 RoadContext 最小 shape 与权威源 Adapter 契约。
- [x] 冻结 EventDelivery 最小 shape、状态机和禁用主平台 Adapter 契约。
- [x] 冻结 MissionOrchestrator 的 S9 ERD、状态机、权限和错误语义。
- [x] 明确 TimescaleDB 安装/参数延后到 I3 目标环境验证，未经 DBA 批准不固化。
- [x] 将内部冻结结果同步到 API、数据库、S5/S6/S9 分册和总 PRD；外部阻断项保持未关闭。

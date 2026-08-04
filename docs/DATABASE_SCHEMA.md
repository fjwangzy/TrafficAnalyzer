# DATABASE_SCHEMA.md — TrafficAnalyzer 数据库结构

> 2026-07-16 本机开发环境已用全新 `road9`/TimescaleDB 纯净初始化，不迁移任何旧库或旧消息历史。生产 TimescaleDB 参数、权威围栏/规则、法制证据和主平台合同仍须书面批准。

## 1. 已冻结的数据架构决策（目标态）

以下决策由项目方确认，自 2026-07-13 起作为后续设计、开发与验收基线：

| 决策项 | 目标契约 |
| --- | --- |
| PostgreSQL connection database | `road9`；这是连接参数中的 database，不自动解释为同名 schema |
| 时序能力 | 在 `road9` 安装并启用 TimescaleDB 扩展 |
| 无人机平台自建表 | 表名一律以 `uav_` 开头 |
| 消息命名 | Kafka Topic、`msg_type` 及平台实时消息类型一律以 `uav_` 开头 |
| 指标权威存储 | PostgreSQL/TimescaleDB |
| 废弃链路 | Grafana、Telegraf、InfluxDB 不进入目标部署和验收链路 |

这里的 `uav_` 表前缀约束只约束无人机平台创建、迁移和拥有的表，不要求改名、复制或迁移智慧交通大项目已有的路网主数据表。现有路网表由数据资产方拥有，无人机平台只读引用。此前对 `ycx` connection database 和 `road10` schema 的只读调查仅作为历史证据，不再构成目标连接或权威数据源选择。

以下内容仍为 `【待确认】`，不得写死为已具备：

- `road9` connection database 的实际连接地址、目标 schema、账户、TLS、连接池和读写权限；不能因为 database 名称为 `road9` 就假定 schema 也叫 `road9`；
- TimescaleDB 可用版本、安装权限、license 能力与 `CREATE EXTENSION` 执行主体；
- 路网表/视图准确名称、字段、代码表、几何类型、SRID、GCJ02 语义和版本有效期规则；
- 生产数据量、chunk 大小、压缩/列式存储能力和保留期。

### 1.1 本地开发库实况（2026-07-16 纯净切换）

- 当前连接 database 为 `road9`，应用对象位于 `public`；这只是本地开发现状，不代表生产目标 schema 已冻结。
- migration head为`20260728_0020`，版本表为`uav_alembic_version`；`0012`增加检测事实lineage，`0013`增加inbox可恢复派发，`0014/0015`增加轨迹研判维度/索引，`0016/0017`建立GCJ-02渠化地图与多视频源视觉配准，`0018`增加路口项目、视频接入、分段素材绑定和标定检查审计，`0019`增加飞行分段、跟踪profile与运行质量字段。`0020`中的独立地理注册表已在本机应用但现已停用，保留仅为非破坏性迁移兼容；运行时世界事实改由视频/SRT当前帧矩阵生成。
- 正式本机端口 `5432` 由根 Compose 的 TimescaleDB 提供，使用稳定新卷 `traffic_road9_data`；不挂载旧 PostgreSQL、实验 TimescaleDB 或旧目标卷。
- migration 自动启用 TimescaleDB 并创建 5 张 `uav_*` hypertable。初始化数据仅允许管理员账号，业务、指标、轨迹、任务和告警表为空。
- `uav_traffic_metrics`、`uav_track_points`、`uav_conflict_events`、`uav_telemetry_metrics`、`uav_system_metrics`、普通表 `uav_track_events` 及长期 `uav_message_inbox` 已实现。永久性输入错误进入独立的 `uav_message_dead_letters`；可变技术复核状态位于普通表 `uav_conflict_reviews`，两者都不更新追加型冲突事实。
- I4 已创建候选围栏、候选规则、执法线索详情和追加型复核审计表；执法线索仍以 `uav_ai_events(event_type=enforcement_clue)` 为唯一事件主记录，证据复用通用 `uav_evidence_*`，没有复制事件或投递状态机。
- 本地扩展版本仅是工程验证基线；生产版本、许可、chunk、压缩、保留、连续聚合、容量、备份恢复和 HA 参数仍为验收阻断项。

对象归属、迁移波次和待冻结责任见 [`docs/superpowers/plans/2026-07-15-road9-contract-freeze-matrix.md`](superpowers/plans/2026-07-15-road9-contract-freeze-matrix.md)。

## 2. PostgreSQL/TimescaleDB 逻辑架构（I3 工程实现）

```text
uav_* Kafka topics / Platform APIs
  -> UAV message consumer（校验 schema_version + 幂等去重）
     -> 普通 PostgreSQL 表：业务状态、配置、绑定、投递状态
     -> TimescaleDB hypertables：指标、遥测、轨迹和冲突时序事实
        -> Platform REST/WebSocket 查询与聚合

road9 路网主数据（外部拥有，只读）
  -> 版本快照/只读视图/API
  -> uav_road_context_snapshots + uav_visual_lane_bindings
  -> 事件和时序事实只保存版本化引用，不修改路网主数据
```

目标部署不再包含 `Kafka -> Telegraf -> InfluxDB -> Grafana` 路径。Kafka 可继续作为实时消息总线，但持久化消费者直接写入 `road9`；平台看板和历史 API 从 PostgreSQL/TimescaleDB 查询。

### 2.1 扩展与迁移管理

建议的目标初始化前置条件如下；具体 DDL 由 DBA 审核后执行：

```sql
-- 目标 database: road9
CREATE EXTENSION IF NOT EXISTS timescaledb;
```

- 扩展是否已安装、版本是否符合项目要求、应用账户能否执行扩展安装均为 `【验收阻断】【待确认】`。
- 平台迁移版本表必须命名为 `uav_alembic_version`；不得创建默认的 `alembic_version` 等无 `uav_` 前缀自建表。
- 应用运行账户不应拥有扩展安装、database 创建或路网主表 DDL 权限；安装/升级由 DBA 账户执行。
- 所有 DDL、hypertable 转换、策略创建和回滚脚本必须纳入版本化迁移，不依赖运行时 `create_all()` 隐式建表。

## 3. 表职责总览（I1 契约；普通表按 migration 实现）

### 3.1 TimescaleDB hypertable

| 表名 | 时间列 | 事实粒度 | 推荐唯一键 | 主要用途 |
| --- | --- | --- | --- | --- |
| `uav_traffic_metrics` | `observed_at` | 路口/道路/车道/采样时刻 | `(observed_at, source_system, source_message_id, grain_type, grain_key)` | 车辆数、速度、排队、方向流量、拥堵指标 |
| `uav_track_points` | `observed_at` | 一条轨迹的一个时序点 | `(observed_at, source_system, source_message_id, point_seq)` | 轨迹点序列、时空查询和 BEV 复盘 |
| `uav_conflict_events` | `occurred_at` | 一次冲突事件/升级 | `(occurred_at, source_system, source_message_id)` | TTC/PET、冲突证据和风险复盘 |
| `uav_telemetry_metrics` | `observed_at` | 无人机遥测采样 | `(observed_at, source_system, source_message_id)` | 飞行轨迹、姿态、云台和定位质量 |
| `uav_system_metrics` | `observed_at` | 实例/设备/指标采样 | `(observed_at, source_system, source_message_id, metric_name)` | GPU、CPU、内存、管道和消息积压 |

这些表保存追加型时序事实。告警确认、事件投递状态、用户、任务等会被更新的业务对象不得为了“统一”而强行做成 hypertable。

### 3.2 普通 PostgreSQL 表

| 表名 | 主键/唯一性候选 | 职责 |
| --- | --- | --- |
| `uav_users` | `id`；`username`、`email` 唯一 | 平台用户与角色 |
| `uav_alerts` | `id` | 告警当前状态、确认信息和证据引用 |
| `uav_drones` | `id`；设备编码/序列号候选唯一 | 无人机身份、型号、启用状态、默认路口和默认源引用；在线状态由遥测计算 |
| `uav_video_sources` | `id` | RTSP/服务器 MP4 配置、密钥引用、启用和验证状态；打开的 stream 不入库 |
| `uav_telemetry_sources` | `id` | MQTT、服务器 SRT 或 DJI Cloud JSON 遥测配置；`config` 保存回放时间偏移/同步容忍窗口，另含密钥引用、启用和验证状态 |
| `uav_flight_plans` | `id` | 单次/周期计划、时区、路网/源引用、状态和修订版本 |
| `uav_missions` | `id`；`(flight_plan_id, scheduled_start_at)` 首次执行唯一 | 一次计划窗口或立即执行任务的生命周期、计划快照、实际时间、原因和 pipeline 引用 |
| `uav_pipelines` | `id` | 分析管道实例与运行状态 |
| `uav_audit_logs` | `id`；主体/业务对象/发生时间索引 | 配置、启停、自动执行、失败、停止、重试和敏感操作审计 |
| `uav_track_events` | `id`；`(source_system, source_message_id)` 唯一 | 完成轨迹业务主记录、摘要和轨迹点父对象 |
| `uav_conflict_reviews` | `event_id` | 冲突事实的可变技术复核状态与 revision；不代表警情处置或违法认定。`20260715_0009` 以 existence guard + delete cascade trigger 替代不可可靠恢复的 regular→Hypertable FK |
| `uav_enforcement_zones` | `id`；候选配置 revision | 本地候选电子围栏及几何快照；权威 Adapter 未冻结时不能发布为权威配置 |
| `uav_enforcement_rules` | `id`；`rule_version_id` | 执法候选规则领域内容，引用 `uav_rule_versions`，不得保存违法或处罚结论 |
| `uav_enforcement_clues` | `event_id`；`source_event_id` 唯一 | `uav_ai_events(event_type=enforcement_clue)` 的执法专属事实，不复制事件状态机 |
| `uav_enforcement_review_audits` | `id`；`event_id/revision` 索引 | AI 线索技术确认/驳回的追加型审计；不代表违法认定、案件或处罚状态 |
| `uav_ai_events` | `(source_system, source_event_id)`；`(source_system, idempotency_key)` 唯一 | 向智慧交通主平台交付的 AI 事件主记录 |
| `uav_event_outbox` | `id`；`(source_system, message_id, destination)` 唯一；外发幂等键另设条件唯一 | 待投递消息、下一次重试时间和当前投递状态 |
| `uav_event_delivery_attempts` | `id` | 每次投递尝试和响应摘要 |
| `uav_event_feedback` | `id`；`(source_system, feedback_idempotency_key)` 唯一 | 主平台确认/驳回和结果反馈审计 |
| `uav_dead_letters` | `id` | EventDelivery/outbox 对外投递超过重试上限后的人工补偿入口 |
| `uav_message_dead_letters` | `(topic, partition, offset)` 唯一 | 入站 Kafka schema/身份冲突等永久错误的耐久隔离；成功写入后才可推进对应 offset |
| `uav_evidence_packages` | `id`；`(source_system, source_event_id)` 索引 | 事件证据清单、对象存储引用、哈希和完整性元数据 |
| `uav_evidence_items` | `id`；`package_id` 索引 | 单个图片/视频/测绘/结构化证据项；`storage_backend=managed|server_asset` 区分内容寻址对象与 allowlist 原文件引用；新冲突事件使用 `conflict_original_frame`、`conflict_detector_frame` 两项，后者是 `ShowNode.frame_result` 的原尺寸 JPEG，禁止证据侧重绘。检测图以 `derived_from_id` 指向原图并在 metadata 保存同一帧时间。检测任务先写 managed 内容地址，Platform 校验相对 `storage_key`、大小和 SHA-256 后只登记引用；历史 `conflict_trajectory_reconstruction`/`conflict_keyframe` 保留。`survey_report_annotated_image` 保存报告固化的带逐边长度 JPEG，并以 `derived_from_id` 指向 BEV、metadata 记录报告版本/帧/量算数；server asset 的 `item_metadata.source_fingerprint` 保存 size/mtime/ctime，指纹变化后必须回退到完整 SHA-256 校验 |

`storage_backend=managed` 的 `storage_key` 只保存内容地址，不包含图片本体。road9 备份、恢复或运行拓扑切换必须同时保留对应对象目录；本机原生 Platform 的 canonical 目录为 `.runtime/survey`，不能把 `/tmp/traffic-survey-data` 当作持久证据源。引用存在但对象缺失属于完整性失败，应返回 `409` 并进入修复清单，禁止伪造或静默替换。
| `uav_message_inbox` | `(source_system, message_id)` 唯一 | 长期 canonical 消费幂等、消息身份校验、处理状态与事实引用审计 |
| `uav_road_context_snapshots` | `(road_data_version, inter_id)` | 路网只读版本快照/缓存元数据 |
| `uav_visual_lane_bindings` | `(binding_id)`；业务唯一键待定 | 本地视觉车道到权威路口/Link/车道的版本化绑定 |
| `uav_alembic_version` | `version_num` | UAV 平台数据库迁移版本 |

若后续新增任何中间表、审计表、关联表、物化结果表或 Timescale continuous aggregate，其物理名称同样必须以 `uav_` 开头。TimescaleDB 自动创建的内部对象不属于平台自建表，不受此前缀约束。

所有消息、事件、投递、反馈和证据相关普通表都必须保存 `source_system`，canonical 值固定为 `uav_traffic_analyzer_ai`；涉及消息 ID、事件 ID 或幂等键的跨系统唯一约束必须把 `source_system` 纳入组合键。

### 3.3 规划业务表目录（PRD 级、DDL 待冻结）

> 本目录来自总 PRD 与 S5 分册的逻辑实体，是后续 migration/DDL 评审输入，不表示这些表已经创建或字段已经冻结。第 3.1、3.2 节列出的 canonical 核心表仍是唯一基线；本节与核心表同名的条目表示补充其业务字段，不得重复建表或另造同义表。

| 领域 | 规划物理表 | 形态候选 | 与 canonical 基线的关系 | DDL 待冻结重点 |
| --- | --- | --- | --- | --- |
| 事故测绘 | `uav_survey_tasks` | 普通表 | 测绘任务主对象；结果事件统一关联 `uav_ai_events(event_type=survey_result)` | 状态机、任务分配、任务/事件唯一关系、软删除 |
| 事故测绘 | `uav_capture_batches` | 普通表 | 隶属测绘任务，`source_profile_id` 关联目录来源并组织视频/帧引用、遥测、标定和质量检查 | batch 唯一键、时间范围、coverage、版本、内容哈希 |
| 事故测绘 | `uav_capture_frames` | 普通表 | 已实现的关键帧事实，关联原始帧/BEV 证据、遥测、质量和帧变换 | 帧号与 batch 唯一、派生证据完整性 |
| 事故测绘 | `uav_capture_ingestion_jobs` | 普通表 | 已实现的 MP4+DJI SRT/Cloud JSON 后台处理任务 | batch 唯一、状态、attempt/max_attempts、错误与完成时间 |
| 事故测绘 | `uav_survey_measurements` | 普通表候选 | 隶属 `uav_survey_tasks`，保存点/线/面量算值和误差 | 几何/数值类型、坐标系、单位、修订版本、唯一键 |
| 事故测绘 | `uav_scene_annotations` | 普通表/PostGIS 候选 | 隶属 capture batch/测绘任务，保存事故车辆、痕迹和散落物的版本化标注 | category、geometry/SRID、来源、置信度、review_state、版本链 |
| 事故测绘 | `uav_survey_reports` | 普通表 | 报告元数据；证据材料引用 `uav_evidence_packages`、`uav_evidence_items` | 报告版本、签章/导出引用、不可变状态和保留期 |
| 执法 | `uav_enforcement_zones` | 已实现普通表 | 只保存本地候选电子围栏，不复制或覆盖权威路网几何 | authority_status、geometry/checksum、road_data_version、revision、retired |
| 执法 | `uav_enforcement_rules` | 已实现普通表 | 执法候选规则内容，引用共性 `uav_rule_versions` | 候选事实 schema、适用区、revision、retired；权威发布保持 503 |
| 执法 | `uav_enforcement_clues` | 已实现一对一详情表 | 仅保存 `uav_ai_events(event_type=enforcement_clue)` 专属事实，不另建事件主表或状态机 | 车辆二分类、视频/雷达/融合字段隔离、规则/围栏快照、质量边界 |
| 执法复核 | `uav_enforcement_review_audits` | 已实现追加型普通表 | 记录技术确认/驳回及 revision，不改写线索事实 | actor、reason、from/to status、reviewed_at；不含处罚状态 |
| 证据 | `uav_evidence_packages` | 已实现 canonical 普通表 | 第 3.2 节既有基线；`owner_type/owner_id` 支持测绘与执法事件共用 | 包版本、事件关联、内容哈希、存储状态、保留策略 |
| 证据 | `uav_evidence_items` | 已实现 canonical 普通表 | 第 3.2 节既有基线；保存执法原视频/SRT/帧/片段等不可变引用 | 材料类型、父子派生、哈希、对象引用、访问控制 |
| 审计 | `uav_audit_logs` | canonical 追加型普通表/分区表候选 | 第 3.2 节既有基线；统一记录同步、发布、绑定、调阅、导出、删除、调度和回滚 | 审计主体、前后值、trace_id、防篡改、归档分区 |
| 路网上下文 | `uav_road_context_snapshots` | canonical 普通表 | 第 3.2 节既有基线；缓存 manifest/校验值，不复制权威路网库 | 快照内容边界、校验、发布/退役、保留和回滚 |
| 设备绑定 | `uav_device_intersection_bindings` | 普通表 | 无人机/相机/任务到权威路口的有效期映射 | 设备类型、有效期排他约束、任务优先级、审计 |
| 视觉车道绑定 | `uav_visual_lane_bindings` | canonical 普通表 | 第 3.2 节既有基线；本地车道到 inter/link/lane 的版本化绑定 | calibration/version 唯一键、确认/退役、差异与回滚 |
| 地图匹配 | `uav_map_match_results` | 普通表/分区表候选 | 轨迹/事件的匹配结果或候选；权威 ID 同时回写对应事实摘要 | subject 类型、候选集、revision、置信度、拒判原因、保留期 |
| 规则治理 | `uav_rule_versions` | 普通表 | 拥堵、冲突、测绘和执法共用的规则发布元数据 | 规则类型、schema、审批、生效窗口、原子切换和回滚 |
| 无人机资产 | `uav_drones` | canonical 普通表 | 第 3.2 节既有基线；保存 UAV 平台所需设备身份、型号和配置；时序遥测仍进 `uav_telemetry_metrics` | 与大项目设备主数据关系、唯一编码、状态快照边界 |
| 无人机接入 | `uav_video_sources` | canonical 普通表 | 第 3.2 节既有基线；保存 RTSP/服务器 MP4 配置与验证状态，运行时 stream 不入库 | secret reference、脱敏、allowlist、验证状态、与遥测源配对 |
| 无人机接入 | `uav_telemetry_sources` | canonical 普通表 | 保存 MQTT、服务器 DJI `.srt` 或 DJI Cloud JSON 配置与验证状态 | secret reference、Topic、allowlist、`config.time_offset_sec/sync_tolerance_sec`、解析/覆盖质量、与视频源配对 |
| 飞行计划 | `uav_flight_plans` | canonical 普通表 | 第 3.2 节既有基线；保存 once/weekly 计划定义，不保存真实飞控航线 | schedule schema、IANA timezone、跨午夜、例外日期、状态、修订和冲突查询 |
| 任务执行 | `uav_missions` | canonical 普通表 | 第 3.2 节既有基线；每个计划窗口或立即请求形成一个执行事实 | `(flight_plan_id,scheduled_start_at)` 唯一、状态机、快照、retry 父子关系、错误分类 |
| 管道执行 | `uav_pipelines` | canonical 普通表 | 第 3.2 节既有基线；保存 Mission 的 Pipeline 期望状态和摘要，进程句柄留内存 | Mission 关系、节点归属、恢复、停止和错误摘要 |
| 标定 | `uav_calibrations` | 普通表 | 保存标定版本、适用设备/路口、参数引用和质量状态 | 参数 schema、版本、审批、有效期、文件/对象引用 |
| 车道标注任务 | `uav_lane_annotation_tasks` | 普通表 | 承接现有 JSON/文件任务状态；确认结果关联 `uav_visual_lane_bindings` | 任务状态、图片引用、标注版本、幂等和迁移校验 |
| 身份角色 | `uav_roles` | 普通表候选 | 是否从 `uav_users.role` 拆出取决于统一身份/RBAC 模型 | 角色来源、权限关系、同步权威和迁移策略 |
| 数据迁移 | `uav_migration_quarantine` | 已取消，不创建 | 本机不迁移旧数据，因此不得创建迁移隔离表 | 运行态和验收均确认该表不存在 |

#### S3 本地开发迁移基线（2026-07-14）

- Alembic `20260714_0001` → `20260714_0002` 已可在空 PostgreSQL database 上顺序执行，版本表为 `uav_alembic_version`。
- S3 已创建 `uav_survey_tasks`、`uav_capture_batches`、`uav_capture_frames`、`uav_capture_ingestion_jobs`、`uav_survey_measurements`、`uav_scene_annotations`、`uav_survey_reports`，并复用 `uav_evidence_*`、`uav_ai_events`、`uav_event_outbox`、attempt、dead-letter、rule 和 audit 表。
- 本地启动只连接 `road9`、执行 Alembic 并创建管理员；不存在旧用户/告警自动复制路径。
- 当前正式本机库必须具备 TimescaleDB；普通 PostgreSQL 不属于 canonical 验收拓扑。

#### S5/S6/S9 本地开发迁移基线（2026-07-15）

- Alembic `20260715_0003` 以前向方式增加 `uav_road_context_snapshots`、`uav_visual_lane_bindings`、`uav_device_intersection_bindings`、`uav_event_feedback`、`uav_message_inbox` 和六张 S9 普通表，并扩展统一事件投递字段；历史 migration 未修改。
- Alembic `20260716_0011` 增加 `uav_evidence_items.storage_backend`、`uav_capture_batches.source_profile_id` 与 `uav_lane_annotation_tasks`，使原始服务器素材零复制引用、来源到测绘关联和车道标注跨重启持久化进入正式 `road9`。
- `uav_video_sources` 与 `uav_telemetry_sources` 共享 `profile_id` 形成 SourceProfile API 聚合，不创建第三张重复真源表。
- `uav_flight_plans.revision` 用于乐观并发；`uav_missions` 对非空 `(flight_plan_id, scheduled_start_at)` 建唯一约束；Mission 与 Pipeline 使用独立主键和状态字段。
- 已验证隔离空库迁移、`20260714_0002` 升级、`0003 → 0002 → 0003` 回滚恢复演练、真实 PostgreSQL revision 冲突及双调度实例防重。生产 schema、备份恢复、保留期和 TimescaleDB 参数仍须 DBA 书面批准。

#### S4 本地执法候选迁移基线（2026-07-15）

- Alembic `20260715_0008` 以前向方式创建 `uav_enforcement_zones`、`uav_enforcement_rules`、`uav_enforcement_clues`、`uav_enforcement_review_audits`，并为通用证据所有权和 `uav_ai_events` 技术复核摘要增加字段；历史 migration 未修改。
- 已验证空库 `0001 → 0008`、既有 S3 `20260714_0002 → 0008`、隔离库 `0008 → 0007 → 0008`、围栏/规则 revision 冲突、线索幂等和复核 revision。
- 本地围栏与规则始终为 `candidate/unverified`；权威发布接口在 Adapter 和审批合同未冻结时返回 503，不写入伪造的 approved/published 状态。
- `inter_xqh` 工程契约样本只验证真实 MP4/SRT 哈希、证据引用、质量空值、技术复核和持久化；`validation_fixture=true` 且 `detected_enforcement_clue=false`，不得表述为真实违法检测或法制验收。

目录收敛规则：

- `uav_ai_events` 是 S1～S4 对外交付事件的唯一主表；测绘、执法或冲突领域表只能保存任务/配置/专属详情，不得复制事件 ID、投递状态、审核状态和证据主关系。
- `uav_event_outbox`、`uav_event_delivery_attempts`、`uav_event_feedback`、`uav_dead_letters` 是唯一可靠投递与反馈基线，业务分册不得各建一套 outbox/receipt/dead-letter 表。
- `uav_evidence_packages`、`uav_evidence_items`、`uav_road_context_snapshots`、`uav_visual_lane_bindings` 在第 3.2 节已存在；本目录只是补充 PRD 责任，不触发第二套同名或同义表。
- `uav_rule_versions` 保存共性发布元数据，`uav_enforcement_rules` 保存执法领域规则内容；二者通过外键/版本键关联，不重复保存两套生效状态。
- `uav_map_match_results` 是否独立持久化、是否按时间分区，必须由查询需求、数据量和历史复现要求决定；未冻结前不得为了“预留”自动建表。
- S8 全域态势工作台默认通过 `uav_traffic_metrics`、`uav_telemetry_metrics`、`uav_system_metrics`、`uav_ai_events`、`uav_alerts`、任务/管道状态和权威路网只读对象构建读模型，不新建 `dashboard` 业务真源表；待办任务是现有事件、测绘、投递和配置状态的权限化摘要，不新建第二套任务真源。为性能增加的连续聚合、物化视图或缓存须使用 `uav_` 命名、可从事实重建，并保留 `as_of/window/coverage/road_data_version`。
- S9 的 SourceProfile 是 API 聚合，不预先要求独立物理表；`uav_video_sources` 与 `uav_telemetry_sources` 的一对一配对外键/关联方式由 ERD 冻结。不得同时以 profile 表和两张源表保存两套启用、默认或验证状态。
- `uav_flight_plans` 是排期定义真源，`uav_missions` 是执行事实真源，`uav_pipelines` 是分析进程状态真源；三者 ID、状态机和恢复语义不得混用。FlightPlan 只启停 AI Pipeline，不保存或下发真实飞控航线。
- 所有候选表的主键、外键、PostGIS 类型、schema、RLS、索引、分区、保留和迁移顺序由正式 migration/DDL 统一冻结；PRD 表名目录不能替代数据库设计评审。

### 3.4 切换前状态去向盘点（历史快照，迁移方案已取消）

> 本表保存 2026-07-15 切换前的设计盘点，不再是执行计划。其中“迁库”描述的旧数据搬运已取消；当前只由 Alembic 从空库创建 canonical 表并 seed 管理员，Python 对象、进程句柄、打开的视频流等瞬态资源继续留在运行时内存。

| 当前对象/载体 | 当前形态 | 目标 disposition | 目标表/权威源 | 边界与待办 |
| --- | --- | --- | --- | --- |
| DRONES / `drone_store` | 内存设备与最新状态 | 迁库 + 运行时缓存 | `uav_drones`；遥测历史进 `uav_telemetry_metrics` | 设备身份/配置持久化，在线状态由新鲜遥测计算；与大项目设备主数据权威关系 `TBD` |
| MISSIONS | 当前内存状态，创建即启动管道 | 迁库并拆分计划/执行语义 | `uav_flight_plans` + `uav_missions` | FlightPlan 保存排期；Mission 保存一次执行和冻结快照；现有立即执行入口标记 `trigger_type=manual` |
| intersection/device map | 本地映射/配置与外部路网调查 | 外部权威 + 迁库绑定 | 外部权威路口只读视图/API + `uav_device_intersection_bindings` | 不盲建重复 `uav_intersections` 路口底库；仅保存设备/任务到权威 `inter_id` 的版本化绑定 |
| PipelineManager desired/config | 内存管理对象 | 迁库 | `uav_pipelines` | 保存管道配置、期望状态和可恢复状态摘要 |
| PipelineManager 进程句柄/队列/锁 | OS/Python 运行时对象 | 继续内存 | 无数据库表 | PID/handle 不作为可恢复真源；服务重启后按持久化期望状态重新核对/拉起，策略 `TBD` |
| 管道/GPU/系统运行指标 | 内存/消息/旧 InfluxDB | 迁库 | `uav_system_metrics` | 仅追加时序事实；不得把进程对象序列化入库 |
| alerts | 切换前内存 + 无前缀 `alerts` 表 | 历史方案为迁库（已取消旧数据复制） | `uav_alerts` | 当前空库只使用 canonical 表；不复制主平台派警处置状态 |
| calibration / lane annotation JSON | 文件/JSON | 迁库，原文件按迁移期只读保留 | `uav_calibrations`、`uav_lane_annotation_tasks`、`uav_visual_lane_bindings` | 校验版本、坐标、图片/文件哈希和绑定关系；切换后由数据库/API 成为 UAV 配置真源 |
| `video_src` / `telemetry_source` / `telemetry_file_path` | 当前请求中的字符串或环境变量 | 迁库配置 + 运行时解析 | `uav_video_sources` + `uav_telemetry_sources` | 实时 RTSP+MQTT；本地 MP4+DJI `.srt` 或 Cloud JSON 成对；路径 allowlist，凭据只存 secret reference |
| 视频 `_STREAMS` | 运行时 stream 注册表 | 继续内存 | 无配置表之外的运行时表 | 打开的 stream、连接对象和帧缓存不入库；配置只保存在 canonical source 表中 |
| users / role 字段 | 切换前无前缀 `users` 表及行内 role | 历史方案为迁库（已取消旧用户复制）；角色拆表 `TBD` | `uav_users`；可选 `uav_roles` | 当前只 seed 本机管理员；是否拆角色表由统一身份/RBAC 权威模型冻结 |

历史方案原要求逐项给出迁移脚本和旧数据对账，但该要求已随“空库切换、不迁移历史数据”决定取消。标为“继续内存”的对象仍不得为了满足表目录而创建占位表，标为“外部权威”的对象不得被复制成无人机平台路网主库。

## 4. hypertable 公共字段与约束（目标契约）

所有 hypertable 至少包含：

| 字段 | 类型 | 约束/说明 |
| --- | --- | --- |
| `source_system` | TEXT | 非空，唯一 canonical 值 `uav_traffic_analyzer_ai`；参与幂等唯一约束 |
| `source_message_id` | UUID | 对应 canonical envelope 的 `message_id`；生产端生成，重试保持不变 |
| `msg_type` | TEXT | 必须是对应的 `uav_*` canonical 类型 |
| `schema_version` | TEXT | 如 `uav_stats/v1` |
| `observed_at` / `occurred_at` | TIMESTAMPTZ | 业务发生时间，统一以 UTC 存储 |
| `produced_at` | TIMESTAMPTZ | 消息生产时间 |
| `ingested_at` | TIMESTAMPTZ | 数据库接收时间，默认 `now()` |
| `camera_id` | TEXT/NULL | 设备侧相机标识；准确类型待冻结 |
| `drone_id` | TEXT/NULL | 无人机标识 |
| `intersection_id` | TEXT/NULL | 迁移期本地路口标识 |
| `inter_id` | TEXT/NULL | 路网权威路口 ID，无法匹配时为空 |
| `road_data_version` | TEXT/NULL | 与权威路网 ID 同时保存 |
| `road_context_status` | TEXT | `ok/stale/missing/version_mismatch` |
| `source_time_raw` | JSONB/NULL | 原始时间字段和值；迁移/重建后仍保留，禁止覆盖 |
| `source_time_semantics` | TEXT | `event_time/stream_relative/consumer_time/writer_time/reconstructed/unknown` |
| `time_quality` | TEXT | `verified/reconstructed/ingest_only/quarantined` |
| `payload` | JSONB | 暂未结构化或版本扩展字段；高频过滤字段应单列 |

`source_system` 应同时设置非空和检查约束，拒绝 `uav_traffic_analyzer_ai` 以外的替代值；不能只靠应用默认值保证。

`source_time_raw/source_time_semantics/time_quality` 同样适用于 `uav_track_events`、`uav_ai_events` 和 `uav_migration_quarantine` 等承载历史时间的普通表；不得因本节标题为 hypertable 而省略。

### 4.1 时间语义

- 数据库存储使用 `TIMESTAMPTZ` 和 UTC；API 可按请求时区展示，禁止存储无时区本地时间。
- 指标、遥测和轨迹点以各自采样时刻 `observed_at` 分区；冲突以业务发生时刻 `occurred_at` 分区。普通表 `uav_track_events` 不使用 hypertable 时间分区。
- `produced_at` 用于消息延迟评估，`ingested_at` 用于入库延迟和补录识别，二者不能替代业务时间。
- 新 canonical 消息必须提供可验证的业务时间；新写入默认 `source_time_semantics=event_time`、`time_quality=verified`。
- 离线视频回放必须以可证明的录像开始绝对时间/任务时间锚点加流相对秒重建业务时间，并保留原始相对值，设置 `source_time_semantics=reconstructed`、`time_quality=reconstructed` 和 `payload.replay=true`；准确锚点规则 `【待确认】`。

#### 4.1.1 遗留 InfluxDB 时间风险（历史分析，迁移已取消）

> 本节只解释为何不能安全回填旧数据，不产生迁移器、隔离表、对账或回填任务。当前本机库从空数据开始。

当前实现的时间字段不是统一业务时钟：`FrameElement.timestamp` 是视频/流相对秒；完成轨迹的 `timestamp_first/timestamp_last` 也可能是相对秒，但历史写入曾把 `timestamp_last` 当 Unix 秒解释，导致记录落在 epoch 附近。统计和冲突消息缺少统一业务 timestamp 时，Influx writer 会回退到 `time.time()`，此时 Influx point time 表示消费/写入时刻，不是事件发生时刻。

历史方案禁止把所有旧 Influx `time` 一律映射到 `observed_at/occurred_at`；以下表格仅保存已取消方案的风险依据：

| 遗留来源 | 已知语义 | 允许映射 | 禁止做法 |
| --- | --- | --- | --- |
| `camera_*` / `intersection_stats` | 多数为 Telegraf/Platform 消费或写入时刻 | 只证明为 `ingested_at`；若另有录像/任务绝对时间证据，可重建 `observed_at` | 直接声明为车辆观测时刻 |
| `track_events.timestamp_first/last` | 可能是流相对秒 | 原值进 `source_time_raw`；有录像开始绝对时间和同源校验时重建起止时间 | 直接 `to_timestamp(relative_seconds)` |
| epoch 附近的 `track_events` point time | 可能由相对 `timestamp_last` 误作 Unix 秒产生 | 隔离，关联源视频/任务重建；无法重建时经审批丢弃或仅留迁移审计 | 当作 1970 年真实业务事件进入查询 |
| `conflict_events` | 消息常无业务 timestamp，Influx time 可能是 writer fallback | 只证明为 `ingested_at`；有原视频帧/任务时间锚点时才重建 `occurred_at` | 用写入时间计算事件发现时延或 TTC 发生时刻 |

已取消迁移方案曾规定：

1. 每条迁移记录保留 `source_time_raw`、`source_time_semantics`、`time_quality` 和原 measurement/series 标识。
2. 能由源视频绝对开始时间、任务记录或明确业务字段重建的，写入 canonical 表并标记 `reconstructed`，同时保存重建算法/证据引用。
3. 只能证明消费/写入时刻的，只能保存为 `ingested_at`；不得为了满足 hypertable 非空时间列而伪造 `observed_at/occurred_at`。
4. 无法证明业务时间或命中 epoch 异常的记录进入 `uav_migration_quarantine` 候选表，不直接进入 canonical hypertable；由数据负责人决定从源视频重建、保留为迁移审计或批准丢弃。
5. 历史对账、SLA、模型准确率和事件时效统计默认排除 `time_quality=ingest_only/quarantined`，是否纳入特定报表必须显式说明。

### 4.2 唯一键和幂等

- 第一层全局幂等由普通表 `uav_message_inbox` 的唯一键 `(source_system, message_id)` 保证，不受消息时间或 hypertable chunk 边界影响。
- TimescaleDB hypertable 的唯一索引必须包含时间分区列，因此事实表唯一键至少包含“时间列 + `source_system` + `source_message_id`”；一条消息拆成多粒度/多点记录时还必须包含 `grain_type + grain_key` 或 `point_seq`。这是第二层防重，不能代替 inbox。
- `source_message_id` 在生产端首次生成；同一消息重试、旧新 Topic 双投或消费者重放时不得变化。
- 旧消息和无前缀 Topic 已由运行时直接拒绝；不存在为其生成 `source_message_id` 的迁移适配器。
- AI 事件对外投递使用 `idempotency_key`；与内部时序消息的 `source_message_id` 分工明确，不互相替代。
- 禁止用到达时间或数据库自增 ID 作为跨系统幂等键。

`uav_message_inbox` 最少字段与处理规则：

| 字段 | 类型候选 | 说明 |
| --- | --- | --- |
| `source_system` / `message_id` | TEXT / UUID | 组合唯一键；source_system 固定 canonical 值 |
| `payload_hash` | TEXT | canonical 序列化后的内容哈希 |
| `status` | TEXT | `received/processed/failed/quarantined` |
| `topic` / `partition` / `offset` | TEXT / INTEGER / BIGINT | Kafka 来源定位；非 Kafka 输入允许为空并记录 adapter source |
| `first_seen_at` | TIMESTAMPTZ | 首次接收时间 |
| `processed_at` | TIMESTAMPTZ/NULL | canonical 事实成功提交时间 |
| `fact_refs` | JSONB | 实际写入表、主键/时间键引用数组 |
| `error_code` / `error_detail` | TEXT/NULL | 失败/隔离原因；详情必须脱敏 |
| `dispatch_status` | TEXT | `pending/dispatched`；事实提交后等待 WS/告警副作用完成 |
| `dispatch_attempts` / `last_dispatch_error` | INTEGER / TEXT | 派发尝试次数和脱敏错误摘要 |
| `last_dispatch_attempt_at` / `dispatched_at` | TIMESTAMPTZ/NULL | 最近尝试和完成时间 |

- canonical 事实写入和 inbox `status=processed + fact_refs` 更新必须在 `road9` 的同一事务提交；事实失败时不得留下已处理标记。
- 收到相同 `(source_system,message_id)` 且 hash 相同时返回既有结果，不重复写入；hash 不同时隔离到 `uav_message_dead_letters` 并告警，不覆盖原消息或事实。历史批量迁移中无法判定时间语义的记录仍使用独立 migration quarantine 口径。
- inbox 不是迁移期临时表。保留期至少覆盖 Kafka 最大重放窗口、离线回迁窗口和审计追溯窗口；在正式期限冻结前不得早于其关联事实删除。

### 4.3 Kafka consumer 事务与 offset 边界（目标契约）

- Consumer 配置必须 `enable_auto_commit=false` 且新组从 `earliest` 开始。
- 单条消息按“校验 → 数据库事务写 inbox/facts 并标记 `dispatch_status=pending` → 提交事实 → 派发 WS/告警 → 标记 `dispatched` → 手动提交 Kafka offset”执行。
- 数据库事务失败时回滚且不提交 offset；派发失败记录尝试和错误并保持 pending，Kafka 重放时继续派发。只有 dispatched 的重复消息才能跳过副作用。
- 不可重试入站消息必须先把 `uav_message_dead_letters` 记录耐久提交，再手动提交 offset；日志不是耐久隔离。`uav_dead_letters` 继续只处理 EventDelivery/outbox 对外投递失败，二者不得混用。
- Kafka offset 不属于 PostgreSQL 事务，目标是 at-least-once delivery + exactly-once business effect，不能在验收材料中误称为跨系统 exactly-once transaction。

### 4.4 chunk 与索引候选

首版候选策略如下，必须经容量压测和 DBA 评审后冻结：

| 表 | chunk 时间间隔候选 | 常用索引候选 |
| --- | --- | --- |
| `uav_traffic_metrics` | 1 天 | `(inter_id, grain_type, observed_at DESC)`、`(camera_id, observed_at DESC)` |
| `uav_telemetry_metrics` / `uav_system_metrics` | 1 天 | `(drone_id, observed_at DESC)`、`(metric_name, observed_at DESC)` |
| `uav_track_points` | 1 天 | `(track_event_id, observed_at ASC)` |
| `uav_conflict_events` | 7 天 | `(inter_id, occurred_at DESC)`、业务事件/轨迹对 ID |

- 首版不启用额外 space partition，除非容量测试证明单时间维无法满足写入或维护要求。
- JSONB 仅对已确认的过滤路径建立表达式/GIN 索引，避免无差别索引放大写入成本。
- chunk interval 应使活跃 chunk 的索引能进入可用内存；上述数值只是评审起点。

## 5. 指标与事件表核心字段（目标契约）

### 5.1 `uav_traffic_metrics`

除公共字段外，至少包含：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `cars` | DOUBLE PRECISION | 当前车辆数/滑动窗口平均 |
| `active_tracks` | INTEGER | 活跃轨迹数 |
| `avg_speed_kmh` | DOUBLE PRECISION | 平均速度 |
| `queue_count` | INTEGER | 排队车辆数 |
| `congestion_index` | DOUBLE PRECISION/NULL | 拥堵指数，口径待冻结 |
| `direction_flow` | JSONB | 直行、左转、右转、掉头统计 |
| `roads` | JSONB | 动态 Link/道路统计数组；目标主字段 |
| `grain_type` | TEXT | `intersection/link/lane`，决定本行指标粒度 |
| `grain_key` | TEXT | 对应粒度稳定键；优先使用权威 ID，本地键须显式标记 |
| `link_id` / `lane_id` | TEXT/NULL | Link/车道粒度的权威 ID；路口粒度为空 |
| `window_start` / `window_end` | TIMESTAMPTZ | 指标覆盖窗口 |
| `expected_samples` / `actual_samples` | INTEGER | 预期/实际参与样本数 |
| `dropped_samples` | INTEGER | 背压、队列满或采样策略丢弃数 |
| `coverage_ratio` | DOUBLE PRECISION | `actual/expected`，范围 0～1；分母为 0 的规则待冻结 |
| `drop_reason` | TEXT/NULL | 丢弃/降采样原因枚举 |

旧 `road_1`～`road_N` 不由运行时适配器读取，也不作为目标表列展开。`uav_traffic_metrics` 通过 `grain_type` 统一承载路口、Link 和车道粒度，不再拆分另一套车道指标表。目标数据优先使用权威 `link_id/lane_id`、指标值和 `road_data_version` 表达。

### 5.2 `uav_track_events` 与 `uav_track_points`

`uav_track_events` 是普通业务表，地图和世界坐标列全部可空；类型化保存 `track_id`、`association_id`、跟踪方法/质量、地理质量、路网质量、质量原因和可空 `geo_registration_id`。`uav_track_points` 是按 `observed_at` 分区的 hypertable，逐点保存 `track_event_id`、`point_seq`、像素坐标及可空 ENU/GCJ-02；同一轨迹内 `point_seq` 单调递增。像素、源时间、源帧号、ENU 和 GCJ-02 按同一索引；缺失地理能力写空值而不丢点。完整 Kafka payload 继续保留时间/帧号与逐点谱系，不新增第二套轨迹事实表。

### 5.3 `uav_conflict_events`

至少包含事件 ID、机动车/非机动车轨迹 ID、`prediction_type`、TTC、PET、最小距离、冲突角、风险分、严重度、场景、证据、预测位置、地图匹配和质量字段。同一轨迹对升级事件是否复用业务事件 ID、如何表达修订版本须在消息契约冻结时确认。

### 5.4 `uav_telemetry_metrics` 与 `uav_system_metrics`

- 遥测至少保存定位、姿态、云台、速度、悬停状态、定位质量和任务/管道引用。
- 系统指标采用 `metric_name + metric_value + labels JSONB` 的可扩展模型；高频固定指标可按压测结果单列。
- `uav_system_metrics` 必须持续记录各 Topic attempted/published/dropped、spool/queue 深度与高水位、最后成功时间和 coverage；运行遥测降采样也必须生成相应窗口覆盖信息。
- `coverage_ratio` 低于待冻结门槛的数据必须带质量标志，默认不得作为完整时段参与业务 KPI、SLA 或模型验收。
- 不再为每个摄像头创建独立 measurement/表，摄像头和路口通过列与索引区分。

## 6. 普通业务表关键边界（目标契约）

### 6.1 `uav_users` 与 `uav_alerts`

当前代码和空白 `road9` 已使用 `uav_users`、`uav_alerts`；不会从遗留 `users`、`alerts` 复制主键、记录或关联关系。认证、告警确认与重启恢复只基于 canonical 表验证。

`uav_alerts` 保存告警当前状态及关联 `uav_conflict_events`/`uav_ai_events` 的引用，不复制智慧交通主平台的派警、处置、案件归档状态。

### 6.2 AI 事件与可靠投递

- `uav_ai_events` 保存子项目事件事实和审核状态；智慧交通主平台分配的 ID 作为外部引用。
- `uav_ai_events.event_type` 的事故测绘 canonical 值固定为 `survey_result`；正式枚举/CHECK 约束必须拒绝 `accident_survey`，运行时不存在遗留别名适配器。
- `uav_event_outbox` 保存事件类消息的待投递 payload、`generated/delivering/delivered/delivery_failed` 状态和下次重试时间；既可承载内部 Kafka 事件 spool，也可承载智慧交通主平台外发 outbox，必须用 destination/type 区分。
- `uav_event_delivery_attempts` 保存尝试时间、目标、耗时、响应码和脱敏错误摘要。
- `uav_event_feedback` 保存主平台 `confirmed/rejected`、原因和可用结果，反馈消费以平台反馈 ID/幂等键去重。
- `uav_dead_letters` 保存 EventDelivery/outbox 超过重试上限的外发记录及人工处理状态；入站 Kafka schema/身份错误由 `uav_message_dead_letters` 保存。两类失败都不得仅在日志中记录后丢弃。
- `uav_evidence_packages`/`uav_evidence_items` 保存证据包与证据项元数据、哈希和外部对象引用；大视频/图片不直接写入 PostgreSQL 大字段，具体对象存储由大项目确认。
- 业务事务与 outbox 写入必须原子提交；网络投递不得阻塞视频逐帧处理。

`uav_event_outbox` 至少保存 `source_system`、`message_id`、可空 `idempotency_key`、`destination_type`、`destination`（Topic/接口标识）、`payload_hash`、`payload`、`status`、`attempt_count`、`next_retry_at`、`created_at`、`delivered_at` 和脱敏 `last_error`。内部消息以 `(source_system,message_id,destination)` 防重；主平台外发再对非空 `(source_system,idempotency_key,destination)` 建条件唯一索引。事件首次生成与 outbox 入列必须原子；仅在 broker/目标平台确认后标记 delivered/清理，重启重放复用原 ID。若检测进程不能直接事务写 `road9`，必须使用具备 fsync/崩溃恢复能力的本地持久化 spool，再由适配器转入 canonical outbox；进程内队列不合格。

### 6.3 路网快照与视觉绑定

- `uav_road_context_snapshots` 只保存从 `road9` 路网数据读取的版本/缓存元数据，不能成为另一个无版本路网主库。
- `uav_visual_lane_bindings` 保存 `local_lane_key -> inter_id + link_id + lane_id + road_data_version` 以及置信度、方法和人工确认信息。
- 历史快照：2026-07-20 曾以 `retired/invalidated` 失效旧道路 JSON 标注；该批历史业务记录已在
  ADR-020 一次性重建中清除。当前 `uav_visual_lane_bindings` 仅服务版本化渠化地图，不含
  `roads_json` 列。
- 主数据版本变化不得重写历史指标、轨迹或事件；每条事实保留产生时的 `road_data_version`。
- 管道启动时读取已发布版本快照并缓存，不得逐帧查询远程/共享路网表。
- `road9` 中具体路网表/视图路径仍为 `【验收阻断】【待确认】`；此前调查的 `road10.*` 不再作为目标引用。

### 6.4 无人机数据源、FlightPlan、Mission 与 Pipeline

- `uav_video_sources` 接受 `rtsp/mp4`，`uav_telemetry_sources` 接受 `mqtt/srt/file`；其中 `srt` 固定指 DJI `.srt` 遥测字幕，`file` 固定指 DJI Cloud API JSON 导出，不是视频协议。
- 实时配对为 `rtsp + mqtt`，本地配对为 `mp4 + srt/file`。API 可将成对记录聚合为 SourceProfile，但数据库只能有一套启用、默认和验证状态真源。
- RTSP/MQTT 凭据只保存 secret reference；服务器本地路径保存规范化值和 allowlist 根标识，禁止明文密码、任意路径和打开的流对象。
- `uav_flight_plans` 至少保存 `drone_id/inter_id/road_data_version/video_source_id/telemetry_source_id/ai_mode/status/schedule_type/timezone/schedule_json/revision/enabled_at/retired_at`。`schedule_json` 的 schema 版本、CHECK 约束和索引须由 migration 冻结，不能存不可验证的任意 JSON。
- `uav_missions` 至少保存 `flight_plan_id/trigger_type/scheduled_start_at/scheduled_end_at/actual_started_at/actual_ended_at/status/reason_code/error_summary/pipeline_id/parent_mission_id/retry_number` 以及设备、源、路网和计划快照。
- 首次计划执行必须对非空 `(flight_plan_id, scheduled_start_at)` 建唯一约束；立即执行 Mission 的 `flight_plan_id` 可空并使用独立请求幂等键。retry 新建 Mission 并通过 `parent_mission_id` 关联，不覆盖原失败记录。
- `uav_flight_plans` 使用 `draft/enabled/paused/completed/retired`；`uav_missions` 使用 `pending/starting/running/completed/failed/skipped/cancelled`。状态转换、操作者和原因进入 `uav_audit_logs`。
- 调度器通过 PostgreSQL advisory lock 或经批准的数据库租约竞争执行资格；锁不是业务事实，不能以锁记录替代 Mission 唯一约束和状态事务。
- `uav_pipelines` 保存期望状态、配置快照、执行节点和错误摘要；PID/handle/queue/lock 仍属于运行内存。Mission 与 Pipeline 不共享状态字段或主键。
- `uav_telemetry_metrics` 必须带可空的 Mission/Pipeline 引用、设备 ID、业务时间和质量，便于区分实时任务、本地回放和非任务遥测。

## 7. 压缩、连续聚合与保留策略候选（待确认）

以下仅为容量评审候选，不是已创建策略：

| 数据 | 压缩/列式转换候选 | 在线明细保留候选 | 长期策略候选 |
| --- | --- | --- | --- |
| 路口/车道指标 | 7 天后 | 180 天 | 1 分钟/5 分钟连续聚合保留 2 年 |
| 遥测/系统指标 | 7 天后 | 90 天 | 分钟级聚合保留 1 年 |
| 轨迹点 `uav_track_points` | 30 天后 | 365 天 | 轨迹主记录由普通表独立保留，点列按合同归档或延长保留 |
| 冲突事件 | 30 天后 | 365 天以上 | 依据执法/审计要求冻结，不得仅按成本删除 |

- 策略名称、DDL 语法依赖最终 TimescaleDB 版本；必须在目标环境验证后纳入迁移。
- 连续聚合物化视图名称必须以 `uav_` 开头，例如 `uav_traffic_metrics_1m`。
- 删除策略必须区分原始指标、证据事件和业务记录。事故测绘、执法线索、告警及主平台交付记录不能套用普通指标的短保留期。
- 启用压缩/列式转换前必须验证乱序补写、事件修订、备份恢复和查询性能。

## 8. canonical Kafka 数据模型（本机核心链路已实施）

| Topic | `msg_type` | 目标消费者 | 保留期 |
| --- | --- | --- | --- |
| `uav_statistics_{camera_id}` | `uav_stats` | Platform/TimescaleDB writer | 24 小时候选 |
| `uav_track_complete_{camera_id}` | `uav_track_complete` | Platform/TimescaleDB writer | 24 小时候选 |
| `uav_conflicts_{camera_id}` | `uav_conflict` | Platform/TimescaleDB writer、告警引擎 | 24 小时候选 |
| `uav_telemetry_{camera_id}` | `uav_telemetry` | Platform/TimescaleDB writer | 24 小时候选 |
| `uav_system_metrics` | `uav_system_metrics` | Platform/TimescaleDB writer | 24 小时候选 |

`uav_ai_events` / `uav_ai_event_feedback` 是待主平台合同冻结的外部集成候选，不属于当前 Platform Kafka consumer 的五类运行时订阅。

当前 Platform 订阅正则：

```text
^(uav_statistics_|uav_track_complete_|uav_conflicts_|uav_telemetry_).+$|^uav_system_metrics$
```

Topic 的复数/单数按上表固定，禁止消费者自行猜测；`msg_type` 只表达消息类别，具体业务 `event_type`（如 conflict、congestion）无需添加 `uav_`。

生产者必须用 allowlist Topic builder 和显式 `camera_id` 生成 camera-scoped Topic；禁止通过字符串替换/切片从 `uav_statistics_*` 派生其他 Topic。builder 的输入校验、映射和异常必须有单元测试。

## 9. 切换前历史实现（已退役）

> 本节只保存 2026-07-16 前的历史背景，不描述当前代码。当前运行时已使用 `road9`、TimescaleDB 和 canonical `uav_*`，且明确不迁移历史数据。

切换前实现曾包括：

- 旧 Topic：`statistics_*`、`track_complete_*`、`conflicts_*`、`telemetry_*`、`system_metrics`；
- 旧 `msg_type`：`stats`、`track_complete`、`conflict`、`telemetry` 等；
- Telegraf 将部分统计消息写入 InfluxDB 1.8；
- Platform 的历史指标、轨迹和冲突查询依赖 InfluxDB measurements；
- Grafana 使用 InfluxDB/旧 PostgreSQL 数据源；
- PostgreSQL 业务表仍存在无前缀的 `users`、`alerts`；
- 代码可能通过 SQLAlchemy `create_all()` 初始化表，而非受控版本迁移。

### 9.1 历史统计双写去重（P0）

旧 `statistics_*` 可能把同一消息经两条路径写入 InfluxDB：Telegraf 写 `camera_{N}`，Platform consumer 写 `intersection_stats`。迁移时两边是同源副本，不得把数值或行数相加。

| 迁移步骤 | 约束 |
| --- | --- |
| 来源标记 | 每行保留 `legacy_source_path=telegraf_camera/platform_intersection`、measurement、series/tag、raw time 和 payload/field fingerprint |
| 路口映射 | 先冻结 camera ID 到 intersection ID 的有效期映射，不能只按当前配置回填历史 |
| 重复识别 | 综合来源映射、字段指纹和经时间语义校正后的容差；Influx time 只能作为信号之一，不能单独判重 |
| 取值策略 | 确认同源后选择批准的权威分支，或仅对另一分支独有字段做补全；`cars`、方向流量、道路活跃度和样本数不得求和 |
| 歧义处理 | 无法证明同源/独立的记录进入隔离集，保留两份原值，不进入业务汇总 |
| 对账输出 | 分列两分支原始行数、确认重复数、择源数、字段补全数、歧义数和最终 canonical 行数 |

迁移脚本必须在抽样路口和跨时段数据上验证去重误合并/漏合并率；阈值、权威分支和容差未签字前不得执行全量回迁。

### 9.2 历史兼容迁移方案（已取消）

以下步骤未用于本机切换。实际处置是空白新库初始化、旧写入方停止、旧资产 7 天不挂载保留，
到期后使用固定 allowlist 脚本人工清理；禁止恢复旧消息兼容或导入旧数据。

1. DBA 确认 `road9`、TimescaleDB 版本/权限、备份恢复和 migration 账户。
2. 创建 `uav_*` 普通表、hypertable、索引和策略；发布只读路网视图/快照接口。
3. 消费端先支持新旧 Topic，并把旧消息规范化为 canonical envelope；通过 `uav_message_inbox` 去重。
4. 生产端切换到 `uav_*` Topic/`msg_type`。如需短期双投，必须复用 `source_message_id` 并限定窗口。
5. 对 PostgreSQL/TimescaleDB 与旧 InfluxDB 做数量、时间桶、关键指标和抽样事件对账。
6. 历史 API 切换到 PostgreSQL/TimescaleDB，观察期通过后停止 Telegraf/InfluxDB 新写入。
7. 冻结旧库只读并按确认的历史回迁/归档方案处理，随后移除 Grafana、Telegraf、InfluxDB 部署和配置。
8. 删除旧 Topic 消费兼容与无前缀表只能在所有生产者、消费者、回放工具和主平台联调方完成切换后执行。

迁移期禁止让新旧消费者各自生成不同事件 ID 后重复写入，也禁止在未完成数据对账和回滚演练前直接删除旧 InfluxDB 数据。

## 10. 验收门禁

- `SELECT current_database()` 返回 `road9`。
- `pg_extension` 中存在经确认版本的 TimescaleDB；应用账户无扩展安装权限但具备所需 DML 权限。
- UAV 平台自建关系的物理表名均匹配 `^uav_`；不存在新建的无前缀业务表。
- 所有目标 Topic、`msg_type` 和 WebSocket 消息类型均匹配 `^uav_`。
- Topic builder 显式使用 camera ID 且不含字符串替换派生；各 kind 路由单测通过。
- 事件 spool/outbox 经断网、队列满、进程崩溃和重启测试无静默丢失；指标 drop/coverage 可观测且低覆盖窗口被正确降质。
- Consumer 关闭 auto commit；数据库失败不提交 offset，数据库提交后崩溃重放由 inbox 幂等吸收，同 ID 不同 hash 被隔离。
- hypertable 写入、乱序补录、幂等重放、时间桶聚合、压缩/保留策略和备份恢复通过验收。
- 路网引用携带 `road_data_version`；无法匹配时为空并标记 `unmapped`，不伪造权威 ID。
- Platform 历史查询不再依赖 InfluxQL；目标部署不启动 Grafana、Telegraf、InfluxDB。
- Telegraf `camera_N` 与 Platform `intersection_stats` 双写完成去重/择源，未简单相加；迁移数量、分钟级聚合、轨迹/冲突抽样和告警关联对账达到双方冻结阈值。

### 10.1 本机 MP4 + SRT 实施证据（2026-07-16）

- Alembic head 为 `20260716_0012`；`uav_track_events` / `uav_track_points` 增加 Mission/Pipeline/Run/Source/Inter/Road/Quality lineage 和逐点业务时间。
- `uav_ai_events` 已持久化 `congestion`、`quality_degradation` 和 `survey_result`，证据通过 `uav_evidence_packages` / `uav_evidence_items` 保存 SHA-256 和内容地址。
- 检测进程的文件 spool 位于独立持久卷，不建表、不提供业务查询、Kafka 确认后删除；未引入 SQLite 或第二业务数据库。
- 完整验收计数与查询见 `docs/test_report_mp4_srt_product_deep_demo.md`。

### 10.2 轨迹研判类型化维度（2026-07-21）

Alembic `20260721_0014` 为 `uav_track_events` 增加可空列：
`yolo_class_id INTEGER`、`yolo_class_name TEXT`、`yolo_model_id TEXT`、
`class_mapping_version TEXT`、`start_road_id TEXT`、`exit_road_id TEXT`。原始 canonical
`payload` 继续保留；以上列用于筛选、聚合、排序和来源追溯，不形成第二份业务真源。

迁移只从 payload 中复制已经存在的 `yolo_class_id`、`start_road_id` 和 `exit_road_id`；
旧记录没有模型来源时，`yolo_class_name`、`yolo_model_id`、`class_mapping_version` 必须保持空，
禁止按当前权重或类别表反推。新增索引覆盖路口+结束时间、YOLO 类别、入口/出口和转向等实际
研判过滤维度；查询仍必须先在 PostgreSQL 完成路口、窗口与筛选条件收敛，再进入应用聚合。

后续 `20260721_0015` 增加 `(inter_id, source_profile_id, ended_at)` 与
`(mission_id, pipeline_id, track_id)` 查询索引。本机 `road9` 已升级到 `20260721_0015`；真实
30 分钟查询的过滤 SQL 执行约 3.5ms，完整分析读模型约 0.25s（崇华路样本）。四路口真实数据对账与历史字段
缺失说明见 `docs/test_report_trajectory_analysis_multi_intersection_20260721.md`。

### 10.3 GCJ-02 渠化地图与轨迹重建（2026-07-21）

Alembic `20260721_0016` 删除新写入链路中的旧坐标列并建立渠化地图实体；后续
`20260721_0017` 将视觉配准唯一键扩展为 `map_version_id + source_profile_id`，保证同一路口
多个正拍视频各自固定 pixel→ENU 单应矩阵。该阶段 schema head 为 `20260721_0017`；当前本机
head 已前向迁移到 10.5 节的 `20260723_0019`：

- `uav_channelized_map_versions`：路口、YCX/地图版本、`draft → candidate → link_verified → lane_verified → retired` 状态、GCJ-02/ENU 几何、锚点、拓扑和质量结果；
- `uav_visual_registrations`：原图/正射影像、控制点、pixel→ENU 单应矩阵、残差和复核状态；
  verified 记录的 `residuals` 同时保存配准视频时刻、`registration_position_gcj02` 与
  `registration_gimbal_yaw_deg`，作为运行时逐帧运动补偿的不可变参考；
- 重建的 `uav_visual_lane_bindings`：本地稳定车道键、可空 YCX lane ID、不透明 link ID、几何来源、置信度和审核状态。

### 10.4 路口项目与视频发现（2026-07-22）

Alembic `20260722_0018` 增加四个仅承载工作流与审计的实体，不把项目表当作外部路网真值：

- `uav_intersection_projects`：稳定 `project_id`、可空正式 `inter_id`、GCJ-02 项目中心、阶段和乐观修订号；
- `uav_video_ingestion_jobs`：视频优先/路口优先模式、期望项目、SourceProfile/素材引用、悬停证据、候选与错误码；
- `uav_source_intersection_bindings`：SourceProfile 到项目的分段绑定，保存起止偏移、绑定质量、坐标证据与确认人；
- `uav_calibration_review_records`：提交检查、通过或退回的不可覆盖审计记录，不承载角色隔离；通过记录必须保存影像地图对照、版本差异、配准误差、拓扑、车道方向和停止线六项全真检查表。

最新 `RoadContextSnapshot` 只用于幂等回填项目壳；正式路网事实仍来自已验证 RoadContext，运行时仍只接受不可变 `lane_verified` Bundle。

`uav_track_events/uav_track_points/uav_conflict_events/uav_telemetry_metrics` 的公共位置字段只使用
GCJ-02，米制计算字段明确以 `_enu_m` 结尾。`source_lane_id` 与 `matched_link_id` 均为字符串，
不得假设 road9/YCX 对象 ID 可解析为数字或业务编码。

已发布地图与上游 `uav_road_context_snapshots` 通过不可变 `source_checksum` 关联，不能用本地
`*-IMAGERY-FIT-*` 地图版本冒充 YCX 快照版本。`lane_verified` 发布会将精确命中的快照更新为
`quality_status=verified`，并写入 GCJ-02 锚点、转换版本和 `map_version_id`；Dashboard 只据此
投放路口中心和高德地图。

本机 2026-07-21 已执行一次性清理：除一条重建起点审计外，所有历史业务/派生表为零；主数据、
Alembic 版本和 20 个原始文件 SHA-256 保留。证据见
`docs/test_report_gcj02_rebuild_local.json`，操作见 `docs/runbook_trajectory_data_reset_and_replay.md`。

### 10.5 巡航跟踪质量事实（2026-07-23）

Alembic revision `20260723_0019` 增加：

- `uav_flight_plans.tracking_profile`：旧记录回填 `hover_only_legacy`，新记录 server default 为 `hover_cruise_v1`。
- `uav_visual_registrations.registration_pose/camera_calibration/map_coverage_enu_m`：JSON 质量谱系。
- `uav_pipelines.flight_phase/tracking_quality/formal_analytics_eligible/runtime_quality`：由 canonical `uav_stats` 在 inbox 与指标事实的同一数据库事务内更新。
- `uav_flight_segments`：`id`、`source_profile_id`、`mission_id`、起止 offset、`phase`、`quality_status`、`classifier_version`、`motion_statistics`、`map_version_id`、`created_at`。

飞行分段是 SourceProfile/Mission 的类型化索引事实；完整轨迹、冲突及逐帧诊断仍保存在既有 payload JSON 和轨迹点表中，不建立第二套轨迹事实。迁移 downgrade 故意拒绝执行，因为质量事实与已生成轨迹不可安全回退；业务回滚通过 `tracking_profile=hover_only_legacy` 完成。

本机开发库已于 2026-07-23 从 `20260722_0018` 前向迁移到 `20260723_0019`。现有 xqh verified registration `VRG-3351d2719cf74f1798ef0fc0` 仅回填可从 selected capture frame `FRM-4221C85DCB81@49.616233s` 和 32 条 `lane_verified` 车道证明的谱系：配准位姿、相机参数哈希与车道覆盖 MultiPolygon；未修改 homography、车道几何或发布状态。`platform/scripts/backfill_cruise_registration_lineage.py` 默认 dry-run，目标 ID 必填，遇到非空且不同的既有谱系时拒绝覆盖；回填后重复 dry-run 为 `changed=false / would_change=false`。浮点比较仅容忍 `1e-12` 级数据库序列化舍入，ID、字符串、结构或超容差数值变化仍拒绝覆盖。

### 10.6 图像关联 ID 与业务轨迹 ID（2026-07-24，2026-07-28 修订）

ByteTrack 仍前置于 H/ENU，但 `uav_track_events.track_id` 现在表示独立于地图质量的图像业务轨迹；
`association_id` 保留原始图像关联身份。地理或地图质量变化不拆分记录。候选关联只在未满足成熟
时长/点数时存在，不写完成事实。

### 10.7 分层轨迹质量与停用地理注册兼容结构（2026-07-28，2026-07-30修订）

Alembic`20260728_0020`已在本机创建`uav_source_geo_registrations`及相关可空外键。该结构不删除、不回写，
但API、Mission选择、Pipeline环境和检测运行时均已停止读写；它不是外部输入，也不再决定世界坐标或tracking profile。
世界事实由视频尺寸、相机参数和同步遥测形成的当前帧矩阵生成，路网表只服务Lane/Link匹配。

同一迁移为 `uav_track_events` 增加可查询的 `association_id/tracking_method/tracking_quality/
geo_reference_quality/road_match_quality/quality_reasons/geo_registration_id`。原坐标、地图和车道列继续
可空，原始 Kafka payload 完整保留。该不可逆迁移不删除或回写旧运行结果。

### 10.8 参数化渠化编辑模型（2026-08-03，无迁移）

本次不新增表或 Alembic revision。`uav_channelized_map_versions.topology.editor_model` 保存 `parameterized|freeform` 版本模型及可重开像素几何；服务端派生草稿同时在 topology/quality 写 `derived_from_map_version_id` 并把 `reviewed` 归零。`uav_visual_registrations.registration_pose` 保存固定影像/移动路网的版本化姿态。正式 ENU/GCJ-02 Lane/Feature 仍写既有 geometry JSON，`uav_visual_lane_bindings` 仍是候选/发布车道绑定事实。`lane_verified` 行和绑定保持不可变，编辑器元数据不进入 Runtime Bundle。

# API_CONTRACTS.md — TrafficAnalyzer API 契约

> 2026-07-16 本机运行时已切到 canonical 契约。带有旧 Topic、旧 `msg_type` 或旧观测链路的后续章节仅是历史快照，不再存在运行时兼容；REST 路径保持不变。

## 0. canonical 消息与持久化契约（本机已实施）

### 0.1 已冻结决策

| 契约项 | 目标值 |
| --- | --- |
| PostgreSQL connection database | `road9`；不自动假定同名 schema |
| 时序持久化 | PostgreSQL + TimescaleDB 扩展 |
| UAV 平台 Topic | 全部以 `uav_` 开头 |
| UAV 平台 `msg_type` / WebSocket `type` | 全部以 `uav_` 开头 |
| UAV 平台自建表 | 全部以 `uav_` 开头 |
| 指标查询权威源 | `road9` 中的 `uav_*` 普通表与 TimescaleDB hypertable |
| 废弃目标链路 | Grafana、Telegraf、InfluxDB 不进入目标部署和验收 |

本机新库最初由 Alembic `20260715_0010` 从空库创建，当前 head 为 `20260728_0020`，不回迁任何
旧数据；生产连接、权限、容量、HA 和路网外部合同仍需确认。

### 0.2 canonical Topic 与 `msg_type`

| Topic | canonical `msg_type` | 说明 |
| --- | --- | --- |
| `uav_statistics_{camera_id}` | `uav_stats` | 路口/道路/车道实时统计 |
| `uav_track_complete_{camera_id}` | `uav_track_complete` | 完成轨迹 |
| `uav_conflicts_{camera_id}` | `uav_conflict` | 换道/机非冲突事件 |
| `uav_telemetry_{camera_id}` | `uav_telemetry` | 无人机遥测 |
| `uav_system_metrics` | `uav_system_metrics` | GPU、CPU、管道和消息链路指标 |

Topic 的单复数按上表固定。`msg_type` 必须与 Topic 映射一致；业务字段 `event_type` 使用 `conflict/congestion/survey_result/enforcement_clue` 等领域枚举，不因消息前缀规则改写。事故测绘跨系统结果的唯一 canonical 枚举为 `survey_result`。

`uav_ai_events` / `uav_ai_event_feedback` 是待主平台合同冻结的外部集成候选，不属于本机 Platform 当前订阅范围，也不能借此扩展本次只含上述五类 Topic 的运行时。

当前 Platform 订阅正则：

```text
^(uav_statistics_|uav_track_complete_|uav_conflicts_|uav_telemetry_).+$|^uav_system_metrics$
```

#### Topic builder 实施约束

- camera-scoped Topic 必须通过单一 allowlist builder 生成，例如 `build_uav_topic(kind="statistics", camera_id=camera_id)`；调用方必须显式传入并校验 `camera_id`，禁止从已有 Topic 文本反推。
- builder 映射固定为 `statistics -> uav_statistics_{camera_id}`、`track_complete -> uav_track_complete_{camera_id}`、`conflicts -> uav_conflicts_{camera_id}`、`telemetry -> uav_telemetry_{camera_id}`；全局 Topic 使用独立常量。
- 禁止用 `replace("statistics", "conflicts")`、字符串切片、正则替换或复制其他 Topic 名来派生目标 Topic；这类实现会在前缀、camera ID 或未来版本变化时静默路由错误。
- `camera_id` 的字符集、长度、数值/业务 ID 类型仍待设备契约冻结；builder 必须拒绝空值、路径/通配符字符和未注册 kind，而不是自动回退到默认相机。

### 0.3 canonical 消息信封

所有目标 Kafka 消息使用统一信封，业务内容放入 `data`。同一消息重试或迁移期双投时必须复用 `message_id`；幂等唯一键为 `(source_system, message_id)`：

```json
{
  "message_id": "6ec171d1-b3c1-4d75-b6bd-a099ad4f3560",
  "msg_type": "uav_stats",
  "schema_version": "uav_stats/v1",
  "occurred_at": "2026-07-13T02:00:00.123Z",
  "produced_at": "2026-07-13T02:00:00.180Z",
  "source_system": "uav_traffic_analyzer_ai",
  "camera_id": "id_1",
  "drone_id": "drone_001",
  "intersection_id": "INT_camera_1",
  "inter_id": "authoritative-inter-id",
  "road_data_version": "published-version-id",
  "trace_id": "trace-uuid",
  "source_time_semantics": "event_time",
  "time_quality": "verified",
  "data": {}
}
```

公共字段约束：

| 字段 | 必填 | 约束 |
| --- | --- | --- |
| `message_id` | 是 | UUID；生产端首次生成，重试/双投不变；`uav_track_complete` 按 `pipeline_id + track_id` 确定性生成 |
| `msg_type` | 是 | 必须是上表中的 `uav_*` 类型 |
| `schema_version` | 是 | `{msg_type}/v{major}`；破坏性变更升级 major |
| `occurred_at` | 是 | 业务发生时间，RFC 3339；目标库存 UTC `TIMESTAMPTZ` |
| `produced_at` | 是 | 消息生成时间，用于链路延迟计算 |
| `source_system` | 是 | 唯一 canonical 值 `uav_traffic_analyzer_ai`；参与消息/事件幂等唯一约束 |
| `camera_id` / `drone_id` | 条件必填 | 按消息来源携带，准确类型待冻结 |
| `intersection_id` | 条件必填 | 迁移期本地 ID，不能冒充权威路网 ID |
| `inter_id` / `road_data_version` | 条件必填 | 有权威路网匹配时必须同时保存 |
| `trace_id` | 是 | 跨生产、消费、入库、对外交付的链路追踪 ID |
| `source_time_semantics` | 是 | 新实时消息为 `event_time`；合法回放重建为 `reconstructed` |
| `time_quality` | 是 | 新实时消息为 `verified`；历史迁移还可为 `reconstructed/ingest_only/quarantined` |
| `source_time_raw` | 条件必填 | 历史迁移或回放重建时保存原始时间值/字段，不得覆盖 |
| `data` | 是 | 消息类型对应的业务对象 |

消费者必须先校验 `msg_type + schema_version`，再通过长期 canonical 表 `uav_message_inbox` 的唯一键 `(source_system, message_id)` 做全局幂等；事实写入与 inbox 置为 `processed` 必须在同一数据库事务提交。未知 major 版本进入 `uav_message_dead_letters`，不得按旧结构猜测解析。

`uav_message_inbox` 保存 `payload_hash/status/topic/partition/offset/first_seen_at/processed_at/fact_refs`，并以 `dispatch_status/dispatch_attempts/last_dispatch_error/last_dispatch_attempt_at/dispatched_at` 记录事实提交后的副作用恢复状态。相同 ID、相同 hash 的重放不重复写事实；仅 `dispatched` 可跳过 WS/告警，`pending` 必须继续派发。相同 ID、不同 hash 视为消息身份冲突，必须隔离并告警，不能覆盖原事实。hypertable 唯一键只是第二层防重，不能替代 inbox 的跨时间全局唯一性。

### 0.4 各消息 `data` 边界

- `uav_stats`：保留车辆数、活跃轨迹、速度、排队、方向流量、动态 `roads[]`、`lane_stats[]`、路网和质量字段。旧 `road_1`～`road_N` 不进入 canonical 主结构，也没有运行时迁移适配器。
- `uav_track_complete`：保留轨迹 ID、车辆类别、转向、起止时间、速度、ENU/像素轨迹、入口/出口 Link/车道、地图匹配与质量字段。
- `uav_conflict`：保留双方轨迹 ID、TTC/PET、最小距离、冲突角、场景、风险分、证据和预测位置；当前 near-miss 判定口径不因消息改名而变化。事件产生时，`KafkaProducerNode` 只冻结待发布信封；必须等 `ShowNode` 生成检测器实际 `frame_result` 后，才保存并发布固定排序的 `conflict_original_frame`、`conflict_detector_frame`。不得在证据模块重绘或缩放检测图。`evidence_files[]` 只携带 `kind/storage_backend/storage_key/sha256/size_bytes/media_type/width/height`，禁止携带 Base64 或本机绝对路径。
- Platform 对 `evidence_files[]` 执行存储根约束、相对键格式、大小和 SHA-256 校验，通过后在冲突事实事务内登记一个 `uav_evidence_packages` 和两条 `uav_evidence_items`，不复制检测器已保存的文件；事件 payload 将私有 `evidence_files` 替换为持久化 `evidence_refs`。保存或校验失败不得丢弃真实冲突事实，必须写 `evidence_status=incomplete`、稳定错误码和空 `evidence_refs`。
- `evidence_refs[]`：包含 `id/kind/url/storage_backend/storage_key/sha256`；`url` 通过鉴权的 `GET /api/v1/survey-evidence/{id}/content` 返回不可变内容。数据库引用存在但对象缺失时返回 `409`，不得以占位图伪装成功。本机原生 Platform 使用仓库忽略的持久目录 `.runtime/survey`，不得使用 `/tmp` 作为 managed 证据的默认长期存储。
- `uav_telemetry`：保留无人机定位、姿态、云台、速度、悬停、任务/管道和定位质量。
- `uav_system_metrics`：使用指标名、值、单位、实例和 labels，禁止继续按摄像头创建独立 measurement。
- `uav_ai_event`：使用本节信封，并在 `data` 中携带 `source_event_id`、`idempotency_key`、业务事件、证据和投递所需字段。S1～S4 的路口态势、`lane_change`、`conflict`、`risk_hotspot`、`survey_result`、`enforcement_clue` 统一通过 `event_type` 区分，不为每个场景再建立无统一治理的独立 Topic。
- `uav_ai_event_feedback`：携带 `source_event_id`、`platform_event_id`、`confirmed/rejected`、原因、反馈时间和可用的处置结果；不得把主平台派警状态复制为子项目状态机。

`uav_conflicts_{camera_id}` 是低延迟内部冲突流；需要对外交付时由集成适配器生成对应的 `uav_ai_event`，并以稳定的 `source_event_id` 建立来源关系。两条消息不能被当成两个独立业务事件重复入库或重复告警。

#### 消息可靠性等级

| 消息类别 | Topic/类型 | 目标投递语义 |
| --- | --- | --- |
| 事件事实 | `uav_track_complete`、`uav_conflict`、`uav_ai_event`、`uav_ai_event_feedback` | 发送前进入持久化 spool/outbox；broker 确认后才能清理，失败重试复用原 `message_id` |
| 业务任务/告警 | `uav_lane_annotation_task`、`uav_alert_new/uav_alert_updated` | 来源业务事务必须持久化；WebSocket 允许断线重连后从 API 补取，不以瞬时推送作为唯一事实 |
| 高频指标 | `uav_stats`、`uav_system_metrics` | 允许在批准的背压策略下聚合、降采样或丢弃，但必须记录 coverage/drop，不能静默丢失 |
| 无人机遥测 | `uav_telemetry` | 普通运行监控可按批准策略降采样；被测绘/执法证据引用的时间段必须进入持久化证据/事件路径，不得按普通指标丢弃 |

持久化 spool 可由本地耐久队列或 `road9` 中的 `uav_event_outbox` 实现，具体部署形态待冻结；仅使用进程内队列不满足事件可靠性要求。spool/outbox 至少保存 `source_system/message_id/topic/payload_hash/payload/status/attempt_count/next_retry_at/created_at/last_error`，进程重启后能够重放且不生成新 ID。

指标消息或对应 `uav_system_metrics` 必须提供/可计算 `window_start/window_end/expected_samples/actual_samples/dropped_samples/coverage_ratio/drop_reason`。生产端还要持续暴露 attempted/published/dropped、队列高水位和最后成功时间；低于待冻结 coverage 门槛的数据不得作为完整时段参与业务 KPI 或验收。

### 0.5 WebSocket 目标命名

| Channel | 推送 `type` | 内容 |
| --- | --- | --- |
| `uav_intersection:{intersection_id}` | `uav_stats` / `uav_track_complete` / `uav_conflict` | 路口实时态势、轨迹、冲突 |
| `uav_alerts` | `uav_alert_new` / `uav_alert_updated` | 全局 UAV 告警流，供总览和告警中心订阅 |
| `uav_alerts:{intersection_id}` | `uav_alert_new` / `uav_alert_updated` | 指定路口的 UAV 平台告警 |
| `uav_system` | `uav_system_metrics` | 系统指标与管道状态 |
| `uav_telemetry:{drone_id}` | `uav_telemetry` | 无人机遥测 |
| `uav_calibration` | `uav_lane_annotation_task` | 车道标注/标定任务创建与状态更新 |

WebSocket 推送沿用 `{channel, type, data, ts}` 外壳，但 `type` 和 UAV 平台 channel 必须使用上述 `uav_` canonical 名称。同一告警可同时投放全局与路口级频道，必须复用同一告警 ID，前端按 ID 去重，不能形成两个业务告警。旧 channel 已下线，运行时直接拒绝，不存在并行发布适配层。

`subscribe`、`unsubscribe`、`ping`、`pong` 是 WebSocket 传输控制动作，不属于 UAV 业务消息 `type`，无需增加 `uav_` 前缀；控制动作中的业务 `channel` 仍必须使用上表 canonical 名称。

### 0.6 目标持久化映射

| `msg_type` | 目标表 | 类型 |
| --- | --- | --- |
| `uav_stats` | `uav_traffic_metrics` | TimescaleDB hypertable；以 `grain_type` 区分路口/道路/车道 |
| `uav_track_complete` | `uav_track_events`、`uav_track_points` | 普通业务表 + TimescaleDB hypertable |
| `uav_conflict` | `uav_conflict_events`；必要时关联 `uav_alerts` | hypertable + 普通表 |
| `uav_telemetry` | `uav_telemetry_metrics` | TimescaleDB hypertable |
| `uav_system_metrics` | `uav_system_metrics` | TimescaleDB hypertable |
| `uav_ai_event` | `uav_ai_events`、`uav_event_outbox`、`uav_event_delivery_attempts`、`uav_evidence_packages`、`uav_evidence_items` | 普通表 |
| `uav_ai_event_feedback` | `uav_event_feedback`；同步更新 `uav_ai_events` 审核摘要 | 普通表 |

入站 Kafka 的 schema/身份冲突等永久错误进入普通表 `uav_message_dead_letters`，耐久提交后才推进 offset；EventDelivery/outbox 超过重试上限的外发失败进入 `uav_dead_letters`。两者都不是另一个对外业务 Topic；是否增加运维专用 Topic需另行评审。

所有 Kafka 类型还共同写入 `uav_message_inbox` 作为全局幂等与消费审计；该表不是迁移期临时表，目标系统长期保留。

历史 API 路径可保持不变，但目标实现必须改为查询 PostgreSQL/TimescaleDB。具体表字段、hypertable 分区、唯一键、压缩和保留候选见 `docs/DATABASE_SCHEMA.md`。

### 0.7 已退役旧契约

下表只保留切换前后名称对照。Platform、Console2 和检测器运行时只接受右侧 canonical 值，
不再适配、双投或 fallback；历史数据不迁移。

| 已退役 Topic / `msg_type` | canonical Topic / `msg_type` | 当前规则 |
| --- | --- | --- |
| `statistics_{n}` / `stats` | `uav_statistics_{camera_id}` / `uav_stats` | 拒绝左侧 |
| `track_complete_{n}` / `track_complete` | `uav_track_complete_{camera_id}` / `uav_track_complete` | 拒绝左侧 |
| `conflicts_{n}` / `conflict` | `uav_conflicts_{camera_id}` / `uav_conflict` | 拒绝左侧 |
| `telemetry_{n}` / `telemetry` | `uav_telemetry_{camera_id}` / `uav_telemetry` | 拒绝左侧 |
| `system_metrics` / `system_metrics` | `uav_system_metrics` / `uav_system_metrics` | 拒绝左侧 |

`detections_*`、`vlm_analysis` 或场景专用的 `lane_change/risk_events/survey/enforcement` 旧 Topic 不属于当前订阅范围，运行时拒绝；未来若正式增加检测/VLM 调试流，必须另行冻结 `uav_` Topic、保留期和 schema，不能借迁移输入恢复旧名称。

事故测绘遗留事件类型 `accident_survey` 已退役且无迁移适配器。生产者、`uav_ai_event/v1` schema 校验、数据库约束和主平台接口必须拒绝它；唯一 canonical 枚举为 `survey_result`。

#### 遗留时间迁移约束（P0）

旧数据不得把 Influx point time 一律映射为 canonical `occurred_at/observed_at`：

- `FrameElement.timestamp` 以及旧完成轨迹的 `timestamp_first/timestamp_last` 是流相对秒，不是 Unix 时间戳；历史轨迹曾可能因此落在 epoch 附近。
- 旧统计/冲突消息缺少业务 timestamp 时，Influx writer 回退的 `time.time()` 只代表消费/写入时刻，只能映射为 `ingested_at`。
- 迁移适配器必须按 measurement/字段分支保留 `source_time_raw/source_time_semantics/time_quality`。只有持有源视频绝对开始时间、任务时间锚点或明确业务字段时，才能重建业务时间并标记 `reconstructed`。
- epoch 异常轨迹或无法证明业务时间的记录必须隔离；由数据负责人决定从源视频重建、保留为迁移审计或批准丢弃。不得为满足非空分区时间而伪造事件时间。
- `time_quality=ingest_only/quarantined` 的记录不能参与事件时效、SLA、模型准确率或按业务发生时间统计。详细迁移矩阵见 `docs/DATABASE_SCHEMA.md` 第 4.1.1 节。

#### Consumer 事务与 offset 约束（P0）

- 目标 Kafka consumer 必须关闭 `enable_auto_commit`；禁止在数据库事务完成前提交 offset。
- 标准顺序为：拉取消息 → 校验 envelope/hash → 开启 `road9` 事务 → 写/锁定 `uav_message_inbox` → 写 canonical 事实 → 更新 inbox `processed/fact_refs` → 提交数据库事务 → 手动提交 Kafka offset。
- 数据库失败必须回滚且不提交 offset，使消息可重放。若数据库已提交但 offset 尚未提交即崩溃，重放由 inbox 返回相同事实引用后再提交 offset，不能重复写事实。
- schema/身份冲突等不可重试消息只有在 `uav_message_dead_letters` 隔离记录耐久提交后才能提交 offset，禁止“记录日志后跳过”。该表与对外投递失败使用的 `uav_dead_letters` 分离。
- 因此目标语义是 Kafka at-least-once + inbox/事实幂等，形成业务上的 exactly-once effect；不得宣称 Kafka 与 PostgreSQL 存在未实现的分布式事务。

#### 遗留统计双写迁移约束（P0）

历史 `statistics_*` 同一统计消息可能同时经 Telegraf 写入 `camera_{N}` measurement，并由 Platform consumer 写入 `intersection_stats`。两条路径是同源双写，不是两份独立车流量：

- 迁移前按 camera/intersection 映射、来源路径、原始时间、字段指纹和允许的时间差建立重复识别规则；规则与阈值待抽样验证后冻结。
- 对可确认的同源记录选择一条权威分支或按字段补全合并，绝对禁止把 `cars`、方向流量、道路活跃度或样本数简单相加。
- 无法确认是否同源时分组隔离并保留 `legacy_source_path/measurement/raw_time/payload_hash`，不得以“总量更完整”为由合并。
- 对账报告分别列出 Telegraf 分支数、Platform 分支数、确认重复数、择源/合并数、歧义数和最终迁移数；双写原始行数不能直接作为业务样本数。

以下迁移方案已取消，不用于本机切换；本机采用空库初始化和旧资产 7 天不挂载保留：

1. 消费端先兼容新旧消息并统一写入 `road9` 的 `uav_*` 表；旧消息按 Topic partition/offset 生成稳定 `message_id`，新旧消息均进入长期 `uav_message_inbox`。
2. 生产端再切换 canonical Topic/`msg_type`；若短期双投，必须复用 `message_id` 并在数据库侧去重。
3. PostgreSQL/TimescaleDB 与旧 InfluxDB 完成数量、时间桶和事件抽样对账后，历史 API 才能切换权威源。
4. 观察期结束后停止 Telegraf/InfluxDB 新写入，并移除 Grafana、Telegraf、InfluxDB 部署；历史数据回迁或归档范围仍待确认。
5. 旧 Topic、旧 WebSocket channel、旧无前缀表的下线窗口须与全部生产者、消费者和智慧交通主平台联调方共同冻结。

当前本机门禁是 canonical Topic/msg_type/channel 拒绝旧值、空库 migration、数据库断开恢复、健康探测和旧资产未挂载。生产可靠性门禁仍独立保留。

### 0.8 路网引用边界

- `road9` 是 PostgreSQL connection database 的目标值，不等同于已确认的 schema 名。
- UAV 表只保存 `road_data_version + inter_id/link_id/lane_id` 等版本化引用和视觉绑定，不修改既有路网主数据。
- 无法匹配时权威 ID 置空并标记 `map_match_method=unmapped`；不得用 `road_N` 或本地 lane 数组下标伪造。
- 管道启动读取已发布路网快照并缓存，不得逐帧查询共享路网表。
- 此前 `ycx`/`road10` 调查只作为历史证据，`road10` 不再是目标连接或权威源选择。

### 0.9 全域态势工作台读契约（S8 I5-A 与内部查询契约已实现）

首屏 Dashboard 以交通指挥中心主任为第一用户。`DashboardReadModel` 已实现下列 5 个只读接口，不新增第二套事件或处置真源。项目事实接口使用 `uav.dashboard/v1`；服务器典型矩阵使用独立的 `uav.dashboard-situation/v1`：

| 方法与候选路径 | 用途 | 最小返回边界 |
| --- | --- | --- |
| `GET /api/v1/dashboard/overview` | 主任核心指标、重点关注榜、权限化待办摘要和整体健康 | 已返回 `project_scope/road_data_versions/as_of/window_start/window_end/data_quality/coverage_ratio/schema_version`、指标分子分母/质量/原因和 `pending_tasks`；compare/变化摘要待冻结 |
| `GET /api/v1/dashboard/intersections` | 按权限、bbox 和筛选返回路口摘要 | 已支持单值 `risk/monitor/quality`、GCJ-02 `bbox=min_lon,min_lat,max_lon,max_lat`、`q`、`offset/limit`；返回 `project_total/total/has_more/filters`。未实现聚合簇/zoom，不允许一次无限拉取 |
| `GET /api/v1/dashboard/intersections/{inter_id}` | 选中路口详情 | 任务、无人机、管道、态势、事件、路网版本、质量及专业页面稳定深链参数 |
| `GET /api/v1/dashboard/drones` | 当前视野/任务关联的无人机保障摘要 | `drone_id`、任务/路口、位置、遥测时间、定位质量和授权后的状态摘要 |
| `GET /api/v1/dashboard/situation?day_of_week=1..7&step_index=0..287` | 首页服务器典型时段路口/路段态势 | `time_profile/source/cache/summary/intersections/segments`；坐标和 `paths_gcj02` 可直接进入高德地图 |

接口路径不属于消息/自建表 `uav_` 前缀规则，但响应中的业务消息类型、事件引用和后端自建物理对象仍须遵守第 0 节 canonical 契约。overview 与地图摘要必须在同一权限和可比较时间口径下返回；缺失数据使用明确的 `stale/missing/unknown`，不得以 `0` 代替。S8-TBD-001/005 未关闭时，覆盖、拥堵、保障和综合可信度使用 `value=null + numerator/denominator + unverified reason`。

高德地图只接受 GCJ-02 坐标。正式 `RoadContext` 必须绑定 `lane_verified` 地图；本机验收点位必须明确登记 `status=test + usage=local_acceptance_only` 和 GCJ-02 来源。其他未验证或缺坐标记录进入 `isolated/map_exclusion_reason`。浏览器不得执行 WGS84 转换，也不得回退其他底图。

`bbox` 非 4 个数、经纬度越界或最小值不小于最大值返回 `422 invalid_bbox`。`limit` 为 1～1000，默认 200；`offset` 不小于 0。road9 查询超时或 SQLAlchemy 依赖异常返回 `503 dashboard_dependency_unavailable`，前端可保留最后成功快照并重试，不得回退 Mock。此内部查询契约解决实现者选择项，但正式项目范围、权限过滤、点位聚合/zoom、缓存、SLA 和错误预算仍由 S8-TBD-002/006/007/009 书面冻结。

`situation` 连接 PostgreSQL database=`ycx`，只读联结 `road9.dim_data_version/dim_inter_info/dim_link_info` 与 `xianchang.dws_inter_evaluation_5min_mm/dws_inter_link_status_5min_mm`。查询只使用启用道路版本，过滤删除态、无效坐标、空或无法转换的几何；LineString 和 MultiLineString 统一返回 `paths_gcj02`。路口范围取指标表全部有效 `inter_id`，路段范围取全部有效 `inter_id + link_id`，所选时槽无指标时仍返回范围对象并将状态置为 `missing`。`summary` 同时提供路口 `good/near_saturated/oversaturated/missing` 与路段 `smooth_segments/slow_segments/congested_segments/missing_segments` 汇总，首页前三个 KPI 直接读取该响应。

缓存键为 `road_version + day_of_week + step_index`，TTL 300 秒，LRU 上限 64。命中返回 `cache.status=hit`；外部连接失败且同一星期/时槽存在最近成功值时返回 `cache.status=stale/stale=true`；无缓存返回 `503 dashboard_dependency_unavailable`。该接口只用于首页态势展示，不允许写服务器、不写本地库，也不改变 Mission、检测、无人机统计或事件事实。

主任首屏默认只订阅 `uav_alerts` 和 `uav_system`；选中路口后订阅 `uav_intersection:{intersection_id}`，需要无人机实时详情时再订阅 `uav_telemetry:{drone_id}`。禁止同时订阅城市全部路口明细频道。若未来新增全局路口状态增量，channel 和 `type` 必须以 `uav_` 开头并经过容量、恢复和幂等评审。

重点关注榜必须返回可复算的入榜原因、持续时间、变化方向、规则/窗口和质量，不得只返回不透明综合分。上一可比时段只有在辖区、项目路口集合、指标口径和 coverage 可比较时才允许输出变化百分比。

`pending_tasks` 只聚合本平台可执行的 `ai_review/survey_delivery/integration_replay/configuration_check`，按当前身份和数据范围过滤，并从现有事件、测绘、投递和配置状态计算；不得新增第二套任务真源，也不得返回主平台派警、处置、结案或处罚决定。

### 0.10 无人机对接与飞行计划契约（S9 内部工程契约已实现）

本节已由 Alembic `20260715_0003`、`MissionOrchestrator`、PostgreSQL repository 和 Console2 `/drones` 四页签实现。`DRONES` 只保留最新遥测运行缓存，不再承担设备或 Mission 业务真源；`POST /api/v1/missions` 保留兼容入口，并把旧原始源字段规范化为持久化 `manual` Mission 快照。权威设备主数据、生产 secret provider、主平台和权威路网合同仍为外部验收阻断，不因本地实现而关闭。

#### 0.10.1 术语与状态

- SRT 固定指 DJI `.srt` 遥测字幕，不指 Secure Reliable Transport 视频协议。
- 实时源固定配对为 RTSP 视频 + MQTT 遥测；本地回放支持服务器 MP4 + DJI `.srt` 字幕遥测，或 MP4 + DJI Cloud API JSON 导出（`.json`/`.txt`，`source_type=file`）。
- `FlightPlan` 是排期定义，状态为 `draft/enabled/paused/completed/retired`。
- `Mission` 是一次执行，状态为 `pending/starting/running/completed/failed/skipped/cancelled`。
- FlightPlan 保存 canonical `inter_id + road_data_version`；当前 Pipeline 所需 `intersection_id` 由兼容适配器生成，不能替代权威路口 ID。
- FlightPlan 只自动启停 AI 检测 Pipeline，不下发航点、起降、返航或其他飞控指令。

#### 0.10.2 目标 REST 路由

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/api/v1/drones` | 按权限查询/创建设备档案 |
| GET/PATCH | `/api/v1/drones/{drone_id}` | 查询/编辑、启停和默认路口/源引用 |
| GET/POST | `/api/v1/drones/{drone_id}/sources` | 查询脱敏源配置/创建成对数据源 |
| GET | `/api/v1/sources` | 查询授权范围内全部脱敏 SourceProfile 聚合 |
| PATCH | `/api/v1/drones/{drone_id}/sources/{source_profile_id}` | 编辑、启停或设为默认 |
| POST | `/api/v1/drones/{drone_id}/sources/{source_profile_id}/validate` | 校验 RTSP+MQTT、MP4+SRT 或 MP4+DJI Cloud JSON |
| GET/POST | `/api/v1/flight-plans` | 查询/创建 FlightPlan |
| GET/PATCH/DELETE | `/api/v1/flight-plans/{flight_plan_id}` | 查询/编辑；仅 draft 且无 Mission 时可删除 |
| POST | `/api/v1/flight-plans/{flight_plan_id}/enable` | 校验设备、源、路网、排期和权限后启用 |
| POST | `/api/v1/flight-plans/{flight_plan_id}/pause` | 暂停生成未来 Mission，不停止运行中的 Mission |
| POST | `/api/v1/flight-plans/{flight_plan_id}/retire` | 永久停止未来执行并保留历史 |
| GET | `/api/v1/flight-plans/{flight_plan_id}/occurrences` | 预览/查询带时区的未来执行窗口 |
| GET/POST | `/api/v1/missions` | 查询执行记录/立即执行兼容入口 |
| GET | `/api/v1/missions/{mission_id}` | 查询计划快照、实际时间、状态、原因和 pipeline 引用 |
| POST | `/api/v1/missions/{mission_id}/stop` | 取消待执行或停止运行 Mission |
| POST | `/api/v1/missions/{mission_id}/retry` | 从 failed Mission 创建新重试 Mission |

写操作仅 `admin` 可用；当前 `operator/viewer` 只读。服务端执行权限检查，前端隐藏按钮不能替代鉴权。正式统一身份角色映射仍由 S9-TBD-008 批准。

写入请求的实体更新使用 `revision` 乐观并发；revision 冲突、计划重叠等并发冲突返回 409，状态/质量门禁返回 422，调度器、数据库或运行依赖不可用返回 503。API 时间保存为 UTC，并显式返回业务时区，默认 `Asia/Shanghai`。

#### 0.10.3 无人机与数据源最小 shape

无人机档案至少包含：

```json
{
  "drone_id": "drone_001",
  "name": "M300 RTK #1",
  "model": "DJI Matrice 300 RTK",
  "serial_number_masked": "***8A31",
  "enabled": true,
  "online_status": "online",
  "default_inter_id": "inter-001",
  "default_source_profile_id": "source-profile-001",
  "last_telemetry_at": "2026-07-13T08:00:00Z"
}
```

成对数据源最小 shape：

```json
{
  "source_profile_id": "source-profile-001",
  "drone_id": "drone_001",
  "name": "生产实时源",
  "mode": "live",
  "enabled": true,
  "is_default": true,
  "video": {
    "video_source_id": "video-source-001",
    "type": "rtsp",
    "location_masked": "rtsp://camera.example/***",
    "credential_ref": "secret://uav/drone_001/rtsp"
  },
  "telemetry": {
    "telemetry_source_id": "telemetry-source-001",
    "type": "mqtt",
    "broker_masked": "mqtts://broker.example:8883",
    "topic": "thing/product/drone_001/osd",
    "credential_ref": "secret://uav/drone_001/mqtt"
  },
  "validation": {
    "status": "valid",
    "validated_at": "2026-07-13T08:00:00Z",
    "error_code": null
  }
}
```

本地回放使用 `mode=local`、`video.source_type=mp4`；遥测可为 `source_type=srt` 或 `source_type=file`。`file` 只接受 allowlist 内可解析的 DJI Cloud API JSON `.json/.txt`，并可携带 `time_offset_sec` 与 `sync_tolerance_sec`；两者持久化到 `uav_telemetry_sources.config`，由 PipelineManager 传给生产入口。偏移后的最近记录超过容忍窗口时必须返回无有效遥测，不得沿用旧记录或插值。响应只返回文件名、同步参数和验证摘要，不返回服务器完整路径。

#### 0.10.4 FlightPlan 与 Mission 最小 shape

```json
{
  "flight_plan_id": "flight-plan-001",
  "name": "小清河早高峰",
  "status": "enabled",
  "drone_id": "drone_001",
  "inter_id": "inter-001",
  "road_data_version": "road9-2026-07-13",
  "source_profile_id": "source-profile-001",
  "ai_mode": "intersection_situation",
  "schedule": {
    "type": "weekly",
    "timezone": "Asia/Shanghai",
    "weekdays": [1, 2, 3, 4, 5],
    "start_local_time": "07:00:00",
    "end_local_time": "09:00:00",
    "effective_from": "2026-07-13",
    "effective_to": "2026-12-31",
    "excluded_dates": ["2026-10-01"]
  }
}
```

`schedule.type=once` 时使用带 offset 的 `start_at/end_at`。weekly 的结束时刻不晚于开始时刻时，结束时间落在下一自然日。数据库时间以 UTC 保存，API 必须返回业务时区。

Mission 至少返回 `mission_id/flight_plan_id/trigger_type/scheduled_start_at/scheduled_end_at/actual_started_at/actual_ended_at/status/reason_code/error_summary/pipeline_id/parent_mission_id/retry_number` 以及创建时冻结的设备、源、路网和计划快照。首次计划执行使用 `(flight_plan_id, scheduled_start_at)` 幂等；retry 创建新 Mission 并引用原 Mission，不能覆盖失败事实。

#### 0.10.5 调度、冲突与错误

- 调度器在 FastAPI 单体中作为后台服务运行，扫描周期不超过 5 秒；多实例通过 PostgreSQL advisory lock/数据库租约和唯一约束保证单调度者效果。
- 同一无人机的 enabled 计划不得有重叠窗口；不同无人机可监测同一路口。
- 平台重启时，当前时间仍在窗口内则幂等恢复；窗口已结束则 `status=skipped, reason_code=window_missed`，不自动补跑。
- 编辑计划只影响未来执行；已生成/运行 Mission 保留原计划和数据源快照。
- 本地视频 EOF 正常完成并返回 `reason_code=source_eof`；Pipeline 非零退出返回 `reason_code=pipeline_error`，窗口内运行时丢失返回 `reason_code=pipeline_runtime_missing`，错误摘要必须脱敏。调度 tick 将 Pipeline `stopped/error` 同步到 Mission 和 `uav_pipelines`，不得等到窗口结束才掩盖真实终态。
- 同一无人机已有 `pending/starting/running` Mission 时，手动启动返回 HTTP `409` 和 `code=drone_mission_active`；不同无人机/路口可独立启动。
- 统一错误至少包含 `validation_error`、`forbidden`、`not_found`、`state_conflict`、`schedule_overlap`、`source_invalid`、`road_context_invalid`、`pipeline_start_failed` 和 `scheduler_unavailable`。

验收接缝固定为：创建无人机/数据源 → 创建并启用 FlightPlan → 调度生成 Mission 并调用 PipelineManager → 查询视频/SRT 同步与遥测 → 到时或 EOF 停止 → 查询 Mission/审计。当前本地 PostgreSQL、双调度实例、重启恢复、停止/重试和 `inter_xqh` MP4+SRT 已通过工程验证；`docs/test_report_s9_inter_xqh_eof.json` 进一步证明 5GB 原视频在恢复新 Pipeline 后自然 EOF并写入 `completed/source_eof`。计划到 Pipeline running 的 P95 偏差目标 ≤10 秒及生产容量仍需在批准环境验收，同一窗口重复 Mission/Pipeline 数必须为 0。

### 0.11 执法候选线索契约（S4 本地工程契约已实现）

I4 通过 `EnforcementService` 将候选围栏、候选规则、统一 AI 事件、证据引用和技术复核收敛为一个事务边界。实现只形成 `unverified` 的 AI 待复核线索；权威围栏/规则、违法认定、法定测速、案件和处罚均不属于本接口。

| 方法 | 路径 | 权限与行为 |
| --- | --- | --- |
| GET/POST | `/api/v1/enforcement/zones` | 授权用户读取；仅 admin 创建本地 candidate 围栏 |
| GET/PATCH | `/api/v1/enforcement/zones/{zone_id}` | 查询或使用 `revision` 乐观并发更新 candidate/retired 配置 |
| POST | `/api/v1/enforcement/zones/{zone_id}/publish` | 权威 Adapter/审批合同未冻结时固定返回 503，不模拟 published |
| GET/POST | `/api/v1/enforcement/rules` | 查询或由 admin 创建候选事实规则；禁止声明 approval/penalty/violation |
| GET/PATCH | `/api/v1/enforcement/rules/{rule_id}` | 查询或使用 `revision` 更新 candidate/retired 规则 |
| POST | `/api/v1/enforcement/rules/{rule_id}/publish` | 外部批准链未冻结时固定返回 503 |
| GET/POST | `/api/v1/enforcement/clues` | 查询线索；admin/内部接缝按 `source_event_id + idempotency_key` 幂等写入事实和证据 |
| GET | `/api/v1/enforcement/clues/{event_id}` | 返回 AI 事件、执法详情、证据引用/哈希、技术复核和投递阻断状态 |
| POST | `/api/v1/enforcement/clues/{event_id}/review` | admin 以 `expected_revision` 技术确认/驳回；只追加复核审计 |
| GET | `/api/v1/enforcement/truck-summary` | 返回真实分类/质量聚合；没有在线事实时为空，不生成模拟车辆位置 |

写操作仅 admin 可用；`operator/viewer` 只读。revision 冲突返回 409，状态、质量或雷达字段门禁返回 422，权威发布或主平台依赖不可用返回 503。服务端权限是唯一可信边界，Console2 按钮禁用不能替代鉴权。

`vehicle_class` 只允许 `truck/non_truck/unknown`。视频速度必须带方法和质量；雷达速度必须带真实设备 ID 与 `calibration_status=valid`；没有独立视频与雷达测量及融合方法时，`fused_speed_kmh` 必须为空。字段缺失时返回空值和质量原因，禁止用视频速度回填雷达或融合值。

每条线索以 `uav_ai_events(event_type=enforcement_clue)` 为事件主记录，`uav_enforcement_clues` 只保存领域事实；证据使用 `uav_evidence_packages/uav_evidence_items`，复核追加到 `uav_enforcement_review_audits`。EventDelivery 外部 Adapter 未冻结时保持 `not_queued/blocked`，不得产生成功回执或 delivered 状态。

`platform/scripts/validate_i4_inter_xqh.py` 只创建带 `validation_fixture=true`、`detected_enforcement_clue=false` 的工程契约样本，使用真实 MP4/SRT 哈希验证证据和持久化；它不是检测器生成的违法线索，也不构成精度、法制或生产验收。

## 1. Kafka 旧消息快照（历史，运行时已拒绝）

> 本节基于 commit `e69acee` 的历史代码。以下无 `uav_` 前缀名称仅用于理解旧快照；当前运行时拒绝，不能作为迁移兼容、生产者输入或正式验收契约。

### Topic 命名
- 统计：`statistics_{camera_id}`（如 `statistics_1`）
- 完成轨迹：`track_complete_{camera_id}`（如 `track_complete_1`）
- 冲突事件：`conflicts_{camera_id}`（如 `conflicts_1`）

### 统计消息格式（statistics_{n}，向后兼容扩展）
```json
{
  "camera_id": "id_1",
  "cars": 12,
  "msg_type": "stats",
  "intersection_id": "INT_camera_1",
  "active_tracks": 12,
  "active_trajectories": [
    {
      "track_id": 142,
      "vehicle_class": "motor",
      "yolo_class_id": 3,
      "direction_class": "straight",
      "turn_behavior": null,
      "duration_sec": 3.2,
      "avg_speed_kmh": 18.4,
      "max_speed_kmh": 27.6,
      "trajectory_px": [[100,200], [105,210]],
      "trajectory_enu_m": [[12.3, -5.2], [12.8, -4.9]],
      "trajectory_gcj02": [[121.456789, 31.234567], [121.456794, 31.234571]],
      "current_point_enu_m": [12.8, -4.9],
      "anchor_gcj02": [121.456789, 31.234567],
      "timestamp_first": 120.5,
      "timestamp_last": 123.7
    }
  ],
  "road_1": 4.2,
  "road_2": 3.8,
  "road_3": null,
  "road_4": 2.1,
  "road_5": 1.5,
  "direction_flow": {
    "straight": {"count": 5, "avg_speed_kmh": 28.3, "avg_headway_sec": 2.1, "min_headway_sec": 1.5},
    "left_turn": {"count": 3, "avg_speed_kmh": 22.1, "avg_headway_sec": null, "min_headway_sec": null},
    "right_turn": {"count": 2, "avg_speed_kmh": 25.0, "avg_headway_sec": null, "min_headway_sec": null},
    "u_turn": {"count": 0, "avg_speed_kmh": 0, "avg_headway_sec": null, "min_headway_sec": null},
    "unknown": {"count": 1}
  },
  "queue_count": 2,
  "avg_speed_kmh": 26.5,
  "lane_stats": null,
  "lane_source": "model",
  "lanes": [],
  "road_polygons": {
    "1": [1195, 361, 1297, 310, 1399, 315, 1350, 380]
  },
  "conflict_count": 0,
  "tcc_diagnostics": {
    "enabled": true,
    "calibration_valid": true,
    "motor_tracks": 12,
    "non_motor_tracks": 4,
    "eligible_motor_tracks": 8,
    "eligible_non_motor_tracks": 3,
    "candidate_pairs": 24,
    "prediction_candidates": 0,
    "evidence_passed": 0,
    "deduplicated": 0,
    "events_emitted": 0,
    "business_events_emitted": 0,
    "experimental_events_emitted": 0,
    "status": "no_prediction_candidates"
  },
  "drone_position": {
    "anchor_lat": 31.234567,
    "anchor_lon": 121.456789,
    "easting_m": 15.3,
    "northing_m": -8.2
  },
  "is_hovering": false
}
```

### 完成轨迹消息格式（track_complete_{n}）
```json
{
  "msg_type": "track_complete",
  "intersection_id": "INT_camera_1",
  "track_id": 142,
  "start_road": 1,
  "exit_road": 3,
  "turn_behavior": "left_turn",
  "vehicle_class": "motor",
  "yolo_class_id": 2,
  "duration_sec": 8.4,
  "avg_speed_kmh": 22.3,
  "max_speed_kmh": 35.1,
  "trajectory_px": [[100,200], [105,210]],
  "trajectory_enu_m": [[12.3, -5.2], [12.8, -4.9]],
  "trajectory_gcj02": [[121.456789, 31.234567], [121.456794, 31.234571]],
  "entry_point_enu_m": [10.1, -6.5],
  "exit_point_enu_m": [18.4, 2.1],
  "anchor_gcj02": [121.456789, 31.234567],
  "timestamp_first": 120.5,
  "timestamp_last": 128.9
}
```

### 冲突事件消息格式（conflicts_{n}）
```json
{
  "msg_type": "conflict",
  "intersection_id": "INT_camera_1",
  "motor_id": 142,
  "non_motor_id": 156,
  "prediction_type": "path_intersection",
  "motor_position_enu_m": [12.3, -5.2],
  "non_motor_position_enu_m": [12.3, -5.2],
  "distance_m": 0.0,
  "ttc_sec": 1.5,
  "pet_sec": 0.2,
  "arrival_time_delta_sec": 0.2,
  "motor_arrival_ttc_sec": 1.3,
  "non_motor_arrival_ttc_sec": 1.5,
  "severity": "warning",
  "conflict_scene": "suspected_right_turn_mv_nmv",
  "conflict_angle_deg": 90.0,
  "evidence": ["hard_ttc_or_pet", "hard_pet"],
  "risk_score": 70,
  "motor_speed_kmh": 25.0,
  "anchor_gcj02": [121.456789, 31.234567]
}
```

冲突检测默认启用（`conflict_detection.enabled: true`），但无有效单应性矩阵、双方世界坐标速度向量或足够历史轨迹时会自动跳过，避免像素距离和短轨迹抖动误报。`ttc_sec` 基于 motor/non_motor 世界坐标运动趋势做未来 `0-5s` 候选交汇预测；有足够历史轨迹时，预测方向优先取最近一个有效轨迹段，速度大小沿用 `SpeedEstimationNode` 的米/秒估计，避免线性回归测速方向在转弯或轨迹错位时制造虚假交点。默认路径交点候选必须同时满足：双方预测路径存在空间交点、到达时间差不超过 `arrival_time_tolerance_sec`（默认 `1.0s`）、且双方到达交点这段时间内的连续同刻最小中心距进入 `same_time_collision_radius_m`（默认 `0.8m`）共同冲突区；只有数学射线交点但同刻距离仍偏大的 0.9m~1.7m 擦肩轨迹不会被判成相撞。同刻 CPA 候选默认关闭（`enable_same_time_cpa: false`），显式开启后也只使用 `same_time_collision_radius_m`，且 CPA 的 `pet_sec=0` 不作为 PET 侵占证据。候选还必须满足 `30°~150°` 冲突角，并归入无车道标注轨迹几何近似场景：`suspected_right_turn_mv_nmv` 或 `suspected_unprotected_left_turn`。机动车转弯场景除首尾 heading 差外，还要求转弯前后两段投影位移都达到 `min_turn_leg_m`（默认 `2.0m`），用于过滤短窗口小折线和近直行误分。

最终 `conflict` 事件需要 near-miss 证据：`hard_ttc_or_pet`（默认 TTC <= 1.5s）可直接触发；路径交点 `hard_pet`（默认 PET <= 1.0s）只表示极近抢行强度，必须叠加 `hard_deceleration`、`hard_steering`、`stop_or_yield` 之一才触发事件，避免仅凭数学交点和低 PET 把近距离错位经过报成 near-miss。`hard_steering` 只把非机动车短窗口 heading 突变视为避险证据，机动车正常右/左转不计作避险急转向。`prediction_type` 标识候选来源，默认业务口径只展示/处理 `path_intersection`；显式启用扩展时产生的 `same_time_cpa` 属于中心点同刻最近接近候选，Monitoring 冲突回放入口会过滤该类 CPA-only 擦肩事件。旧格式事件仅在缺少 `prediction_type` 且 `distance_m` 近似 `0.0` 时按路径交点兼容，带 `prediction_type=path_intersection` 但 `distance_m` 非零的畸形消息也会被前端过滤，0.9m/1.3m/1.7m 等非零距离旧 CPA 消息不会进入业务冲突列表。`distance_m` 表示预测冲突时刻的双方距离，路径交点场景为 `0.0`；`motor_position_enu_m` / `non_motor_position_enu_m` 表示预测冲突点附近的双方未来 ENU 世界坐标。`motor_arrival_ttc_sec` / `non_motor_arrival_ttc_sec` 表示双方到达冲突点的预测时间。`motor_id` / `non_motor_id` 轨迹对同级别事件不重复上报，但允许从 `warning` 升级为 `critical` 再次上报，直到轨迹清理后释放状态。Platform Kafka consumer 的实时冲突缓存和 WebSocket 推送同样按 `motor_id` / `non_motor_id` upsert，同级重复消息会被丢弃，升级消息会替换原事件并重新推送。机非分类由 `vehicle_classification.non_motor_class_names` / `non_motor_class_ids` 配置非机动车集合；未配置的已知检测类别按机动车处理。摩托车、电动车相关类别默认归入非机动车。

### 世界坐标说明

所有计算坐标使用**东北天(ENU)**坐标系，单位为米，原点为 `anchor_gcj02`：
- `easting_m` (+X) = 东向偏移
- `northing_m` (+Y) = 北向偏移

ENU 与 GCJ-02 的双向转换只由服务端版本化实现完成；浏览器不得使用近似公式。

### 字段说明（统计消息）
| 字段 | 类型 | 说明 |
|------|------|------|
| `camera_id` | string | 格式 `id_{N}`，N 为摄像头编号 |
| `cars` | int | 当前帧滑动窗口平均车辆数 |
| `active_tracks` | int | 当前帧活跃跟踪目标数 |
| `active_trajectories` | array | 当前活跃轨迹轻量快照；包含 `trajectory_px` 证据，以及地图已验证时的 `trajectory_enu_m`、`trajectory_gcj02`、`anchor_gcj02`、`map_version_id` 和车道匹配字段 |
| `road_1` ~ `road_5` | float \| null | 每条道路的车辆活跃度（辆/分钟） |
| `msg_type` | string | 消息类型标识（"stats"） |
| `intersection_id` | string | 路口标识（`INT_camera_{N}`） |
| `direction_flow` | dict \| null | 方向流量统计（始终输出） |
| `queue_count` | int | 当前排队车辆数 |
| `avg_speed_kmh` | float | 整体平均车速 |
| `lane_stats` | dict \| null | 车道级统计（有标注或模型检测时输出） |
| `lane_source` | string \| null | 车道数据来源：`"manual"` / `"model"` / `"auto"` / `null` |
| `road_polygons` | dict | 当前检测配置中的道路多边形，供悬停生成标注任务后导出复用 |
| `conflict_count` | int | 当前帧正式 TCC 事件数；只计 `prediction_type=path_intersection && distance_m≈0.0`，实验 `same_time_cpa` 不计入 |
| `tcc_diagnostics` | dict \| null | TCC 轻量漏斗：检测/标定状态、输入及合格机非轨迹、候选配对、预测、证据、去重、正式/实验事件计数和可解释状态 |
| `drone_position` | dict \| null | 无人机位置（有遥测时输出） |
| `is_hovering` | bool | 是否悬停 |

### 发送频率
- 由 `kafka_producer_node.how_often_sec` 控制（默认 1 秒）
- 第一帧始终发送
- `active_trajectories` 随统计消息发送，是成熟且生命周期未结束轨迹的当前尾部快照，避免长时间运行时 Kafka 单条消息无限增长；console 按 `track_id` 累积尾部点列用于 BEV 显示和 GeoJSON 导出。只有关联结束、源时间断点、关联超时或自然 EOF 才通过 `uav_track_complete_{camera_id}` 发送完整轨迹；30 秒统计窗口到期不得触发完成。

### BEV GeoJSON 导出
- Console2 必须把 SourceProfile-scoped 历史 REST 快照与当前 WebSocket 状态分开保存；历史采样刷新不得清空或覆盖 `active_trajectories` / `candidate_trajectories`。`uav_stats`、`uav_track_complete` 和 `uav_conflict` 还必须携带并匹配当前运行 `pipeline_id`，同一 SourceProfile 的旧 Pipeline 消息或缺失 Pipeline lineage 的消息不得进入当前实时会话；Pipeline 切换时必须清空旧会话的统计、活动/候选/完成轨迹和实时冲突。BEV 只绘制至少两个合法 `trajectory_gcj02` 点的轨迹；只有 `trajectory_px` 的候选显示“地理投影不可用”，不得执行浏览器侧像素→地图猜测。
- Console BEV 视图导出时会合并三类轨迹：当前活跃轨迹快照、当前会话已完成轨迹、历史 API 查询轨迹。
- 展示层可限制绘制数量以保持流畅，但导出使用当前会话缓存的全量轨迹数据，不受 BEV 显示上限裁剪。
- GeoJSON geometry 使用 `trajectory_gcj02`，坐标顺序固定 `[longitude, latitude]`；properties 保留 `trajectory_enu_m`、`trajectory_px`、地图版本和车道匹配 lineage。

### 生产者
- 文件：`nodes/KafkaProducerNode.py`
- 序列化：`json.dumps(x).encode("utf-8")`
- 异步发送：主线程只调用 `_enqueue(topic, data)` 写入有界队列；后台 `kafka_sender` 线程调用 `KafkaProducer.send()`，Kafka 阻塞或短暂失败不会阻塞检测管道。

### 消费者
- 本段描述的旧消费者已删除。当前由 Platform/TimescaleDB writer 直接写入 `road9`。

### ⚠️ 当前约束
- **拒绝旧契约**：旧 `road_1`~`road_N`、旧 Topic 和旧 `msg_type` 不由运行时接收；消息必须使用动态 `roads[]` 和第 0 节冻结的 `uav_*` canonical 契约。
- **禁止恢复旧 Grafana/InfluxQL**：新增道路、车道和指标只进入 canonical 消息及 PostgreSQL/TimescaleDB 模型。
- **禁止双投/fallback**：本机切换窗口已经结束，只保留第 0 节冻结的 `uav_*` Topic。

### 规划中：智慧交通主平台 AI 事件联动契约（PRD v1.7，尚未实现）

> 本节记录 `docs/generated/2026-06-29-uav-traffic-ai-prd.md` v1.7 及 `docs/generated/uav-traffic-ai-prd/S6-main-platform-integration-prd.md` 的待冻结目标契约，不代表当前代码已实现。最终传输方式、URL/Topic、认证、SLA、字段类型、必填性、枚举、错误码和兼容策略须与智慧交通主平台方联调确认后转为正式契约。

所有态势风险、换道冲突、测绘和执法线索事件至少包含：

```json
{
  "message_id": "6ec171d1-b3c1-4d75-b6bd-a099ad4f3560",
  "msg_type": "uav_ai_event",
  "schema_version": "uav_ai_event/v1",
  "occurred_at": "2026-07-13T02:00:00.123Z",
  "produced_at": "2026-07-13T02:00:00.180Z",
  "source_system": "uav_traffic_analyzer_ai",
  "intersection_id": "INT_camera_1",
  "inter_id": "authoritative-inter-id",
  "road_data_version": "published-version-id",
  "trace_id": "trace-uuid",
  "source_time_semantics": "event_time",
  "time_quality": "verified",
  "data": {
    "source_event_id": "uav-ai-event-uuid",
    "idempotency_key": "stable-retry-key",
    "platform_event_id": null,
    "event_type": "conflict",
    "road_context_status": "ok",
    "link_id": "authoritative-link-id",
    "lane_id": null,
    "map_match_method": "manual",
    "map_match_confidence": 0.98,
    "position_gcj02": {"longitude": 121.456789, "latitude": 31.234567},
    "severity": "high",
    "confidence": 0.91,
    "quality_status": "ok",
    "evidence_refs": []
  }
}
```

契约冻结前必须确认：

- 主平台分配/映射 `platform_event_id`，并对相同 `(source_system, idempotency_key)` 返回同一接收结果；
- 子项目事件投递状态为 `generated/delivering/delivered/delivery_failed`，不复制主平台派警处置状态；
- 投递失败使用持久化出站队列、指数退避和死信告警，不得静默丢弃；
- 主平台回传 `confirmed/rejected`、原因和可用的处置结果，供质量统计和模型反馈；
- AI `high/medium/low` 与主平台 P1/P2/P3 的映射独立配置；
- 换道/冲突扩展字段包含换道前后车道、横向偏移/速度、加速度、轨迹曲率、TTC、PET、最小距离、冲突角度、冲突点 ENU/GCJ02、预测时域和预测方法；
- 执法线索同时保留视频估算速度、雷达速度（可空）、融合/采信速度及各自来源和质量信息。

#### 规划中：路网主数据上下文字段

统计、完成轨迹和 AI 事件统一增加以下可选字段，待路网适配器和智慧交通主平台契约冻结后实现：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `road_data_version` | string | 任务启动时冻结的已发布路网版本 |
| `road_context_status` | string | `ok/stale/missing/version_mismatch` |
| `inter_id` | string | 路网主数据权威路口ID；原 `intersection_id` 暂保留兼容 |
| `link_id` / `lane_id` | string \| null | 当前轨迹或事件匹配到的权威 Link/车道ID |
| `entry_link_id` / `exit_link_id` | string \| null | 完成轨迹入口/出口 Link |
| `entry_lane_id` / `exit_lane_id` | string \| null | 完成轨迹入口/出口车道，可无法识别 |
| `map_match_method` | string | `manual/master_geometry/trajectory/model/unmapped` |
| `map_match_confidence` | number \| null | 0～1；`unmapped` 时为空或 0 |

主数据ID必须和 `road_data_version` 同时保存。无法匹配时字段置空并标记 `unmapped`，不得使用本地数组序号或 `road_N` 兼容字段伪造权威ID。

## 2. Flask 视频流 API

### 端点

#### `GET /`
- 返回：HTML 页面（`utils_local/templates/index.html`）
- 内容：包含 `<img src="/video"/>` 的简单页面

#### `GET /video`
- 返回：`multipart/x-mixed-replace; boundary=frame` MJPEG 流
- 每帧格式：JPEG 编码的 numpy 数组
- 帧尺寸：由 `video_server_node.output_size` 控制（默认 `[1280, 720]`）
- JPEG 质量：由 `video_server_node.jpeg_quality` 控制（默认 `92`）
- 绑定地址：`0.0.0.0:8100`

#### Platform `GET /api/v1/video/camera/{camera_id}`
- 返回：运行中 PipelineManager 管道的 MJPEG 流，`multipart/x-mixed-replace; boundary=frame`
- 用途：旧客户端兼容和运维诊断；Console2 实时监控屏与无人机屏不再调用该端点。
- 无运行管道：返回 `404 {"error":"camera_not_running","camera_id":N}`
- 认证：该端点为公开只读流端点，由 `AuthMiddleware.PUBLIC_PATHS` 放行。

#### Console2 检测器直连
- Pipeline 启动时按 `PIPELINE_VIDEO_BASE` 登记 `video_stream_url`；本机默认值为 `http://127.0.0.1:{video_port}/video`。
- 外部检测进程调用 `POST /api/v1/pipelines/register` 时可显式提交 `video_stream_url`。
- `/monitoring` 和 `/drones` 只使用响应中的 `video_stream_url`；Vite 仅代理 `/api`、`/ws`，不代理 `/camera_*`。
- 登记值仅接受无凭据、无 query/fragment 的 `http/https` URL。UAT/生产必须配置浏览器可达的 HTTPS 模板。

### 技术细节
- 使用 Flask 的 `Response` 生成器实现流式推送
- 帧通过 `cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])` 编码
- 服务器在守护线程中运行（`Thread(daemon=True)`）
- 帧更新通过 `self._frame` 实例变量，无锁保护（可能出现撕裂）

## 3. Nginx 旧客户端兼容路由

### 路由规则
```nginx
location ~ ^/camera_(\d+)$ {
    rewrite ^/camera_(\d+)$ /api/v1/video/camera/$1 break;
    proxy_pass http://platform:8000;
    proxy_buffering off;
}
```

### 兼容访问方式
| URL | 代理到 |
|-----|--------|
| `http://localhost:8009/camera_1` | `platform:8000/api/v1/video/camera/1` |
| `http://localhost:8009/camera_2` | `platform:8000/api/v1/video/camera/2` |
| `http://localhost:8009/camera_N` | `platform:8000/api/v1/video/camera/N` |

### 约束
- camera ID 必须对应 PipelineManager 中状态为 `running` 的管道
- Platform 在容器内访问该管道的 `127.0.0.1:{video_port}/video`
- Console2 不使用这些路径；新客户端以 Pipeline/Mission 响应的 `video_stream_url` 为准

## 4. 旧时序数据模型（历史快照，已退役）

> 本节仅保存历史快照，不再用于迁移对账或当前代码定位。目标平台不向旧时序库写入或查询，历史数据明确不迁移；新的指标字段不得加入此模型。

### 数据库
- 名称：`influx`
- 版本：InfluxDB 1.8
- 保留策略：30 天自动删除

### Measurement
- 命名：`camera_{N}`（由 Telegraf `name_override` 控制）
- 每个摄像头一个 measurement

### 字段
| 字段 | 类型 | 说明 |
|------|------|------|
| `cars` | float | 车辆总数（滑动窗口平均） |
| `road_1` ~ `road_5` | float | 道路活跃度（辆/分钟） |
| `camera_id` | string | 摄像头标识（`id_N`） |

### 标签
- 无自定义标签（Telegraf 默认添加 `host` 标签）

### 查询示例（Grafana InfluxQL）
```sql
-- 车辆数时序图
SELECT mean("cars") FROM "camera_1" WHERE $timeFilter GROUP BY time($interval)

-- 当前道路拥堵
SELECT road_1, road_2, road_3, road_4, road_5 FROM "camera_1" ORDER BY time DESC LIMIT 1

-- 道路拥堵趋势
SELECT road_1, road_2, road_3, road_4, road_5 FROM "camera_1" ORDER BY time DESC
```

## 5. 管道节点接口

### 标准接口
```python
class SomeNode:
    def __init__(self, config: dict) -> None:
        """从 Hydra 配置字典初始化节点"""
        ...

    def process(self, frame_element: FrameElement) -> FrameElement:
        """处理一帧，返回增强的 FrameElement"""
        if isinstance(frame_element, VideoEndBreakElement):
            return frame_element
        ...
        return frame_element
```

### 特殊接口

#### VideoReader（生成器模式）
```python
def process(self) -> Generator[FrameElement, None, None]:
    """逐帧产出 FrameElement，流结束时产出 VideoEndBreakElement"""
```

#### VideoSaverNode（终端节点）
```python
def process(self, frame_element: FrameElement) -> None:
    """写入帧到文件，收到 VideoEndBreakElement 时释放资源"""
```

#### FlaskServerVideoNode.VideoServer（终端节点）
```python
def process(self, frame_element: FrameElement) -> None:
    """更新帧缓冲区，Flask 线程持续推送"""
```

## 6. 旧 Dashboard API（历史快照，已退役）

> 以下接口仅供清点/导出旧看板。目标部署移除 Grafana，不得把这些 API 纳入新平台验收。

### 获取仪表盘
```
GET http://localhost:3111/api/dashboards/uid/{uid}
Authorization: Basic {base64(admin:admin)}
```

### 更新仪表盘
```
POST http://localhost:3111/api/dashboards/db
Content-Type: application/json
{
  "dashboard": {...},
  "message": "update reason",
  "overwrite": true
}
```

### 已知仪表盘 UID
| 摄像头 | UID |
|--------|-----|
| Camera 1 | `edycr94pt2mm8b` |
| Camera 2 | `adycu34xs035sb` |

### ⚠️ 安全风险
- `export_dashboards.py` 和 `fetch_dashboard.py` 中硬编码了 `admin:admin` 凭据
- 这些脚本仅用于开发环境，生产环境不应使用

---

## 7. 平台 Web 服务 API（platform/app/api/v1/）

> 2026-05-29 从微服务重构为单体架构。含旧 Topic 或旧 WebSocket 名称的示例仅是历史快照；当前契约以第 0 节为准。

### 基础 URL
- 本地开发：`http://localhost:8000`
- Docker Compose：Platform API `http://localhost:8000`；Console `http://localhost:8080`（Console 内部通过 `/api/` 代理到 `platform:8000`）

### 健康检查端点（无需认证）

#### `GET /health`
- 返回：`{"status": "healthy"}`
- 用途：存活检查（liveness probe）

#### `GET /ready`
- 当前实现只检查 canonical 依赖：
```json
{
  "status": "ready",
  "services": {
    "database": "healthy",
    "kafka": "healthy",
    "timescaledb": "healthy",
    "pipeline_manager": "healthy"
  }
}
```
- 用途：就绪检查；HTTP 保持 200 兼容，但 database、Kafka、TimescaleDB 任一为
  `degraded/not_configured` 时整体 `status=degraded`，不得作为容器就绪信号。

### 认证端点

#### `POST /api/v1/auth/register`
- 必须携带 admin Bearer JWT；系统不提供匿名自注册。
- 请求体：
```json
{
  "username": "string",
  "email": "user@example.com",
  "password": "string",
  "role": "viewer"
}
```

- 返回（201）：
```json
{
  "id": 1,
  "username": "string",
  "email": "user@example.com",
  "role": "viewer",
  "is_active": true
}
```
- 错误（400）：`{"detail": "Username already registered"}`
- 错误（401/403）：未登录或非管理员。

#### `POST /api/v1/auth/login`
- 请求体：
```json
{
  "username": "string",
  "password": "string"
}
```
- 返回（200）：
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "user": {
    "id": 1,
    "username": "admin",
    "email": "admin@example.com",
    "role": "admin",
    "is_active": true
  }
}
```
- 错误（401）：`{"detail": "Incorrect username or password"}`
- 响应同时设置 `uav_media_session` HttpOnly Cookie，仅供 WebSocket、MJPEG 和 HLS；
  `SameSite=strict`、`Path=/`，Max-Age 与 JWT 一致，uat/production 强制 `Secure`。

#### `POST /api/v1/auth/logout`
- 公开且幂等；清除 `uav_media_session`，即使 Bearer 已过期也可退出。
- 返回（200）：`{"status": "logged_out"}`。

#### `GET /api/v1/auth/media-session`
- 只接受 `uav_media_session` Cookie，校验 JWT 后回查用户仍存在且启用。
- 返回（200）：当前媒体会话主体；无效、过期或禁用用户返回 401。

#### `GET /api/v1/auth/me`
- 请求头：`Authorization: Bearer <token>`
- 返回（200）：
```json
{
  "id": 1,
  "username": "string",
  "email": "user@example.com",
  "role": "admin",
  "is_active": true
}
```

### 用户只读端点（需要 JWT）

#### `GET /api/v1/users`
- 用途：Console 的 Admin / Users 页面展示真实平台用户，不返回密码哈希。
- 返回：
```json
[
  {
    "id": 1,
    "username": "admin",
    "email": "admin@example.com",
    "role": "admin",
    "is_active": true,
    "created_at": "2026-05-29T00:00:00"
  }
]
```

### 受保护端点（需 Bearer token）

#### `GET /api/v1/intersections`
- 请求头：`Authorization: Bearer <token>`
- 返回（200）：
```json
{
  "intersections": [
    {
      "id": "int-001",
      "name": "Demo Roundabout A",
      "roads": 5,
      "cameras": 2
    }
  ]
}
```

#### `GET /api/v1/drones`
- 请求头：`Authorization: Bearer <token>`
- 返回（200）：
```json
[
  {
    "id": "DJI-M300-001",
    "model": "DJI Matrice 300 RTK",
    "status": "idle",
    "battery": 85
  }
]
```

#### `POST /api/v1/drones`
- 请求头：`Authorization: Bearer <token>`
- 请求体：
```json
{
  "id": "string",
  "model": "string",
  "status": "idle"
}
```
- 返回（201）：创建的无人机对象

#### `GET /api/v1/system/health`
- 请求头：`Authorization: Bearer <token>`
- 返回（200）：
```json
{
  "status": "healthy",
  "service": "platform",
  "kafka_connected": true,
  "ws_connections": 0,
  "ws_channels": {},
  "pipelines_active": 0
}
```

#### `GET /ready`
- 公开端点，用于平台依赖就绪检查；只返回 canonical 依赖。
- 返回（200）：
```json
{
  "status": "ready",
  "services": {
    "database": "healthy",
    "kafka": "healthy",
    "timescaledb": "healthy",
    "pipeline_manager": "healthy"
  },
  "pipelines_active": 0
}
```

### 事故测绘 REST API（S3 当前实现）

除证据下载外，所有接口使用 `/api/v1` 前缀和 Bearer JWT；证据下载同样要求 JWT。
事故民警只能访问分配给自己的任务，管理员可查看全部任务；服务器资产导入和对外投递仅管理员可用。
创建、状态动作、采集、量算、报告和投递写接口接受 `Idempotency-Key`，同键重试返回原业务结果。
状态修订不一致返回 `409`，状态机或质量门禁不满足返回 `422`。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET/POST | `/survey-tasks` | 查询/创建测绘任务 |
| GET | `/survey-tasks/{task_id}` | 读取任务、状态、质量和版本 |
| POST | `/survey-tasks/{task_id}/actions` | 前置核验、选择批次、提交/退回/技术复核、取消 |
| GET/POST | `/survey-tasks/{task_id}/capture-batches` | 查询批次/流式上传 MP4+SRT 并入队 |
| POST | `/survey-tasks/{task_id}/capture-batches/import` | 以 `source_profile_id` 引用已登记 MP4+DJI SRT/Cloud JSON，或兼容显式 allowlist 资产键；响应含遥测类型、同步配置和原始引用状态 |
| GET | `/survey-tasks/{task_id}/frames` | 查询原始帧、BEV、遥测和测量变换摘要；可量算帧返回 `metric_transform`（BEV 像素→ENU 米制 3×3 矩阵），供浏览器只读计算绘制中边长，服务端仍是最终量算真源 |
| GET/POST | `/survey-tasks/{task_id}/measurements` | 查询/创建服务端 ENU 点线面量算 |
| DELETE | `/survey-tasks/{task_id}/measurements/{measurement_id}` | 按 revision 删除当前量算版本 |
| GET/POST | `/survey-tasks/{task_id}/annotations` | 查询/创建关联持久关键帧的场景标注 |
| PATCH/DELETE | `/survey-tasks/{task_id}/annotations/{annotation_id}` | 按 revision 修改/删除车辆、痕迹、散落物或其他对象标注并写审计 |
| GET/POST | `/survey-tasks/{task_id}/reports` | 查询/生成 PDF+JSON+GeoJSON+标注 JPEG 成果包；列表与生成响应返回 `pdf_url/json_url/geojson_url/annotated_images[]`，其中标注图包含 `frame_id/frame_number/measurement_count/evidence_id/url/sha256` |
| POST | `/survey-tasks/{task_id}/reports/{report_id}/deliver` | 经批准质量规则、URL 和 outbox 投递主平台 |
| GET | `/survey-evidence/{evidence_id}/content` | 鉴权读取 managed 对象或 allowlist server asset，支持原视频 HTTP Range；拒绝绝对路径、路径穿越、缺失和哈希不一致引用；返回 `ETag`、`X-Content-SHA256`、`X-Storage-Backend`。server asset 首次登记或快速指纹变化时完整校验 SHA-256，未变化时以已持久化 size/mtime/ctime 快速确认，避免批次列表反复扫描大文件 |

浏览器上传单文件上限统一为 8GB，Console2 Nginx、根入口和 Platform 使用同一边界；超过
上限返回 413。`approve_review` 必须携带且只能携带以下六个 checklist 键，并全部为 true：
`task_and_location`、`source_materials`、`coordinate_chain`、`measurements`、
`edit_history`、`quality_status`。缺失、false 或额外键返回 422；批准审计的
`after_value.review_checklist` 保存完整清单。

量算画布以 `metric_transform` 对当前鼠标预览边实时显示米制长度，已保存的线、折线、面积和
对象按服务端 `metric_geometry` 在每条边上显示长度。报告生成时，每个包含当前量算的 BEV
帧都会固化为 `survey_report_annotated_image` 证据并嵌入 PDF；Console2 历史任务优先读取该
不可变标注图，旧报告没有该字段时使用原 BEV 与版本化量算记录只读重绘，不改写历史报告。

测绘结果 canonical schema 为 `uav.survey-result.v1`，事件固定
`msg_type=uav_ai_event`、`event_type=survey_result`、
`source_system=uav_traffic_analyzer_ai`。当前 S3 API 已实现本地闭环；主平台最终 URL、鉴权、回执、签章、归档和正式误差阈值仍由 S3/S6 评审冻结。

### WebSocket 端点

> 当前运行时只接受第 0.5 节的 canonical channel 和 `uav_*` 业务消息 `type`。

#### `WS /ws/realtime`
- 连接 URL：`/ws/realtime`，浏览器自动携带 `uav_media_session` HttpOnly Cookie。缺失、无效、
  过期或禁用用户在握手阶段以 `4401` 关闭；若 URL 出现 `access_token` query 同样拒绝。
- 连接后发送订阅消息：
```json
{
  "action": "subscribe",
  "channels": ["uav_intersection:INT_camera_1", "uav_alerts", "uav_telemetry:drone_001"]
}
```
也兼容单频道格式：
```json
{"action": "subscribe", "channel": "uav_system"}
```
- 客户端不得发送 `publish`；服务端返回 `unsupported_action`，不会广播客户端业务载荷。
- 服务端推送消息格式：
```json
{
  "channel": "uav_intersection:INT_camera_1",
  "type": "uav_stats",
  "data": {
    "intersection_id": "INT_camera_1",
    "cars": 12,
    "direction_flow": {...},
    "drone_position": {...}
  },
  "ts": 1234567890.123
}
```
- Channel 命名（已对齐 Kafka topic）：
  - `uav_intersection:{intersection_id}` — 实时统计 + 轨迹完成 + 冲突事件
  - `uav_alerts` / `uav_alerts:{intersection_id}` — 全局/路口级告警
  - `uav_telemetry:{drone_id}` — 无人机实时遥测
  - `uav_system` — GPU/系统指标
  - `uav_calibration` — 标定/车道标注任务
- Platform Kafka consumer 默认订阅 topic pattern：
```text
^(uav_statistics_|uav_track_complete_|uav_conflicts_|uav_telemetry_).+$|^uav_system_metrics$
```

### 认证机制
- REST JWT 在 `Authorization: Bearer <token>` 头中传递；Console2 保存在
  `sessionStorage:uav_access_token`。
- WebSocket、MJPEG 和 HLS 只使用后端登录时设置的 HttpOnly `uav_media_session`；前端不可读取。
- WebSocket URL 不携带 token；出现 `access_token` query 时即使 Cookie 有效也以 4401 拒绝。
- Token 包含 `sub`（user_id）、`username`、`role` 字段
- 中间件在 `platform/app/middleware/auth.py` 中实现
- 公开路径白名单不包含 register、Pipeline proxy map 或媒体内容；logout 只清 Cookie且幂等。
- WebSocket 客户端只允许 subscribe/unsubscribe/ping；`publish` 返回 `unsupported_action`。
- register、system/users/calibration 和 external pipeline register 要求 admin；Pipeline/FFmpeg
  写操作要求 operator/admin；前端菜单隐藏不是安全边界。
- 后端角色固定映射为 Console2 展示角色：`admin → 管理员`、`operator → 交通指挥员`、`viewer → 数据分析员`

## 8. 平台 REST API（43 条路由）

### 管道管理 `/api/v1/pipelines`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/pipelines` | 登录用户列出所有管道实例 |
| GET | `/api/v1/pipelines/summary` | 管道概览（running/stopped/error 计数） |
| POST | `/api/v1/pipelines` | operator/admin 启动；视频、遥测和 RTSP 必须通过 allowlist；车道/道路标注参数固定为空 |
| POST | `/api/v1/pipelines/register` | 仅 admin 登记外部管道；校验 camera、端口、canonical Topic 和重复占用。地图版本可空；无图时登记为 `road_context_status=missing / quality_status=degraded`，轨迹事件仍可输出。`candidate_only` 只为旧调用兼容，不再表示成熟轨迹被隔离 |
| DELETE | `/api/v1/pipelines/{id}` | operator/admin 停止并记录审计 |
| POST | `/api/v1/pipelines` | 启动新管道（201 Created） |
| GET | `/api/v1/pipelines/{id}` | 获取管道详情 |
| GET | `/api/v1/pipelines/{id}/status` | 获取管道健康状态 |
| DELETE | `/api/v1/pipelines/{id}` | 停止管道（进程组 SIGTERM → 10s → SIGKILL） |

#### 启动管道请求体
```json
{
  "drone_id": "drone_001",
  "intersection_id": "INT_camera_1",
  "video_src": "rtsp://192.168.1.100:554/stream",
  "map_version_id": "CMV-example-lane-verified",
  "telemetry_source": "srt",
  "telemetry_file_path": "test_videos/inter_xqh/telemetry.srt"
}
```

直接 `POST /api/v1/pipelines` 提供的 `map_version_id` 必须指向相同路口、相同路网版本的不可变
`lane_verified` 地图；运行中请求切换仍拒绝。`POST /api/v1/missions` 可选传入
`map_version_id` 进行严格绑定：该地图必须属于当前 `inter_id`，并具备当前 SourceProfile 的
`lane_verified`地图、Lane/Link几何与地图锚点；否则返回`422/runtime_map_not_ready`。未显式指定地图时，Mission先尝试调用方给出的已就绪
`road_data_version`，否则自动选择当前路口最新的完整`lane_verified`地图，
并把准确的map/version/checksum/选择策略冻结到`context_snapshot`。Console2快速启动
不再发送无人机档案中的原始道路版本，由 Platform 执行该源级选择。

手动 Mission 在没有任何可用地图时仍可启动 Pipeline，此时
`road_context_status=missing`、`quality_status=unverified`，只不生成 Lane ID、Link ID 与匹配质量。
世界坐标由当前帧视频尺寸、相机参数和同步遥测矩阵决定；检测、像素跟踪、完成事件、速度、方向、统计、TCC
和 MJPEG 均使用各自证据门禁，不读取路网匹配状态。

本地开发可通过环境变量控制平台启动的检测器子进程：
- `PIPELINE_PYTHON`：检测器 Python 解释器，例如 `/Users/yaoyao/miniconda3/envs/py312/bin/python`
- `PIPELINE_FRAME_STRIDE`：写入检测器 `FRAME_STRIDE` 环境变量，例如 `3`
- `PIPELINE_DEVICE`：检测设备；Apple Silicon 开发态固定为 `mps`
- `PIPELINE_IMGSZ`：遥测缺失超过 2 秒后的自适应回退分辨率，默认 `960`；它不关闭自适应策略
- `ADAPTIVE_IMGSZ_ENABLED`：已退役的环境开关，生产配置不再读取。Platform 与离线验收器默认显式
  开启 AGL 三档 `640/960/1280`；只有诊断命令的 `--no-adaptive-imgsz` 可临时使用固定尺寸
- `PIPELINE_VIDEO_READY_TIMEOUT_SEC`：等待检测器 MJPEG 端口完成绑定的秒数，默认 `45`
- `MISSION_PIPELINE_MISSING_GRACE_SEC`：运行 Mission 启动后确认 runtime 缺失的宽限秒数，默认 `15`
- `KAFKA_BOOTSTRAP`：检测器和平台 Kafka 地址，例如 `localhost:9092`

Apple Silicon 交互式运行使用 `scripts/mac_local_platform.sh up`。Platform 与检测器都使用
原生 `.venv-mps`，Pipeline/Mission 请求不能覆盖设备、解释器或 `imgsz`。本地文件仍由
Platform 在仓库 `test_videos/` allowlist 内解析；本机 MJPEG 直连地址由
`PIPELINE_VIDEO_BASE=http://127.0.0.1:{video_port}/video` 生成。
由 Platform 启动的检测器必须在端口绑定成功后向 stdout 输出 `MJPEG_READY port=<port>`；
执行器收到该信号前不得返回启动成功。等待超时或检测器提前退出时，Pipeline/Mission 按启动
失败返回并清理子进程，Console2 不得得到一个尚不可连接的 `running` 视频地址。
Mission 已进入 `running` 后，调度器在上述宽限期内遇到一次 runtime 查询缺失只记录告警并继续
观察；宽限期后仍缺失才写入 `pipeline_runtime_missing`，防止并发启动/轮询造成伪失败。

Apple Silicon 本机 MPS 回放使用 `scripts/run_native_mps_replays.py` 调用
`POST /api/v1/pipelines/register` 登记宿主机外部进程；登记请求中的视频路径仍使用
项目内 allowlist 相对路径，实际宿主机绝对路径只注入检测器的 `VIDEO_SRC`，不会写入 API
或审计记录。登记请求必须显式提交 `source_profile_id` 和 `inter_id`，Platform 原样记录并返回，
Console2 以该来源谱系关联活动 Pipeline、MJPEG 与实时 WebSocket 数据。外部进程必须携带返回的
`pipeline_id`、SourceProfile、`inter_id` 和
RoadContext 质量字段写入 canonical 信封。验收产物以 `pipeline_id` 过滤，避免混入同 Topic
历史消息。批处理进程通过 register 接口登记，和由 Platform 直接启动的交互式本地管道仍是
两种不同生命周期。登记请求同时提交浏览器可达的 `video_stream_url`，使监控屏和无人机屏
无需经过 Platform/Vite 视频代理。

无已发布地图的本地巡航工程回放使用普通外部 Pipeline 登记，固定
`map_version_id=null / road_context_status=missing / quality_status=degraded`。成熟图像轨迹进入
`active_trajectories`、通用车辆计数与 `uav_track_complete/v1`；仅 Lane ID、Link ID 与匹配质量保持关闭。
只有尚未满足最短时长和点数的图像关联位于 `candidate_trajectories`。

生产 Docker 发布使用根 `Dockerfile` 构建 Platform 与检测器统一镜像。检测实现位于镜像
`/app`，`PIPELINE_PROJECT_ROOT=/app`；权重与视频分别只读挂载到 `/app/weights` 和
`/app/test_videos`，不再依赖整个仓库的 `/project` 挂载。镜像安装
`platform/pipeline-requirements.txt` 并使用 `platform/pipeline-constraints.txt` 固定
`numpy<2`、`torch==2.2.2`、`torchvision==0.17.2`。

Platform 启动只初始化 PipelineManager；只有 Pipeline API 或 Mission 调度才会通过执行
seam 拉起 `main_optimized.py`。开发和生产都使用同操作系统的本地子进程，差异仅由部署配置
选择 macOS MPS 或 Linux CPU/CUDA。启动命令追加 `hydra/job_logging=disabled`，
检测器 multiprocessing 子进程也会检测 `FileHandler` 是否可写并在必要时降级到 console。
原独立检测器镜像保存在 `Dockerfile.detector`，不属于 canonical Compose。

平台会为每条检测管道创建独立进程组；停止管道时终止整个进程组，避免 `main_optimized.py` 的 multiprocessing worker 被父进程遗留后继续向 Kafka 写数据。
后台健康检查会每 5 秒检查子进程退出状态：`return_code == 0` 表示视频处理自然结束，
管道状态转为 `stopped`；非零退出才转为 `error`，并把 stderr 尾部写入
`error_message` 用于页面诊断。

#### 管道响应体
```json
{
  "pipeline_id": "pipe-a1b2c3d4",
  "drone_id": "drone_001",
  "intersection_id": "INT_camera_1",
  "video_src": "rtsp://...",
  "map_version_id": "CMV-a1b2c3d4",
  "topic_name": "uav_statistics_10",
  "camera_id": 10,
  "video_port": 8101,
  "video_stream_url": "http://127.0.0.1:8101/video",
  "status": "running",
  "started_at": 1234567890.123,
  "stopped_at": 0,
  "error_message": "",
  "uptime_seconds": 120.5
}
```

浏览器从 Pipeline 或 Mission 响应读取 `video_stream_url` 并直连检测器输出。远端部署不得使用
`127.0.0.1` 默认值，必须通过 `PIPELINE_VIDEO_BASE` 登记浏览器可达的 HTTPS 地址。

新建 Pipeline 返回 canonical `topic_name=uav_statistics_10`；consumer 不接收无前缀 Topic。

### 路口管理 `/api/v1/intersections`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/intersections` | 列出所有路口 |
| GET | `/api/v1/intersections/summary` | 系统级概览（车流量/拥堵/告警/无人机在线/管道数） |
| GET | `/api/v1/intersections/{id}` | 路口详情（含当前分配的无人机信息） |
| GET | `/api/v1/intersections/{id}/stats` | SourceProfile-scoped 历史统计；`period` 控制窗口，`granularity` 控制返回采样桶；响应含标量态势与 `direction_flow`，仅读最后一个保留点的 `tcc_diagnostics` |
| GET | `/api/v1/intersections/{id}/lane-stats` | 车道级历史统计；`period` 与 `granularity` 同样生效 |

历史统计查询不得为趋势图加载 `uav_traffic_metrics.payload` 全量审计 JSON。实现必须投影已类型化的
标量列、按 `granularity` 每桶保留最新观测，并仅为最后一个返回点补读一次 TCC 诊断。Console2
`/monitoring` 的趋势和转向流量只消费当前 `source_profile_id` 的响应；近期事件只展示具有同一
SourceProfile lineage 的严格路径交点冲突或实时告警，不混入无法证明来源的全局固定告警。

### 无人机管理 `/api/v1/drones`（当前 S9 实现）

以下端点由 `MissionOrchestrator` 统一访问 `road9` repository；运行时 `drone_store` 只叠加最新遥测和在线状态，不保存业务配置或 Mission 真源。完整写权限、revision、错误和调度语义见第 0.10 节。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | `/api/v1/drones` | 查询/创建持久化无人机档案并叠加最新遥测状态 |
| GET/PATCH | `/api/v1/drones/{id}` | 查询/按 revision 更新无人机档案 |
| GET/POST | `/api/v1/drones/{id}/sources` | 查询/创建脱敏 SourceProfile |
| GET | `/api/v1/sources` | 查询授权范围内全部 SourceProfile |
| GET | `/api/v1/sources/{profile_id}/results` | 汇总该来源关联的 Mission、态势/轨迹/冲突计数、测绘批次、关键帧、场景/车道标注、报告和 Console2 深链 |
| PATCH/POST | `/api/v1/drones/{id}/sources/{profile_id}` | 更新或校验成对数据源 |
| GET | `/api/v1/drones/{id}/trajectory` | 无人机飞行轨迹 |
| GET | `/api/v1/drones/{id}/hover-points` | 悬停点位列表 |
| GET | `/api/v1/telemetry/{id}` | 最新遥测数据 |
| GET | `/api/v1/telemetry/{id}/history` | 遥测历史 |
| GET/POST | `/api/v1/flight-plans` | 查询/创建 FlightPlan |
| GET/PATCH/DELETE | `/api/v1/flight-plans/{id}` | 查询/更新/删除允许删除的计划 |
| POST | `/api/v1/flight-plans/{id}/{enable|pause|retire}` | 计划状态动作 |
| GET | `/api/v1/flight-plans/{id}/occurrences` | 预览未来窗口 |
| GET/POST | `/api/v1/missions` | 查询执行记录/创建手动兼容 Mission |
| GET | `/api/v1/missions/{id}` | Mission 详情及 Pipeline 独立状态 |
| POST | `/api/v1/missions/{id}/{stop|retry}` | 停止或创建重试 Mission |

#### `POST /api/v1/missions`（持久化入口）

调用必须传已登记的 `source_profile_id` 和 `inter_id`，并创建持久化 `trigger_type=manual` Mission
快照。`road_data_version` 可选：缺失时允许启动检测器与 MJPEG，Mission/Pipeline 明确记录路网上下文
缺失；依赖 `lane_verified` 地图的 Lane ID、Link ID 与匹配质量不可用，世界坐标与其他分析不受影响。旧视频路径、遥测
路径和道路 JSON 字段属于禁止的额外字段，请求返回 422。Pipeline 启动失败时 Mission 进入
`failed` 并保存脱敏分类原因。

请求：
```json
{
  "name": "小清河早高峰巡检",
  "drone_id": "UAV-INTER-XQH",
  "source_profile_id": "SRC-INTER-XQH-0403-PM",
  "inter_id": "011wwe0z19700001",
  "road_data_version": "20260501-IMAGERY-FIT-V1"
}
```

响应使用第 0.10.4 节 Mission shape，并分别返回 `status`、`pipeline_id` 和 `pipeline_status`；canonical Topic 为 `uav_statistics_{camera_id}`。Platform 管理的动态检测器在每次 Platform 启动时以 epoch 秒初始化运行时 `camera_id`，随后进程内递增，避免恢复 Mission 复用旧 Topic 并排在历史积压之后。该值只用于运行时 Topic/视频实例寻址；物理来源身份必须使用 `source_profile_id`，业务运行身份必须使用 `mission_id` / `pipeline_id`。

### 轨迹复盘 `/api/v1/trajectories`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/trajectories/{intersection_id}` | 查询路口历史轨迹，支持 `period` / `limit`、任务、数据源、车型、方向以及空间投放筛选 |
| GET | `/api/v1/trajectories/{intersection_id}/conflicts` | 查询路口历史冲突事件，支持 `period` / `limit` 及可选 `source_profile_id`、`pipeline_id`、`prediction_type` 过滤，返回 TTC/PET、场景、证据、风险分和预测位置 |
| POST | `/api/v1/trajectories/{intersection_id}/conflicts/{event_id}/review` | 管理员按 `expected_revision` 技术确认/驳回；409 表示 revision 冲突，结果不等同警情处置 |
| GET | `/api/v1/trajectories/{intersection_id}/turn-summary` | 查询转向行为汇总 |

Console GIS 页调用 `GET /api/v1/trajectories/{intersection_id}?period=all&limit=500&spatial_ready=true&min_gcj02_points=6`。`spatial_ready=true` 要求 `trajectory_gcj02` 点数达到 `min_gcj02_points` 且 `anchor_gcj02` 非空；过滤在 PostgreSQL 的 `ORDER BY/LIMIT` 前执行。

Console Monitoring 在无运行 Pipeline 时调用
`GET /api/v1/trajectories/{intersection_id}?period=24h&limit=500&source_profile_id={profile_id}&spatial_ready=true&min_gcj02_points=2`
恢复当前视频源的 BEV 历史轨迹。该查询只用于离线回放窗口；运行中 Pipeline 仍以当前 WebSocket
会话的 active/completed 轨迹为准，避免历史轨迹混入实时检测状态。
同一页面还会调用 `GET /api/v1/trajectories/{intersection_id}/conflicts?period=1h&limit=200`，展示历史冲突 pair、TTC/PET、业务场景、证据和风险分。Monitoring 使用当前 `source_profile_id` 并固定 `prediction_type=path_intersection` 回填最近 24 小时事件；可在任务复盘时另加 `pipeline_id` 精确过滤。I3 当前实现查询 TimescaleDB hypertable `uav_conflict_events`，并从普通表 `uav_conflict_reviews` 合并复核状态；正式 `/gis`、`/events` 路由不再读取轨迹/事件 Mock。

`GET /api/v1/intersections/{intersection_id}/stats` 额外支持可选 `source_profile_id`。历史统计响应保留 `pipeline_id`、`source_profile_id` 和 `tcc_diagnostics`，Monitoring 必须按当前 SourceProfile 请求，避免同一路口不同视频源的漏斗状态串线。

### 告警中心 `/api/v1/alerts`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/alerts` | 告警列表，支持 `severity/status/limit/offset` |
| GET | `/api/v1/alerts/{id}` | 告警详情 |
| POST | `/api/v1/alerts/{id}/acknowledge` | 确认告警 |
| GET | `/api/v1/alerts/{id}/push-logs` | 告警推送记录 |

AlertEngine 创建告警和确认告警时写入 `road9` 中的 `uav_alerts`。Platform 启动时会加载已持久化告警，
因此告警列表、详情和确认状态可跨服务重启保留。PostgreSQL 不可用时，平台降级为内存告警，
实时 WebSocket 使用 `uav_alerts` / `uav_alerts:{intersection_id}`；数据库不可用时历史告警不可跨重启恢复。

### 系统监控 `/api/v1/system`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/system/health` | 健康检查（含 pipelines_active） |
| GET | `/api/v1/system/gpu` | GPU 实时指标 |
| GET | `/api/v1/system/gpu/history` | GPU 历史（I3 当前查询 `uav_system_metrics`） |
| GET | `/api/v1/system/kafka/topics` | Kafka topic 状态 |
| GET | `/api/v1/system/kafka/consumers` | Kafka consumer group 状态 |
| GET | `/api/v1/system/models` | YOLO 模型列表 |

### 标定中心（历史像素契约，已退役）

> 本小节仅保留清库前的审计背景。旧保存端点当前返回 `410`，旧 JSON、像素车道和
> `lane_annotation_db_path` 不再进入任何运行时。当前契约见本文件末尾“GCJ-02 渠化地图契约”。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/calibration/summary` | 标定参数摘要 |
| GET | `/api/v1/calibration/records` | 标定参数记录 |
| GET | `/api/v1/calibration/lane-tasks` | 车道标注任务列表 |
| POST | `/api/v1/calibration/lane-tasks/from-survey-frame` | 管理员从已持久化真实测绘关键帧幂等创建可恢复车道标注任务；帧必须绑定已登记 `source_profile_id` 并具有有效 pixel→ENU 变换，返回任务会持久化两者供页面重载恢复 |
| GET | `/api/v1/calibration/lane-tasks/{task_id}/image` | 管理员 Bearer 鉴权后返回车道标注任务 JPEG；Console2 以 Blob URL 注入画布，不公开直链 |
| GET | `/api/v1/calibration/lane-annotations` | 已保存车道标注参数列表 |
| GET | `/api/v1/calibration/lane-annotations/{intersection_id}` | 查询某路口可复用车道参数 |
| POST | `/api/v1/calibration/lane-tasks/{task_id}/annotation` | 保存人工车道标注结果 |

当前车道标注任务由 Kafka `uav_stats` 消息触发。同一路口 `is_hovering=true` 且 `drone_position.easting_m/northing_m` 在 `lane_annotation_hover_radius_m` 半径内持续超过 `lane_annotation_hover_seconds`（默认 30 秒），并且该路口没有已保存人工车道参数时，平台生成一个 `pending` 任务。悬停统计消息会携带压缩 JPEG 快照字段 `annotation_snapshot_jpeg` 以及 `annotation_snapshot_width/height`；平台收到后落盘为任务图片，并通过 `image_url` 返回给 console 车道标注画布。

保存请求：

```json
{
  "lanes": [
    {
      "lane_id": "L1",
      "name": "直行车道",
      "direction": "straight",
      "polygon": [0, 0, 10, 0, 10, 20, 0, 20]
    }
  ],
  "roads": {
    "1": [0, 0, 10, 0, 10, 20, 0, 20]
  }
}
```

保存后平台会写入 `lane_annotation_db_path`，并导出管道可直接读取的扩展 JSON：

```json
{
  "roads": {"1": [0, 0, 10, 0, 10, 20, 0, 20]},
  "lanes": {
    "L1": {
      "name": "直行车道",
      "direction": "straight",
      "polygon": [0, 0, 10, 0, 10, 20, 0, 20]
    }
  },
  "calibration": {"source": "manual_lane_annotation"}
}
```

以上导出格式是 2026-07-20 以前的历史标注审计快照，已由一次性 GCJ-02 重建清除，不再进入
视频源启动参数，也不存在活动失效脚本或兼容入口。当前标注只使用版本化渠化地图契约。

### 就绪检查 `/ready`

> 当前响应只包含 canonical 依赖，详见第 7 节健康检查约束。

```json
{
  "status": "ready",
  "services": {
    "database": "healthy",
    "kafka": "healthy",
    "timescaledb": "healthy",
    "pipeline_manager": "healthy"
  },
  "pipelines_active": 2
}
```

## 9. WebSocket 旧消息类型（历史快照，运行时已拒绝）

> 本章所有无 `uav_` 前缀的 channel 和 `type` 仅保存历史快照；当前代码不识别、不迁移并直接拒绝。当前契约见第 0.5 节。

### `stats` 消息
通过 `intersection:{id}` 频道推送，与 Kafka statistics topic 格式一致（含 direction_flow, drone_position, lane_stats）。

### `track_complete` 消息
通过 `intersection:{id}` 频道推送，与 Kafka track_complete topic 格式一致（含 trajectory_px, trajectory_world_m, turn_behavior）。

### `conflict` 消息
通过 `intersection:{id}` 频道推送，与 Kafka conflicts topic 格式一致。
- Monitoring 页面按当前 SourceProfile 回填最近 20 个历史路径交点事件，并与 WebSocket 实时冲突按事件 ID 去重；刷新、晚进入页面或实时链路暂时断开时仍可恢复事实。页面只把 `prediction_type=path_intersection && distance_m≈0.0` 作为业务冲突回放；旧格式仅在 `distance_m` 近似 `0.0` 时兼容，`same_time_cpa`、旧 CPA 非零距离消息或畸形 path 非零距离消息会被过滤。WebSocket 非 connected 状态明确标为历史/REST 降级展示，不能继续声称“实时”。
- severity="critical" → AlertEngine 创建 P1 告警
- severity="warning" → AlertEngine 创建 P2 告警

### `telemetry` 消息
通过 `telemetry:{drone_id}` 频道推送：
```json
{
  "channel": "telemetry:drone_001",
  "type": "telemetry",
  "data": {
    "drone_id": "drone_001",
    "lat": 36.702909,
    "lon": 117.022330,
    "alt_agl": 130.0,
    "gimbal_pitch": -90.0,
    "gimbal_yaw": 0.8,
    "horizontal_speed": 0.0,
    "is_hovering": true,
    "timestamp": 1234567890.123
  },
  "ts": 1234567890.456
}
```

历史 Drones 页面曾根据 `/api/v1/drones` 返回的无人机 ID 订阅
`telemetry:{drone_id}`；当前页面只订阅第 0.5 节的 `uav_telemetry:{drone_id}`。收到 WebSocket 消息后立即覆盖轮询得到的最新遥测值；
`GET /api/v1/telemetry/{id}` 仍保留为首屏加载和断线兜底。

### `alert_new` 消息
通过 `alerts` 频道推送（AlertEngine 触发）：
```json
{
  "channel": "alerts",
  "type": "alert_new",
  "data": {
    "id": "alert-xxx",
    "intersection_id": "INT_camera_1",
    "alert_type": "conflict",
    "severity": "P1",
    "title": "机非冲突 (TTC=1.5s)",
    "status": "open",
    "created_at": "2026-05-30T21:00:00Z"
  },
  "ts": 1234567890.789
}
```

## 2026-07-16 真实事件与轨迹查询补充

- `GET /api/v1/events`：统一返回 `congestion`、`quality_degradation`、`survey_result` 和 `conflict`，保留 `mission_id` / `pipeline_id` / `source_profile_id` / `inter_id` / `road_data_version` / `quality_status` 与 `evidence_refs`。
- `GET /api/v1/events/{event_id}`：返回规则指标、关联轨迹和内容寻址证据；`PUT /api/v1/events/{event_id}/review` 使用 `expected_revision` 实现技术复核乐观锁。
- `GET /api/v1/trajectories/{intersection_id}` 默认返回包括像素降级在内的全部完成轨迹，支持 `period=all|1h|24h`、`mission_id`、`source_profile_id`、车型和方向筛选。地图投放可显式使用 `spatial_ready=true&min_gcj02_points=N`，先在 PostgreSQL 过滤至少 N 个非空 GCJ-02 点再应用 `limit`。
- 持续拥堵证据在第 30 个连续超阈值样本定格；页面不得以打开详情时的当前画面替换历史证据。

## 2026-07-21 轨迹研判分析契约

`uav_track_complete/v1` 的 `data` 在既有业务车型 `vehicle_class` 之外，新增以下可追溯字段：

| 字段 | 语义 | 历史规则 |
| --- | --- | --- |
| `yolo_class_id` | 推理时模型输出的原始类别 ID | 仅复制 payload 中已经存在的可信值 |
| `yolo_class_name` | 推理时 `model.names[class_id]` 的原始名称 | 不得用当前模型字典猜填旧记录 |
| `yolo_model_id` | `权重文件名@SHA-256前12位` | 无来源证据时为空 |
| `class_mapping_version` | YOLO 类别到业务车型的映射版本 | 无来源证据时为空 |
| `start_road_id` / `exit_road_id` | 入口/出口道路上下文 | 只回填 payload 中可信道路字段 |

`GET /api/v1/trajectories/{intersection_id}/analysis` 是 `/gis` 的一致性分析读模型。它支持
`period=latest30m|all|1h|24h`，或显式 `start_at + end_at`；`latest30m` 锚定所选筛选条件下
最新一条可回放轨迹，而不是当前墙钟或最新降级记录。可叠加 `slice_start_at + slice_end_at`、
`source_profile_id`、`mission_id`、`vehicle_class`、`yolo_class_id`、`turn_behavior`、
`quality_status`、`movement_key`、`bucket_sec` 与 `track_limit`。显式起止时间必须成对提供；
`track_limit` 有服务端硬上限，时间桶总数最多 720。

响应同时返回 `quality`、`timeline`、`movement_ranking`、`class_summary.business`、
`class_summary.yolo`、`slice_tracks` 和 `conflicts`。`movement_source` 在测试质量辅助视图中可以是：

- `road_context`：具有入口/出口或入口/转向道路上下文；
- `trajectory_quadrant_inferred`：缺少路网匹配时的测试候选，不进入正式统计；
- `turn_behavior_fallback`：测试候选，不进入正式统计；
- `unmapped`：没有足够证据形成流向。

排名优先完整路网流向，其次是明确标注的轨迹方位推断，再到道路/转向降级；未知组不会因为
数量大而覆盖更可解释的流向。轨迹去重与冲突归因使用可用的
`source_profile_id + mission_id + pipeline_id + track_id`；缺字段时只在剩余 lineage 仍可安全唯一时
关联，禁止只按会复用的 `track_id`。业务车型、YOLO、转向和质量筛选必须应用于 lineage 去重后的
canonical 完成事实，不能先过滤旧版本记录再去重，否则分类统计与筛选 KPI 会不一致。地图只返回
当前时间片内可回放的 `trajectory_gcj02` 片段，每条最多
60 个抽样点，优先保留首末点、转折点和冲突附近点，并返回 `trajectory_sampled` 与
`trajectory_original_point_count`；不可回放轨迹仍计入总量，并通过
`slice_non_replayable_omitted` 和 `spatial_coverage_ratio` 显式降质。
`trajectory_gcj02` 与 `trajectory_enu_m` 必须按同一组时间片索引和抽样索引返回，禁止一边返回
当前片段、另一边返回整条完成轨迹。Console2 自动回放可预取下一非空时间片，但等待期间必须保留
当前已确认片段，不得把请求中状态显示为 0 条轨迹。

## 2026-07-21 GCJ-02 渠化地图契约

### 路口项目与统一视频接入（2026-07-22）

以下接口全部要求 `admin`，当前不扩展角色枚举或制图/复核人员隔离：

| 方法 | 路径 | 契约 |
|---|---|---|
| GET/POST | `/calibration/intersection-projects` | 查询或创建稳定项目；正式 `inter_id` 可在发现阶段为空 |
| GET/PATCH | `/calibration/intersection-projects/{project_id}` | 查询或按 `revision` 修改项目 |
| GET | `/calibration/intersection-projects/{project_id}/workspace` | 汇总 RoadContext、分段素材绑定、地图版本和唯一下一步动作 |
| POST | `/calibration/video-ingestions` | `project_id` 为空表示视频优先；传入表示路口优先并作为期望归属校验 |
| GET | `/calibration/video-ingestions/{job_id}` | 返回 WGS84 原始中心、GCJ-02 匹配中心、悬停时间段、候选距离与状态 |
| POST | `/calibration/video-ingestions/{job_id}/resolve` | `bind_expected_project`、`bind_existing_project` 或 `create_project`；绑定写入独立时间范围和质量 |
| POST | `/calibration/channelized-maps/{id}/submit-check` | 保存一次提交检查审计 |
| POST | `/calibration/channelized-maps/{id}/check` | `admin` 记录通过/退回、问题和检查表；`approved` 必须显式通过影像地图对照、版本差异、配准误差、拓扑、车道方向和停止线六项门禁且无开放问题，发布前最近结果必须为 `approved` |

悬停发现按 1Hz 重采样，使用不少于 15 秒、云台俯角不高于 `-80°`、位置半径 P95 不超过 5m、派生速度 P95 不超过 1m/s 的稳定段。DJI 原始经纬度以 WGS84 留存，候选距离只用固定版本转换后的 GCJ-02 计算。本地 RoadContext 候选优先；最近候选不超过 80m 且与第二候选差不少于 80m 才可标记 `auto_high_confidence`。无遥测绑定为 `manual_unverified`。

唯一公共地理坐标系为 `GCJ02`，公共字段限定为 `position_gcj02`、`geometry_gcj02`、
`trajectory_gcj02`、`anchor_gcj02` 和 `coordinate_system: "GCJ02"`。米制计算字段为
`geometry_enu_m`、`trajectory_enu_m`；GeoJSON 和 bbox 均按 `[longitude, latitude]`。

| 方法 | 路径 | 约束 |
| --- | --- | --- |
| POST | `/calibration/channelized-maps/bootstrap/{inter_id}` | 管理员操作；本地存在则不访问 YCX，本地不存在才只读导入该路口 |
| POST | `/calibration/road-context/import-ycx` | YCX 只读事务；WKT 通过 PostGIS `ST_GeomFromText(...,4326)` 读取；ID 按不透明 geomhash 字符串处理 |
| POST | `/calibration/channelized-maps` | 管理员从外部完整几何创建新的 `draft`；不得用于浏览器自行复制已发布版本 |
| POST | `/calibration/channelized-maps/{map_version_id}/derive-draft` | 服务端从非 retired 版本派生新 `draft`，复制 Lane/Link/Feature 与绑定并在 topology/quality 写入 `derived_from_map_version_id`；源版本保持不可变，复核状态归零 |
| POST | `/calibration/lane-keyframe-extractions` | 管理员为当前路口选择已启用、`valid`、本地 SourceProfile；请求必须逐项确认五项测绘预检。服务端在同一事务内创建 `source=lane_calibration` 测绘任务、完成预检并将原视频/遥测不可变引用入抽帧队列；支持 `Idempotency-Key` |
| POST | `/calibration/lane-tasks/from-survey-frame` | 从已持久化且具备 SourceProfile、pixel→ENU 变换的真实关键帧幂等创建可恢复标注任务 |
| GET/PUT | `/calibration/channelized-maps/{map_version_id}` | 读取或编辑 `draft/candidate`；已发布版本不可变 |
| POST | `/calibration/channelized-maps/{map_version_id}/fit-from-image` | 必填已登记 `source_profile_id`；服务端执行 `pixel → ENU → GCJ02`，按地图+来源幂等保存拟合车道、渠化要素和视觉配准 |
| POST | `/calibration/visual-registrations/{id}/verify` | 人工确认配准；媒体路径必须位于显式 allowlist 根目录 |
| POST | `/calibration/channelized-maps/{map_version_id}/publish` | 执行残差、拓扑、自交、重叠、方向、停止线和人工复核门禁 |
| GET | `/calibration/channelized-maps/{map_version_id}/runtime-bundle` | 仅 `lane_verified` 可读，供 Mission 固定注入 |

`lane_info` 仅以 `geometry_source=link_offset_derived` 导入为候选。正式发布至少需要一个
`imagery_fitted` 或 `manual_override` 车道、已验证视觉配准和真实停止线。拟合数量不一致时使用
本地稳定 `local_lane_id`，`source_lane_id` 可空，不得拼造 YCX ID。

Console2 的正拍编辑器可先调用 `POST /calibration/lane-keyframe-extractions`，把当前路口已登记的
本地视频与遥测交给既有 `SurveyWorker` 异步抽帧；页面轮询批次的 `queued/processing` 状态，待真实
关键帧落库后，再按 `inter_id` 读取任务、采集批次和关键帧并调用
`POST /calibration/lane-tasks/from-survey-frame`。页面不得用空白任务或浏览器端近似公式代替真实帧；
任务返回的 `source_profile_id` 与 `homography_pixel_to_enu` 是后续拟合的默认输入。画布使用
`contain` 后的真实影像视口反算自然像素坐标，点击黑边不产生顶点。当前地图的 ENU 车道面可
在浏览器端用该矩阵的逆变换叠加到关键帧，点击后复制为拟合草稿；顶点拖拽和整车道平移只更新
自然像素坐标且不越出图像边界。参考车道跨出关键帧时，页面必须先把多边形裁剪到自然影像矩形，
再允许复制和整体拖动，避免首次拖动因边界纠正产生跳位。该逆变换仅服务交互预览，正式持久化仍必须调用
`fit-from-image` 由服务端执行 `pixel → ENU → GCJ02`。地图状态不在 `draft/candidate` 时页面必须
先调用 `POST /calibration/channelized-maps` 新建草稿，不能向不可变版本提交拟合。
`lane-tasks/from-survey-frame` 返回的单应矩阵必须标记
`homography_coordinate_frame=map_enu`，并携带 `map_version_id`、`map_anchor_gcj02`。服务端以
帧 GPS 的 WGS-84→GCJ-02→地图 ENU 位移对源影像单应矩阵做平移；不得把源图坐标误套
`BEV view_transform⁻¹`。旧任务或地图锚点不一致时 `fit-from-image` 返回 422，要求从真实关键帧
刷新任务。

完成轨迹必须携带非空且同索引的 `trajectory_px/trajectory_timestamps_sec/trajectory_frame_nums`；
`trajectory_enu_m/trajectory_gcj02` 必须等长并允许逐点为 `null`。`map_version_id`、
`matched_lane_key`、`source_lane_id`、`matched_link_id`、`movement_key` 与匹配置信度全部可空。
视觉配准残差中的 `registration_position_gcj02: [longitude, latitude]` 与
`registration_gimbal_yaw_deg` 只用于车道地图制作、复核及 Lane/Link 几何谱系，不进入车辆世界
投影。运行时只要固定的 `lane_verified` Bundle 可用即可产生正式车道级字段；视频/SRT世界事实及
TCC不要求该 Bundle，也不要求任何独立来源配准。

`GET /trajectories/{intersection_id}` 对每条记录显式返回 `coordinate_system: "GCJ02"`；
`anchor_gcj02/trajectory_enu_m/trajectory_gcj02/map_version_id` 和车道匹配字段以事实表类型化列
覆盖原始 payload，浏览器不得从旧字段或运行时默认值猜测坐标系。

外部原生 MPS 重跑在每源自然 EOF 后形成一个 completed Mission。Mission `context_snapshot`
使用 `uav.replay-batch-provenance/v1`，固定 `replay_batch_id/pipeline_id/source_profile_id`、视频与
遥测 SHA-256、模型 SHA-256、`map_version_id/road_data_version/coordinate_transform_version`、
抽帧参数和验收产物路径。事实表以类型化 `mission_id + pipeline_id + source_profile_id` 追溯该
快照；原始 Kafka `payload` 保持逐字保存，不在最终关联时回写或伪造 Mission 字段。

## 2026-07-23 巡航跟踪增量契约

canonical Topic、`msg_type`、WebSocket channel 和 `*/v1` schema 版本保持不变；以下均为可选向后兼容字段，不增加旧 Topic 或双投：

- `uav_stats.data`：`flight_phase`、`flight_segment_id`、`geo_reference_quality`、`tracking_diagnostics`、四层能力 `trajectory_output_eligible/geo_analytics_eligible/road_analytics_eligible/tcc_analytics_eligible`、兼容聚合 `formal_analytics_eligible`、活动/候选轨迹及采集质量字段。
- `tracking_diagnostics.mahalanobis_gate` 为只读工程诊断，包含 `mahalanobis_gate_mode=shadow`、`eligible_pair_count`、`would_reject_eligible_pair_count` 和 `would_strand_track_count`；它不得改变图像 ID，也不是 IDF1/HOTA 或正式 ID switch 指标。
- `candidate_trajectories` 仅表示尚未满足图像轨迹最短时长和点数的关联；成熟轨迹无论地图是否存在都进入 `active_trajectories`。候选不得计入完成数、速度、车道、流量或 TCC。
- `tracking_diagnostics.lifecycle` 可选且向后兼容，包含 `active_track_count/mature_track_count/candidate_track_count/completed_track_count/termination_reason/same_id_mature_to_candidate_count`；同一 ID 成熟后回到候选属于契约违例，正常计数必须为 0。
- `uav_track_complete` 必须携带非空 `termination_reason`，每个 `pipeline_id + track_id` 只允许一个逻辑完成事实；Producer 对该组合生成确定性 `message_id`，重试由 `uav_message_inbox` 和事实唯一约束幂等拦截，不增加 schema major 或数据库迁移。
- `trajectory_px` 固定表示逐源帧车辆地面接触点，并与 ENU/GCJ-02/时间/帧号/质量谱系同索引；旧 bbox 中心仅以可选 `trajectory_bbox_center_px` 输出。active 与 completed 使用同一语义。
- `trajectory_enu_m/trajectory_gcj02` 由 ByteTrack 后的逐帧世界投影唯一生成，下游不得使用当前 H 或当前 GCJ-02 锚点重算历史。内部 ENU 在速度回归前保留浮点全精度，序列化层可按契约格式化。投影暂缺时两个世界序列按同索引保留 `null`，后续恢复点仍可产生有效坐标；消费方必须结合逐点质量谱系判断，不得压缩掉 `null` 破坏对齐。
- 背景视觉 `camera_motion_warp` 递推得到的 `trajectory_display_px` 是检测进程内的当前帧渲染缓存，`KafkaProducerNode` 必须在发布 `candidate_trajectories` 前剔除；不得从该字段持久化或重建世界事实，也不得用当前帧 H 替代它。
- `association_id` 是地理参考之前分配的图像身份；ByteTrack 确认后立即映射稳定业务 `track_id`。地理质量、地图覆盖和路网匹配变化不创建新 ID。
- `tracking_method` 当前值为 `motion_compensated_image_v2`。`uav_track_complete.data` 增加四层能力、分层质量、降级原因、`road_context_status`和可空地图字段；Topic、`msg_type`、channel与v1版本不变。历史`geo_registration_id`数据库列保留但新消息不再写入。
- `uav_conflict.data`：`flight_phase` 与双方 `tracking_quality` 摘要。冲突只接受已成熟图像关联的可信世界轨迹与源时间；envelope 的 `quality_status` 取双方轨迹、地理参考和时间质量的最差值，不读取地图、Lane 或 Link。
- 所有 envelope 的 `quality_status` 按当前帧/轨迹动态计算，不再只复制 Mission 启动时值。
- 实时源带设备 `recorded_at` 时使用 `source_time_semantics=event_time/time_quality=verified`；离线回放时间锚点使用 `reconstructed`；缺少事件时间为 `ingest_only`。冲突遇到 `ingest_only/quarantined` 必须标记 `quality_status=unverified`，经批准的 `reconstructed` 回放仍可参与离线正式分析。

`uav.cruise-eval/v1` 仅是可选的外部真值只读输入，不属于运行时契约，也不构成人工标注工作包。项目不生成、预标注、分派或审核其中的真值；只有未来外部项目主动提供已批准数据时才运行该评测器。顶层必须包含 `mission_manifest`、`ground_truth_provenance` 和 `frames`：

- 每个 Mission 固定 `mission_id/intersection_id/source_profile_id/map_version_id/runtime_bundle_sha256/model_id/config_sha256`、三阶段、场景标签、拍摄 profile，以及带相对路径和 SHA-256 的 MP4/遥测资产。
- 身份真值要求人工来源、独立复核和 `reference_id`；位置与速度真值要求批准来源、`reference_id` 和 `calibration_valid=true`。模型预测或当前帧 H 重投影不能作为真值。
- 每帧固定 `mission_id/intersection_id/timestamp_sec/agl_m/uav_ground_speed_mps`，并携带 ground truth/predictions；帧 lineage 必须命中 manifest。
- `scripts/evaluate_cruise_tracking.py --audit-only` 返回 `uav.cruise-acceptance-audit/v1`，状态为 `production_evidence_ready|production_evidence_blocked` 和稳定的命名失败项；完整评测返回 IDF1/HOTA/ID switch/位置/速度/车道/泄漏门禁。没有外部批准真值时不运行完整评测，工程报告把这些指标记为 `not_evaluated`。

新增/扩展 REST：

- `GET /api/v1/calibration/source-profiles/{source_profile_id}/flight-segments`：按 SourceProfile 查询持久化飞行分段。
- `GET /api/v1/sources/{profile_id}/results`：新增 `flight_segments[]`。
- Mission/Pipeline 列表和详情返回 `tracking_profile`、`tracking_profile_selection_reason`、`flight_phase`、`tracking_quality`、兼容字段 `formal_analytics_eligible`、`runtime_quality`，并显式返回四层 `capabilities={trajectory,geo,road,tcc}` 与各层 `capability_reasons`。首个 Stats 到达前四层值为 `null/runtime_sample_pending`，不得根据地图或总质量猜测；到达后按当前帧四个独立布尔值更新。
- FlightPlan/Mission create可选`tracking_profile=hover_cruise_v1|hover_only_legacy`。显式值优先；
  未显式指定时固定选择`hover_cruise_v1`。最终值和选择原因固化到Mission snapshot，恢复时不重选。
- `POST /api/v1/missions` 与 `POST /api/v1/pipelines` 接受 `frame_stride: 1..30`，默认 `3`；语义固定为“每 N 个源帧处理 1 帧”。Mission 将实际值固化到 `context_snapshot.frame_stride`，Pipeline 列表/详情以 `frame_stride` 回显，Platform 再通过 `FRAME_STRIDE` 注入检测子进程。`POST /api/v1/pipelines/register` 可选上报外部进程的实际值；未上报时返回 `null`，不得猜测。
- `uav_stats.data.inference_context` 包含 `metric_scope=yolo_predict_single_processed_frame`、device、
  precision、model、`effective_imgsz`、`agl_tier`、`frame_stride`；`inference_ms` 仅是 YOLO 单处理帧，
  `pipeline_processing_ms` 是 FrameElement 创建至 Kafka 节点的整帧管道耗时，两者不得混用。
- `uav_stats.data.recognition_diagnostics` 是可选向后兼容的工程诊断，包含
  `truth_status/truth_reason`、`valid_yolo_detection_count/yolo_class_counts`、
  `emitted_image_track_count/emitted_track_class_counts`、`unassociated_detection_count`、
  `same_frame_track_to_detection_ratio`、`invalid_detector_geometry_count`，以及源画面面积阈值
  `small_target_max_area_px2=4096` 下的小目标检测/轨迹分类计数和同帧转化率。它不得被解释为
  precision、recall、IDF1/HOTA 或正式 ID switch；无外部批准真值时这些指标保持 `not_evaluated`。
- `uav_stats.data.tcc_diagnostics` 除输入、候选、预测、证据和事件数外，包含速度缺失/过低、历史
  或位移不足、距离过滤、预测/场景/证据/严重度过滤及去重计数；`quality_gate_blocked` 与合法无事件
  是不同状态。
- 为保持 Kafka 默认 1MB 请求边界，Stats 的 `active_trajectories + candidate_trajectories` 合计最多
  200 条并优先最新成熟轨迹；`active_tracks/eligible_active_tracks` 仍是完整计数，新增
  `active_trajectories_truncated/candidate_trajectories_truncated` 明确被省略数量。完整轨迹不截断，
  继续通过 `uav_track_complete_*` 发布。
- visual registration 可为地图制作保留版本化 `registration_pose`、`camera_calibration`、`map_coverage_enu_m`；Runtime Road Map Bundle 不携带这些来源姿态、编辑器元数据或世界投影矩阵，只携带生成后的 Lane/Link/Feature 地图事实。

`registration_pose` 固定为 `uav.channelized-editor/registration-pose/v1`：`fixed_surface=source_image`、`center_px[2]`、`translation_px[2]`、`rotation_deg`、`uniform_scale`。地图制作时的 AGL、云台 yaw/pitch/roll、zoom、GCJ-02 位置及遥测矩阵属于 `camera_calibration` 或任务原始变换谱系，不得混入操作员姿态。它们只证明地图制作谱系，不能作为运行时世界真源或 tracking profile 选择条件。

`POST /api/v1/calibration/channelized-maps/{id}/fit-from-image` 保持旧矩阵-only请求兼容；携带 `registration_pose` 时，服务端必须使用标注任务原始矩阵按 `H_task × inverse(T_pose)` 重算，并以归一化容差拒绝不一致的 `homography_pixel_to_enu`。可选 `editor_model` 使用 `uav.channelized-editor/model/v1`，保存到 `ChannelizedMapVersion.topology.editor_model`；`mode=parameterized` 至少包含一个进口骨架，`mode=freeform` 可用空骨架保存曲线控制点、人工要素及完整像素几何。正式 Feature 类型包括 `crosswalk`、`channelizing_island`、`waiting_zone`、`stop_line`、`lane_boundary`、`lane_marking`。Runtime API 必须剔除 `editor_model`。

影像拟合继续拒绝单车道自交和同一 Link 内车道面重叠；不同 Link 的合法转向流可在路口内部交叉。该 Link 域规则避免把十字路口的穿越关系误判成几何重叠错误。

Mission 启动使用的 `RoadContext.runtime_map_bundle` 与校准 runtime-bundle API 必须返回完全相同的 Lane/Link 地图字段；漏传或版本不一致只关闭 road 能力。衍生的 imagery-fit 地图若自身 `source_checksum` 为空，只允许沿 `quality.source_map_version_id` 追溯其父地图的不可变 checksum；不得按版本名猜测或回退到任意最新 snapshot。

## Replay V2 shadow 契约（2026-08-04）

V2 开发隔离 Topic 为：

- `uav_replay_v2_statistics_{source_key}` / `uav_stats`
- `uav_replay_v2_track_complete_{source_key}` / `uav_track_complete`
- `uav_replay_v2_conflicts_{source_key}` / `uav_conflict`
- `uav_replay_v2_telemetry_{source_key}` / `uav_telemetry`
- `uav_replay_v2_mission_{source_key}` / `uav_replay_mission`

消费者组固定 `uav-platform-replay-v2`，订阅表达式固定为
`^uav_replay_v2_(statistics|track_complete|conflicts|telemetry|mission)_.+$`。旧 canonical 正则不得匹配这些 Topic。Stats 禁止携带完整 active/candidate 尾迹；最终 journey 只在 Mission sealed 后发布。

`GET /api/v1/trajectories/{intersection_id}/replay-missions` 默认返回 sealed Mission，结构版本
`uav.replay-missions/v1`；`include_incomplete=true` 仅管理员可用于诊断，普通用户请求返回 403。摘要包含 SourceProfile、Pipeline/Run、开始时间、T+时长、坐标覆盖率、journey/行为数量、算法版本和统一 `not_evaluated` 准确率字段。

`GET /api/v1/trajectories/{intersection_id}/replay` 必须提供 `mission_id`，可选
`cursor_sec/window_sec/max_points/page_after/track_id/behavior/vehicle_class/yolo_class_id/turn_behavior/movement_key`。`page_after` 是服务端签发的 opaque 锚点；响应 `pagination.next_page_after` 以稳定 `(track_id, point_seq)` 顺序继续，页间不得重复点。响应版本为 `uav.trajectory-replay/v1`，返回连续 Mission T+ cursor、像素与可空 ENU/GCJ-02、冻结速度、质量、sampling boundary、episodes、maneuvers 和 Runtime segment 引用。接口不插值，不跨明确 quality gap 连线；已经离开时间窗的 journey 不得用最后一点持续钉到 Mission 结束；非 sealed Mission 返回 404。

`analysis.movement_ranking` 与返回的每条 track 必须包含一致的
`movement_key/movement_label/movement_source`。sealed event 缺少正式 `movement_key` 时，服务端从
完整 journey 的 ENU 首尾象限及冻结转向恢复 `approach:{cardinal}|exit:{cardinal}`，标签使用
“东进口 → 西出口”格式且 `movement_source=trajectory_quadrant_inferred`；无法确定进口时才返回
`turn:{turn_behavior}` 与“直行（进口未知）”。`movement_key` 过滤必须使用同一有效流向，不能只与
数据库中的可空原始字段比较。

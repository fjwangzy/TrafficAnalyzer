# API_CONTRACTS.md — TrafficAnalyzer API 契约

> 本文分为“目标契约”和“当前实现/遗留契约”两层。目标契约是后续开发与验收基线，但尚未完成代码与数据迁移；带有旧 Topic、旧 `msg_type`、InfluxDB 或 Grafana 的章节仅用于描述当前代码和迁移兼容，不能作为新接口继续扩展。

## 0. 目标消息与持久化契约（已决策，待实现）

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

当前代码尚未完成上述迁移。`road9` 连接、TimescaleDB 扩展可用性/版本/权限、目标 schema、迁移窗口、历史数据回迁和路网字段仍需确认。

### 0.2 canonical Topic 与 `msg_type`

| Topic | canonical `msg_type` | 说明 |
| --- | --- | --- |
| `uav_statistics_{camera_id}` | `uav_stats` | 路口/道路/车道实时统计 |
| `uav_track_complete_{camera_id}` | `uav_track_complete` | 完成轨迹 |
| `uav_conflicts_{camera_id}` | `uav_conflict` | 换道/机非冲突事件 |
| `uav_telemetry_{camera_id}` | `uav_telemetry` | 无人机遥测 |
| `uav_system_metrics` | `uav_system_metrics` | GPU、CPU、管道和消息链路指标 |
| `uav_ai_events` | `uav_ai_event` | 向智慧交通主平台交付的 AI 事件 |
| `uav_ai_event_feedback` | `uav_ai_event_feedback` | 主平台审核/结果反馈 |

Topic 的单复数按上表固定。`msg_type` 必须与 Topic 映射一致；业务字段 `event_type` 使用 `conflict/congestion/survey_result/enforcement_clue` 等领域枚举，不因消息前缀规则改写。事故测绘跨系统结果的唯一 canonical 枚举为 `survey_result`。

目标订阅正则：

```text
^(uav_statistics_|uav_track_complete_|uav_conflicts_|uav_telemetry_).+$|^uav_(system_metrics|ai_events|ai_event_feedback)$
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
| `message_id` | 是 | UUID；生产端首次生成，重试/双投不变 |
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

`uav_message_inbox` 至少保存 `payload_hash/status/topic/partition/offset/first_seen_at/processed_at/fact_refs`。相同 ID、相同 hash 的重放返回既有处理结果且不重复写事实；相同 ID、不同 hash 视为消息身份冲突，必须隔离并告警，不能覆盖原事实。hypertable 中包含时间分区列的唯一键只是第二层防重，不能替代 inbox 的跨时间全局唯一性。inbox 保留期不得短于 Kafka 最大重放、历史回迁和审计窗口，具体期限待容量/审计评审冻结。

### 0.4 各消息 `data` 边界

- `uav_stats`：保留车辆数、活跃轨迹、速度、排队、方向流量、动态 `roads[]`、`lane_stats[]`、路网和质量字段。旧 `road_1`～`road_N` 仅由迁移适配器读取，不进入 canonical 主结构。
- `uav_track_complete`：保留轨迹 ID、车辆类别、转向、起止时间、速度、ENU/像素轨迹、入口/出口 Link/车道、地图匹配与质量字段。
- `uav_conflict`：保留双方轨迹 ID、TTC/PET、最小距离、冲突角、场景、风险分、证据和预测位置；当前 near-miss 判定口径不因消息改名而变化。
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

WebSocket 推送可沿用 `{channel, type, data, ts}` 外壳，但 `type` 和 UAV 平台 channel 必须使用上述 `uav_` canonical 名称。同一告警可同时投放全局与路口级频道，必须复用同一告警 ID，前端按 ID 去重，不能形成两个业务告警。迁移期旧 channel 只能由适配层并行发布，并设置明确下线日期。

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

### 0.7 新旧兼容与切换规则

| 旧 Topic / `msg_type` | canonical Topic / `msg_type` | 兼容规则 |
| --- | --- | --- |
| `statistics_{n}` / `stats` | `uav_statistics_{camera_id}` / `uav_stats` | 适配旧平铺 payload 为统一信封 |
| `track_complete_{n}` / `track_complete` | `uav_track_complete_{camera_id}` / `uav_track_complete` | 保留完整轨迹字段 |
| `conflicts_{n}` / `conflict` | `uav_conflicts_{camera_id}` / `uav_conflict` | 不改变冲突业务判定口径 |
| `telemetry_{n}` / `telemetry` | `uav_telemetry_{camera_id}` / `uav_telemetry` | 补充消息 ID 和业务时间 |
| `system_metrics` / `system_metrics` | `uav_system_metrics` / `uav_system_metrics` | 统一指标 envelope |

当前代码/环境若仍存在 `detections_*`、`vlm_analysis` 或场景专用的 `lane_change/risk_events/survey/enforcement` Topic，只能作为迁移输入：有交付价值的事件规范化到 `uav_ai_events`，纯调试/中间推理消息退出生产订阅。是否保留原始检测/VLM 调试流及其保留期属于 `【待确认】`，但任何保留后的名称也必须以 `uav_` 开头。

事故测绘遗留事件类型 `accident_survey` 只允许迁移适配器读取，并必须在进入 canonical schema 前转换为 `survey_result`，同时在兼容审计字段中保留原始值。目标生产者、`uav_ai_event/v1` schema 校验、数据库约束和主平台接口必须拒绝 `event_type=accident_survey`；不得把二者作为两个可并存枚举。

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

迁移原则：

1. 消费端先兼容新旧消息并统一写入 `road9` 的 `uav_*` 表；旧消息按 Topic partition/offset 生成稳定 `message_id`，新旧消息均进入长期 `uav_message_inbox`。
2. 生产端再切换 canonical Topic/`msg_type`；若短期双投，必须复用 `message_id` 并在数据库侧去重。
3. PostgreSQL/TimescaleDB 与旧 InfluxDB 完成数量、时间桶和事件抽样对账后，历史 API 才能切换权威源。
4. 观察期结束后停止 Telegraf/InfluxDB 新写入，并移除 Grafana、Telegraf、InfluxDB 部署；历史数据回迁或归档范围仍待确认。
5. 旧 Topic、旧 WebSocket channel、旧无前缀表的下线窗口须与全部生产者、消费者和智慧交通主平台联调方共同冻结。

切换门禁：Topic builder 路由单测通过；事件在断网、队列满、进程崩溃/重启场景无静默丢失；指标 coverage/drop 可核算；数据库失败时 offset 未提交且重放成功；提交数据库后崩溃的重放未重复写事实；Telegraf/Platform 双写已去重/择源且未相加。任一门禁未通过不得关闭旧链路或宣称迁移完成。

### 0.8 路网引用边界

- `road9` 是 PostgreSQL connection database 的目标值，不等同于已确认的 schema 名。
- UAV 表只保存 `road_data_version + inter_id/link_id/lane_id` 等版本化引用和视觉绑定，不修改既有路网主数据。
- 无法匹配时权威 ID 置空并标记 `map_match_method=unmapped`；不得用 `road_N` 或本地 lane 数组下标伪造。
- 管道启动读取已发布路网快照并缓存，不得逐帧查询共享路网表。
- 此前 `ycx`/`road10` 调查只作为历史证据，`road10` 不再是目标连接或权威源选择。

### 0.9 全域态势工作台读契约（S8 I5-A 与内部查询契约已实现）

首屏 Dashboard 以交通指挥中心主任为第一用户。`DashboardReadModel` 已实现下列 4 个只读接口，只聚合现有 RoadContext、任务/设备、时序指标、AI 事件、测绘、投递和系统健康事实，不新增第二套事件或处置真源。当前内部 schema 为 `uav.dashboard/v1`；正式 SLA、缓存、全局增量和回补仍由 S8-TBD-006 冻结：

| 方法与候选路径 | 用途 | 最小返回边界 |
| --- | --- | --- |
| `GET /api/v1/dashboard/overview` | 主任核心指标、重点关注榜、权限化待办摘要和整体健康 | 已返回 `project_scope/road_data_versions/as_of/window_start/window_end/data_quality/coverage_ratio/schema_version`、指标分子分母/质量/原因和 `pending_tasks`；compare/变化摘要待冻结 |
| `GET /api/v1/dashboard/intersections` | 按权限、bbox 和筛选返回路口摘要 | 已支持单值 `risk/monitor/quality`、WGS84 `bbox=min_lon,min_lat,max_lon,max_lat`、`q`、`offset/limit`；返回 `project_total/total/has_more/filters`。未实现聚合簇/zoom，不允许一次无限拉取 |
| `GET /api/v1/dashboard/intersections/{inter_id}` | 选中路口详情 | 任务、无人机、管道、态势、事件、路网版本、质量及专业页面稳定深链参数 |
| `GET /api/v1/dashboard/drones` | 当前视野/任务关联的无人机保障摘要 | `drone_id`、任务/路口、位置、遥测时间、定位质量和授权后的状态摘要 |

接口路径不属于消息/自建表 `uav_` 前缀规则，但响应中的业务消息类型、事件引用和后端自建物理对象仍须遵守第 0 节 canonical 契约。overview 与地图摘要必须在同一权限和可比较时间口径下返回；缺失数据使用明确的 `stale/missing/unknown`，不得以 `0` 代替。S8-TBD-001/005 未关闭时，覆盖、拥堵、保障和综合可信度使用 `value=null + numerator/denominator + unverified reason`。

当前 OSM 开发底图只接受 `RoadContext` 与 `coordinate_reference` 均为 verified、`display=WGS84` 且坐标有效的路口。GCJ02 或未验证记录进入 `isolated/map_exclusion_reason`，直至正式瓦片/坐标 Adapter 冻结；禁止将 GCJ02 数值直接投放到 WGS84 OSM。

`bbox` 非 4 个数、经纬度越界或最小值不小于最大值返回 `422 invalid_bbox`。`limit` 为 1～1000，默认 200；`offset` 不小于 0。road9 查询超时或 SQLAlchemy 依赖异常返回 `503 dashboard_dependency_unavailable`，前端可保留最后成功快照并重试，不得回退 Mock。此内部查询契约解决实现者选择项，但正式项目范围、权限过滤、点位聚合/zoom、缓存、SLA 和错误预算仍由 S8-TBD-002/006/007/009 书面冻结。

主任首屏默认只订阅 `uav_alerts` 和 `uav_system`；选中路口后订阅 `uav_intersection:{intersection_id}`，需要无人机实时详情时再订阅 `uav_telemetry:{drone_id}`。禁止同时订阅城市全部路口明细频道。若未来新增全局路口状态增量，channel 和 `type` 必须以 `uav_` 开头并经过容量、恢复和幂等评审。

重点关注榜必须返回可复算的入榜原因、持续时间、变化方向、规则/窗口和质量，不得只返回不透明综合分。上一可比时段只有在辖区、项目路口集合、指标口径和 coverage 可比较时才允许输出变化百分比。

`pending_tasks` 只聚合本平台可执行的 `ai_review/survey_delivery/integration_replay/configuration_check`，按当前身份和数据范围过滤，并从现有事件、测绘、投递和配置状态计算；不得新增第二套任务真源，也不得返回主平台派警、处置、结案或处罚决定。

### 0.10 无人机对接与飞行计划契约（S9 内部工程契约已实现）

本节已由 Alembic `20260715_0003`、`MissionOrchestrator`、PostgreSQL repository 和 Console2 `/drones` 四页签实现。`DRONES` 只保留最新遥测运行缓存，不再承担设备或 Mission 业务真源；`POST /api/v1/missions` 保留兼容入口，并把旧原始源字段规范化为持久化 `manual` Mission 快照。权威设备主数据、生产 secret provider、主平台和权威路网合同仍为外部验收阻断，不因本地实现而关闭。

#### 0.10.1 术语与状态

- SRT 固定指 DJI `.srt` 遥测字幕，不指 Secure Reliable Transport 视频协议。
- 实时源固定配对为 RTSP 视频 + MQTT 遥测；本地回放固定配对为服务器 MP4 文件 + `.srt` 遥测文件。
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
| POST | `/api/v1/drones/{drone_id}/sources/{source_profile_id}/validate` | 校验 RTSP+MQTT 或 MP4+SRT |
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

本地回放使用 `mode=local_replay`、`video.type=file`、`telemetry.type=srt_file`。保存前对服务器路径做 realpath 规范化并限制在批准的 `UAV_LOCAL_ASSET_ROOTS` 内；响应只返回授权后的脱敏/相对显示值。校验至少包含 MP4 存在/可读/可解码、SRT 存在/可读/可解析以及时间或帧覆盖匹配。

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

## 1. Kafka 消息契约（当前实现/遗留，待迁移）

> 本节基于 commit `e69acee` 的代码现状。以下无 `uav_` 前缀名称只允许迁移兼容，不得用于新增生产者或正式目标验收。

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
      "trajectory_world_m": [[12.3, -5.2], [12.8, -4.9]],
      "current_point_m": [12.8, -4.9],
      "world_anchor_lat_lon": [31.234567, 121.456789],
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
  "trajectory_world_m": [[12.3, -5.2], [12.8, -4.9]],
  "entry_point_m": [10.1, -6.5],
  "exit_point_m": [18.4, 2.1],
  "world_anchor_lat_lon": [31.234567, 121.456789],
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
  "motor_position_m": [12.3, -5.2],
  "non_motor_position_m": [12.3, -5.2],
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
  "world_anchor_lat_lon": [31.234567, 121.456789]
}
```

冲突检测默认启用（`conflict_detection.enabled: true`），但无有效单应性矩阵、双方世界坐标速度向量或足够历史轨迹时会自动跳过，避免像素距离和短轨迹抖动误报。`ttc_sec` 基于 motor/non_motor 世界坐标运动趋势做未来 `0-5s` 候选交汇预测；有足够历史轨迹时，预测方向优先取最近一个有效轨迹段，速度大小沿用 `SpeedEstimationNode` 的米/秒估计，避免线性回归测速方向在转弯或轨迹错位时制造虚假交点。默认路径交点候选必须同时满足：双方预测路径存在空间交点、到达时间差不超过 `arrival_time_tolerance_sec`（默认 `1.0s`）、且双方到达交点这段时间内的连续同刻最小中心距进入 `same_time_collision_radius_m`（默认 `0.8m`）共同冲突区；只有数学射线交点但同刻距离仍偏大的 0.9m~1.7m 擦肩轨迹不会被判成相撞。同刻 CPA 候选默认关闭（`enable_same_time_cpa: false`），显式开启后也只使用 `same_time_collision_radius_m`，且 CPA 的 `pet_sec=0` 不作为 PET 侵占证据。候选还必须满足 `30°~150°` 冲突角，并归入无车道标注轨迹几何近似场景：`suspected_right_turn_mv_nmv` 或 `suspected_unprotected_left_turn`。机动车转弯场景除首尾 heading 差外，还要求转弯前后两段投影位移都达到 `min_turn_leg_m`（默认 `2.0m`），用于过滤短窗口小折线和近直行误分。

最终 `conflict` 事件需要 near-miss 证据：`hard_ttc_or_pet`（默认 TTC <= 1.5s）可直接触发；路径交点 `hard_pet`（默认 PET <= 1.0s）只表示极近抢行强度，必须叠加 `hard_deceleration`、`hard_steering`、`stop_or_yield` 之一才触发事件，避免仅凭数学交点和低 PET 把近距离错位经过报成 near-miss。`hard_steering` 只把非机动车短窗口 heading 突变视为避险证据，机动车正常右/左转不计作避险急转向。`prediction_type` 标识候选来源，默认业务口径只展示/处理 `path_intersection`；显式启用扩展时产生的 `same_time_cpa` 属于中心点同刻最近接近候选，Monitoring 冲突回放入口会过滤该类 CPA-only 擦肩事件。旧格式事件仅在缺少 `prediction_type` 且 `distance_m` 近似 `0.0` 时按路径交点兼容，带 `prediction_type=path_intersection` 但 `distance_m` 非零的畸形消息也会被前端过滤，0.9m/1.3m/1.7m 等非零距离旧 CPA 消息不会进入业务冲突列表。`distance_m` 表示预测冲突时刻的双方距离，路径交点场景为 `0.0`；`motor_position_m` / `non_motor_position_m` 表示预测冲突点附近的双方未来世界坐标。`motor_arrival_ttc_sec` / `non_motor_arrival_ttc_sec` 表示双方到达冲突点的预测时间。`motor_id` / `non_motor_id` 轨迹对同级别事件不重复上报，但允许从 `warning` 升级为 `critical` 再次上报，直到轨迹清理后释放状态。Platform Kafka consumer 的实时冲突缓存和 WebSocket 推送同样按 `motor_id` / `non_motor_id` upsert，同级重复消息会被丢弃，升级消息会替换原事件并重新推送。机非分类由 `vehicle_classification.non_motor_class_names` / `non_motor_class_ids` 配置非机动车集合；未配置的已知检测类别按机动车处理。摩托车、电动车相关类别默认归入非机动车。

### 世界坐标说明

所有世界坐标使用**东北天(ENU)**坐标系，单位为米，原点为世界锚点GPS位置：
- `easting_m` (+X) = 东向偏移
- `northing_m` (+Y) = 北向偏移

**GPS还原公式**：
```
lat = anchor_lat + northing_m / 111320
lon = anchor_lon + easting_m / (111320 × cos(radians(anchor_lat)))
```

### 字段说明（统计消息）
| 字段 | 类型 | 说明 |
|------|------|------|
| `camera_id` | string | 格式 `id_{N}`，N 为摄像头编号 |
| `cars` | int | 当前帧滑动窗口平均车辆数 |
| `active_tracks` | int | 当前帧活跃跟踪目标数 |
| `active_trajectories` | array | 当前活跃轨迹轻量快照，用于平台 BEV 与检测画面同频实时投放；每项包含最近尾部 `trajectory_px`、`trajectory_point_count`、`trajectory_tail_start`、`is_trajectory_tail`，有有效单应性/运动补偿时包含尾部 `trajectory_world_m`、`current_point_m`、`world_anchor_lat_lon` |
| `road_1` ~ `road_5` | float \| null | 每条道路的车辆活跃度（辆/分钟） |
| `msg_type` | string | 消息类型标识（"stats"） |
| `intersection_id` | string | 路口标识（`INT_camera_{N}`） |
| `direction_flow` | dict \| null | 方向流量统计（始终输出） |
| `queue_count` | int | 当前排队车辆数 |
| `avg_speed_kmh` | float | 整体平均车速 |
| `lane_stats` | dict \| null | 车道级统计（有标注或模型检测时输出） |
| `lane_source` | string \| null | 车道数据来源：`"manual"` / `"model"` / `"auto"` / `null` |
| `road_polygons` | dict | 当前检测配置中的道路多边形，供悬停生成标注任务后导出复用 |
| `conflict_count` | int | 当前帧冲突事件数 |
| `drone_position` | dict \| null | 无人机位置（有遥测时输出） |
| `is_hovering` | bool | 是否悬停 |

### 发送频率
- 由 `kafka_producer_node.how_often_sec` 控制（默认 1 秒）
- 第一帧始终发送
- `active_trajectories` 随统计消息发送，是活跃轨迹的当前尾部快照，避免长时间运行时 Kafka 单条消息无限增长；console 按 `track_id` 累积尾部点列用于 BEV 显示和 GeoJSON 导出，车辆离场/超出分析窗口后的完整轨迹仍通过 `track_complete_{n}` 发送。

### BEV GeoJSON 导出
- Console BEV 视图导出时会合并三类轨迹：当前活跃轨迹快照、当前会话已完成轨迹、历史 API 查询轨迹。
- 展示层可限制绘制数量以保持流畅，但导出使用当前会话缓存的全量轨迹数据，不受 BEV 显示上限裁剪。
- GeoJSON `properties` 会保留 `trajectory_world_m`、`trajectory_px`、`track_id`、车辆类型、速度、时间戳、转向行为等原始字段，便于离线复盘。

### 生产者
- 文件：`nodes/KafkaProducerNode.py`
- 序列化：`json.dumps(x).encode("utf-8")`
- 异步发送：主线程只调用 `_enqueue(topic, data)` 写入有界队列；后台 `kafka_sender` 线程调用 `KafkaProducer.send()`，Kafka 阻塞或短暂失败不会阻塞检测管道。

### 消费者
- 当前消费者包含 Telegraf `[[inputs.kafka_consumer]]`，配置在 `services/telegraf/telegraf.conf`。该消费者属于待退役旧链路；目标消费者由 Platform/TimescaleDB writer 直接写入 `road9`。

### ⚠️ 契约约束
- **迁移期不得直接破坏旧消费者**：旧 `road_1`~`road_N` 和旧 Topic 只由兼容适配器接收；目标消息使用动态 `roads[]` 和 `uav_*` canonical Topic。
- **禁止为旧 Grafana/InfluxQL 继续扩展契约**：新增道路、车道和指标只进入 canonical 消息及 PostgreSQL/TimescaleDB 模型。
- **旧 Topic 必须下线**：切换窗口内可兼容或受控双投，但最终只保留第 0 节冻结的 `uav_*` Topic。

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
- 用途：浏览器 `<img src="/camera_N">` 无法携带 Bearer token，且检测器子进程绑定在 Platform 容器内 `127.0.0.1:{video_port}`；因此由 Platform 先在容器内访问 `http://127.0.0.1:{video_port}/video`，再把流转发给前端。
- 无运行管道：返回 `404 {"error":"camera_not_running","camera_id":N}`
- 认证：该端点为公开只读流端点，由 `AuthMiddleware.PUBLIC_PATHS` 放行。

#### Vite dev `GET /camera_N`
- 前端开发服务器将 `/camera_N` 转发到 `http://localhost:8000/api/v1/video/camera/{N}`。
- 不再直接转发到宿主机 `localhost:{video_port}/video`，因为 Docker Platform 启动的检测器端口只在容器本地可达。

### 技术细节
- 使用 Flask 的 `Response` 生成器实现流式推送
- 帧通过 `cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])` 编码
- 服务器在守护线程中运行（`Thread(daemon=True)`）
- 帧更新通过 `self._frame` 实例变量，无锁保护（可能出现撕裂）

## 3. Nginx 反向代理路由

### 路由规则
```nginx
location ~ ^/camera_(\d+)$ {
    resolver 127.0.0.11 [::1];
    set $camera_id $1;
    proxy_pass http://traffic_analyzer_camera_$camera_id:8100/video;
}
```

### 访问方式
| URL | 代理到 |
|-----|--------|
| `http://localhost:8009/camera_1` | `traffic_analyzer_camera_1:8100/video` |
| `http://localhost:8009/camera_2` | `traffic_analyzer_camera_2:8100/video` |
| `http://localhost:8009/camera_N` | `traffic_analyzer_camera_N:8100/video` |

### 约束
- 容器名必须遵循 `traffic_analyzer_camera_{N}` 格式
- Nginx 使用 Docker 内部 DNS（`127.0.0.11`）解析容器名
- 只代理 `/video` 端点，不代理 `/`

## 4. InfluxDB 数据模型（当前遗留，目标废弃）

> 本节仅用于迁移对账和定位当前代码。目标平台不再向 InfluxDB 写入或查询；新的指标字段不得加入此模型。

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

## 6. Grafana API（当前遗留，目标废弃）

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

> 2026-05-29 从微服务重构为单体架构。除第 0 节明确的目标变更外，本节响应是当前代码现状；含 `influxdb`、旧 Topic 或旧 WebSocket 名称的示例尚待迁移。

### 基础 URL
- 本地开发：`http://localhost:8000`
- Docker Compose：Platform API `http://localhost:8000`；Console `http://localhost:8080`（Console 内部通过 `/api/` 代理到 `platform:8000`）

### 健康检查端点（无需认证）

#### `GET /health`
- 返回：`{"status": "healthy"}`
- 用途：存活检查（liveness probe）

#### `GET /ready`
- 当前实现返回：
```json
{
  "status": "ready",
  "services": {
    "database": "healthy",
    "kafka": "healthy",
    "influxdb": "healthy",
    "websocket": "healthy"
  }
}
```
- 用途：就绪检查（readiness probe），各服务可能为 `healthy`、`degraded` 或 `unavailable`

目标实现删除 `influxdb` 依赖项，显式检查 `road9` 和 TimescaleDB，例如：

```json
{
  "status": "ready",
  "services": {
    "database": "healthy",
    "timescaledb": "healthy",
    "kafka": "healthy",
    "websocket": "healthy"
  }
}
```

该目标响应尚未实现；扩展版本不符、hypertable migration 未完成或 `road9` 不可写时，`timescaledb`/`database` 必须返回 `degraded` 或 `unavailable`。

### 认证端点（无需 JWT）

#### `POST /api/v1/auth/register`
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
- 下例为当前实现；目标实现使用 `timescaledb_connected` 替代 `influxdb_connected`。
- 请求头：`Authorization: Bearer <token>`
- 返回（200）：
```json
{
  "status": "healthy",
  "uptime_seconds": 3600,
  "kafka_connected": true,
  "influxdb_connected": true
}
```

#### `GET /ready`
- 公开端点，用于平台依赖就绪检查。下例为当前实现；目标依赖字段按本章前述 `database/timescaledb/kafka/websocket` 返回，不再暴露 `influxdb`。
- 返回（200）：
```json
{
  "status": "degraded",
  "services": {
    "database": "degraded",
    "kafka": "degraded",
    "influxdb": "healthy",
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
| POST | `/survey-tasks/{task_id}/capture-batches/import` | 从服务器 allowlist 导入真实 MP4+DJI SRT 并入队 |
| GET | `/survey-tasks/{task_id}/frames` | 查询原始帧、BEV、遥测和测量变换摘要 |
| GET/POST | `/survey-tasks/{task_id}/measurements` | 查询/创建服务端 ENU 点线面量算 |
| DELETE | `/survey-tasks/{task_id}/measurements/{measurement_id}` | 按 revision 删除当前量算版本 |
| GET/POST | `/survey-tasks/{task_id}/reports` | 查询/生成 PDF+JSON+GeoJSON 成果包 |
| POST | `/survey-tasks/{task_id}/reports/{report_id}/deliver` | 经批准质量规则、URL 和 outbox 投递主平台 |
| GET | `/survey-evidence/{evidence_id}/content` | 鉴权读取不可变证据或报告对象 |

测绘结果 canonical schema 为 `uav.survey-result.v1`，事件固定
`msg_type=uav_ai_event`、`event_type=survey_result`、
`source_system=uav_traffic_analyzer_ai`。当前 S3 API 已实现本地闭环；主平台最终 URL、鉴权、回执、签章、归档和正式误差阈值仍由 S3/S6 评审冻结。

### WebSocket 端点

> 以下无前缀 channel 和 `type` 仅是遗留/迁移期兼容，非目标契约。目标值以第 0.5 节为准：`uav_intersection:*`、全局 `uav_alerts`、路口级 `uav_alerts:*`、`uav_system`、`uav_telemetry:*`、`uav_calibration` 以及对应 `uav_*` type。

#### `WS /ws/realtime`
- 连接 URL：`/ws/realtime?access_token=<JWT>`。缺失或无效 Token 在握手阶段以 `4401` 关闭；WebSocket 不读取 Cookie。
- 连接后发送订阅消息：
```json
{
  "action": "subscribe",
  "channels": ["intersection:INT_camera_1", "alerts", "telemetry:drone_001"]
}
```
也兼容单频道格式：
```json
{"action": "subscribe", "channel": "system"}
```
- 服务端推送消息格式：
```json
{
  "channel": "intersection:INT_camera_1",
  "type": "stats",
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
  - `intersection:{intersection_id}` — 实时统计 + 轨迹完成 + 冲突事件
  - `alerts` — 系统级告警（AlertEngine 触发）
  - `telemetry:{drone_id}` — 无人机实时遥测
- `system` — GPU/系统指标
- Platform Kafka consumer 默认订阅 topic pattern：
```text
((statistics|track_complete|conflicts|telemetry)_.*|system_metrics)
```

该正则是当前代码现状；目标订阅正则见第 0.2 节。

### 认证机制
- JWT token 在 `Authorization: Bearer <token>` 头中传递
- Console2 仅使用 `sessionStorage:uav_access_token`，不读取旧 Console Cookie 或 Token key
- WebSocket 因浏览器握手不能附加 Authorization header，使用 `access_token` query 参数并执行相同 JWT 校验
- Token 包含 `sub`（user_id）、`username`、`role` 字段
- 中间件在 `platform/app/middleware/auth.py` 中实现
- 公开路径白名单：`/health`、`/ready`、`/api/v1/auth/login`、`/api/v1/auth/register`、`/docs`、`/openapi.json`
- `/api/v1/system*`、`/api/v1/users*`、`/api/v1/calibration*` 由后端要求 `role=admin`；前端菜单隐藏和角色预览不是安全边界
- 后端角色固定映射为 Console2 展示角色：`admin → 管理员`、`operator → 交通指挥员`、`viewer → 数据分析员`

## 8. 平台 REST API（43 条路由）

### 管道管理 `/api/v1/pipelines`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/pipelines` | 列出所有管道实例 |
| GET | `/api/v1/pipelines/summary` | 管道概览（running/stopped/error 计数） |
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
  "roads_json": "configs/entry_exit_lanes.json",
  "telemetry_source": "srt",
  "telemetry_file_path": "test_videos/inter_xqh/telemetry.srt"
}
```

`roads_json` 可传空字符串，平台会把子进程 `ROADS_JSON` 置空，检测管道按无道路标注模式运行。未显式传自定义道路文件且仍为默认 `configs/entry_exit_lanes.json` 时，平台会优先查找该路口已保存的人工车道标注导出文件。

本地开发可通过环境变量控制平台启动的检测器子进程：
- `PIPELINE_PYTHON`：检测器 Python 解释器，例如 `/Users/yaoyao/miniconda3/envs/py312/bin/python`
- `PIPELINE_FRAME_STRIDE`：写入检测器 `FRAME_STRIDE` 环境变量，例如 `3`
- `KAFKA_BOOTSTRAP`：检测器和平台 Kafka 地址，例如 `localhost:9092`

Docker 部署中，平台容器通过 `PIPELINE_PROJECT_ROOT=/project` 启动挂载的根
`main_optimized.py`。镜像必须安装 `platform/pipeline-requirements.txt`
中的检测器依赖，并用 `platform/pipeline-constraints.txt` 固定
`numpy<2`、`torch==2.2.2`、`torchvision==0.17.2`；否则
`POST /api/v1/pipelines` 会创建任务但很快进入 `error`，典型错误为
`ModuleNotFoundError: No module named 'hydra'`，或因新版 Torch/CUDA/NumPy
解析导致镜像过重、OpenCV 不兼容。由于 `/project` 为只读挂载，Platform 启动
检测器时还会追加 `hydra/job_logging=disabled`，避免 Hydra 文件日志 handler
尝试写入 `logs/app.log` 导致 `ValueError: Unable to configure handler 'file'`。
检测器 multiprocessing 子进程也会检测 `FileHandler` 是否可写，不可写时自动移除
file handler 并降级到 console，避免 reader/tracker/show worker 因同一日志配置退出。

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
  "roads_json": "configs/entry_exit_lanes.json",
  "topic_name": "statistics_10",
  "camera_id": 10,
  "video_port": 8101,
  "status": "running",
  "started_at": 1234567890.123,
  "stopped_at": 0,
  "error_message": "",
  "uptime_seconds": 120.5
}
```

新建 Pipeline 当前返回 canonical `topic_name=uav_statistics_10`。consumer 在迁移期继续接收 `statistics_10` 等旧 Topic，但新生产者不得再生成旧命名消息。

### 路口管理 `/api/v1/intersections`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/intersections` | 列出所有路口 |
| GET | `/api/v1/intersections/summary` | 系统级概览（车流量/拥堵/告警/无人机在线/管道数） |
| GET | `/api/v1/intersections/{id}` | 路口详情（含当前分配的无人机信息） |
| GET | `/api/v1/intersections/{id}/stats` | 历史统计（I3 当前查询 `uav_traffic_metrics`） |
| GET | `/api/v1/intersections/{id}/lane-stats` | 车道级历史统计 |

### 无人机管理 `/api/v1/drones`（当前 S9 实现）

以下端点由 `MissionOrchestrator` 统一访问 `road9` repository；运行时 `drone_store` 只叠加最新遥测和在线状态，不保存业务配置或 Mission 真源。完整写权限、revision、错误和调度语义见第 0.10 节。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | `/api/v1/drones` | 查询/创建持久化无人机档案并叠加最新遥测状态 |
| GET/PATCH | `/api/v1/drones/{id}` | 查询/按 revision 更新无人机档案 |
| GET/POST | `/api/v1/drones/{id}/sources` | 查询/创建脱敏 SourceProfile |
| GET | `/api/v1/sources` | 查询授权范围内全部 SourceProfile |
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

#### `POST /api/v1/missions`（持久化兼容入口）

新调用应传已登记的 `source_profile_id`；迁移期仍接受旧 `video_src/telemetry_file_path`，但会执行 allowlist、realpath、类型和配对校验，创建持久化 `trigger_type=manual` Mission 快照。Pipeline 启动失败时 Mission 进入 `failed` 并保存脱敏分类原因，不再写入内存 `MISSIONS`。

请求：
```json
{
  "name": "小清河早高峰巡检",
  "drone_id": "drone_7",
  "intersection_id": "INT_camera_7",
  "video_src": "test_videos/inter_xqh/DJI_20260403142902_0001_V小清河北路与水屯路路口.mp4",
  "roads_json": "",
  "telemetry_source": "srt",
  "telemetry_file_path": "test_videos/inter_xqh/telemetry.srt"
}
```

响应使用第 0.10.4 节 Mission shape，并分别返回 `status`、`pipeline_id` 和 `pipeline_status`；canonical Topic 为 `uav_statistics_{camera_id}`。

### 轨迹复盘 `/api/v1/trajectories`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/trajectories/{intersection_id}` | 查询路口历史轨迹，支持 `period` / `limit` |
| GET | `/api/v1/trajectories/{intersection_id}/conflicts` | 查询路口历史冲突事件，支持 `period` / `limit`，返回 TTC/PET、场景、证据、风险分和预测位置 |
| POST | `/api/v1/trajectories/{intersection_id}/conflicts/{event_id}/review` | 管理员按 `expected_revision` 技术确认/驳回；409 表示 revision 冲突，结果不等同警情处置 |
| GET | `/api/v1/trajectories/{intersection_id}/turn-summary` | 查询转向行为汇总 |

Console GIS 页会在选中路口后调用 `GET /api/v1/trajectories/{intersection_id}?period=1h&limit=200`，展示最近历史轨迹数量、轨迹 ID、转向、车辆类型、均速、时长和轨迹点数，用于复盘 `track_complete` 写入后的路线形态。
同一页面还会调用 `GET /api/v1/trajectories/{intersection_id}/conflicts?period=1h&limit=200`，展示历史冲突 pair、TTC/PET、业务场景、证据和风险分。I3 当前实现查询 TimescaleDB hypertable `uav_conflict_events`，并从普通表 `uav_conflict_reviews` 合并复核状态；正式 `/gis`、`/events` 路由不再读取轨迹/事件 Mock。

### 告警中心 `/api/v1/alerts`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/alerts` | 告警列表，支持 `severity/status/limit/offset` |
| GET | `/api/v1/alerts/{id}` | 告警详情 |
| POST | `/api/v1/alerts/{id}/acknowledge` | 确认告警 |
| GET | `/api/v1/alerts/{id}/push-logs` | 告警推送记录 |

当前 AlertEngine 创建告警和确认告警时会写入 PostgreSQL `alerts` 表；目标迁移到 `road9` connection database 中的 `uav_alerts`（实际 schema 待确认）。Platform 启动时会加载已持久化告警，
因此告警列表、详情和确认状态可跨服务重启保留。PostgreSQL 不可用时，平台降级为内存告警，
实时 WebSocket `alerts` 推送仍继续工作，但历史告警不可跨重启恢复。

### 系统监控 `/api/v1/system`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/system/health` | 健康检查（含 pipelines_active） |
| GET | `/api/v1/system/gpu` | GPU 实时指标 |
| GET | `/api/v1/system/gpu/history` | GPU 历史（I3 当前查询 `uav_system_metrics`） |
| GET | `/api/v1/system/kafka/topics` | Kafka topic 状态 |
| GET | `/api/v1/system/kafka/consumers` | Kafka consumer group 状态 |
| GET | `/api/v1/system/models` | YOLO 模型列表 |

### 标定中心 `/api/v1/calibration`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/calibration/summary` | 标定参数摘要 |
| GET | `/api/v1/calibration/records` | 标定参数记录 |
| GET | `/api/v1/calibration/lane-tasks` | 车道标注任务列表 |
| GET | `/api/v1/calibration/lane-tasks/{task_id}/image` | 管理员 Bearer 鉴权后返回车道标注任务 JPEG；Console2 以 Blob URL 注入画布，不公开直链 |
| GET | `/api/v1/calibration/lane-annotations` | 已保存车道标注参数列表 |
| GET | `/api/v1/calibration/lane-annotations/{intersection_id}` | 查询某路口可复用车道参数 |
| POST | `/api/v1/calibration/lane-tasks/{task_id}/annotation` | 保存人工车道标注结果 |

当前车道标注任务由 Kafka `stats` 消息触发；目标迁移后触发类型为 `uav_stats`。同一路口 `is_hovering=true` 且 `drone_position.easting_m/northing_m` 在 `lane_annotation_hover_radius_m` 半径内持续超过 `lane_annotation_hover_seconds`（默认 30 秒），并且该路口没有已保存人工车道参数时，平台生成一个 `pending` 任务。悬停统计消息会携带压缩 JPEG 快照字段 `annotation_snapshot_jpeg` 以及 `annotation_snapshot_width/height`；平台收到后落盘为任务图片，并通过 `image_url` 返回给 console 车道标注画布。

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

后续飞行启动检测管道时，将该导出文件作为 `roads_json` 即可复用人工车道标注；`VideoReader` 会读取 `lanes` 并让 `LaneDetectionNode` 标记为 `lane_source="manual"`。

平台 `POST /api/v1/pipelines` 在调用方未显式指定自定义 `roads_json`（仍为默认 `configs/entry_exit_lanes.json`）时，会优先查找该 `intersection_id` 的已保存车道标注，命中后自动把 `roads_json` 替换为导出文件路径。

### 就绪检查 `/ready`

> 下例为当前实现。目标响应移除 `influxdb`，增加 `timescaledb`，详见第 7 节健康检查约束。

```json
{
  "status": "ready",
  "services": {
    "database": "healthy",
    "kafka": "healthy",
    "influxdb": "healthy",
    "pipeline_manager": "healthy"
  },
  "pipelines_active": 2
}
```

## 9. WebSocket 消息类型（遗留/迁移期兼容，非目标契约）

> 本章所有无 `uav_` 前缀的 channel 和 `type` 只用于当前代码识别与迁移，不得作为目标接口继续开发；目标契约见第 0.5 节。

### `stats` 消息
通过 `intersection:{id}` 频道推送，与 Kafka statistics topic 格式一致（含 direction_flow, drone_position, lane_stats）。

### `track_complete` 消息
通过 `intersection:{id}` 频道推送，与 Kafka track_complete topic 格式一致（含 trajectory_px, trajectory_world_m, turn_behavior）。

### `conflict` 消息
通过 `intersection:{id}` 频道推送，与 Kafka conflicts topic 格式一致。
- Monitoring 页面会保留并显示最近 20 个实时冲突 pair；同一 `motor_id` / `non_motor_id` 的重复消息会合并为一条事件行。点击事件行会在 BEV 上叠加 motor/non_motor 短时回放层，回放控制状态与实时 `active_trajectories` 投放解耦。页面只把 `prediction_type=path_intersection && distance_m≈0.0` 作为业务冲突回放；旧格式仅在 `distance_m` 近似 `0.0` 时兼容，`same_time_cpa`、旧 CPA 非零距离消息或畸形 path 非零距离消息会被过滤，避免仅中心点 0.9m~1.7m 擦肩事件进入机非冲突列表。BEV 回放中的风险圈和距离辅助线均使用事件预测位置，不能使用播放进度下两车当前点替代预测冲突点。
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

Drones 页面会根据 `/api/v1/drones` 返回的无人机 ID 动态订阅
`telemetry:{drone_id}`，收到 WebSocket 消息后立即覆盖轮询得到的最新遥测值；
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

# S9 无人机对接与飞行计划管理分册 PRD

## 0. 文档元数据

| 项 | 内容 |
| --- | --- |
| 上位文档 | [无人机交通智能感知系统总 PRD](../2026-06-29-uav-traffic-ai-prd.md) v2.1（2026-07-14） |
| 分册编号 | S9 |
| 产品名称 | 无人机对接与飞行计划管理 |
| 目标路由 | `/drones`（无人机、数据源、飞行计划、执行记录四个页签） |
| 文档状态 | I1/I2 内部工程契约与真实闭环已完成；设备权威、生产接入、权限矩阵、容量和高可用仍待正式批准 |
| 重要性 / 优先级 | 高 / P0 |
| 需求方 | 交通管理部门 / 投标项目组 |
| 产品、审核人与批准日期 | 【待补充：姓名、部门、日期】 |
| 主要评审方 | 无人机作业方、交通指挥中心、产品、平台架构、前端、运维、测试、DBA、网安、智慧交通主平台方 |
| 关联分册 | S1 路口态势、S5 路网与共性能力、S7 质量验收与运营、S8 城市一图概览 |
| 架构基线 | PostgreSQL database=`road9` + TimescaleDB；UAV 自建表和内部消息使用 `uav_` 前缀；FastAPI 单体 + PipelineManager |

> 本分册中的 **SRT** 固定指 DJI 视频配套的 `.srt` 遥测字幕文件，不指 Secure Reliable Transport 视频传输协议。实时无人机使用 RTSP 视频 + MQTT 遥测，本地测试使用服务器 MP4 文件 + `.srt` 遥测文件。

已签署合同/澄清文件优先于总 PRD 最新批准版，总 PRD 优先于本分册。凡标记 `【待确认】`、`【待补充】`、`【外部依赖】` 或 `【验收阻断】` 的内容，不得直接作为生产默认值或验收通过依据。

## 1. 分册目标与边界

### 1.1 Problem Statement

I2 实施前，平台只能从无人机遥测或管道消息形成内存记录，并通过 `POST /api/v1/missions` 携带原始源字段立即启动检测管道，无法稳定回答以下运营问题：

1. 一架无人机有哪些经过批准的视频与遥测接入方式，当前默认使用哪一组，凭据和本地路径是否安全、可用。
2. 哪架无人机应在什么时间监测哪个权威路口，早晚高峰等周期排期是否冲突，临时任务如何与周期计划共存。
3. 计划到点后是否只启动了一次 AI 任务，平台重启或多实例运行时是否会重复启动，任务结束后是否按计划停止。
4. 任务失败是视频、SRT、MQTT、路网、管道还是调度问题，操作人员能否从页面和 API 获得可诊断原因。
5. 本地 MP4 + SRT 回放能否复用与实时无人机相同的任务、管道、遥测和验收链路，而不是依赖命令行临时拼接参数。

上述内存实现仅是历史迁移基线。自 Alembic `20260715_0003` 起，Drone/Source/FlightPlan/Mission/Pipeline 已使用 `road9` repository；`DRONES` 只保留最新遥测运行缓存，FlightPlan、Mission 与 Pipeline 的 ID、状态和恢复语义严格分离。

2026-07-15 工程验收已使用 `inter_xqh` 5.0GB MP4 + DJI SRT 完成计划触发、canonical `uav_statistics_*` Pipeline 启动、模拟 Platform 重启恢复和窗口结束；浏览器四页签展示真实持久化记录。补充的 `recovery_eof` 验证以 `frame_stride=300` 完整读取同一原视频，恢复后 Pipeline `pipe-fc39f315` 自然零退出，Mission `MSN-995CEBE0415E` 持久化为 `completed/source_eof`，证据见 `docs/test_report_s9_inter_xqh_eof.json`。该证据不关闭设备权威、RTSP/MQTT 生产接入、正式权限、容量和节点级高可用门禁。

### 1.2 Solution

在现有 `/drones` 管理入口中建设无人机档案、成对数据源、飞行计划和 Mission 执行记录四项能力：

- 无人机档案持久化设备身份和期望配置，实时状态与历史遥测分离管理。
- 每架无人机可配置多组实时或本地回放数据源，并在计划中明确选择一组视频源和遥测源。
- FlightPlan 保存单次或每周周期排期；每次到期执行物化为独立 Mission，并由调度服务调用 PipelineManager 自动启停 AI 检测。
- 平台以持久化状态、幂等键和 PostgreSQL advisory lock 保证重启恢复与多实例单调度者语义。
- 页面和 API 统一展示来源校验、计划冲突、实际执行、失败原因、关联管道和审计记录。

### 1.3 产品目标

1. 管理员可以在不修改代码或 Compose 的情况下登记无人机及其 RTSP+MQTT 或 MP4+SRT 数据源。
2. 管理员可以按权威路口和时间创建单次/每周计划，并在启用前预览执行窗口和冲突。
3. 计划实际启动时间与计划时间偏差不超过 10 秒，且一个计划窗口只产生一个 Mission。
4. 平台重启后可以从 `road9` 恢复未来计划和当前窗口，不依赖进程内对象恢复业务事实。
5. 使用现有 `inter_xqh` MP4+SRT 资产完成与生产一致的端到端回归。

### 1.4 范围边界

本期包含：

- 无人机档案 CRUD、启停、在线/遥测摘要、默认路口和默认数据源；
- 实时 RTSP+MQTT、本地 MP4+SRT 两类成对数据源的配置、脱敏、校验和默认选择；
- 单次计划、每周周期计划、例外日期、跨午夜、暂停/退役和重叠检查；
- 计划执行物化、调度启停、重启恢复、多实例幂等、失败诊断、人工停止和人工重试；
- `/drones` 四页签管理界面、权限、审计和验收指标。

本期不包含：

- DJI FlightHub/Cloud API 航点规划、航线下发、起降、返航、云台控制或其他飞控动作；
- 多无人机覆盖优化、自动换机、续航预测和任务抢占算法；
- Secure Reliable Transport 视频协议接入；
- 浏览器上传、本地浏览器文件直读、对象存储资产库和媒体转码；
- 复制智慧交通主平台的设备资产主数据或权威路网底库；
- 对视频内容做无限期归档或把视频二进制写入 PostgreSQL。

## 2. 用户、场景与价值

### 2.1 角色与职责

| 角色 | 核心任务 | 权限边界 |
| --- | --- | --- |
| 系统管理员 | 维护无人机、数据源、计划，执行校验、启停、停止和重试 | 仅在授权项目/路口范围；敏感凭据只可引用，不可回显 |
| 交通指挥员 | 查看无人机保障、计划和执行状态，进入实时监测核验 | 只读；不得修改源配置或执行飞控动作 |
| 数据分析员 | 查看授权路口的计划覆盖和历史 Mission，关联报告/复盘 | 只读；不查看密钥或未授权源地址 |
| 无人机作业/运维人员 | 配合提供 RTSP、MQTT、设备编号并处理现场/链路故障 | 飞行责任仍在 DJI 平台和作业制度；本系统只记录结果 |
| 测试/监理 | 使用本地 MP4+SRT 验证调度、同步和幂等 | 按批准测试资产和用例执行，不获得生产密钥 |

### 2.2 User Stories

1. 作为系统管理员，我希望登记无人机的名称、型号和序列号，以便平台使用稳定设备身份而不是临时消息 ID。
2. 作为系统管理员，我希望启用或停用无人机，以便退役或维护中的设备不能被新计划选择。
3. 作为系统管理员，我希望为一架无人机配置多组数据源，以便生产、备用和本地回放互不覆盖。
4. 作为系统管理员，我希望把 RTSP 视频与 MQTT 遥测组成一组实时源，以便检测和运动补偿使用同一任务上下文。
5. 作为测试人员，我希望把服务器 MP4 与 `.srt` 文件组成一组本地源，以便复现真实视频与逐帧遥测。
6. 作为系统管理员，我希望验证数据源的可达性和格式，以便错误配置不能进入启用计划。
7. 作为网安人员，我希望 API 和日志不回显 RTSP/MQTT 凭据，以便避免凭据泄露。
8. 作为运维人员，我希望看到最近一次校验时间、结果和脱敏错误，以便定位视频或遥测链路问题。
9. 作为系统管理员，我希望创建指定无人机、权威路口和时间段的单次计划，以便安排临时交通监测。
10. 作为系统管理员，我希望创建按星期重复的早晚高峰计划，以便减少重复配置。
11. 作为系统管理员，我希望设置例外日期，以便节假日或设备维护日不自动执行。
12. 作为系统管理员，我希望预览未来执行窗口，以便在启用周期计划前确认跨午夜和时区结果。
13. 作为系统管理员，我希望系统拒绝同一无人机的重叠计划，以便避免一架设备同时执行多个任务。
14. 作为交通指挥员，我希望不同无人机可以同时监测同一路口，以便重大保障场景允许多视角覆盖。
15. 作为系统管理员，我希望计划到点自动启动 AI 管道并到时停止，以便无需人工值守管道按钮。
16. 作为运维人员，我希望每次执行都保存计划时间、实际时间、管道 ID 和失败原因，以便审计启动偏差。
17. 作为运维人员，我希望平台重启后恢复仍在时间窗内的计划，以便短时维护不会永久漏掉任务。
18. 作为运维人员，我希望已完全错过的窗口被明确标记为 skipped/window_missed，以便系统不在错误时段补跑。
19. 作为系统管理员，我希望人工停止运行任务，以便数据源异常或现场取消时及时终止分析。
20. 作为系统管理员，我希望在修复错误后重试失败 Mission，以便不必重新录入全部任务上下文。
21. 作为交通指挥员，我希望从执行记录跳转到关联管道和实时监测，以便核验实际分析结果。
22. 作为数据分析员，我希望按无人机、路口、计划、状态和时间筛选 Mission，以便统计任务覆盖和失败率。
23. 作为审计人员，我希望配置、启停、自动执行、失败、停止和重试都有操作人与时间，以便还原责任链。
24. 作为平台负责人，我希望现有立即执行 Mission 接口继续兼容，以便迁移期不阻断当前调用方。

## 3. 前置条件、输入与输出

### 3.1 前置条件

1. `road9` 可用并启用批准版本的 TimescaleDB；目标普通表和迁移版本表使用 `uav_` 前缀。
2. S5 已提供可按 `inter_id + road_data_version` 读取的权威路口上下文及设备/任务绑定边界。
3. PipelineManager 支持按 Mission 启动、查询和停止唯一管道，并返回可诊断错误。
4. 服务器配置本地测试资产允许根目录，例如 `UAV_LOCAL_ASSET_ROOTS`；未配置时禁止启用本地回放源。
5. RTSP/MQTT 凭据使用批准的密钥管理或环境引用；不得把明文凭据保存在业务表、审计详情或响应中。

### 3.2 输入

| 输入域 | 最小字段 | 约束 |
| --- | --- | --- |
| 无人机档案 | `drone_id/name/model/serial_number/enabled/default_inter_id` | 设备权威关系待冻结；序列号按权限脱敏 |
| 视频源 | `video_source_id/drone_id/mode/type/location/credential_ref/enabled` | 实时为 RTSP；本地为服务器 MP4 路径 |
| 遥测源 | `telemetry_source_id/drone_id/mode/type/location_or_topic/credential_ref/enabled` | 实时为 MQTT；本地为服务器 `.srt` 路径 |
| 飞行计划 | 无人机、两类源、`inter_id`、路网版本、AI 模式、排期、时区 | 所有引用在启用时必须有效 |
| 权限上下文 | 用户、角色、辖区/项目路口范围 | 服务端强制鉴权与数据过滤 |
| 管道结果 | pipeline ID、状态、启动/停止时间、错误摘要 | 与 Mission 一一关联，PID 不是业务主键 |

### 3.3 输出

- 无人机配置、实时状态、最后遥测时间和默认源摘要；
- 数据源校验状态 `unknown/valid/degraded/invalid`、校验时间和脱敏错误码；
- FlightPlan 定义、未来执行预览、冲突结果和状态；
- Mission 计划/实际时间、运行状态、失败/跳过原因、pipeline ID、人工操作和审计引用；
- 调度覆盖、启动偏差、成功率、失败率、错过窗口和重复抑制等运行指标。

## 4. 业务主流程与状态

### 4.1 核心领域对象

| 对象 | 定义 | 生命周期边界 |
| --- | --- | --- |
| Drone | UAV 平台使用的设备档案和期望配置 | 静态资产持久化；在线状态由新鲜遥测计算 |
| VideoSource | 一项视频接入配置 | 只保存配置/密钥引用；打开的 stream 与帧缓存留在运行内存 |
| TelemetrySource | 一项遥测接入配置 | 只保存 MQTT 配置引用或 SRT 文件路径；采样事实进入时序表 |
| FlightPlan | 可复用的排期定义 | 编辑只影响未来执行，不改写已生成或运行中的 Mission |
| Mission | 一个具体计划窗口或立即执行请求 | 保存计划与实际执行事实，关联一个分析 Pipeline |
| Pipeline | Mission 对应的检测进程期望状态和运行摘要 | OS 进程句柄只在内存，业务状态持久化 |

### 4.2 FlightPlan 状态

| 状态 | 说明 | 允许操作 |
| --- | --- | --- |
| `draft` | 配置未启用，可编辑，不生成 Mission | 编辑、校验、启用、删除 |
| `enabled` | 配置有效，调度器生成/执行窗口 | 暂停、编辑未来窗口、退役 |
| `paused` | 暂停生成新 Mission；已运行 Mission 不自动终止 | 编辑、恢复、退役 |
| `completed` | 单次计划执行窗口已结束；周期计划不进入此状态 | 查看、复制、退役 |
| `retired` | 永久停止后续执行，保留历史 | 查看、复制 |

### 4.3 Mission 状态

| 状态 | 进入条件 | 终态/下一步 |
| --- | --- | --- |
| `pending` | 未来窗口已物化 | 到点进入 starting；取消进入 cancelled |
| `starting` | 已取得调度锁并准备启动 Pipeline | 成功进入 running；失败进入 failed |
| `running` | PipelineManager 返回运行且管道存活 | 到时/自然结束进入 completed；失败进入 failed；人工停止进入 cancelled |
| `completed` | 到结束时间正常停止，或本地视频自然结束 | 终态 |
| `failed` | 源、路网、调度或管道错误 | 终态；管理员可基于原上下文创建重试执行 |
| `skipped` | 窗口已完全错过、例外日或启动前条件不满足且策略禁止执行 | 终态；必须带 reason code |
| `cancelled` | 管理员取消待执行或人工停止运行任务 | 终态；必须记录操作者和原因 |

`Mission.status` 与 `Pipeline.status` 不得混用。Mission 表达业务执行，Pipeline 表达分析进程；管道异常退出会驱动 Mission 失败，但 Mission ID 不等于 pipeline ID。

### 4.4 计划创建与执行流程

1. 管理员选择无人机、成对数据源、权威 `inter_id`、`road_data_version` 和 AI 模式。
2. 管理员选择 `once` 或 `weekly`，输入带时区窗口；周期计划另含星期、生效范围和例外日期。
3. 平台校验权限、设备/源启用状态、数据源最近校验结果、路网版本和同无人机时间冲突。
4. 平台返回未来窗口预览；管理员启用后，计划进入 `enabled`。
5. 调度器每不超过 5 秒扫描当前窗口并竞争 PostgreSQL advisory lock；同一窗口以 `(flight_plan_id, scheduled_start_at)` 保证唯一。
6. 唯一调度者创建或读取 Mission，设置 `starting`，调用 PipelineManager，成功后保存 pipeline ID 和实际开始时间。
7. 到达结束时间后调度器停止关联 Pipeline；本地视频提前自然结束时直接完成 Mission。
8. API、页面和审计记录展示计划时间、实际时间、偏差、状态和原因。

### 4.5 重启与多实例恢复

- 平台启动时从数据库读取 `enabled` 计划、`pending/starting/running` Mission 和关联 Pipeline 期望状态。
- 当前时间仍在窗口内且没有有效运行实例时，调度器幂等补启动；已有有效 Pipeline 时只恢复关联，不重复启动。
- 当前时间晚于结束时间时标记 `skipped`，`reason_code=window_missed`，不自动播放历史文件或补发飞控动作。
- 多实例同时扫描时仅持有 advisory lock 的实例可以转换状态和调用 PipelineManager；唯一约束作为最终防重门禁。
- 服务失去数据库连接时不得创建新 Mission；已运行 Pipeline 的处置按已冻结降级策略执行并告警。

## 5. 功能需求与优先级

| 编号 | 功能需求 | 输入 → 输出 | 优先级 |
| --- | --- | --- | --- |
| S9-FR-001 | 无人机档案新增、查询、编辑、启停和按权限过滤 | 设备信息 → Drone | P0 |
| S9-FR-002 | 展示在线状态、当前路口、最后遥测、定位质量和关联 Mission | 遥测/任务 → 状态摘要 | P0 |
| S9-FR-003 | 每架无人机管理多个视频源和遥测源，并选择默认配对 | 源配置 → 可选数据源 | P0 |
| S9-FR-004 | 支持 RTSP+MQTT 实时源 | URL/topic/secret ref → 实时配置 | P0 |
| S9-FR-005 | 支持服务器 MP4+SRT 本地回放源 | allowlist 路径 → 本地配置 | P0 |
| S9-FR-006 | 提供数据源验证，返回分项结果、耗时、时间和脱敏错误 | 源配置 → valid/degraded/invalid | P0 |
| S9-FR-007 | 数据源查询、页面和日志对凭据及敏感地址脱敏 | 敏感配置 → 授权摘要 | P0 |
| S9-FR-008 | 创建、查询、编辑、复制、暂停、恢复和退役 FlightPlan | 计划输入 → 计划状态 | P0 |
| S9-FR-009 | 支持带时区的单次开始/结束时间 | once schedule → 执行窗口 | P0 |
| S9-FR-010 | 支持星期、生效日期、每日时段和例外日期的 weekly 计划 | weekly schedule → 执行窗口 | P0 |
| S9-FR-011 | 结束时间不晚于开始时间时按跨午夜生成结束时刻 | local time → 跨日窗口 | P0 |
| S9-FR-012 | 预览未来执行窗口及本地时间、UTC、DST/时区解释 | 计划 → occurrence preview | P0 |
| S9-FR-013 | 启用/编辑时拒绝同一无人机重叠计划，返回冲突计划和窗口 | 计划 → conflict/accepted | P0 |
| S9-FR-014 | 不因同一路口已有其他无人机计划而拒绝，详情逐机展示 | 多机同路口 → 并行计划 | P1 |
| S9-FR-015 | 到点自动物化唯一 Mission 并启动 Pipeline | due occurrence → running Mission | P0 |
| S9-FR-016 | 到结束时间自动停止 Pipeline；本地视频自然结束可提前完成 | running Mission → completed | P0 |
| S9-FR-017 | 重启后恢复当前窗口并跳过已错过窗口 | persisted state → recovered/skipped | P0 |
| S9-FR-018 | 多实例通过 advisory lock 和唯一约束防止重复执行 | concurrent tick → one Mission | P0 |
| S9-FR-019 | 保留 `POST /missions` 作为立即执行兼容入口，并标记 `trigger_type=manual` | legacy request → Mission | P0 |
| S9-FR-020 | 管理员可停止待执行/运行 Mission并填写原因 | Mission → cancelled | P0 |
| S9-FR-021 | 管理员可从 failed Mission 创建一次重试，保留 parent/retry 关系 | failed Mission → retry Mission | P1 |
| S9-FR-022 | 支持按设备、路口、计划、状态和时间查询执行记录 | filters → Mission page | P0 |
| S9-FR-023 | 执行详情显示计划/实际时间、偏差、源校验、pipeline ID 和原因 | Mission → diagnostics | P0 |
| S9-FR-024 | `/drones` 提供无人机、数据源、飞行计划、执行记录四页签 | API data → management UI | P0 |
| S9-FR-025 | 从 Mission 跳转关联管道、实时监测和无人机详情 | stable IDs → deep links | P1 |
| S9-FR-026 | 所有配置和执行动作写入 `uav_audit_logs` | mutation/execution → audit | P0 |
| S9-FR-027 | 提供计划任务成功率、启动偏差、失败/跳过原因等可观测指标 | executions → metrics | P1 |

## 6. 业务规则与调度口径

| 编号 | 规则 |
| --- | --- |
| S9-BR-001 | SRT 仅表示 `.srt` 遥测字幕；不得将其作为视频协议枚举或把 SRT 文件当作视频源。 |
| S9-BR-002 | 实时模式只允许 RTSP 视频 + MQTT 遥测；本地回放只允许 MP4 文件 + SRT 文件。跨模式混搭需另行评审。 |
| S9-BR-003 | FlightPlan 必须保存 canonical `inter_id + road_data_version`；现有 `intersection_id` 仅可由兼容适配器生成，不得成为权威路口真源。 |
| S9-BR-004 | FlightPlan 编辑不修改已生成或运行中的 Mission；运行实例保留创建时的数据源、路网和计划快照。 |
| S9-BR-005 | `timezone` 默认 `Asia/Shanghai`，API 必须显式返回；数据库时间统一保存为 UTC，页面同时显示业务时区。 |
| S9-BR-006 | 周期计划以本地星期和本地时刻计算；结束时刻不晚于开始时刻表示结束在下一自然日。 |
| S9-BR-007 | 例外日期按计划业务时区的开始日期匹配；命中后不启动并记录 `skipped/exception_date`。 |
| S9-BR-008 | 同一无人机的 enabled FlightPlan 不得有重叠窗口；不同无人机可关联同一路口。 |
| S9-BR-009 | 一个窗口的幂等身份固定为 `(flight_plan_id, scheduled_start_at)`；重试 Mission 使用新 ID 并引用原 Mission，不复用窗口幂等键冒充首次执行。 |
| S9-BR-010 | 数据源未启用、最近验证为 invalid、设备停用、路网版本不可用或权限失效时不得把计划置为 enabled。 |
| S9-BR-011 | 本地文件路径经 realpath 规范化后必须位于 allowlist 根目录内；禁止 `..`、符号链接逃逸和任意服务器路径读取。 |
| S9-BR-012 | 本地校验至少验证 MP4 可解码、SRT 可解析及二者时间/帧覆盖可对齐；精确容差由 S9-TBD-004 冻结。 |
| S9-BR-013 | 实时校验使用有限超时，不在 API 请求内无限等待；失败只返回错误码和脱敏目标摘要。 |
| S9-BR-014 | Mission 启动时间指 PipelineManager 接受并确认运行的时间，不以调度扫描时间或数据库写入时间替代。 |
| S9-BR-015 | 本地视频自然结束视为正常完成；非零进程退出、SRT 初始化失败或源中断按错误分类进入 failed。 |
| S9-BR-016 | 本系统启动/停止的是 AI 检测 Pipeline，不下发无人机飞行指令；页面操作不得命名为“起飞/返航”。 |
| S9-BR-017 | Drone 在线只由新鲜遥测和有效设备状态共同判定；存在静态档案、数据源或未来计划不等于在线。 |
| S9-BR-018 | 只有管理员可写无人机、源、计划和 Mission 控制；指挥员/分析员只读，且均受授权路口范围限制。 |

## 7. 数据、接口与页面

### 7.1 目标数据模型

| 物理对象 | 形态 | 职责 |
| --- | --- | --- |
| `uav_drones` | 普通表 | 无人机身份、型号、序列号、启用状态、默认路口和默认源引用 |
| `uav_video_sources` | 普通表 | RTSP/MP4 配置、密钥引用、启用与验证状态；不保存打开的流 |
| `uav_telemetry_sources` | 普通表 | MQTT/SRT 配置、密钥引用、启用与验证状态 |
| `uav_flight_plans` | 普通表 | 计划定义、状态、排期、时区、路网/源引用和修订版本 |
| `uav_missions` | 普通表 | 每次执行、计划快照、幂等键、状态、原因、实际时间和 pipeline 引用 |
| `uav_pipelines` | 普通表 | 分析管道期望状态、配置快照和运行摘要 |
| `uav_telemetry_metrics` | TimescaleDB hypertable | 定位、姿态、云台、速度、质量及 Mission/Pipeline 引用 |
| `uav_audit_logs` | 追加型普通表/分区表候选 | 配置、启停、自动执行、失败、停止和重试审计 |

DDL 必须通过正式 migration 冻结外键、唯一约束、RLS、索引和删除策略。关键唯一约束至少覆盖无人机编码/序列号候选和 `(flight_plan_id, scheduled_start_at)`；凭据列只存 secret reference。

### 7.2 REST API 目标契约

| 方法与路径 | 用途 | 权限 |
| --- | --- | --- |
| `GET /api/v1/drones` | 列表、筛选和状态摘要 | 授权用户只读 |
| `POST /api/v1/drones` | 创建设备档案 | 管理员 |
| `GET /api/v1/drones/{drone_id}` | 详情、默认源和最后遥测摘要 | 授权用户只读 |
| `PATCH /api/v1/drones/{drone_id}` | 编辑、启停和默认引用 | 管理员 |
| `GET /api/v1/drones/{drone_id}/sources` | 查询脱敏数据源 | 授权用户只读；敏感字段最小化 |
| `POST /api/v1/drones/{drone_id}/sources` | 创建成对实时/本地源 | 管理员 |
| `PATCH /api/v1/drones/{drone_id}/sources/{source_profile_id}` | 编辑、启停或设为默认 | 管理员 |
| `POST /api/v1/drones/{drone_id}/sources/{source_profile_id}/validate` | 执行分项验证 | 管理员 |
| `GET /api/v1/flight-plans` / `POST /api/v1/flight-plans` | 查询/创建计划 | 只读 / 管理员 |
| `GET /api/v1/flight-plans/{id}` / `PATCH /api/v1/flight-plans/{id}` | 查询/编辑计划 | 只读 / 管理员 |
| `DELETE /api/v1/flight-plans/{id}` | 仅删除 draft；其他状态使用 retire | 管理员 |
| `POST /api/v1/flight-plans/{id}/enable` | 全量校验后启用 | 管理员 |
| `POST /api/v1/flight-plans/{id}/pause` | 暂停未来执行 | 管理员 |
| `POST /api/v1/flight-plans/{id}/retire` | 永久停止未来执行 | 管理员 |
| `GET /api/v1/flight-plans/{id}/occurrences` | 预览/查询执行窗口 | 授权用户只读 |
| `GET /api/v1/missions` / `GET /api/v1/missions/{id}` | 查询执行记录和详情 | 授权用户只读 |
| `POST /api/v1/missions` | 立即执行兼容入口 | 管理员 |
| `POST /api/v1/missions/{id}/stop` | 取消待执行或停止运行任务 | 管理员 |
| `POST /api/v1/missions/{id}/retry` | 从 failed Mission 创建重试 | 管理员 |

所有写接口支持统一错误结构，至少区分 `validation_error`、`forbidden`、`not_found`、`state_conflict`、`schedule_overlap`、`source_invalid`、`road_context_invalid`、`pipeline_start_failed` 和 `scheduler_unavailable`。最终字段、分页、错误码和 ETag/并发控制由 S9-TBD-005 冻结。

### 7.3 页面信息架构

`/drones` 保留现有路由并改为四页签：

1. **无人机**：设备列表、启用/在线状态、当前路口、最后遥测、默认源、当前 Mission。
2. **数据源**：实时/本地源、配对关系、默认标记、最近验证、脱敏错误和管理员操作。
3. **飞行计划**：日历/列表、once/weekly、未来窗口预览、冲突提示、启用/暂停/退役。
4. **执行记录**：Mission 筛选、计划/实际时间、启动偏差、状态、失败原因、pipeline 和专业页面深链。

页面必须区分“无人机离线”“数据源无效”“计划暂停”“Mission 失败”和“Pipeline 异常”，不得压缩成一个模糊红点。所有空态、无权限、过期、校验中和调度不可用状态提供文字解释。

## 8. 异常、降级与人工兜底

| 异常 | 系统行为 | 人工兜底 |
| --- | --- | --- |
| RTSP/MQTT 不可达 | 校验失败；计划不能启用或 Mission failed，返回脱敏错误码 | 运维检查网络、设备和 secret reference 后重新验证 |
| MP4/SRT 不存在或越界 | 拒绝保存/启用，不尝试绕过 allowlist | 将批准资产放入允许目录并重新登记 |
| MP4 不可解码或 SRT 不可解析 | 数据源 invalid，Mission 不启动 | 更换文件或修复解析兼容 |
| 视频与 SRT 覆盖不匹配 | valid 降为 degraded/invalid，按冻结阈值决定能否启用 | 核对原始视频、字幕和剪辑时间线 |
| 路网版本失效 | 禁止新启动并标记 `road_context_invalid` | 选择有效已发布版本或修复绑定 |
| 同无人机计划重叠 | 返回冲突计划和时间窗口，不保存为 enabled | 调整时间、暂停冲突计划或更换无人机 |
| 平台重启 | 当前窗口幂等恢复；错过窗口 skipped | 运维核对恢复报告，不手工补飞 |
| 多实例竞争 | advisory lock + 唯一约束只允许一个执行 | 重复尝试记录指标，不能产生第二 Mission/Pipeline |
| 数据库不可用 | 不创建新 Mission；调度健康 degraded | 恢复数据库后按当前/错过窗口规则补偿 |
| Pipeline 启动失败 | Mission failed，保存 stderr 脱敏摘要 | 修复依赖/配置后执行 retry |
| 本地视频提前结束 | 正常 completed，记录 `completion_reason=source_eof` | 无需人工处理；如属资产缺失则重新建任务 |
| 现场取消飞行 | 本系统不下飞控指令；管理员停止 AI Mission 并记录原因 | 作业人员在 DJI 平台执行飞行处置 |

## 9. 非功能、安全与可运维性

| 编号 | 要求 |
| --- | --- |
| S9-NFR-001 | 调度扫描周期不超过 5 秒；在数据库、PipelineManager 和源正常时，计划时间到 Pipeline running 的偏差 P95 ≤ 10 秒。 |
| S9-NFR-002 | `(flight_plan_id, scheduled_start_at)` 在并发、重启和重试下至多创建一个首次 Mission；重复启动数必须为 0。 |
| S9-NFR-003 | 所有计划、Mission 和管道状态可从 `road9` 恢复；PID、连接对象和流缓存不得序列化为业务真源。 |
| S9-NFR-004 | RTSP/MQTT 密钥、URL 用户信息、Token 和密码不得出现在 API 响应、审计详情、应用日志或错误堆栈。 |
| S9-NFR-005 | 本地路径经过 allowlist、realpath、文件类型和可读性校验；服务账户只授予批准目录只读权限。 |
| S9-NFR-006 | 写操作必须服务端鉴权、按授权路口校验并记录审计；前端隐藏按钮不构成安全控制。 |
| S9-NFR-007 | 调度、数据源校验、Mission 转换和 Pipeline 操作产生 `uav_system_metrics`，不得新增 InfluxDB/Grafana 目标链路。 |
| S9-NFR-008 | 调度指标至少包含 tick 延迟、锁竞争、due 数、started/completed/failed/skipped、启动偏差和重复抑制数。 |
| S9-NFR-009 | FlightPlan/Mission API 支持分页、过滤和稳定排序；容量按批准的无人机数、计划数和并发任务数压测。 |
| S9-NFR-010 | 时间计算使用 IANA timezone；UTC/本地时间转换、跨午夜和未来可能的 DST 场景由自动化测试固定。 |
| S9-NFR-011 | 删除仅允许 draft 且无 Mission 的计划；其他业务对象采用停用/退役并保留历史与审计。 |
| S9-NFR-012 | 数据源验证和 Pipeline 启停不得阻塞视频逐帧处理；调度故障不得修改运行中算法结果。 |

## 10. 验收指标与用例

验收以平台 API 端到端链路为最高测试接缝：**创建无人机和数据源 → 创建并启用计划 → 调度触发 PipelineManager → 视频/SRT 同步与遥测可查询 → 到时/EOF 停止 → Mission 状态可审计**。单元测试只补足时间窗口、路径校验和状态转换等无法稳定从高层覆盖的纯逻辑。

| 编号 | 前置/操作 | 通过标准 |
| --- | --- | --- |
| S9-AC-001 | 创建无人机、实时源和本地源 | 档案与多源可查询；默认源唯一；敏感字段脱敏 |
| S9-AC-002 | 校验可用 RTSP+MQTT | 分项结果 valid，记录耗时/时间；凭据不出现在响应和日志 |
| S9-AC-003 | 使用 `inter_xqh` MP4+SRT 创建本地源 | MP4 可解码、SRT 可解析、覆盖匹配并通过 allowlist |
| S9-AC-004 | 使用不存在、越界、符号链接逃逸或错误扩展文件 | 请求被拒绝，未读取越界内容，审计无敏感路径泄露 |
| S9-AC-005 | 创建 once 计划并等待执行 | 只创建一个 Mission；P95 启动偏差 ≤10 秒；关联 Pipeline running |
| S9-AC-006 | 创建 weekly 计划，含多星期、生效范围和例外日期 | 预览窗口正确；例外日 skipped；数据库 UTC 与页面本地时间一致 |
| S9-AC-007 | 创建 23:00—01:00 周期计划 | 结束时间落在下一自然日，冲突检测覆盖完整跨日窗口 |
| S9-AC-008 | 创建同一无人机重叠计划 | 启用被拒绝并返回冲突计划/窗口；不同无人机同路口允许 |
| S9-AC-009 | 暂停/编辑 enabled 计划 | 不再生成未来 Mission；运行中 Mission 及其快照不变 |
| S9-AC-010 | 在窗口内重启平台 | 恢复或关联唯一 Mission/Pipeline，不重复启动 |
| S9-AC-011 | 在窗口结束后重启平台 | Mission 为 skipped/window_missed，不补跑视频或调用飞控 |
| S9-AC-012 | 两个平台实例同时扫描同一窗口 | advisory lock 和唯一约束保证一个 Mission、一个 Pipeline |
| S9-AC-013 | 本地视频自然结束早于计划结束 | Mission completed/source_eof，Pipeline 已停止且无 error |
| S9-AC-014 | 注入 SRT 初始化、RTSP、MQTT、Pipeline 启动失败 | Mission failed，错误分类准确且可诊断，未静默成功 |
| S9-AC-015 | 管理员停止 running Mission | Pipeline 被优雅停止，Mission cancelled，操作者/原因有审计 |
| S9-AC-016 | 修复 failed Mission 后 retry | 创建新 Mission 并关联原 Mission；历史失败事实未被覆盖 |
| S9-AC-017 | 非管理员调用写接口 | 返回 403；只读数据按授权路口过滤 |
| S9-AC-018 | 打开 `/drones` 四页签 | 页面与 API 的档案、校验、预览、冲突、状态、原因和深链一致 |
| S9-AC-019 | 调用现有 `POST /missions` | 创建 `trigger_type=manual` 的立即执行 Mission，兼容当前调用方 |
| S9-AC-020 | 抽查数据库、API、日志和审计 | 自建对象使用 `uav_`；无明文凭据；任务/管道/遥测引用完整 |

前端验证复用现有 React Query/API 测试方式；平台验证复用 `platform/tests/test_pipeline_manager.py` 和 Drone Store/API 测试风格；本地端到端复用 `test_pipeline_inter_xqh.py` 资产，但其 56 PASS 基线不能替代本分册调度、权限和持久化验收。

## 11. 依赖、风险与待补充台账

### 11.1 依赖与风险

| 依赖/风险 | 影响 | 缓解 |
| --- | --- | --- |
| 无人机设备权威与本地档案关系未冻结 | 编码冲突、重复资产 | 只保存 UAV 所需配置并保留外部 ID；由 S9-TBD-001 冻结 |
| RTSP/MQTT 凭据管理未接入 | 凭据泄露或无法自动运行 | 先冻结 secret reference 接口，禁止明文落库 |
| `road9`/TimescaleDB 或 DDL 未就绪 | 无法恢复计划和执行 | 纳入 ADR-019 迁移门禁，不回退 InfluxDB |
| 多实例均可启动本机子进程 | 锁与执行节点可能不一致 | 冻结单实例/节点归属和调度租约模型 |
| 视频/SRT 剪辑时间线不一致 | 本地回放运动补偿错误 | 启用前做覆盖校验，保存 time semantics 和质量 |
| 服务器路径能力被滥用 | 任意文件读取 | allowlist、realpath、只读账户、权限和审计 |
| 计划被误解为真实飞行控制 | 运营责任混乱 | 页面统一称“AI 任务启停”，持续声明飞控边界 |

### 11.2 TBD 台账

| 编号 | 待补充内容 | 责任方 | 关闭依据 | 状态 |
| --- | --- | --- | --- | --- |
| S9-TBD-001 | 无人机设备 ID、序列号、外部资产 ID 的权威关系、唯一性和同步策略 | 主平台/无人机作业方/产品 | 批准的设备主数据与映射规范 | 【验收阻断】 |
| S9-TBD-002 | RTSP/MQTT 支持矩阵、认证方式、超时、网络区和 secret reference 接口 | 设备方/网安/架构/运维 | 联调接口与安全评审 | 【验收阻断】 |
| S9-TBD-003 | `UAV_LOCAL_ASSET_ROOTS`、文件权限、保留/清理、大小和允许格式 | 运维/网安/测试 | 本地资产运行规范 | 【验收阻断】 |
| S9-TBD-004 | MP4 与 SRT 时间/帧覆盖校验公式、容差、降级与拒绝阈值 | 算法/测试/设备方 | 批准的同步测试规范 | 【验收阻断】 |
| S9-TBD-005 | 内部 API schema、409/422/503、revision 已实现；正式分页、统一身份与版本批准 | 平台/前端/架构 | OpenAPI、契约测试与批准记录 | 【工程完成/正式批准阻断】 |
| S9-TBD-006 | ERD、DDL、空库/0002 升级已实现；生产 schema、对账、备份与回滚批准 | DBA/平台/架构 | `20260715_0003`、迁移测试和 DBA 批准报告 | 【工程完成/正式批准阻断】 |
| S9-TBD-007 | 5 秒调度、advisory lock、唯一约束和进程恢复已实现；生产节点归属、数据库故障和 HA 演练 | 架构/运维/平台 | 高可用设计与目标环境故障演练 | 【工程完成/正式批准阻断】 |
| S9-TBD-008 | 管理员、指挥员、分析员在设备/源地址/计划/Mission 上的字段和数据权限 | 产品/统一身份/网安 | 权限矩阵与渗透测试 | 【待确认】 |
| S9-TBD-009 | 计划、Mission、审计和数据源验证记录的保留期及删除/退役规则 | 产品/网安/DBA | 数据保留与删除制度 | 【待确认】 |
| S9-TBD-010 | 无人机规模、计划数量、并发 Pipeline、调度 tick 和 API 性能验收环境 | 项目经理/架构/测试 | 容量模型与性能报告 | 【待确认】 |
| S9-TBD-011 | `/drones` 四页签视觉原型、日历形态、移动/大屏适配和可访问性 | 产品/设计/前端 | 批准原型与 UI 验收 | 【待补充】 |
| S9-TBD-012 | 现有内存 DRONES/MISSIONS、立即执行调用方和历史任务的迁移/兼容期限 | 平台/运维/产品 | 迁移清单、灰度和退役记录 | 【验收阻断】 |

### 11.3 进入开发与上线门禁

- 内部开发所需的 S9-TBD-004/005/006/007 工程基线已冻结；S9-TBD-001/002/003 及正式批准未关闭时仅允许受控开发/测试，不得进入生产验收。
- 进入联调前完成 RTSP+MQTT 与 MP4+SRT 两类源契约测试、`road9` migration 和权限矩阵。
- 上线前必须通过 S9-AC-001~020、重启/多实例故障演练、凭据扫描和现有 Mission 兼容回归。
- 任一计划窗口出现重复 Mission/Pipeline、明文凭据泄露、路径逃逸或错误时间补跑，均为阻断上线问题。

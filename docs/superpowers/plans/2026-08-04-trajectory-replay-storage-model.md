# 交通轨迹真实复盘与存储治理计划

> 状态：Replay V2 shadow 实现与五源原生 MPS 工程验收已完成，仍停在正式切换门前；未获单独批准前不改名、不覆盖 canonical 表/Topic。本文记录 2026-08-04 至 2026-08-05 已确认的领域边界、接口、存储策略、实现结果与验收证据。

## 1. 目标与当前证据

目标是在路口悬停和路段巡航两类采集模式下，真实记录并复盘车辆行驶、停车、队列形成与释放、启动、掉头等行为，同时控制 Kafka 与 `road9` 的持续增长。

当前实现存在两类结构性问题：

- 轨迹分析按固定约 1.4 秒切换时间片，未按逐点事件时钟推进；PostgreSQL 轨迹点缺少逐点速度，无法同源还原时间、位置和业务速度。
- 2026-08-04 本机快照中，`uav_traffic_metrics` 约 51GB，`uav_track_points` 约 6GB。主要放大来自周期 Stats 携带轨迹尾迹、消息向多粒度行展开，以及完整 payload 在 inbox、指标行、轨迹摘要和逐点事实间重复，而不是轨迹点类型列本身。

本计划只证明系统产出事实可复现。没有外部批准真值时，IDF1、HOTA、正式 ID switch、位置 RMSE、速度 MAE 和 ReID 归并准确率均保持 `not_evaluated`，不得从轨迹观感、数量或 IoU 推导。

## 2. 领域模型与真实复盘口径

### 2.1 五层事实

1. **Mission/Source 时间轴**：保存任务、素材、飞行阶段、模型、算法与参数版本；统一以任务源开始时刻为 `T+0`。
2. **Runtime Track**：ByteTrack 形成的连续图像身份；遥测、世界坐标或地图质量不得改变其身份。
3. **TrackPoint**：回放唯一位置事实，保存相对时间、源帧号、像素坐标、可空 ENU/GCJ-02、质量谱系和封存速度。
4. **Episode/Maneuver**：从完整点序列派生 `moving`、`stopped`、`releasing`、队列、掉头等有起止时间的状态或动作，不反向修改轨迹点。
5. **Traffic Aggregate**：5 分钟流量、速度、停车、队列、转向和质量统计；可按版本重算，不携带完整轨迹尾迹。

### 2.2 回放时钟与画面

- 第一阶段只建设轨迹时钟，不同步播放原视频。
- 所有车辆共享 Mission 的 `T+` 相对时钟，默认全任务同步回放；筛选单车不改变公共时间轴。
- 只展示持久化的实采点，不做位置插值。正常短间隔采用 sample-and-hold；超过任务记录的跟踪断点阈值时隐藏标记，不跨缺口连线。
- 缺少可信 ENU 的点继续按像素位置回放，世界位置和速度为 `null`，并返回明确质量原因。
- 回放倍速只压缩显示时间，不改变车辆业务速度。

### 2.3 事件保真抽样

轨迹结束后，先在完整处理帧序列上完成速度和行为计算，再选择原始实采点持久化；不得生成插值点。

采用已确认的“均衡”包线：

- 首点、末点、状态变化、质量变化、坐标有效性变化、道路匹配变化和 Maneuver 边界强制保留。
- 运动段最长 500ms 必须保点；相对原系统轨迹的折线偏差达到 0.5m或航向变化达到 10°时提前保点。
- 停车段每 2 秒保留一个真实心跳点，并保留停车进入、退出点。
- 每条轨迹保存 `source_point_count`、`retained_point_count`、抽样算法版本和包线参数，回放接口显式返回抽样质量。

### 2.4 速度、停车、队列与掉头

- 速度按任务记录的算法版本计算。当前基线为最近最多 15 个可信 ENU 点的时间线性回归，并以窗口 5 做 EMA。
- 完成轨迹使用完整点序列重算后，把瞬时速度、ENU 速度向量和 EMA 业务速度封存到保留点；查询不得再用稀疏点改变业务速度。主画面显示 EMA，详情显示瞬时值、向量、算法版本和质量。
- `stopped` 采用低速、位移和迟滞联合规则：EMA 不高于 2km/h 且 2 秒内位移不超过 1.5m 才进入；速度不低于 5km/h 持续 1 秒或位移明显扩大后退出。参数随算法版本固化。
- 没有可靠车道、停止线或路口拓扑时只记录 `stopped`，不得正式判定 Queue。
- 有可靠道路上下文时形成 `standing_queue` 和 `queue_release`。没有权威信号相位时，可从车流形成与释放模式推断 `inferred_red_signal_queue`，但必须单列数量、置信度和算法版本，不得与未来的 `verified_red_signal_queue` 相加。
- 正式几何掉头使用 `geometric_u_turn`：关键段 ENU 有效率至少 80%、累计转向至少 135°、转向前后各行驶至少 3m、反向保持至少 1 秒且无时间断点。它不等同于经道路法规语义确认的掉头流向。

### 2.5 跨片段身份归并

- 不放宽在线 ByteTrack，也不让世界坐标参与在线图像身份关联。
- Mission 自然 EOF 后运行运动约束与轻量 ReID/外观向量联合的离线归并；只接受唯一高置信一对一匹配，歧义片段保持分离。
- 在线消息使用稳定 `runtime_track_id`；任务封存后，对外历史 API 的 `track_id` 表示归并后的任务内车辆行程身份。
- 内部必须保留 `source_runtime_track_ids`、匹配分数、证据摘要、模型和算法版本，不能物理覆盖原 Runtime Track。普通界面只展示最终 `track_id`。
- ReID 向量和临时车辆裁剪图仅在任务归并期使用；归并完成后删除，只保留版本、分数和来源映射。没有外部身份真值时只声明工程门禁，不声明归并准确率。

## 3. Kafka、PostgreSQL 与 DWS 落地

### 3.1 Kafka 消息瘦身

- 相机 Topic 身份绑定稳定 Source/Camera，不再按 Pipeline 启动时间生成新 Topic；同一来源反复回放不得制造 Topic。
- Stats 只携带当前类型化指标和必要的当前点，不携带 active/candidate 完整尾迹；完成轨迹只在终止时发布一次事件保真点列。
- 生产者启用 Zstd；使用稳定 `message_id`、持久 spool/outbox 和 Platform inbox 保持至少一次交付与幂等。
- 本地 Kafka 默认保留 6 小时且每分区最多 256MiB；UAT 为 24 小时/1GiB；生产为 24 小时/4GiB。冲突与证据引用遵循独立审计策略。

### 3.2 原子事实表

- `uav_track_points` 使用类型列保存相对毫秒、帧号、像素、可空 ENU/GCJ-02、瞬时/EMA速度、速度向量、点质量和抽样边界；不在每点复制完整消息 payload。
- `uav_track_events` 只保存完成摘要、最终 `track_id`、来源 Runtime Track 映射、行为摘要和质量，不再复制完整轨迹数组。
- 新增类型化 Episode/Maneuver 事实，保存起止 offset、状态/动作、版本、质量和证据引用；不得使用通用大 JSON 代替稳定查询列。
- `uav_message_inbox` 保留消息哈希、Topic/partition/offset、状态和紧凑事实引用；完整 payload 只在确有审计需要的消息类别保留一次。

### 3.3 `uav_traffic_metrics` 的 DWS 设计

采用已确认的方案 A：只参考服务器 `ycx.xianchang.dws_inter_evaluation_5min_mm` 的窄表、类型列、5 分钟槽位和复合键设计；`road9` 独立计算，不在运行时查询、复制或依赖服务器 DWS。

- 增加短保留的 `uav_traffic_metric_samples`，只保存生成 5 分钟聚合所需的类型化秒级样本与覆盖率，不携带轨迹数组或完整 payload。
- 将 `uav_traffic_metrics` 收敛为实际日期的路口 5 分钟 DWS，唯一粒度为 `window_start + inter_id + source_profile_id + mission_id + calc_version`；保存 `window_end`、流量、均速/P85、停车数量/时长、队列长度、释放数量、几何掉头数量、推断红灯队列数量/置信度及样本覆盖质量。
- Link、Lane 和 Turn 使用独立窄 DWS 表，不再用 `grain_type` 把一条大 Stats payload 展开并复制到多个粒度行。
- 增加派生的 `uav_inter_evaluation_5min_mm`，按 `inter_id + source_profile_id + day_of_week + step_index + profile_version` 形成典型时段矩阵。它只服务典型态势和历史对比，不参与真实轨迹回放。
- `day_of_week/step_index` 只存在于典型矩阵；实际 5 分钟事实必须保留 `TIMESTAMPTZ window_start`、Mission/Source 谱系和算法版本。
- 饱和度、服务水平和不均衡指数只有在车道容量、有效流量和算法版本齐备时计算，否则为 `null + reason`。不得照搬外部表数值或把其 `turn_count` 解释为掉头车辆数。

### 3.4 压缩与保留

- Timescale 列存/压缩：本地 1 天后；UAT 的 Stats/Telemetry 7 天、TrackPoint 14 天后；生产的 Stats/Telemetry 7 天、TrackPoint 30 天后。
- 本地：5 分钟 Stats 7 天、Telemetry/System 7 天、Track/Event 30 天、Inbox 2 天。
- UAT：5 分钟 Stats 30 天、Telemetry 30 天、Track 180 天、Inbox 7 天。
- 生产：5 分钟 Stats 180 天、Telemetry 90 天、Track 365 天、Inbox 30 天；1 分钟/5 分钟长期聚合保留 2 年。
- 冲突、证据、审计、原始 MP4/SRT 不套用通用自动删除策略。删除旧卷、旧 Topic 或历史事实必须另获明确授权。

## 4. API 与 Console 契约

- 新增 `GET /api/v1/trajectories/{intersection_id}/replay-missions`，默认只列 sealed Mission；`include_incomplete=true` 只用于管理员诊断。
- 新增 `GET /api/v1/trajectories/{intersection_id}/replay`，强制要求 `mission_id`；支持 `cursor_sec`、`window_sec`、`max_points`、`track_id` 和行为/分类/流向筛选。
- 响应版本为 `uav.trajectory-replay/v1`，返回任务时长、T+游标、最终 `track_id`、内部可审计 Runtime Track 引用、逐点 offset/frame/位置/速度/质量、Episode/Maneuver、抽样信息和截断信息。
- Console 使用单一事件时钟推进全任务轨迹；不自行计算速度、世界坐标、停车、排队或掉头，不跨缺口绘线。
- DWS API 查询实际 5 分钟窗口；典型时段 API 单独查询 `*_5min_mm`，不得把典型值伪装成当前实况。

### 4.1 产品链路硬隔离

- `实时监测 → BEV` 只消费当前 Pipeline 的实时 active/completed/candidate 轨迹；不请求 Replay V2 API、不选择 Mission、不创建回放时钟，也不读取 sealed journey。
- `智能研判 → 轨迹回放` 只消费自然 EOF 后 sealed 的 Mission。默认选择最新 sealed Mission；“全部 Mission”只做汇总，播放和时间轴禁用，禁止跨任务伪回放。
- `/gis` 保留原有页面结构。世界坐标存在时走现有高德地图；否则切换像素平面，仍计为可回放，空间覆盖率单独显示。

## 5. 实施顺序与验收

1. 先增加会失败的契约和领域测试，锁定时间、点列对齐、抽样包线、速度封存、状态迟滞、缺失世界事实和 DWS 唯一粒度。
2. 实现轨迹完成封存器、Episode/Maneuver 和离线归并；在线 ByteTrack、逐帧世界事实所有权及能力门禁保持不变。
3. 在隔离的新 Compose project、端口和卷上创建新 schema、压缩/保留策略及 Kafka 配置；不得在原 51GB 表上原地破坏性改造。
4. 实现紧凑 Kafka 契约、事务写入、5 分钟 DWS 和典型矩阵，再切换回放 API 与 Console。
5. 使用原生 macOS/MPS，从原素材重建五个业务位置：
   - `SRC-INTER-XQH-0403-PM`
   - `SRC-MP4NEW-HY-0625-AM`
   - `SRC-MP4NEW-LS-0625-AM`
   - `SRC-MP4NEW-CH-0625-AM`
   - `SRC-MP4729-JS-0729-3MS`
6. 每源必须达到自然 EOF、Kafka/road9 精确对账、轨迹点/时间/速度/质量同索引、停车/启动/掉头场景回归、缺失 ENU 不伪造、地图不改世界事实和浏览器可见回放门禁。
7. 容量门禁至少包含：Topic 数量不随重复 Pipeline 增长；Stats 消息不携带轨迹尾迹；事实行不重复完整 payload；新旧同源回放的 PG/Kafka 字节量、行数和查询延迟形成对照；保留策略和压缩策略在目标 Timescale 版本实测生效。
8. 全部门禁通过后再切换读写。旧数据库、Kafka Topic 和卷保持离线只读，删除另行审批；失败时回退读路径，不回写旧事实。

## 6. 明确不做

- 不把服务器 `ycx.xianchang` DWS 作为 UAV 运行时依赖，也不定期复制其数据到 `road9`。
- 不用当前标定重算历史世界坐标，不让地图吸附改写轨迹。
- 不用插值点或稀疏点二次重算替代完整序列速度。
- 不把 `stopped` 自动等同于 Queue，不把推断红灯等同于权威信号相位。
- 不在无真值条件下宣称生产身份、位置、速度或掉头准确率。

## 7. 2026-08-04 至 2026-08-05 shadow 实现与门禁状态

- 工作树/分支：`/Users/yaoyao/.codex/worktrees/611d/TrafficAnalyzer` / `codex/trajectory-replay-v2`；大文件只引用主工作树绝对路径，spool/证据写 `/private/tmp/traffic-analyzer-replay-v2-*`。
- Kafka：使用 `uav_replay_v2_{statistics|track_complete|conflicts|telemetry|mission}_{source_key}`，消费者组固定 `uav-platform-replay-v2`；旧 canonical 正则不匹配。
- PostgreSQL：独立 `uav_replay_v2_alembic_version`，当前 head `20260805_rv2_0003`；V2 秒级指标为 Timescale hypertable，7 天后压缩、90 天后保留清理。sealed Mission 完整到达后幂等重建 intersection/link/lane/turn 真实 5 分钟聚合和独立典型矩阵；canonical revision、核心事实表行数和 schema checksum 在迁移前后未变。
- 本机 shadow：Platform `8200`、Console `5273`、视频端口从 `18101` 起；`replay_v2` profile 不启动 Mission 调度、survey、告警同步等控制面写入，非认证变更接口返回 405。
- 五个 SourceProfile 已以 `frame_stride=14`、`imgsz=640`、独立 Mission/Run/Pipeline 串行跑到自然 EOF：合计 1,966 条 Stats、6,539 条最终 journey、6,088 条遥测和 5 条 sealed Mission，294,387 个源点/保留点的字段对齐失败为 0；每源 Kafka 与 V2 PG 均精确对账，Stats 未携带完整轨迹尾迹。
- V2 表当前约 201,400,320 bytes；消息 P95 分别为 Stats 14,083 bytes、journey 50,845 bytes、telemetry 1,473 bytes。15 次 `30s/20,000 points` 回放查询中位数 1,767.700ms、P95 2,769.671ms；这是本机 shadow 容量/延迟证据，不是生产 SLA。
- 五个稳定来源共 25 个 V2 Topic；重复 `ensure_topics` 两次均返回空，复跑不增加 Topic。验收中发现并修复 `TccEvidencePublisherNode` 曾绕过 V2 选择器写入 5 条 canonical conflict 的问题；精确保留清理 manifest 后回收 5 条 conflict/inbox 和两个仅由 V2 创建的错误 Topic，实际探针已证明冲突进入 V2 Topic/表。最终 canonical 仍为 `292244/19493/902896/102406/36245/103`，`pipe-rv2-*` canonical conflict 为 0，五个预留 canonical Topic 为 0。
- 完整证据为 `/private/tmp/traffic-analyzer-replay-v2-five-source-batched-20260805/summary.json`。Shadow 工程门禁已通过；正式精度仍统一为 `not_evaluated`，正式切换仍须单独破坏性批准。
- 最终自动化门禁为根测试 `235 passed`、Platform `280 passed / 5 skipped / 10 subtests`、Console2 `184 passed`、XQH `55 PASS / 0 FAIL / 1 WARN`、Console production build 与 `git diff --check` 通过；ADR-019 strict 仅保留既有 `local_runtime_evidence` 外部门禁。

### 2026-08-05 XQH 全长补充验收

- Mission `MSN-RV2-a863b59ca9f1` 使用主工作树绝对视频/权重、`frame_stride=10`、原生 MPS 跑到自然 EOF；992.325 秒源时间、1,443 runtime segment、64,444 原始点封存为 1,427 journey，正式精度继续全部 `not_evaluated`。
- Kafka/PG 精确对账为 700 Stats、1,427 journey、3 conflict、2,372 telemetry、1 sealed Mission；Stats 无完整尾迹、点数组对齐失败 0、canonical Topic 写入为空。四类实际聚合为 `10/32/114/23`，典型矩阵 10。
- 首次运行器汇总因只等待消息而未等待聚合事务，并发现无 movement key 时 turn 粒度为空，正确判 FAIL；修复为聚合收敛等待并用 `turn_behavior:*` 显式降级后，同一 sealed Mission 复验通过。原 FAIL 与 postfix PASS 分文件保留在 `/private/tmp/traffic-analyzer-replay-v2-xqh-full-20260805-v4`。
- 当前门禁为根 `241 passed`、Platform `291 passed / 6 skipped / 10 subtests`、PG 集成 `1 passed`、Console `185 passed`、XQH `55 PASS / 0 FAIL / 1 WARN` 和 production build；ADR-019 strict 仍只有既有外部 `local_runtime_evidence` blocker。正式切换未执行。

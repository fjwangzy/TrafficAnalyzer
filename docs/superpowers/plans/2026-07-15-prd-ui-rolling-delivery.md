# 无人机交通 AI PRD/UI 滚动交付计划

> 状态：本地工程收尾完成；正式验收等待外部输入  
> 建立日期：2026-07-15  
> 基线分支：`codex/2.0`  
> 基线提交：`fad252f`  
> 上位文档：`docs/generated/2026-06-29-uav-traffic-ai-prd.md` v2.1

## 1. 整体目标

将 S1～S9 从“PRD 评审草案 + 部分 UI 原型 + 遗留运行链路”滚动推进为可追溯、可运行、可验收的无人机交通 AI 子项目：

1. 业务状态、时序指标和执行事实以 PostgreSQL database=`road9` + TimescaleDB 为目标真源。
2. UAV 内部 Topic、`msg_type`、WebSocket channel 和本项目自建表统一使用 `uav_` 前缀。
3. Console2 正式路由不直接依赖 `mockData`，所有未知、缺失、过期、降级和无权限状态如实显示。
4. S1～S9 每项需求均可追溯到页面、接口、数据/消息、测试和验收证据。
5. 旧 InfluxDB/Telegraf/Grafana 链路在迁移对账、回滚演练和观察期通过后退役。

工程完成与正式验收分开管理。工程可以交付真实闭环；精度、法制、主平台、权威路网和合同偏差等外部事项必须取得书面关闭依据，不能由代码测试替代。

## 2. 当前基线与追踪矩阵

| 分册 | PRD/产品状态 | 当前实现 | 下一验收接缝 |
| --- | --- | --- | --- |
| S1 路口态势 | 详细评审草案，业务阈值待冻结 | 检测管道、实时监控、TimescaleDB 指标事实和 `road9` 历史查询已真实化 | 冻结正式指标/质量阈值，完成历史 Influx 对账和生产容量/保留验收 |
| S2 冲突识别 | 规则、验收集和合同偏差待关闭 | 冲突算法、`inter_xqh` 基线、冲突事实、GIS/事件历史查询和技术复核已真实化 | 冻结规则/验收集，完成历史对账、主平台处置映射和生产验收 |
| S3 事故测绘 | 工程闭环完成，正式验收阻断未关闭 | PostgreSQL、worker、量算、报告、UI 和真实全量材料验证已完成 | 仅处理正式精度、法制、签章、归档、主平台合同及增量缺陷 |
| S4 执法检测 | 本地工程闭环完成，规则/法制/雷达/权威发布待关闭 | candidate 围栏/规则、统一 AI 线索、证据哈希、技术复核和 Console2 三视图已真实化 | 关闭批准规则、雷达、法制证据、权威围栏和主平台合同；不得把本地 fixture 当真实违法检测 |
| S5 路网共性 | 内部接口已冻结，外部权威合同阻断 | RoadContext、snapshot/binding DDL 和 fixture/road9 Adapter 已实现 | 取得权威视图、坐标和版本合同后替换 Adapter，推进 I3 地图匹配 |
| S6 主平台集成 | 内部接口已冻结，外部主平台合同阻断 | EventDelivery 与统一 event/outbox/attempt/feedback/dead-letter DDL 已实现；外部 Adapter 禁用 | 冻结正式传输/认证/schema/SLA 后联调，不模拟成功 |
| S7 质量运营 | 最后汇总冻结 | 本地目标栈、迁移/恢复/故障/性能/短时巡检和退役审计已实现 | 冻结生产阈值、持续运行、灾备、试点、主平台联调和退役批准 |
| S8 全域工作台 | 信息架构已冻结，核心口径待批准 | DashboardReadModel、四类聚合 API、真实 OSM 点位门禁和全状态 UI 已实现；正式 `/` 不读 Mock | 冻结项目范围/KPI/底图/权限并完成获批数据下的 5 秒/30 秒主任任务验收 |
| S9 飞行任务 | 工程闭环完成，正式验收阻断未关闭 | `road9` 持久化、MissionOrchestrator、canonical Topic、四页签与真实 MP4+SRT 已完成 | 关闭设备/RTSP/MQTT/权限/容量/生产 HA 外部门禁 |

## 3. 模块、接口与接缝

后续实现按深模块组织，页面和业务调用方只依赖下列接口，不直接拼接数据库、消息或外部平台细节：

| 模块 | 对调用方暴露的接口 | 隐藏的实现复杂度 | Adapter |
| --- | --- | --- | --- |
| RoadContext | 按 `inter_id + road_data_version` 读取不可变上下文和质量状态 | 权威源读取、版本快照、checksum、缓存、坐标语义、视觉绑定、降级 | `road9` 只读 Adapter；测试 fixture Adapter |
| MetricStore | 写入 canonical 指标/轨迹/冲突事实并按时间窗口查询 | inbox 幂等、TimescaleDB hypertable、空值/Decimal/时间语义、迁移对账 | TimescaleDB Adapter；测试数据库 Adapter |
| EventDelivery | 记录 AI 事件、投递到期事件、应用回执/反馈 | outbox、attempt、dead-letter、重试、幂等、payload hash、外部等级映射 | 主平台 HTTP/Kafka Adapter；测试 Adapter |
| MissionOrchestrator | 管理计划、生成执行、停止/重试并查询审计结果 | advisory lock/租约、时间窗、冲突校验、状态机、PipelineManager、重启恢复 | PipelineManager Adapter；测试 Adapter |
| DashboardReadModel | 读取 overview、地图摘要和单路口详情 | 权限过滤、统一 `as_of`、覆盖率、重点排序、缓存、部分来源降级 | PostgreSQL/TimescaleDB 查询 Adapter；测试 Adapter |

接口是调用方和测试的共同验证面。内部重构不得要求 Console2 理解存储表、Topic 推导、重试或外部平台协议。

## 4. 滚动迭代

### I0：基线统一与可追溯计划

**入口**：`fad252f` 基线可构建、可测试。  
**交付**：统一分册上位 PRD 版本；建立本计划和 S1～S9 追踪矩阵；在 `docs/TASKS.md` 建立迭代状态入口。  
**验证**：文档链接有效；目标/现状/迁移基线不混写；Console2、Platform 基线保持通过。  
**退出门禁**：后续任务均能归属唯一迭代和验收接缝。

### I1：S5/S6/S9 最小契约与 ADR-019 迁移设计

**入口**：I0 完成。  
**交付**：

- 输出 `road9` 对象归属/迁移矩阵，冻结权威路网逻辑视图、RoadContext shape、SRID/GCJ02 和版本语义。
- 冻结 AI 事件、outbox、attempt、dead-letter、feedback 的状态与最小字段。
- 冻结 Drone、视频源、遥测源、FlightPlan、Mission、Pipeline 的 ERD、状态机、权限和恢复语义。
- 固定 TimescaleDB 延后到 I3 安装验证；版本、chunk、压缩、保留、连续聚合和备份恢复未经 DBA 批准不固化。

**验证**：`docs/API_CONTRACTS.md`、`docs/DATABASE_SCHEMA.md`、S5/S6/S9 分册一致；候选值仍标记候选；所有外部决定有负责人、截止时间和关闭依据。  
**退出门禁**：DDL/migration 和模块接口可直接实施，无重复真源或未决字段命名。

### I2：S9 真实飞行任务闭环

**入口**：I1 的 S9 ERD、权限和调度语义冻结。  
**交付**：受控 migration；持久化 Drone/Source/FlightPlan/Mission/Pipeline；≤5 秒调度扫描；advisory lock/租约；停止、重试、EOF 和重启恢复；Console2 `/drones` 四页签真实接线。  
**验证**：`inter_xqh` MP4+DJI SRT 覆盖 once/weekly、跨午夜、例外日、重叠拒绝、多实例去重、失败、停止/重试和非管理员 403。  
**退出门禁**：重启不丢计划/执行事实，同一窗口不产生重复 Mission/Pipeline。

### I3：S1/S2 时序持久化与研判闭环

**入口**：MetricStore、RoadContext 和 EventDelivery 接口可用。  
**交付**：canonical `uav_` 消息；inbox + 手动 offset；指标/轨迹/冲突写入 TimescaleDB；历史接口切读 `road9`；事件中心、GIS 回放和技术复核真实化。  
**验证**：单元/契约/崩溃点/重放/空值/时间语义测试；`inter_xqh` 56 项基线；旧/新存储数量、时间桶、关键聚合和抽样事件对账。  
**退出门禁**：页面、REST、WebSocket 与数据库值及质量状态一致，遗留写入可进入停写观察期。

### I4：S4 执法线索闭环

**入口**：S4 规则、围栏、证据、雷达依赖和主平台映射冻结。  
**交付**：候选/批准/退役围栏；货车/非货车二分类规则；线索详情；证据不可变引用；技术复核和 EventDelivery 接入；Console2 执法三视图真实化。  
**验证**：命中、例外、低质量、无坐标、规则版本切换、证据缺失、重复投递和权限测试。  
**退出门禁**：系统只输出 AI 线索，不产生违法认定、处罚或案件状态。

### I5：S8 全域态势真实首屏

**入口**：S1/S2/S3/S4/S9 可提供稳定事实，S8 核心口径冻结。  
**交付**：DashboardReadModel；overview/intersections/detail/drones 接口；真实地图点位；KPI、重点榜、待办、保障和质量状态；移除正式路由 Mock。  
**验证**：正常、空态、过期、断线、底图失败、坐标异常、部分来源失败、无权限、大屏和办公端；5 秒辨识全局、30 秒定位重点；关键截图入库。  
**退出门禁**：前端不重新计算业务口径，不使用 `0` 代替缺失，不用随机/数组位置冒充真实坐标。

### I6：S7 总体验收与迁移退役

**入口**：I2～I5 工程闭环完成，外部阻断进入正式关闭。  
**交付**：统一数据集和标注方案、业务/算法/性能阈值、故障注入、灾备、RPO/RTO、试点、运营手册、迁移对账、旧链路退役和发布回滚方案。  
**验证**：全量自动化、真实材料、主平台联调、性能与持续运行、备份恢复、权限与审计、视觉验收。  
**退出门禁**：总 PRD 第 14 章阻断逐项关闭，发布清单与实际部署一致，InfluxDB/Telegraf/Grafana 无新增写入且可安全移除。

## 5. 滚动执行规则

1. 同一时间只允许一个主迭代处于 `执行中`；可并行做不改变其契约的 UI 探索，但不得将候选值写成生产默认。
2. 每轮开始重新检查工作树、分支、数据库 migration、TimescaleDB 扩展和外部依赖；保留并合并用户现有修改。
3. 每个垂直切片按“PRD/口径 → 接口/DDL/消息 → 后端 → Console2 → 自动化 → 真实链路 → 浏览器状态与截图 → 文档”闭环。
4. 每轮退出时同步实际受影响的总 PRD/分册、`API_CONTRACTS`、`DATABASE_SCHEMA`、`ARCHITECTURE`、`TASKS` 和视觉验收记录。
5. 验收失败或外部决定缺失时，保持 `unverified/blocked`，记录责任人、所需证据和下一可执行动作，不伪造成功。
6. I0 完成后，滚动状态转入 I1；后续每完成一轮，将本文件状态、证据链接和下一轮风险一并更新。

## 6. 当前滚动状态

| 迭代 | 状态 | 最近证据 | 下一动作 |
| --- | --- | --- | --- |
| I0 | 已完成 | 基线 `fad252f`；分册引用统一为总 PRD v2.1；Console2 43/43；Platform 41 + 11 subtests | 保持追踪矩阵和 TASKS 状态同步 |
| I1 | 已完成（内部工程契约） | RoadContext、EventDelivery、MissionOrchestrator；migration `20260715_0003`；API/DDL/状态机一致 | 外部权威路网与主平台合同保持 blocked |
| I2 | 已完成（工程闭环） | PG 调度并发/重启/停止/EOF/error 集成通过；另从 Console2 页面在本地 `road9@20260715_0009` 登记源、启用 once 计划并由调度器触发 `MSN-5A61F57DA1D7`，396.663 秒后自然写入 `completed/source_eof`；四页签及截图；`inter_xqh` 56/0/0 | 生产 RTSP/MQTT、权限、容量和 HA 进入正式专项验收 |
| I3 | 已完成（本地工程闭环） | Alembic `20260715_0004`～`0007`；TimescaleDB 2.28.2/PG17 隔离验证；5 张 hypertable、MetricStore、inbox/事实幂等、输入死信、手动 offset；历史 API 与 `/gis`、`/events` 真实切读和技术复核 | 生产版本/容量/保留/压缩/HA、历史 Influx 对账和正式 S1/S2 指标仍保持 blocked |
| I4 | 已完成（本地工程闭环） | Alembic `20260715_0008`；EnforcementService；candidate zone/rule、统一事件、通用证据、技术复核审计；Console2 `/enforcement/**` 真实切读；真实 MP4/SRT 哈希工程样本和权威发布 503 门禁 | 批准规则、权威围栏、雷达/检定/融合、法制证据、统一身份和主平台合同仍 blocked；滚动进入 I5 |
| I5 | 内部工程完成 / 正式验收阻断 | DashboardReadModel、4 个聚合 API、正式 `/` Mock 清除、KPI null/WGS84 门禁、服务端筛选/bbox/分页、422/503、底图失败降级、45/45 前端测试和真实阻断态截图 | 项目范围/底图/KPI/权限、点位聚合/全局增量回补、获批正常/混合状态及 5 秒/30 秒正式验收仍 blocked |
| I6 | 本地工程完成 / 正式验收阻断 | `uav.adr019-retirement-audit/v1` 为 12 pass / 6 blocked；完整 `road9 + Apache Kafka KRaft + Platform + Console2` 目标栈构建/强 readiness/代理登录/API 通过，目标镜像无 Influx 客户端；空库/回滚 migration、`0009` 完整性触发器、Timescale-aware 备份恢复、三类 Influx measurement 只读盘点、80/80 localhost 只读请求、隔离 `200→503→200` 断库恢复和 60 秒/13 样本 readiness 巡检通过 | 等待批准并执行生产镜像/秘密/TLS/SASL/HA、性能阈值/批准时长的持续运行、正式 RPO/RTO、历史字段/时间映射与回填对账、试点、主平台联调和旧链路退役 |

## 7. 阶段收尾（2026-07-15）

- I1～I6 的本地可实施工程项停止继续扩张，后续仅处理明确缺陷或已获得批准输入的正式验收项。
- 最终本地门禁为 Platform `76 passed / 5 skipped / 11 subtests`、Console2 `45/45` 与生产构建、根目录轻量及 EOF `10 passed`、`inter_xqh` `56 PASS / 0 FAIL / 0 WARN`、`git diff --check` 通过。
- S9 页面触发证据见 `console2/design-qa.md` 的“Page-triggered retained screenshots”和 `docs/TASKS.md` T-449；截图保存在本机 `console2/.design-qa/`，不假定由 Git 管理。
- 本阶段没有关闭任何权威路网、正式精度/法制、主平台、生产参数、历史对账、试点或安全退役阻断项；总体状态继续为 `blocked_external`。
- 下一阶段从外部批准清单中选择唯一主线；若继续产品/UI，应优先使用已冻结契约补齐获批数据状态和正式任务验收，不新增 Mock 或候选生产默认值。

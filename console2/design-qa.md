# Console 2 全流程测试验收记录

## Evidence

- execution date: `2026-07-14`
- implementation routes: `/login`、`/`、`/monitoring`、`/gis`、`/events`、`/survey/**`、`/enforcement/**`、`/drones`、`/admin/**`
- browser evidence: `output/playwright/console2/`
- verified viewports: `1366×768`、`1440×900`、`1920×1080`
- account: Platform `admin`（JWT 存于 `sessionStorage:uav_access_token`）
- environment: Platform `127.0.0.1:8000`，Console2 `127.0.0.1:4173`

## Acceptance Result

功能与视觉主流程条件通过，生产全量验收仍阻断于 Kafka 健康误报及本轮未具备的完整 Kafka/TimescaleDB 目标链路环境。

- 16 个正式路由全部返回 200，页面标题、认证守卫与统一两级导航正确。
- 四个关键真实模块在三档分辨率下均无页面级横向溢出或主要内容裁切。
- 登录、监控、事件复核、测绘、执法、飞行任务、标定、集成交付和系统身份主流程均完成点击级验证。
- 原“浏览器运行时无法建立连接”的 P0 已关闭。

## Findings

### [P1] Kafka 降级状态被健康接口误报为正常

- Location: `platform/app/api/v1/system.py:35`、`platform/app/api/v1/system.py:102`、`console2/src/pages/AdminPages.jsx:223`。
- Evidence: Platform 持续记录 `Unable connect to kafka:9092`、`running in degraded mode`；但 `/api/v1/system/health` 返回 `kafka_connected: true`，`/system/kafka/consumers` 返回 `state: Stable, members: 1`，系统页显示“UAV 消息链路 健康 / connected”。
- Cause: 健康判断使用 `_running`；该字段表示重连循环仍运行，不表示 `_consumer` 已连接。
- Impact: 指挥和运维人员会把实时数据中断误判为正常，属于上线阻断。
- Suggested fix: 暴露独立连接状态或以有效 consumer/最近成功消费时间判定；topics/consumer API 同步返回 degraded/no-data。

### [P2] 系统 Topic 表缺少稳定 React key

- Location: `console2/src/components/Common.jsx:48`、`console2/src/pages/AdminPages.jsx:225`。
- Evidence: 浏览器控制台稳定复现 `Each child in a list should have a unique key prop`，来源为 `DataTable` 的 `tbody`。
- Cause: `DataTable` 默认使用 `row.id`，Topic 行只有 `name/partitions/tps/lag`。
- Impact: 当前仅为控制台错误，但 Topic 增量变化时可能产生错误复用或行状态错位。
- Suggested fix: Topic 表传入 `rowKey='name'`，或映射时补 `id: topic.name`，并增加回归断言。

### [P3] 快速路由切换会留下 WebSocket 关闭警告

- Location: `console2/src/hooks/useWebSocket.js:66`。
- Evidence: 批量路由巡检期间出现 `WebSocket is closed before the connection is established`；停留在监控页时连接可建立。
- Impact: 不阻断业务，但污染浏览器告警并增加真实断线排查噪声。
- Suggested fix: 组件卸载时区分“尚在 CONNECTING”与已建立连接，避免把主动清理记录为连接失败。

### [P3] `/favicon.ico` 返回 404

- Impact: 不影响功能，仅产生一次无意义控制台错误。

## Verified Workflows

- 认证：未登录深链重定向、安全回跳、错误密码提示、正确登录、退出与重新登录。
- 工作台与研判：重点路口详情 → 轨迹研判；风险热区图层与回放暂停。
- AI 事件：高风险筛选、事件详情、技术确认状态更新。
- 实时监测：路口切换、查询参数同步、检测器/BEV 主次切换、告警复核提交。
- 事故测绘：创建任务 → 采集质检 → 新增量算对象 → 技术复核 → 报告投递。
- 执法线索：线索检索、技术确认、候选区域创建保存、货车专题跳转。
- 飞行任务：四页签、计划冲突阻断、Mission 审计及停止操作。
- 标定中心：四页签；真实标注任务绘制 4 顶点、闭合 1 条车道并保存成功。
- 集成与交付：死信详情、原幂等键重放、质量交付与证据审计页签。
- 系统与身份：真实健康数据、模型列表、只读用户同步。

## Automated Verification

- `console2 npm test`: `36/36 passed`。
- `console2 npm run build`: passed；保留大 chunk 性能提示。
- `python -m pytest platform/tests -q`: `37 passed, 11 subtests passed`；8 条既有弃用告警。
- `git diff --check`: passed。

## Visual QA

- 登录、工作台、实时监测、标定中心和系统与身份均已生成三档截图。
- 1440×900 目视检查：统一左侧一级业务域和顶部二级导航一致；工作台地图、监测主画布、标注画布和系统表格均无遮挡或裁切。
- 1366×768 与 1920×1080 页面级 `scrollWidth > innerWidth` 均为 `false`。
- 截图目录：`output/playwright/console2/`。

## Completion Checklist

- [x] 自动测试与生产构建通过。
- [x] 全正式路由浏览器巡检完成。
- [x] 认证与权限守卫完成点击级验证。
- [x] S1–S9 主要业务流完成点击级验证。
- [x] 四个真实模块三档分辨率截图完成。
- [x] 原浏览器证据 P0 关闭。
- [ ] 修复 Kafka 健康误报并在 broker 断开/恢复场景回归。
- [ ] 修复 Topic 表 key 控制台错误。
- [ ] 在 ADR-019 目标 Kafka + road9/TimescaleDB 全栈下补跑实时消息、历史查询和恢复验收。

prior result: conditional pass; production acceptance blocked by P1 Kafka health false-positive and missing target-stack environment

## 2026-07-14 S3 测绘模块真实落地复验

### Environment and evidence

- Platform：`127.0.0.1:18000`，隔离数据库 `road9_survey_test`，采集 worker 与 outbox worker 已启动。
- Console2：`127.0.0.1:4173`，Vite 同源代理指向隔离 Platform。
- 真实材料：从 `inter_xqh` 4K 原视频截取 12 秒 H.264 片段，配套原始 SRT 29,741 条遥测记录。
- 真实任务：`SVY-20260714-338423`；采集批次 `BATCH-F9DBFC9C039A`；报告 `RPT-1E56864E8715`。
- 1440×900 截图：`.design-qa/survey-capture-1440.png`、`.design-qa/survey-measure-1440.png`。
- 同状态并排对照：`.design-qa/survey-source-vs-measure.png`，左侧为 `prototype-full-survey-1440.png`，右侧为真实实现。

### Functional QA

- 真实 API 流程完成：创建任务 → 幂等重放 → 前置核验 → MP4+SRT 入队 → worker 提取 6 个关键帧 → 选择批次 → 服务端 ENU 量算 → 技术复核 → PDF/JSON/GeoJSON 成果包。
- 遥测覆盖率 `100%`，6/6 关键帧均生成可用测量变换；测试线段由服务端计算为 `42.49m`。
- 真实 PDF 返回 `%PDF` 文件头且大小 `3157 bytes`；重复报告请求返回同一报告 ID。
- 未批准 `survey_quality` 规则时投递返回 422，页面按钮禁用并展示真实门禁原因，没有伪造成功状态。
- 浏览器验证采集、量算、报告三页；鉴权证据图片通过 Blob API 加载，浏览器控制台无 error/warn。

### Visual comparison

- 1440×900 与原型保持同一深色指挥中心视觉体系、顶部/左侧导航、五步工作流、主画布与右侧质量栏比例。
- 原型中的夜景演示底图和预置测量标注已替换为真实白天关键帧与真实持久化量算线，属于数据真实性差异，不是视觉缺陷。
- 主画布、工具栏、证据缩略图、质量门禁和报告侧栏无裁切、重叠、坏间距或错误圆角。
- 本轮未发现测绘范围内 P0/P1/P2 视觉问题；既有 Kafka 健康误报等跨模块发现仍按上文追踪，不影响 S3 本轮设计 QA 结论。

final result: passed

## 2026-07-16 MP4 + SRT 真实数据深度展示

- Viewport：1440 x 900，Console2 本机容器，`admin` 真实登录态。
- 事件中心：真实拥堵 9.2，连续样本 30，覆盖 100%，丢弃 0，关联检测关键帧；截图 `output/playwright/event-center-real-evidence-1440x900.png`。
- 轨迹研判：Mission `MSN-3421232DD4B9`，页面加载 149 条可见世界坐标折线、Source/Road/Quality lineage 和真实冲突 0 空态；2026-07-17 已以本机在应用浏览器重新可视验收。
- 事故测绘：真实 road9 任务的 4 项量算、技术复核、内容哈希、PDF 预览和投递门禁；截图 `output/playwright/accident-survey-real-report-1440x900.png`。
- 交互：全新 Playwright 会话依次访问 `/events` -> `/gis` -> `/survey`，三页 console 0 error / 0 warning。
- 修复：离线轨迹默认 1h 不可见、MJPEG 首帧竞态、测绘成果版本 `vv7` 重复前缀。

final result: passed

## 2026-07-17 GIS 历史轨迹真实投放修复

- 用户可见问题：筛选条显示 500 条历史轨迹，但 OpenLayers 地图只有散点，看不到可研判折线。
- 根因一：查询先执行 `ended_at DESC LIMIT 500`，最新 500 条恰好没有世界坐标；实际 `INT_camera_1` 有 6,397 条带世界坐标轨迹。
- 根因二：只要求两个世界点后，最新命中仍全部为 5 点短片段，移动长度中位数约 0.68m，折线被 4.5px 终点标记覆盖。库内 `MSN-3421232DD4B9` / `MSN-768382706790` 共 285 条至少 6 点轨迹，点数中位数 50、最大 99、最大首尾跨度约 117m。
- 修复：Platform 支持 `spatial_ready=true&min_world_points=6` 并在 PostgreSQL LIMIT 前过滤；GIS 固定使用空间投放筛选；嵌入式地图 fit padding 改为四边 32px，避免原主监控页左右面板 padding 超过 GIS 地图宽度。
- 实际接口：`INT_camera_1` 返回 285/285 条具有世界锚点且至少 6 点的轨迹，点数中位数 50、最大 99。
- 可视验收：真实任务 `MSN-3421232DD4B9` 页面显示 149 条历史轨迹、149 条世界坐标，地图清楚绘出贯穿路口四向的彩色折线；浏览器 console 0 error / 0 warning。
- 自动化：Platform 104 passed、5 skipped、10 subtests；Console2 8 files / 56 tests passed；production build passed。

final result: passed

## 2026-07-17 轨迹研判首次加载真实数据修复

- 用户可见问题：首次进入 `/gis` 时，项目路口聚合尚未返回，筛选条先显示“0 个路口 · 0 条轨迹”，容易被理解为 `road9` 没数据。
- 根因：`DashboardReadModel._facts()` 每次读取最多 5,000 条交通指标和 5,000 条遥测完整 ORM/JSON 记录，再在 Python 侧选择最新值；实测 `/api/v1/dashboard/intersections` 为 2.46–2.93s，而 500 条轨迹接口仅 24–25ms。
- 修复：PostgreSQL 侧使用 `DISTINCT ON` 按 RoadContext 路口、指标路口和遥测无人机直接选择最新事实；Console2 在请求未完成时显示“路口加载中 · 轨迹等待路口”，请求失败显示“加载失败”并提供“重新加载真实数据”，不再用 0 表达未知状态。
- 性能复验：重建正式本机容器后，路口聚合 5 次为 9.2–16.4ms；500 条轨迹 5 次为 24.0–60.9ms。
- 浏览器复验：真实 `admin` 会话强制刷新 `/gis`，3.97s 内出现“4 个路口 · 500 条轨迹”；页面不包含“0 个路口 · 0 条轨迹”，console 0 error / 0 warning。
- 自动化：Platform 103 passed、5 skipped、10 subtests；Console2 8 files / 55 tests passed；production build passed，保留既有大 chunk 提示。

final result: passed

## 2026-07-15 I5-A S8 主任首屏真实读模型与权威坐标阻断态

### Implementation

- `/` 已移除固定 `14/18`、风险/拥堵/无人机百分比、示例路口、模拟待办和模拟健康状态，改为读取 `road9` 聚合的 `uav.dashboard/v1` 读模型。
- 首页共享顶栏改为服务端授权范围、固定 30 分钟工程窗口和实时 `as_of`；不再显示固定辖区、固定路口数或固定时间。
- KPI 正式口径未批准时返回并展示 `value=null + numerator/denominator + unverified reason`，不把待冻结口径显示成 0 或伪百分比。
- OSM 开发底图仅接收已验证 WGS84 RoadContext；未验证、GCJ02、缺坐标或无权威项目清单的路口进入隔离计数和配置待办。
- 无人机位置和电量读取 TimescaleDB 遥测事实的归一化列；只有 2 分钟内的新鲜遥测才向页面返回坐标和电量。

### Runtime verification

- 隔离链路：Console2 `127.0.0.1:4176` → Platform `127.0.0.1:18004` → PostgreSQL/TimescaleDB `127.0.0.1:6543/road9`。
- 当前 `road9` 没有获批的项目 RoadContext 快照；页面如实显示“暂无可上图的权威路口坐标”、5 个 KPI 待冻结和 1 项项目配置核验，而不是回退到示例路口。
- 新标签完成真实登录与首页加载；控制台 `0 error / 0 warn`。长期 Vite 会话曾在热更新时留下历史 AuthProvider 日志，该历史日志不作为本次干净标签验收结果。

### Retained evidence

- `.design-qa/2026-07-15-i5-dashboard-road9-authority-blocked.png`：最终全屏权威坐标阻断态。
- `.design-qa/2026-07-15-i5-dashboard-before-after.jpg`：I5 同一页面初始状态与最终状态对照；用于核对顶栏、空态和信息密度，不冒充外部 UI 原型基准图。
- Dashboard API 定向测试、真实 PostgreSQL WGS84 分支、Platform/Console2 全量回归、生产构建、OpenAPI 和 diff 门禁的最终数字见本阶段回归记录。

### Acceptance boundary

- I5-A 工程读模型和 truthful empty/blocked 状态完成。
- 项目/辖区清单、正式地图 Adapter、S8-TBD-001 至 006、正常态权威数据、全局增量和 5 秒/30 秒主任任务仍属于 I5-B 或外部书面批准门禁。

final result: I5-A engineering passed; I5-B external authority and full-state acceptance pending

## 2026-07-15 I5-B 内部筛选、依赖降级与底图失败状态

### Implementation

- `GET /api/v1/dashboard/intersections` 已支持 `risk/monitor/quality`、WGS84 `bbox`、`q`、`offset/limit`；响应提供 `project_total/total/has_more/filters`。
- 无效 bbox 返回 `422 invalid_bbox`；road9 超时或 SQLAlchemy 依赖异常返回 `503 dashboard_dependency_unavailable`。
- Dashboard 的“全部/高风险/降级”控件改为服务端查询，切换时保留上一成功快照并执行有限重试；401 仍交给统一会话失效流程，不循环重试。
- OSM 连续 3 个瓦片加载错误后明确显示“城市底图服务不可用”，保留 KPI、关注榜和任务列表，并提供重试；不生成随机或示意点位。

### Verification

- Platform：`58 passed, 4 skipped`，另 `11 subtests passed`。
- Dashboard API 定向：`3 passed`；真实 PostgreSQL/TimescaleDB I3～I5 集成：`4 passed`。
- Console2：`45/45 passed`，production build passed；其中 CityMap 回归实际触发 3 次瓦片错误、验证降级和重试恢复。
- OpenAPI：`94 paths / 110 operations`；Dashboard 路口参数为 `risk, monitor, quality, bbox, q, offset, limit`。
- 干净浏览器标签完成真实登录，点击“高风险”后控件为 active、阻断态保持稳定；控制台 `0 error / 0 warn`。
- 截图：`.design-qa/2026-07-15-i5b-dashboard-server-filter.jpg`。

### Remaining acceptance boundary

- 项目/辖区权限清单、正式地图供应商/坐标 Adapter、批准 KPI 与状态阈值仍为外部阻断。
- 点位聚合/zoom、全局增量、断线期间缺口 REST 回补、部分依赖故障注入、批准正常/混合质量数据和 5 秒/30 秒主任任务尚未完成，不以本地工程测试替代正式验收。

final result: internal query and degradation behaviors passed; external I5-B acceptance remains blocked

## 2026-07-16 四路口验收测试坐标与无人机图标

### Implementation

- 首页地图从 road9 的四个 `local_acceptance_only` WGS84 遥测中位点读取坐标，不使用随机或手工示意点。
- 四个测试点以四旋翼无人机 SVG 图标展示，颜色继续表达风险状态；初始视野取四点几何中心。礼士路与海右路近邻图标对称避让，底层 Feature 经纬度不变，确保四路口同屏且可辨识。
- 页面明确标注“验收测试坐标”，Dashboard 健康保持 degraded，正式道路坐标仍为 unverified。

### Verification

- Platform 定向测试覆盖 test 坐标可上图、普通 unverified 坐标仍隔离和目录幂等坐标来源。
- Console2 组件测试覆盖无人机 SVG、近邻避让不改经纬度、四点中心视野和底图失败边界；全量 `53 passed`，production build 通过。
- 最终 Docker 页面在 1357×912 本机浏览器显示四个可辨识无人机图标、4 个可上图路口和 4 个验收测试坐标；控制台 `0 error / 0 warning`。

final result: local acceptance coordinates passed; authoritative road coordinates remain unverified

## 2026-07-15 I3 TimescaleDB 轨迹研判与事件复核验收

### Runtime evidence

- 隔离链路：Console2 `127.0.0.1:4176` → Platform `127.0.0.1:18004` → TimescaleDB `2.28.2` / PostgreSQL 17 `road9`，migration head `20260715_0007`。
- migration 确认 5 张 hypertable：`uav_traffic_metrics`、`uav_track_points`、`uav_conflict_events`、`uav_telemetry_metrics`、`uav_system_metrics`；入站永久错误使用普通表 `uav_message_dead_letters`。
- `/gis` 从正式 REST/MetricStore 查询 `INT_camera_1` 最近 1 小时事实，显示 1 条轨迹、1 条冲突、`ROAD-LOCAL-INTER-XQH`、`time_quality=ingest_only`、`quality_status=unverified`；未生成模拟热区或无依据坐标。
- `/events` 展示事件 `791e509f3acfac14cfc80ceb1977bc9d1d567777`，标题明确为“I3 工程复核样本（非真实冲突）”，证据包含 `engineering_contract_fixture` 和 `inter_xqh_56_pass`；主平台投递保持 `not_queued/合同未冻结`。
- 管理员执行技术确认后 revision 从 1 增至 2；新标签页重新登录和刷新后仍显示 `confirmed`，证明复核状态来自 `uav_conflict_reviews` 持久化而非 React 内存。
- 浏览器控制台：0 error / 0 warn。

### Truth boundary

- `test_pipeline_inter_xqh.py` 本轮真实 100 帧仍为 `56 PASS / 0 FAIL / 0 WARN`，累计 8051 个检测目标、100/100 遥测与 H 矩阵、90/100 运动补偿、冲突事件 0。
- 为验证冲突详情与 revision 交互，`platform/scripts/validate_i3_inter_xqh.py` 使用真实 SRT 首条时间/锚点写入受控契约样本，并强制标记 `validation_fixture=true`、`unverified`、`ingest_only`；该样本不得表述为真实检测冲突或合同精度证据。
- 权威路网、正式 S1/S2 指标阈值、生产 TimescaleDB 版本/容量/保留/压缩/HA、历史 Influx 对账及主平台合同仍保持 `blocked`。

### Retained screenshots

- `.design-qa/2026-07-15-i3-gis-timescale.png`：真实 `road9` 轨迹/冲突数量、路网版本、时间质量和 TimescaleDB 来源。
- `.design-qa/2026-07-15-i3-events-unverified.png`：复核前 `unverified/ingest_only/not_queued` 事实及责任边界。
- `.design-qa/2026-07-15-i3-events-review-confirmed.png`：技术确认后持久化 revision 2；不产生派警、违法认定或主平台成功状态。

final result: I3 local engineering passed; production and contract acceptance blocked

## 2026-07-15 I4 执法候选线索真实 API 验收

### Runtime evidence

- 隔离链路：Console2 `127.0.0.1:4176` → Platform `127.0.0.1:18004` → TimescaleDB `2.28.2` / PostgreSQL 17 `road9`，migration head `20260715_0008`。
- candidate 围栏 `ZONE-B70E59BD248A`、candidate 规则 `RULE-D5279B1C5CCE`、线索 `CLUE-3236A895FFBF` 均来自真实 REST/PostgreSQL；刷新后技术复核仍为 `reviewed_confirmed` revision 2，不依赖 React 内存。
- 真实材料为 `test_videos/inter_xqh/` 原始 5,395,860,937-byte MP4 和 29,741 条 DJI SRT。MP4 SHA-256 为 `342dea78baf9acdb526a969333ec1c319b6aa39dc92a010548194b5c99b3fcbc`，SRT SHA-256 为 `12ea683bafe9b69066438e02211de30dcb1780924b406e35e63dcb90188010ac`；两个引用和哈希均从线索详情 API 展示。
- 线索显式为 `validation_fixture=true`、`detected_enforcement_clue=false`、车辆 `unknown`、无视频/雷达/融合速度、质量 `unverified`；页面没有模拟证据图、雷达值、在线货车位置或违法结论。
- 权威发布按钮调用真实接口并返回 503，页面显示“仅为本地候选；权威发布 Adapter 和审批合同尚未冻结”；没有写入 published/approved 或伪造主平台成功。
- 浏览器控制台：0 error / 0 warn；页面延续 Console2 既有导航、卡片、标签和表单设计语言。

### Retained screenshots

- `.design-qa/i4-audit/01-clues.png`～`04-zone-form.png`：I4 改造前 Mock 基线。
- `.design-qa/2026-07-15-i4-enforcement-clue-unverified.png`：真实线索事实、空值、证据哈希、质量和外部阻断。
- `.design-qa/2026-07-15-i4-enforcement-review-confirmed.png`：技术确认 revision 2；不表示违法认定或处罚。
- `.design-qa/2026-07-15-i4-candidate-authority-blocked.png`：candidate 围栏/规则和真实 503 权威发布门禁。
- `.design-qa/i4-audit-clues-before-after.jpg`、`.design-qa/i4-audit-zones-before-after.jpg`：同视口前后对比；移除伪证据、伪雷达、伪地图发布和无依据 KPI。

### Automated gates

- Platform：`55 passed, 3 skipped`，另 `11 subtests passed`；I2/I3/I4 三套真实 PostgreSQL integration 合并运行 `3 passed`。
- Console2：`43/43` tests passed，production build passed；仅保留既有的大 chunk 提示。
- 根目录轻量回归：`9 passed`。
- `test_pipeline_inter_xqh.py`：`56 PASS / 0 FAIL / 0 WARN`；100/100 检测、100/100 遥测、100/100 H 矩阵、90/100 运动补偿、累计 8051 个目标。
- OpenAPI：`90 paths / 106 operations`；`git diff --check` passed。

### Truth boundary

- `platform/scripts/validate_i4_inter_xqh.py` 验证真实材料的文件身份、证据、幂等、技术复核和刷新持久化接缝，不运行或伪造执法规则命中；不得把该 fixture 表述为真实检测违法线索。
- 权威 RoadContext/围栏、批准执法规则、货车二分类验收集、雷达设备/检定/融合、法制证据、统一身份和主平台 EventDelivery 仍为 `unverified/blocked`。

final result: I4 local candidate engineering passed; legal and external production acceptance blocked

## 2026-07-15 S9 `road9` 飞行任务四页签真实验收

### Runtime evidence

- 隔离验收链路：Console2 `127.0.0.1:4175` → 当前 Platform `127.0.0.1:18001` → 本地 PostgreSQL `road9` migration `20260715_0003`；未连接占用 8000 的遗留 Docker Platform。
- 真实材料：`test_videos/inter_xqh/` 5.0GB 4K MP4 + DJI `telemetry.srt`；数据源 `SRC-9CAB4266AFA5` 校验为 valid，响应仅展示文件名。
- FlightPlan `PLAN-C67C8E8EE329` 由调度器生成 Mission `MSN-01110B561F66`；初始 Pipeline `pipe-91b8a836`，模拟 Platform 重启后恢复为 `pipe-b6bdbd68`，canonical Topic 为 `uav_statistics_10`。
- 页面分别显示无人机离线（无新鲜遥测）、数据源有效、once 计划已启用/revision 2、Mission completed 与 Pipeline stopped；业务状态和进程状态未混写。
- 浏览器控制台 `0 error / 0 warn`；页面使用真实 API 数据，没有 S9 Mock fallback。

### Retained screenshots

- `.design-qa/2026-07-15-s9-drones-road9.png`：无人机档案及真实离线状态。
- `.design-qa/2026-07-15-s9-sources-inter-xqh.png`：MP4+SRT 配对、脱敏及 valid 状态。
- `.design-qa/2026-07-15-s9-flight-plan.png`：once 窗口、Asia/Shanghai 和 revision。
- `.design-qa/2026-07-15-s9-mission-completed.png`：Mission/Pipeline 分离状态及 window_ended 原因。

### Natural EOF addendum

- 完成审计发现 MissionOrchestrator 未在正常 tick 同步 Pipeline EOF/error，且真实 5GB 视频首次跑到末尾时暴露 `main_optimized.py` 在 sentinel 判断前访问 `.frame` 的异常。
- 当前已增加 Pipeline `stopped/error/missing` → Mission `completed/source_eof`、`failed/pipeline_error`、`failed/pipeline_runtime_missing` 的 PostgreSQL 持久化同步，并将 `VideoEndBreakElement` 在共享内存处理前级联。
- 使用同一 5GB MP4 + DJI SRT、`frame_stride=300`、15 分钟窗口重新执行“计划触发 → 主动停止旧 Pipeline 模拟 Platform 重启 → 恢复新 Pipeline → 自然 EOF”。Mission `MSN-995CEBE0415E`、恢复 Pipeline `pipe-fc39f315`、Topic `uav_statistics_10`，终态为 `completed/source_eof`，观察 392.918 秒；证据见 `docs/test_report_s9_inter_xqh_eof.json`。
- 补充完成纯页面触发的本地 `road9` 验收：Console2 `127.0.0.1:4179` → Platform `127.0.0.1:18005` → migration `20260715_0009`。页面登记无人机 `UAV-PAGE-0715`、有效数据源 `SRC-C74D6FA9EA35`，创建并启用 once 计划 `PLAN-6C3102938EBB`；5 秒调度器在计划时间 `+2s` 创建 Mission `MSN-5A61F57DA1D7` 和 Pipeline `pipe-ec14fc26`。同一 5GB MP4 + DJI SRT 在 `frame_stride=300` 下运行 396.663 秒后自然结束，页面刷新后持久化显示 `Mission completed / Pipeline stopped / source_eof`，运行中与失败计数均为 0。
- 首次页面运行连接到临时 `18004` 实例且沿用生产默认 `frame_stride=None`，已从页面执行 `停止 Mission` 并得到 `stopped/manual_stop`；该运行只作为停止门禁和配置诊断证据，不计入最终通过结果，也未修改生产默认参数。
- RoadContext 继续保持 `unverified`；该验证不关闭生产容量、RTSP/MQTT、设备权威或 HA 门禁。

### Page-triggered retained screenshots

- `.design-qa/2026-07-15-s9-source-registered.jpg`：正式本地 `road9` 中的 MP4+SRT 配对、脱敏摘要和 valid 状态。
- `.design-qa/2026-07-15-s9-page-mission-completed.jpg`：页面触发 Mission 的 `completed/source_eof` 与 Pipeline `stopped` 分离终态。

### Automated gates

- Platform `76 passed, 5 skipped`，另 11 个 subtests passed；显式 PostgreSQL Mission integration `2 passed`，覆盖并发/重启/停止及 EOF/error/missing-runtime 持久化。
- 隔离 `road9_i2_test` 完成 `20260715_0003 → 20260714_0002 → 20260715_0003` 回滚恢复演练。
- Console2 `45/45` tests passed，production build passed。
- 根目录轻量与 EOF sentinel 回归 `10 passed`。
- `test_pipeline_inter_xqh.py`: `56 PASS / 0 FAIL / 0 WARN`；100/100 检测与遥测，100/100 H 矩阵，90/100 运动补偿，累计 8051 个目标。

正式设备主数据、RTSP/MQTT 生产网络、统一身份权限矩阵、容量/高可用和权威 RoadContext 仍为 `unverified/blocked`。

final result: engineering passed; external production acceptance blocked

## 2026-07-15 监控侧栏透明收缩与研判浮条精简

### Implementation

- 左侧“实时态势”和右侧“BEV 与实时事件”面板的卡片背景统一为 `rgba(..., .4)`；文字、指标和控制按钮保持不透明，避免降低可读性。
- 两侧面板默认仅保留 36px 边缘控制条；鼠标进入或键盘聚焦时展开，离开或焦点移出时自动收缩。
- 左右面板分别提供锁定按钮；锁定后指针离开仍保持展开，取消锁定后恢复自动收缩。
- 面板收缩时，检测状态标识与地图工具同步贴近左右边缘，不保留原面板宽度的空占位。
- 删除监控画面底部“AI 事件研判”浮条及其关闭/标记已复核操作；实时事件列表仍保留，完整详情与复核通过“全部事件”进入事件页。

### Verification

- `LiveModules.test.jsx` 验证两侧默认 `collapsed`、40% 透明标记、进入展开、离开收缩、锁定保持、取消锁定恢复，以及监控页不再渲染“AI 事件研判”。
- Console2 全量回归 `43/43` passed，production build passed，`git diff --check` passed。
- `http://127.0.0.1:4174/monitoring?intersection_id=INT_camera_1&view=detector` 本地服务返回 HTTP 200。
- 本轮浏览器刷新本地页被浏览器安全策略阻止，未绕过限制生成新截图；保留实现与自动化证据，实页截图待浏览器恢复后补拍。

final result: implementation and automated verification passed; live screenshot pending

## 2026-07-15 检测器红蓝轨迹误叠加修复复验

- 根因：Console2 将前两条活动/完成世界轨迹压缩成 Recharts `a`/`b` 序列，并以蓝色 `#64a5ff`、红色 `#ff7c62` 覆盖在 MJPEG 检测画面；该图表坐标未与视频像素配准。
- 修复：删除视频上的归一化 Recharts 轨迹层；`trajectory_world_m` 继续仅由 OpenLayers BEV 投放。风险标记只在检测器的风险模式显示，原始画面不增加前端 AI 叠层。
- 回归：WebSocket 连续注入两条 `uav_track_complete`，验证检测器无“车辆轨迹图层”，切换 BEV 后仍收到两条轨迹。Console2 `42/42` tests 与 production build 通过。
- 实页：`127.0.0.1:4174/monitoring?intersection_id=INT_camera_1&view=detector` 中真实 MJPEG 可见；轨迹图层、`.recharts-line`、红蓝 stroke 计数均为 0。
- 截图：`.design-qa/2026-07-15-monitoring-detector-red-blue-lines-fixed.jpg`。

final result: passed

## 2026-07-15 监控 BEV 地图与无道路标注检测验收

### Implementation

- BEV 主视图和右侧预览已从静态 `bev-intersection-night.png` 替换为 OpenLayers + OSM 地图底图，与 Console 1.0 地图实现保持同一技术路径。
- 仅 `trajectory_world_m` 投放到地图；优先使用每条轨迹的 `world_anchor_lat_lon`，缺失时回退路口中心。无轨迹时显示真实地图与 ENU 原点，不绘制模拟轨迹。
- `ROADS_JSON=""` 与地图职责解耦：检测器没有人工道路 ROI，但地图、检测视频和世界坐标层仍可独立工作。

### Runtime verification

- 真实源：`test_videos/inter_xqh/DJI_20260403142902_0001_V小清河北路与水屯路路口.mp4` + `test_videos/inter_xqh/telemetry.srt`。
- 通过现有 Console 1.0 页面调用 Platform Pipeline API，实际请求配置 `roads_json: ''`、`telemetry_source: srt`；创建 Pipeline `pipe-9791972f`、Topic `statistics_12`、Camera `12`。
- Console2 隔离验收实例：`127.0.0.1:4174` → Platform `127.0.0.1:8000`；页面显示 `INT_camera_1 · 实时分析中`、实时链路已连接、BEV OSM 底图和真实检测器 MJPEG 画面。
- 容器 CPU 环境处理 4K 原视频首帧耗时较长；截图时统计快照尚未到达，页面如实显示 `数据过期`、0 活动轨迹，没有用模拟 KPI 或轨迹填充。

### Automated and retained evidence

- Console2 `41/41` tests passed；production build passed，保留既有大 chunk 提示。
- `python test_pipeline_inter_xqh.py` 真实无道路标注回归：`56 PASS / 0 FAIL / 0 WARN`；100/100 帧有检测结果，累计 8051 个目标，100/100 遥测注入，100/100 H 矩阵有效，90/100 运动补偿有效，`cars_amount=82`，冲突事件 0。
- 浏览器 1280×720 验收无横向溢出，OpenLayers canvas 已实际渲染，控制台 0 error / 0 warn。
- `.design-qa/monitoring-bev-map-live-20260715.jpg`：BEV 地图主视图、在线管道和检测器预览。
- `.design-qa/monitoring-detector-no-roads-20260715.jpg`：无道路 ROI 模式下的真实 YOLO/ByteTrack 检测画面，以及右侧 OSM BEV 预览。
- `.design-qa/monitoring-bev-map-clean-20260715.jpg`：BEV 地图最终视图与 OSM attribution。

final result: passed; live page preserved truthful stale-data state during 4K Docker CPU processing

## 2026-07-15 S3 `inter_xqh` 全量原始材料测试

### Material and persisted evidence

- 原始视频：`test_videos/inter_xqh/DJI_20260403142902_0001_V小清河北路与水屯路路口.mp4`，5.0GB、4K、992.358s；未裁剪、未转码。
- 原始遥测：`test_videos/inter_xqh/telemetry.srt`；worker 报告 frame count 29,741、覆盖率 99.9967%。
- 任务 `SVY-20260714-4AF576`；批次 `BATCH-7E8061819ABA`；关键帧 1487、6840、12193、17546、22899、28253，6/6 具备测量变换。
- 服务端量算 `M-4E46F9D4=79.51m`；报告 `RPT-5BECE3A9C5A6`；内容哈希 `39a0740d2a11fb860b3801c90382485a279382656f4e5cabb985eaca7fb778b3`。
- PDF 返回 200、3137 bytes、文件头 `%PDF`；未批准 `survey_quality` 时投递返回 422，没有产生外部成功状态。

### Defects found and closed

- 导入材料后任务由 ready 进入 collecting 并增加 revision，但采集页未重新读取任务，点击“进入量算”发生 409；现已在 import/upload 后同步刷新任务，新增回归测试。
- 报告 POST 已 201 成功但页面未可靠显示返回结果；现已直接用响应更新报告状态并刷新任务/量算，新增无需 reload 的回归测试。
- Console2 `38/38` tests passed，production build passed；chunk size 提示仍是既有性能告警。

### Retained screenshots

- `.design-qa/survey-full-inter-xqh-capture-detail-20260715.png`：完整视频关键帧、批次、覆盖率与质量观测。
- `.design-qa/survey-full-inter-xqh-measure-20260715.png`：真实 BEV、服务端 79.51m 量算线及质量状态。
- `.design-qa/survey-full-inter-xqh-review-20260715.png`：原始帧/BEV 对照、复核清单与量算结果。
- `.design-qa/survey-full-inter-xqh-report-20260715.png`：报告哈希、PDF 摘要、generated 状态与真实投递门禁。

本次仍只证明全量材料工程闭环；RTK/空间覆盖显示 unavailable，正式精度阈值未批准，因此质量保持 unverified。

final result: passed

## 2026-07-16 浏览器批注：研判导航与页面标题栏收敛

### Comparison target

- Source visual truth：`.design-qa/2026-07-16-browser-comments-source.png`。
- Implementation screenshots：`.design-qa/2026-07-16-browser-comments-home-after-1197x912.png`、`.design-qa/2026-07-16-browser-comments-gis-after-1197x912.png`。
- Viewport：1197 × 912，深色主题，管理员已登录；首页与 `/gis` 使用同一 Console2/Platform 本机运行态。
- Full-view comparison：同一首页、同一视口对比确认 `page-heading` 可见标题栏已消失，告警、KPI、地图、侧栏卡片和“进入值守模式”操作保持既有布局与内容，仅按需求整体上移。
- Focused comparison：`/gis` 截图确认顶部二级导航的 ARIA 域名为“智能研判二级导航”，顺序为“AI 事件中心 / 轨迹研判”，且“轨迹研判”保持 active；该路由状态与首页源图不同是本条导航迁移批注的验收目标。

### Findings

- 无剩余 P0/P1/P2：两条浏览器批注均已落实，未发现标题栏残留、导航错域、内容溢出或交互失效。
- 字体与排版：保留既有字体、字号、字重和导航层级；普通页面标题改为 `.sr-only` `h1`，视觉标题不再占位。
- 间距与布局节奏：删除 76px 标题栏目后业务内容自然上移；有页面级操作时只保留 10px 底边距的右对齐紧凑操作行，没有新增空白标题区。
- 色彩与视觉 token：背景、边框、状态色、选中态和阴影均未改动。
- 图像质量与资产：未新增或替换图片、图标、地图或品牌资产；首页地图空态和 GIS OpenLayers 底图保持原实现。
- 文案与内容：仅移除各页 eyebrow、可见标题、说明和 meta；页面级业务按钮、面包屑、筛选器和事实内容保留。

### Comparison history

- 首轮自动化回归发现 P1：共享标题组件被整体删除时，测绘页“提交技术复核”和“生成成果包”随操作区消失。
- 修复：`PageHeader` 保留屏幕阅读器 `h1`，并把 `actions` 迁到独立 `.page-actions` 行；标题、说明和 meta 不再渲染。
- Post-fix evidence：`RouterApp.test.jsx` 29/29、Console2 全量 50/50、production build 均通过；首页截图保留“进入值守模式”，浏览器中“AI 事件中心 → 轨迹研判”导航往返成功，最终 URL 为 `/gis`，console error/warn 为 0。

### Implementation checklist

- [x] `/gis` 从“全域态势”移动到“智能研判”。
- [x] 所有普通页面移除可见标题栏目。
- [x] 保留每页可访问标题和页面级核心操作。
- [x] 同视口全图与聚焦截图对比。
- [x] 自动化测试、生产构建、真实容器和浏览器交互验证。

### Follow-up polish

- 无阻断性或 P3 跟进项。

final result: passed

## 2026-07-16 浏览器批注：开发态提示与顶部操作行收敛

### Comparison target

- Source visual truth：本轮 1357 × 912 浏览器批注截图；同类首页结构复用留存基准 `.design-qa/2026-07-16-browser-comments-source.png`。
- Implementation screenshots：`.design-qa/2026-07-16-browser-comments-home-toolbar-after-1357x912.png`、`.design-qa/2026-07-16-browser-comments-enforcement-after-1357x912.png`。
- Viewport：1357 × 912，深色主题，管理员登录态；首页、`/drones`、`/survey`、`/enforcement/zones` 使用同一 Console2/Platform 本机运行态。
- Full-view comparison：首页保留 KPI、地图、侧栏和底部状态条，删除 `I5 内部工程口径` 开发态横幅；“进入值守模式”与左侧面包屑进入同一顶部行。
- Focused comparison：浏览器量测首页、飞行任务、事故测绘和执法配置的 `.breadcrumb` 与 `.page-actions` 均为 `top=82px`、`height=32px`、`center=98px`；执法配置页不再显示合同冻结、工程契约样本或地图停用等开发说明。

### Findings

- 无剩余 P0/P1/P2：所查业务页未发现内部阶段码、blocked 标识、Mock/fallback、验证样本或开发接入说明残留。
- 字体与排版：沿用既有字号、字重、按钮和面包屑样式；页面操作区只改变定位，不改变控件视觉 token。
- 间距与布局节奏：共享 `.page-actions` 绝对定位到主内容顶部，带操作页面的面包屑预留右侧 320px，1357px 宽度下无碰撞或折行。
- 色彩与视觉 token：背景、边框、状态色、选中态和阴影未改动；真实加载、错误、权限、质量、交付门禁继续使用原 `QualityNotice` 体系。
- 文案与内容：开发过程解释改为面向业务的加载、空态和能力边界文案；“待冻结”等真实数据状态继续保留。
- 图像质量与资产：未新增或替换图片、图标、地图或品牌资产。

### Comparison history

- 首轮自动化回归发现 3 条旧断言仍要求显示 Mock 回退、工程契约样本和长坐标隔离说明；另有 1 条身份同步测试仍依赖旧开发态文案。
- 修复：更新断言验证开发态提示缺席，同时保留 Mission 冲突、线索复核 API、坐标隔离和只读身份源的业务行为验证。
- Post-fix evidence：Console2 全量 50/50 测试通过，production build 通过；本机容器重建后，4 个代表页面顶部操作区量测一致；当前验收标签页 console error/warn 为 0。

### Implementation checklist

- [x] 首页移除 I5/blocked 开发态横幅。
- [x] 页面级操作与左侧面包屑同排对齐。
- [x] 飞行任务、事故测绘、执法配置等同类页面统一处理。
- [x] 隐藏 Mock/fallback、工程契约和后续接入说明，保留真实运行状态。
- [x] 自动化测试、生产构建、真实容器和浏览器同尺寸验证。

### Follow-up polish

- 无阻断性或 P3 跟进项。

final result: passed

## 2026-07-19 浏览器批注：页面纵向撑满与地图点位直达实时监测

### Comparison target

- Source visual truth：本轮浏览器批注 Comment 1/2，以及修改前留存 `.design-qa/2026-07-19-dashboard-before-fill.png`。
- Implementation screenshots：`.design-qa/2026-07-19-dashboard-after-fill.png`、`.design-qa/2026-07-19-monitoring-from-marker.png`。
- Combined comparison：`.design-qa/2026-07-19-dashboard-fill-comparison.jpg`。
- Viewport/state：1357 × 912，深色主题，管理员登录态，首页使用同一 Console2/Platform 本机数据快照。
- Full-view comparison：首页 KPI、地图、右侧卡片和底部状态条的视觉 token 与内容保持不变；主地图工作区向下吸收空余高度，底部深色空白带消失。
- Focused comparison：地图无人机点位从“打开路口详情抽屉”改为单击直接进入对应 `/monitoring?intersection_id=...` 实时检测画面；重点路口列表仍保留详情抽屉入口。

### Findings and fixes

- P1：`.shell-main` 不是弹性容器，`.dashboard-grid` 固定为 540px，1357 × 912 下底部状态条之后留下 98px 空白。修复为共享纵向 flex 容器，并让各业务工作区及列表末级面板吸收剩余高度；首页地图网格由 540px 增至 620px，底部统一保留 18px。
- P1：首页 `CityMap` 点位只更新 `intersection_id` 并打开详情抽屉，未进入用户要求的实时检测画面。修复为点位单击直接导航到 `/monitoring?intersection_id=...`，查询参数使用 URL 编码。
- Post-fix representative pages：`/events` 末级面板 bottom=894px、`/gis` 工作区 bottom=894px，912px 视口下均为 18px 底部间距；两页 `scrollHeight === clientHeight === 848px`，无额外纵向溢出。
- Interaction evidence：在真实首页点击无人机点位后进入 `/monitoring?intersection_id=INT_camera_1`；“实时监测”导航为 active，`飞行姿态数据` 区域可见。

### Visual fidelity review

- 字体与排版：字号、字重、导航层级和卡片标题未改动。
- 间距与布局：只调整主内容的纵向分配和底部 gutter；横向网格、卡片间距、圆角与边框保持原值。
- 色彩与资产：背景、状态色、OpenLayers 底图、无人机图标和现有图片资产未替换。
- 文案与内容：未新增展示文案；路口事实、质量状态、实时画面空态和数据来源保持真实运行态。
- Console：最终验收标签页 0 error / 0 warning。

### Verification

- [x] 同视口修改前后全图并排比较。
- [x] 首页、事件列表、轨迹研判三类页面底部量测。
- [x] 真实地图点位点击与监测页到达验证。
- [x] Console2 全量 80/80 自动化测试。
- [x] Vite production build。

### Follow-up polish

- 无阻断性或 P3 跟进项。

final result: passed

## 2026-07-19 浏览器批注：首页地图标题栏删除

### Comparison target

- Source visual truth：本轮浏览器批注 Comment 1，以及删除前留存 `.design-qa/2026-07-19-dashboard-map-header-before.png`。
- Implementation screenshot：`.design-qa/2026-07-19-dashboard-map-header-after.png`。
- Combined comparison：`.design-qa/2026-07-19-dashboard-map-header-comparison.jpg`。
- Viewport/state：1357 × 912，深色主题，管理员登录态，首页使用同一 Console2/Platform 本机数据快照。
- Full-view comparison：KPI、右侧三组业务卡片、地图图例、状态条和整体栅格保持不变；左侧地图从面板顶部开始显示。
- Focused comparison：用户选中的标题、说明和三个筛选按钮整块消失，没有残留占位或空白标题区。

### Findings and fixes

- P1：删除标题 JSX 后若保留原 `.city-map { height: calc(100% - 48px) }`，地图底部会留下同等空位。同步改为 `height: 100%`，使地图占满面板。
- P2：移除筛选控件后不再保留无入口的 `riskFilter` 状态和条件查询分支；Dashboard 固定请求当前授权范围 `{ limit: 500 }`。
- Post-fix evidence：`.map-master-panel > .panel-title` 数量 0、`地图状态筛选` 数量 0、删除标题不可见；面板 `top=222px/height=620px`，地图 `top=223px/height=618px`，差异仅为 1px 面板边框。
- Interaction evidence：点击真实无人机点位后进入 `/monitoring?intersection_id=INT_camera_1`，实时监测导航 active，飞行姿态区可见。

### Visual fidelity review

- 字体与排版：仅删除指定文案区，其余字号、字重和信息层级未改动。
- 间距与布局：地图向上补齐原 48px 标题空间；横向栅格、卡片间距、圆角和底部 18px gutter 保持不变。
- 色彩与资产：地图底图、无人机点位、状态色、图例和图标资产未替换。
- 文案与内容：仅移除批注明确选中的标题、说明和筛选标签；路口事实和质量信息保持原运行态。
- Console：最终验收标签页 0 error / 0 warning。

### Verification

- [x] 1357 × 912 同视口修改前后并排比较。
- [x] DOM 与像素位置量测确认无标题残留和空白占位。
- [x] 真实地图点位点击与监测页到达验证。
- [x] Console2 全量 79/79 自动化测试。
- [x] Vite production build。

### Follow-up polish

- 无阻断性或 P3 跟进项。

final result: passed

## 2026-07-19 浏览器批注：实时监测双侧栏默认展开

### Comparison target

- Source visual truth：本轮浏览器批注 Comment 1/2，以及修改前留存 `.design-qa/2026-07-19-monitoring-panels-before.png`。
- Implementation screenshot：`.design-qa/2026-07-19-monitoring-panels-after.png`。
- Combined comparison：`.design-qa/2026-07-19-monitoring-panels-comparison.jpg`。
- Viewport/state：1357 × 912，深色主题，管理员登录态，`/monitoring?intersection_id=INT_camera_1`，相同路口与实时数据快照。
- Full-view comparison：顶部路口上下文、中央检测画面、地图工具、时间轴和导航保持原布局；左右两侧由窄边缘状态变为完整信息面板。
- Focused comparison：实时态势面板展示拥堵、四项指标、趋势和车型流量；BEV/实时事件面板展示轨迹投放和事件列表，两个边缘收缩按钮均保留。

### Findings and fixes

- P1：左右侧栏初始 `open=false`，进入实时监测后只能看到窄边缘，关键态势与事件事实需要额外悬停。修复为左右 `open=true`，首次进入即显示完整内容。
- Post-fix evidence：刷新后左、右面板 `data-state` 均为 `expanded`；左栏宽 306px，右栏宽 340px；“收缩实时态势面板”和“收缩BEV与实时事件面板”按钮均存在。
- Interaction evidence：自动化覆盖默认展开、手动收缩、悬停展开和锁定/取消锁定；真实浏览器刷新后双栏保持默认展开。

### Visual fidelity review

- 字体与排版：面板内原有字号、字重、图表标签与事件层级未改动。
- 间距与布局：沿用既有 expanded 宽度和 40% 透明度；中央画面仍完整可见，时间轴与顶部上下文没有被遮挡或裁切。
- 色彩与资产：玻璃面板、状态色、BEV 底图、图标和图表配色均未替换。
- 文案与内容：未新增展示文案；实时态势、质量状态、BEV 轨迹和事件事实保持真实运行态。
- Console：最终验收标签页 0 error / 0 warning。

### Verification

- [x] 1357 × 912 同视口修改前后并排比较。
- [x] 左右面板默认状态、宽度和收缩按钮量测。
- [x] 手动收缩、悬停展开与锁定行为自动化验证。
- [x] Console2 全量 79/79 自动化测试。
- [x] Vite production build。

### Follow-up polish

- 无阻断性或 P3 跟进项。

final result: passed

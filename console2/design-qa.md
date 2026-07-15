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

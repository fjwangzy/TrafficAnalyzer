# TrafficAnalyzer 客户演示前全面测试方案与计划

> 制定日期：2026-07-18  
> 目标环境：当前工作树重建后的本机 canonical Compose  
> 目标：证明客户演示主链可用、数据表达可信、异常可恢复，并形成带证据的问题清单与 Go/No-Go 结论  
> 边界：本计划是本机客户演示就绪验收，不替代生产镜像、共享 UAT、TLS/SASL、HA、容量及 RPO/RTO 正式验收

## 1. 当前基线与测试原则

计划制定时已确认：

- 根 Compose 的 `road9`、`kafka`、`platform`、`console2`、`nginx` 正在运行；`8080`、`8000/ready`、`8009/ready` 返回 200，匿名业务 API 返回 401。
- 当前工作树包含在途改动，运行中的 Console2 镜像不能代表当前源码；正式测试前必须基于当前工作树重新构建并重启根 Compose。
- 当前源码自动化基线：Console2 `14 files / 75 tests passed`，生产构建成功；Platform `126 passed / 5 skipped / 10 subtests passed`；根契约组 `17 passed`。
- 历史审查结论保留在 `docs/UAT_FULL_REVIEW_2026-07-17.md`；本轮不改写历史结论，另行生成演示就绪报告。

执行遵循以下原则：

1. **先冻结、后重建、再测试**：记录 Git 基线、工作树差异、镜像 ID、迁移版本和配置摘要，确保问题可复现。
2. **客户路径优先**：管理员完成全部业务主链；`operator/viewer` 验证真实后端权限；管理员角色预览覆盖 commander、enforcement、survey、analyst 的导航和工作区边界。
3. **真实数据优先**：使用 `road9` 已有真实/验收事实和 `inter_xqh` MP4+DJI SRT；测试夹具必须明确标记，禁止把 Mock、测试坐标或未核验数据包装成权威事实。
4. **读写分层**：第一轮先完成只读路径和现状取证，再使用 `DEMO-UAT-20260718-*` 标记创建可清理测试记录；不修改或删除既有业务证据。
5. **失败留证**：发现问题先保存截图、URL、请求响应、浏览器日志和服务日志，再决定是否重试；不得用刷新或重启掩盖首现缺陷。

## 2. 覆盖范围与测试矩阵

### 2.1 环境、数据链与自动化门禁

| 编号 | 覆盖项 | 关键检查 | 通过标准 |
|---|---|---|---|
| ENV-01 | 基线冻结 | 当前分支/提交、`git status`、diff 校验和、Compose 配置、镜像 ID | 报告可定位到唯一测试基线 |
| ENV-02 | 重建与启动 | 根 Compose 重新构建、启动、依赖顺序、healthcheck、Alembic head | 5 个正式服务启动；Platform、road9、Kafka 健康；无旧链路服务 |
| ENV-03 | 路由入口 | Console2、Nginx、Platform、REST、WS、MJPEG/HLS | 正式入口可达；匿名受保护资源返回 401；无错误代理或绕过 |
| ENV-04 | canonical 契约 | `uav_*` Topic、`msg_type`、WebSocket channel、数据库表 | 无旧 Topic/channel/fallback；ADR-019 strict audit 通过 |
| ENV-05 | 自动化回归 | Platform、Console2、根契约、静态检查、构建 | 所有必跑项通过；skip 与 warning 有解释 |
| ENV-06 | 真实管道 | `inter_xqh` MP4+SRT、检测/遥测/世界坐标/冲突/Kafka | `56 PASS / 0 FAIL / 0 WARN`；真实视频链路按演示配置可启动和自然结束 |

### 2.2 认证、会话与权限

- 未登录访问首页及业务深链时跳转登录，登录后安全回跳原目标；非法外部 redirect 被拒绝。
- 错误密码、禁用用户、失效/篡改 Token、会话恢复、退出登录和重复退出均有明确且可恢复的反馈。
- `admin` 可进入全部模块；`operator` 映射 commander，`viewer` 映射 analyst，只能看到与真实授权一致的页面和操作。
- 管理员角色预览分别切换 commander、enforcement、survey、analyst，验证一级/二级导航、无权限页面和返回路径；角色预览不得改变后端真实权限。
- 管理员控制面、媒体、WebSocket、Pipeline/视频启动停止等接口执行匿名、viewer、operator、admin 四档越权验证。
- 浏览器存储、URL、Nginx 访问日志和错误信息不得暴露可重放凭据。

### 2.3 客户可见业务主链

| 业务域 | 管理员深测主链 | 数据与展示重点 |
|---|---|---|
| 登录与工作台 | 登录 → 全域工作台 → 重点路口 → 实时监测/轨迹研判 | 首屏 5 秒内可辨识；KPI、范围、时间、新鲜度、测试坐标和未核验状态表达真实 |
| 实时监测 | 路口切换 → MJPEG/BEV 主次切换 → WS 更新 → 暂停/恢复 → 告警下钻 | 视频、轨迹、统计和事件属于同一路口；暂停不继续刷新；恢复补齐当前状态 |
| AI 事件中心 | 筛选 → 详情 → 证据 → 技术确认/驳回 → 刷新复核 | 风险、TTC/PET、场景、质量、证据和 revision 可解释且持久化 |
| 轨迹研判 | 路口/时间筛选 → 轨迹地图 → 轨迹详情 → 冲突关联 | 不出现“有数量无折线”；世界坐标、任务/来源/路网/质量 lineage 清楚 |
| 事故测绘 | 创建任务 → 前置核验 → 导入/上传 MP4+SRT → 关键帧 → 点线面量算 → 技术复核 → 报告 | 真实图片、边长、版本、证据哈希、PDF/JSON/GeoJSON、投递门禁一致；无效深链可恢复 |
| 执法线索 | 线索筛选 → 证据 → 技术复核 → 候选区域/规则 → 货车专题 | 明确“技术线索而非违法认定”；候选与权威发布边界真实；revision 冲突可解释 |
| 飞行任务 | 无人机 → 数据源校验 → 计划创建/冲突 → Mission → 停止/重试/自然 EOF | MP4+SRT/RTSP/MQTT 边界、敏感字段脱敏、Mission/Pipeline 终态和审计一致 |
| 标定中心 | 标定汇总 → 标注任务 → 图片加载 → 多边形绘制/闭合/保存 | 图片自然尺寸坐标、车道几何、覆盖率和保存结果一致；刷新后可恢复 |
| 系统与身份 | 服务健康 → Kafka/Consumer → 模型/GPU → 用户 | 健康状态不假绿；部分依赖失败明确降级；身份页只展示实际开放能力 |
| 集成与交付 | 访问默认关闭路由 | 页面明确不可执行；入口、API 和导航均不能把夹具或内存操作呈现为真实治理能力 |

每条主链至少执行：正常路径、真实空态、输入校验失败、依赖失败或无权限路径、刷新后持久化验证。涉及大文件和长管道的路径允许复用已验证材料，但必须重新完成一次客户可见 smoke。

### 2.4 跨模块、视觉与非功能检查

- **跨端一致性**：同一事件/任务/路口在工作台、监控、GIS、事件、测绘或 Mission 页面中的 ID、状态、时间和质量标签一致。
- **浏览器洁净度**：每个正式路由记录 HTTP 状态、页面标题、未捕获异常、console error/warning、失败请求和 WebSocket 状态；目标为 0 个未解释错误/警告。
- **响应式视觉**：至少覆盖 `1024×768`、`1366×768`、`1440×900`、`1920×1080`；检查横向溢出、遮挡、弹窗、表格、地图、画布和导航。
- **键盘与可访问性**：Tab 顺序、可见焦点、Enter/Space、Esc、dialog 焦点恢复、表单标签、状态非纯颜色表达；关键流程做一次键盘完成测试。
- **演示性能门槛**：本机演示网络下，登录后首页 5 秒内可操作，普通页面切换 3 秒内出现有效内容或明确加载态，操作提交 2 秒内出现反馈；长任务显示进度且不假成功。该门槛仅用于演示就绪，不声明为生产 SLA。
- **稳定性**：连续巡检所有正式路由两轮；快速切换页面、重复打开抽屉/弹窗、刷新深链、重复提交幂等请求，不出现白屏、卡死、重复事实或内存假状态。
- **恢复能力**：在功能取证后依次注入 Console2 刷新、Platform 重启、Kafka 短时断开、WS 断开恢复和 road9 短时不可用；验证 `200 → degraded/503 → 200`、重连、状态回补和无重复副作用。
- **安全 smoke**：匿名注册、WS publish、媒体匿名访问、query token、路径/RTSP/端口 allowlist、CSP/安全头和敏感错误信息按既有安全契约复验。

## 3. 执行步骤与时间安排

计划按一个完整工作日执行；若发现 P0/P1，则立即输出 No-Go，不以压缩后续步骤换取表面完成。

| 阶段 | 预计用时 | 执行内容 | 阶段产物 |
|---|---:|---|---|
| 0. 基线冻结 | 30 分钟 | 记录 Git/工作树、Compose、镜像、Alembic、服务与测试数据；确认测试账号和素材 | `环境基线`、数据清单 |
| 1. 重建与预检 | 45 分钟 | 重建根 Compose，检查健康、迁移、入口、日志、旧链路隔离 | 环境 smoke 证据 |
| 2. 自动化门禁 | 60 分钟 | 并行执行前后端、根契约、构建、Ruff、ADR-019 和静态检查 | 自动化结果表 |
| 3. 管理员业务主链 | 3 小时 | 按 2.3 顺序完成所有客户可见业务域与写入路径 | 每域截图、trace、请求/日志证据 |
| 4. 角色与异常矩阵 | 90 分钟 | 真实账号权限、管理员角色预览、无权限、空态、错误输入、会话失效 | 权限矩阵、异常清单 |
| 5. 视觉/性能/恢复 | 90 分钟 | 四档视口、键盘、两轮巡检、服务/WS/Kafka/DB 恢复 | 视觉证据、计时、恢复记录 |
| 6. 分级与复验 | 90 分钟 | 去重问题、确定严重度、复验关键问题、汇总 Go/No-Go | 演示就绪报告、TASKS 条目 |
| 缓冲 | 2 小时 | 环境恢复、长管道、证据补采和 P1 快速复验 | 不降低门禁的时间余量 |

推荐浏览器执行顺序为：`/login → / → /monitoring → /events → /gis → /survey → /enforcement → /drones → /admin/calibration → /admin/system → /admin/integration`。先只读后写，避免前序操作改变后续展示数据。

### 3.1 必跑命令

```bash
docker compose -p traffic_analyzer up -d --build
docker compose -p traffic_analyzer ps

python -m pytest platform/tests -q
python -m pytest test_kafka_active_trajectories.py test_utils_local.py test_byte_tracker_core.py test_main_optimized_eof.py test_road9_compose_runtime.py test_telemetry_file_reader.py test_video_reader_frame_stride.py -q
cd console2 && npm test && npm run build

python test_pipeline_inter_xqh.py
python -m compileall -q platform/app nodes services main_optimized.py
ruff check platform/app platform/tests nodes services main_optimized.py
python scripts/audit_adr019_retirement.py --scope local --strict
git diff --check
```

浏览器验证使用 Playwright CLI，先 snapshot 再交互，路由切换后重新 snapshot；截图、trace 和页面快照统一放到 `output/playwright/demo-2026-07-18/`。

## 4. 问题记录与处理规则

### 4.1 问题分级

| 级别 | 定义 | 演示处理 |
|---|---|---|
| P0 | 安全越权、数据伪造/丢失、主流程完全不可用、系统崩溃 | 立即 No-Go，停止演示版本放行 |
| P1 | 核心演示步骤失败、严重误导、不可恢复白屏/断线、关键依赖假健康 | No-Go；修复并重跑影响域和全局 smoke |
| P2 | 有明确绕行方案但显著影响理解、效率、视觉可信度或辅助功能 | 原则上演示前关闭；确需接受时记录责任人和现场绕行 |
| P3 | 文案、间距、轻微视觉或低频维护问题 | 可带风险放行，但必须记录，不在现场临时解释为“正常” |

### 4.2 单条问题模板

```text
ID：DEMO-20260718-001
标题：[P1][实时监测] 切换路口后视频与 BEV 数据不一致
环境：Git 基线 / 镜像 ID / 浏览器 / 视口 / 账号角色
前置条件：数据、路口、任务或会话状态
复现步骤：1... 2... 3...
预期结果：
实际结果：
客户影响：
证据：截图、trace、console、请求响应、服务日志
严重度与理由：
临时绕行：无 / 具体步骤
责任域：Console2 / Platform / Pipeline / Data / Environment
状态：open / fixed / retest_passed / deferred
关闭证据：修复提交或工作树、回归命令、复验截图
```

去重时以“同一根因 + 同一修复”合并；不同业务影响不得仅因日志相同而合并。P0/P1 必须有独立复现和关闭证据，不能只写聊天结论。

## 5. 放行门禁与交付物

### 5.1 Go 条件

以下条件全部满足才可标记“客户演示 Go”：

1. 测试版本已从当前冻结基线重建，运行版本与测试版本一致。
2. 必跑自动化、生产构建、真实 `inter_xqh`、ADR-019 strict audit 和 `git diff --check` 全部通过。
3. 管理员全部客户主链通过，`operator/viewer` 与管理员角色预览权限矩阵通过。
4. 所有正式路由两轮巡检无白屏、未解释 4xx/5xx、console error/warning 或不可恢复断线。
5. P0/P1 为 0；P2 仅允许有书面接受、责任人和不影响主线的现场绕行；P3 已登记。
6. 页面不把 Mock、验收测试坐标、未核验 KPI、候选规则或本地治理能力表述为权威/生产事实。
7. 演示需要的真实数据、账号、素材、网络与恢复预案已在最终彩排中验证。

任一核心路径失败、健康状态假绿、权限绕过、视频/轨迹/事件串线、数据真实性误导、测试版本与演示版本不一致，均直接判定 No-Go。

### 5.2 交付物

- 本计划：`docs/DEMO_TEST_PLAN_2026-07-18.md`。
- 执行报告：`docs/DEMO_READINESS_REPORT_2026-07-18.md`，记录基线、逐项结果、问题、复验和最终 Go/No-Go。
- 问题台账：开放问题同步到 `docs/TASKS.md`，保留原问题 ID、严重度、责任域和关闭证据。
- 浏览器证据：`output/playwright/demo-2026-07-18/` 下按业务域保存截图、snapshot 和 trace。
- 运行证据：Compose 状态、迁移、自动化结果、关键 API/WS/MJPEG 响应和故障恢复日志纳入执行报告或其引用附件。

## 6. 默认假设

- 客户演示使用本机根 Compose 和当前工作树构建版本，不以当前旧容器或共享 UAT 作为最终结论基线。
- 管理员账号跑完整链路；`operator/viewer` 只做后端授权和典型业务路径，admin 角色预览补齐五类前端业务视角。
- 允许创建带 `DEMO-UAT-20260718-*` 前缀的测试数据和执行受控服务故障注入；不删除既有业务证据，不挂载 ADR-019 退役存储。
- 默认演示治理功能保持关闭；生产镜像、共享 UAT 和外部合同阻断继续单独标记，不用本机演示通过替代正式验收。

# TrafficAnalyzer 客户演示就绪测试报告

> 执行日期：2026-07-18（Asia/Shanghai）  
> 测试范围：当前工作树重建后的本机 canonical Compose、Console2 客户界面、Platform/API、Kafka、road9/TimescaleDB、真实 `inter_xqh` MP4+SRT 管道  
> 依据：[`DEMO_TEST_PLAN_2026-07-18.md`](DEMO_TEST_PLAN_2026-07-18.md)  
> 最终结论：**No-Go**  
> 复验更新：2026-07-19 已关闭 DEMO-20260718-001；当前剩余 1 个 P1、4 个 P2，仍因 readiness 假健康保持 No-Go

## 1. 执行结论

本轮按计划完成了环境重建、自动化门禁、两轮全路由巡检、管理员业务主链、真实角色权限、四档视口、键盘、认证边界、安全 smoke、真实 S9 调度/Mission/Pipeline/MJPEG 以及 Platform、Kafka、road9、WebSocket 故障恢复测试。

自动化与当前源码业务能力总体稳定：Platform、Console2、根契约、静态检查、ADR-019 strict audit 和 `inter_xqh 56 PASS / 0 FAIL / 0 WARN` 全部通过；客户可见的无人机登记、MP4+SRT 数据源校验、飞行计划启用、Mission 调度、实时视频/轨迹/统计、停止审计、执法候选、事件详情、测绘标注图与真实 PDF 均已实测。

初始测试发现 **2 个 P1**，违反客户演示 Go 门禁：

1. 当前工作树构建的生产 Console2 镜像因 Nginx 配置语法错误持续重启，正式 `8080` 入口完全不可用。该项已于 2026-07-19 修复并复验关闭。
2. `/ready` 对 Kafka 和 road9 故障存在假健康/错误 HTTP 语义，关键依赖故障时仍可能被 Compose 或外部门禁判为健康。

另有 **4 个 P2**：实时监测轮询错误无人机 ID、执法候选弹窗键盘焦点失效、Vite 6.4.2 高危开发服务器公告、GIS 缺少可演示的历史轨迹事实。当前仍有 DEMO-20260718-002 这一 P1 未关闭，因此版本仍不能直接用于客户演示。

## 2. 测试基线

| 项目 | 冻结值 |
|---|---|
| 分支 / 提交 | `codex/2.0` / `47eb404890be33931a8a51e4554b2cc2441a3e31` |
| 工作树 | 存在用户在途改动；本轮保留原改动，仅新增测试计划/报告并更新任务台账 |
| tracked diff SHA-256 | `967b9d1b49dc8f743e41007428eb265eeae2575dead7a89d5d8c490ca301a4dd` |
| Platform 镜像 | `sha256:cee9e94aec452dbb006612e176f81c3ae07572a87ed37cdc71d49ecf9c2ad7a0` |
| Console2 镜像 | `sha256:792c0246bf92f8462749ddcdef527806ee5e67c84c86d8ea0150da59cdb744d1` |
| Console2 复验镜像 | `sha256:3e82e867e9084ccd6266694f9a867c1e9dd3ad2627c56f45a06deb11282cd1d0`（2026-07-19） |
| Alembic | `20260717_0013 (head)` |
| Python / Node / npm | Python 3.12.11 / Node 26.0.0 / npm 11.12.1 |
| 正式拓扑 | `road9 + kafka + platform + console2 + nginx`；未发现旧 PostgreSQL/Topic/观测服务回流 |
| 最终活动管道 | `0`；测试 Mission 已通过 UI 停止并持久化 `manual_stop` |

初始测试环境中 Console2 处于 `Restarting (1)`。2026-07-19 复验后，road9、Kafka、Platform 健康，外层 Nginx 运行，Console2 已稳定 `Up`，正式 `8080` 入口恢复 200。

## 3. 自动化与运行门禁

| 检查 | 结果 | 结论 |
|---|---|---|
| `python -m pytest platform/tests -q` | `126 passed, 5 skipped, 10 subtests passed`，1 条 Starlette/httpx 弃用 warning | 通过；skip/warning 非本轮阻断 |
| 根契约与运行组 | `19 passed` | 通过 |
| `cd console2 && npm test` | `14 files / 75 tests passed` | 通过 |
| 2026-07-19 Console2 复验 | `nginx -t` 成功；`14 files / 76 tests passed`；`8080`、`/health` 为 200；匿名业务 API 为 401 | DEMO-20260718-001 关闭 |
| `npm run build` | 构建成功，最大 chunk 403.66 kB | 通过 |
| `python -m compileall ...` | 无错误 | 通过 |
| `ruff check ...` | `All checks passed` | 通过 |
| `git diff --check` | 无错误 | 通过 |
| ADR-019 strict audit | 9 项全部通过 | 通过 |
| `python test_pipeline_inter_xqh.py` | `56 PASS / 0 FAIL / 0 WARN` | 通过；100/100 检测与遥测，90/100 运动补偿 |
| `npm audit --omit=dev --registry=https://registry.npmjs.org` | 1 个 high，Vite 6.4.2 | 不通过；见 DEMO-20260718-005 |
| 生产 Console2 `nginx -t` | exit 1 | 不通过；见 DEMO-20260718-001 |

## 4. 浏览器与客户业务覆盖

### 4.1 路由、视觉与性能

两轮巡检覆盖：

`/`、`/monitoring`、`/events`、`/gis`、`/survey`、`/enforcement`、`/enforcement/zones`、`/enforcement/trucks`、`/drones`、`/admin/calibration`、`/admin/system`、`/admin/integration`，并验证无效测绘深链和未知路由。

- 第二轮全部路由 HTTP 200，H1 正确，无持续 loading，无页面级横向溢出；有效内容时间为 1.10–1.20 秒，满足 3 秒演示门槛。
- `1024×768`、`1366×768`、`1440×900`、`1920×1080` 四档视口通过；首页、监控、测绘、系统页未发现遮挡或横向溢出。
- `/admin/integration` 正确显示“集成与交付未启用”，没有可执行治理动作。
- 无效测绘任务显示“任务不可用 / survey task not found / 返回任务列表 / 重试”；未知路由安全回到 `/`。
- 浏览器错误均可归因于故意的 401/403/404/422 负向探测、受控重启或已登记问题；没有未解释白屏或未捕获异常。

### 4.2 认证、会话与权限

| 场景 | 结果 |
|---|---|
| 错误密码 | 401，页面明确提示，可恢复 |
| 外部 redirect | 登录后回到本源 `/`，未跳转 `evil.example` |
| 篡改 Token | Token 被清除，回到 `/login?redirect=...` |
| 30 分钟 Token 到期 | 自动回登录；重新登录恢复原深链 |
| 退出 / 重复退出 | 首次清除会话并回登录；重复退出幂等返回 200 |
| 禁用账号 | 临时禁用标记测试 viewer 后登录返回 401；随后已恢复启用 |
| 匿名注册 | 401 |
| WS query token | HTTP 403，拒绝握手 |
| 匿名 MJPEG / HLS | 401 |

真实 API 权限矩阵：

| 角色 | Dashboard / Pipeline / Survey 读 | Users / System / Calibration | Pipeline 写 | Drone / Enforcement 写 |
|---|---:|---:|---:|---:|
| admin | 200 | 200 | 允许；无效输入 422 | 允许；无效输入 422 |
| operator | 200 | 403 | 允许；无效源 422 | 403 |
| viewer | 200 | 403 | 403 | 403 |
| anonymous | 401 | 401 | 401 | 401 |

管理员角色预览已覆盖交通指挥员、交通执法人员、事故处理民警、数据分析员和系统管理员；导航与工作区边界符合预期，预览没有扩大真实后端权限。

### 4.3 客户可见主链

- **工作台/监控**：真实管道运行时显示 1280×720 MJPEG、YOLO11/ByteTrack 检测框、244 条活动轨迹、实时统计/事件和 World/BEV 画布；停止后明确显示“监测离线 / 数据过期”，没有用缓存伪装实时。
- **事件中心**：15 条真实事实可见；事件详情包含事件 ID、路口、Mission/Pipeline、数据源、路网版本、质量、证据哈希和技术复核责任边界。
- **轨迹研判**：页面和筛选正常，但当前 road9 返回 0 条历史轨迹/世界坐标/冲突，无法完成有数据下钻；见 DEMO-20260718-006。
- **事故测绘**：7 个任务可见；`SVY-20260716-9C64D0` 报告含 1767×1000 标注图、4 项量算、证据哈希和真实 PDF blob，PDF 可在新窗口打开。
- **执法线索**：创建并持久化候选区域 `ZONE-C871FCBCD8B7` 和候选规则 `RULE-614E1F5BEAC1`，保持 candidate/unverified/阻断权威发布语义。
- **飞行任务**：登记无人机、校验 MP4+SRT 数据源、创建并启用单次计划；调度产生 Mission 和 Pipeline，监控取证后经 UI 停止，终态为“已停止 / stopped / manual_stop”。
- **标定中心**：8 个车道标注任务、4 组视觉参数和真实图像可见；已有车道和 3840×2160 画面尺寸可恢复。标定记录和坐标覆盖为空时页面如实表达。
- **系统与身份**：模型/GPU、Consumer、角色与服务状态可见；依赖假健康另列 P1。

## 5. 真实 S9 测试事实

| 类型 | 测试事实 |
|---|---|
| 账号 | `demo_uat_operator_20260718`、`demo_uat_viewer_20260718` |
| 无人机 | `DEMO-UAT-DRONE-20260718` |
| 数据源 | `SRC-E2BA6A8F6D0F`；MP4 + SRT；校验状态 valid |
| 计划 | `PLAN-72C61B67DB35` / `DEMO-UAT-PLAN-20260718`；enable 后 revision 2 |
| Mission | `MSN-AD3F3E80D3BC`；计划启动偏差 +35s；最终 `manual_stop` |
| Pipeline | `pipe-a0c6fe8c`；camera 10；`uav_statistics_10`；最终 stopped |
| 执法候选 | `ZONE-C871FCBCD8B7`、`RULE-614E1F5BEAC1` |

这些记录均为本机演示验收事实，不得作为权威生产数据。现有业务证据未删除或覆盖。

## 6. 故障恢复结果

| 注入 | 观察 | 恢复 |
|---|---|---|
| Platform restart | 容器重新启动；`/ready` 恢复 200 | 通过 |
| WebSocket 断开 | 浏览器记录一次握手中断；12 秒内重新显示“实时链路已连接” | 通过 |
| Kafka stop | 停止 25 秒后 `/ready` 仍为 `ready`、`kafka: healthy`、HTTP 200 | **失败**，见 DEMO-20260718-002 |
| road9 stop | `/ready` 显示 `timescaledb: degraded`，但 `database: healthy` 且 HTTP 200 | **失败**，见 DEMO-20260718-002 |
| Kafka / road9 restore | 容器回到 healthy，`/ready` 恢复全 healthy | 通过 |

## 7. 问题清单

### DEMO-20260718-001 — [P1][Console2][已关闭] 生产镜像 Nginx 配置无效，正式前端持续重启

- **前置条件**：当前工作树执行 `docker compose -p traffic_analyzer up -d --build`。
- **复现**：查看 `docker compose ps console2` 或运行 `docker run --rm traffic_analyzer-console2 nginx -t`。
- **预期**：Console2 容器健康，`8080` 可访问。
- **实际**：容器持续 `Restarting (1)`；日志为 `unknown directive "8,}\\.(?:js|css)$" in /etc/nginx/conf.d/default.conf:29`。
- **根因证据**：`console2/nginx.conf:29` 的未加引号正则被 Nginx 拆为指令。
- **客户影响**：正式客户界面完全不可用；无绕行可作为正式制品证明。
- **临时绕行**：Vite 4173 仅用于继续测试，不允许用于客户演示放行。
- **修复**：`console2/nginx.conf:29` 将资产缓存正则整体加双引号；`console2/src/build-config.test.js` 增加防回归断言。
- **关闭证据**：2026-07-19 构建镜像 `sha256:3e82e867e9084ccd6266694f9a867c1e9dd3ad2627c56f45a06deb11282cd1d0`；镜像内 `nginx -t` 成功；容器跨过原重启周期稳定 `Up`；`8080` 与 `/health` 返回 200；安全头完整；匿名业务 API 返回 401；Console2 `14 files / 76 tests passed`。
- **责任域 / 状态**：Console2 / Environment；`retest_passed`。

### DEMO-20260718-002 — [P1][Platform] readiness 对 Kafka/road9 故障假健康且始终返回 HTTP 200

- **复现**：分别停止 Kafka、road9 后请求 `http://127.0.0.1:8000/ready`。
- **预期**：关键依赖断开后及时返回 degraded/503；恢复后回 200。
- **实际**：Kafka 停止 25 秒仍返回 `ready`、`kafka: healthy`、HTTP 200；road9 停止时 `timescaledb: degraded`，但 `database: healthy` 且 HTTP 200。
- **根因证据**：`platform/app/main.py:251-294` 使用启动时 `db_available`、Kafka `_running/_consumer` 对象存在性，并始终返回普通 dict/HTTP 200，没有实时连通性探测或非 2xx 响应。
- **客户影响**：Compose/门禁会把已失去实时消息或数据库的系统判为健康，现场可能在绿灯状态下展示陈旧数据。
- **责任域 / 状态**：Platform / Environment；`open`。

### DEMO-20260718-003 — [P2][实时监测] 遥测轮询使用 camera ID 拼接无人机 ID，持续 404

- **前置条件**：真实 Pipeline `camera_id=10`、`drone_id=DEMO-UAT-DRONE-20260718` 正在运行。
- **实际**：页面每 10 秒请求 `/api/v1/telemetry/drone_10` 并得到 404；正确无人机端点返回 200。实时画面和 WS 数据仍可见。
- **根因证据**：`console2/src/App.jsx:141` 固定调用 `platformApi.telemetry(\`drone_${cameraId}\`)`，没有优先使用 Pipeline 的真实 `drone_id`。
- **客户影响**：持续浏览器错误、REST 回补失效；WS 抖动时遥测更易回退为过期。
- **责任域 / 状态**：Console2；`open`。

### DEMO-20260718-004 — [P2][可访问性] 执法候选弹窗不接管/约束焦点，Esc 无法关闭

- **复现**：打开“新建候选区域”，观察焦点；按 Tab、Esc。
- **实际**：焦点仍在背景“新建候选区域”按钮，Tab 进入背景页签；Esc 后 dialog 仍存在。
- **根因证据**：`console2/src/pages/EnforcementPages.jsx:114`、`:121` 仅声明 `role=dialog/aria-modal`，未实现初始焦点、焦点环、Esc 和关闭后的焦点恢复。
- **客户影响**：键盘用户可能误操作背景页面，无法完成关键配置流程。
- **责任域 / 状态**：Console2；`open`。

### DEMO-20260718-005 — [P2][供应链] Vite 6.4.2 命中高危开发服务器公告

- **证据**：`console2/package.json:22` 固定 Vite 6.4.2；官方 npm audit 报 1 high，修复版本 6.4.3。
- **公告**：`GHSA-v6wh-96g9-6wx3`、`GHSA-fx2h-pf6j-xcff`，主要涉及 Windows 开发服务器 UNC/`server.fs.deny` 边界。
- **影响边界**：正式 Linux/Nginx 镜像只服务静态 `dist`，不运行 Vite；但开发/测试兜底服务不应继续使用受影响版本。
- **责任域 / 状态**：Console2 / Supply chain；`open`。

### DEMO-20260718-006 — [P2][演示数据] GIS 历史轨迹主链没有可演示事实

- **复现**：管理员进入 `/gis`，选择全部验收数据或当前 Mission/数据源。
- **实际**：4 个路口可选，但历史轨迹、世界坐标、真实冲突均为 0；无法下钻轨迹详情或冲突关联。
- **对照**：实时监控期间曾显示 244 条活动轨迹，说明检测/实时链路可用；问题集中在历史持久事实或演示数据预置。
- **客户影响**：客户无法现场体验“轨迹研判”核心价值，只能看到真实空态。
- **责任域 / 状态**：Data / Platform；`open`。

## 8. 放行门禁与复验要求

当前保持 **No-Go**。至少完成以下动作后才可重新判定：

1. [x] DEMO-20260718-001 已修复：正式 Console2 镜像、`nginx -t`、容器稳定性、`8080`、安全头和 API 代理已复验通过。
2. 修复 DEMO-20260718-002，Kafka/road9 断开必须使 readiness 在约定时间内返回非 2xx，恢复后回 200；补充自动化故障注入。
3. 修复并复验 DEMO-20260718-003；活动 Pipeline 下浏览器不得再出现错误无人机 ID 的 404。
4. DEMO-20260718-004/005/006 演示前关闭；如延期，必须有责任人、接受人、现场绕行和明确不演示范围。
5. 基于修复后的同一工作树重新构建正式 Compose，重跑自动化、全路由 smoke、真实 S9 Mission/MJPEG、两项 P1 故障注入和 `git diff --check`。

## 9. 证据索引

- Playwright 根目录：`output/playwright/demo-2026-07-18/`
- 完整 trace：`.playwright-cli/traces/trace-1784354235118.trace`
- 网络日志：`.playwright-cli/traces/trace-1784354235118.network`
- 活动管道截图：`.playwright-cli/page-2026-07-18T06-25-04-411Z.png`
- 四档视口截图：`.playwright-cli/page-2026-07-18T06-08-21-023Z.png`、`06-08-40-728Z.png`、`06-08-59-812Z.png`、`06-09-19-646Z.png`
- 关键页面截图：工作台 `06-09-58-277Z.png`、监控空态 `06-10-14-184Z.png`、测绘列表 `06-10-25-813Z.png`
- 实时遥测 404 日志：`.playwright-cli/console-2026-07-18T06-23-13-960Z.log`
- WS 受控重启日志：`.playwright-cli/console-2026-07-18T06-38-14-380Z.log`

本报告只证明当前本机演示版本的执行结果，不替代共享 UAT、生产镜像 pin、秘密管理、TLS/SASL、HA、容量、保留策略和 RPO/RTO 门禁。

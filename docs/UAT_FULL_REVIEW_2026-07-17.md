# TrafficAnalyzer 发布 UAT 前全量审查报告

> 审查日期：2026-07-17  
> 审查基线：`codex/2.0`，`47eb404890be33931a8a51e4554b2cc2441a3e31`  
> 审查方式：前端、后端子代理分离审查并统一修复；主审覆盖跨端契约、数据链、运行态和发布门禁。  
> 复验时间：2026-07-17  
> 结论：**应用代码 Gate A/P0 与非镜像 Gate B 已关闭；完整发布 UAT 仍为 No-Go，仅剩用户明确延期的镜像/发布制品与共享环境门禁。**

## 1. 结论摘要

本机 canonical 拓扑和修复后的应用回归均健康：`road9/TimescaleDB + Kafka KRaft + Platform + Console2 + Nginx` 正在运行，数据库已迁移到唯一 Alembic head `20260717_0013`，ADR-019 本机严格审计重新生成并通过。匿名注册提权、WebSocket 注入、SRT 超容差、控制面 RBAC、媒体鉴权、Kafka 副作用恢复、测绘深链/复核、Demo 隔离、暂停语义、拆包、可访问性和静态质量问题均已关闭。

本轮按确认范围不修改 Dockerfile、`.dockerignore`、Compose 镜像版本、SBOM/签名和共享 UAT 基础设施。因此完整发布 UAT 仍不能放行，剩余阻断集中为：

1. GPU 检测镜像仍需证明包含遥测模块并完成 camera 3 smoke；
2. 仍需从干净提交构建、固定 digest、生成 SBOM/签名和发布清单；
3. 共享 UAT 的 secret、TLS/SASL、端口暴露、容器最小权限与健康探针尚未实施。

应用源码可进入下一步“制品化复验”，但不得把当前本机源码/开发 Compose 直接标记为完整 UAT 候选。

### 1.1 统一修复状态

| 审查域 | 状态 | 落地结果 |
|---|---|---|
| Gate A / P0 | 已关闭 | 注册改为管理员受控；WS 客户端 publish 拒绝；SRT offset/tolerance/越界回归通过 |
| 后端安全与恢复 | 已关闭 | REST/媒体/WS 三类鉴权、active-user 回查、控制面 RBAC、`uav_audit_logs`、RTSP/路径/并发 allowlist、Kafka earliest + 可恢复 dispatch 状态机 |
| 测绘主流程 | 已关闭 | 8GB 一致上限、五类深链错误态、六项受控复核清单、后端强制门禁与审计 |
| 前端可信边界 | 已关闭 | Demo 治理默认物理拆出且关闭；暂停冻结 WS/REST/可见时间；路由 lazy/error boundary；键盘/dialog 语义 |
| 性能与静态质量 | 已关闭 | 入口 35.00 KiB、最大 chunk 403.66 KiB；Ruff 全范围通过；新增代码 CI 门禁 |
| 镜像与共享 UAT | 延期阻断 | 遵照范围未修改 Docker/镜像；制品 pin、SBOM、签名、共享 secret/TLS/HA 等继续 No-Go |

## 2. 审查范围与分级

- 前端：`console2/` 的路由、认证、真实/模拟边界、测绘/实时/治理流程、错误态、可访问性、性能、Nginx 和构建。
- 后端：`platform/app/`、API、认证授权、Kafka/WS/TimescaleDB、Alembic、Mission/Pipeline、`nodes/`、`services/` 和 `main_optimized.py`。
- 集成与发布：根 Compose、Dockerfile、依赖可重复性、运行态、ADR-019、文档一致性和工作树基线。

严重度：P0 为必须立即修复且禁止进入 UAT；P1 为进入相关 UAT 范围前必须关闭或物理隔离；P2 为 UAT 期间应完成的质量/安全改进；P3 为体验和维护性优化。

## 3. P0 Findings（复验全部关闭）

以下保留初审证据作为审计轨迹；“改进”段为当时方案，当前状态以标题和第 1.1 节为准。

### UAT-P0-01 匿名注册可自授管理员角色【已关闭】

- 证据：[`platform/app/middleware/auth.py:12`](../platform/app/middleware/auth.py) 将 `/api/v1/auth/register` 列为公开路径；[`platform/app/api/v1/auth.py:15`](../platform/app/api/v1/auth.py) 无额外授权直接创建用户；[`platform/app/schemas/auth.py:7`](../platform/app/schemas/auth.py) 允许请求传入 `admin|operator|viewer`。本机匿名无效载荷探测返回 422 而非 401，确认入口公开且进入业务校验。
- 影响：攻击者可创建管理员，随后访问系统、用户、标定和其他控制面，属于直接权限提升。
- 改进：UAT/生产关闭公开注册；管理员只能由受控 bootstrap、统一身份或管理员邀请创建。即使保留自注册，服务端也必须强制 `viewer`，忽略客户端角色，并增加匿名/越权回归测试。

### UAT-P0-02 已认证客户端可向实时通道注入伪业务消息【已关闭】

- 证据：[`platform/app/kafka/ws_manager.py:82`](../platform/app/kafka/ws_manager.py) 接受客户端消息；[`platform/app/kafka/ws_manager.py:114`](../platform/app/kafka/ws_manager.py) 的 `publish` 分支只检查名称是否为 `uav_*`，随后广播；[`platform/tests/test_realtime_channels.py:85`](../platform/tests/test_realtime_channels.py) 还明确验证客户端 publish 成功。WebSocket 中间件只要求有效 JWT，不检查发布权限。
- 影响：普通用户可伪造系统指标、态势、告警或其他 canonical 实时消息，污染所有订阅者的判断。
- 改进：生产/UAT完全移除客户端 `publish`；测试注入只能位于不可发布的开发构建或独立受控管理端，并要求管理员权限、审计和严格 schema。增加 viewer/operator 拒绝测试。

### UAT-P0-03 SRT 遥测忽略同步容差并可能返回过期记录【已关闭】

- 证据：[`services/SrtTelemetryParser.py:157`](../services/SrtTelemetryParser.py) 用 `lookup_t` 二分查找，却在 166 行用未偏移的 `frame_timestamp` 计算差值，并在 172 行无条件返回记录。实测 `offset=10s`、查询 `0s` 返回 `9.977s`；查询超出文件范围的 `2000s` 仍返回末条 `992.325s`，而不是 `None`。正确实现可对照 [`services/TelemetryFileReader.py:125`](../services/TelemetryFileReader.py)。
- 影响：视频与遥测断档时，旧 GPS/姿态被当成当前帧数据继续进入单应性、运动补偿、轨迹和证据链，形成静默空间错误。
- 改进：统一以 `lookup_t` 计算最近差值，超容差返回 `None`；补齐正/负 offset、前后越界、采样空洞和精确边界测试，并复跑 MP4+SRT、世界坐标和冲突证据回归。

## 4. P1 Findings（应用项已关闭，镜像/环境项延期）

### UAT-P1-01 管道与视频控制面缺少角色权限和输入边界【已关闭】

- 证据：[`platform/app/middleware/auth.py:100`](../platform/app/middleware/auth.py) 只对 `system/users/calibration` 强制 admin；[`platform/app/api/v1/pipelines.py:125`](../platform/app/api/v1/pipelines.py)、161、211 的启动、外部注册和停止接口没有角色检查；[`platform/app/api/v1/video.py:72`](../platform/app/api/v1/video.py) 还允许触发 FFmpeg。请求可携带 RTSP、文件路径和端口。
- 影响：viewer/operator 可启动高资源子进程、访问非预期网络/路径、注册伪运行态或停止他人管道，带来 SSRF、路径越界、资源耗尽和任务中断风险。
- 改进：把权限收敛为服务端 capability/RBAC 依赖；读权限与 start/register/stop 分开；对 scheme、资产根目录、端口、并发和资源设置 allowlist，所有变更写审计并补充三角色矩阵测试。

### UAT-P1-02 测绘 MP4/SRT 上传会被 Console2 Nginx 默认 1 MB 限制拦截【已关闭】

- 证据：[`console2/src/pages/SurveyPages.jsx:180`](../console2/src/pages/SurveyPages.jsx) 提供大文件上传；[`console2/nginx.conf:1`](../console2/nginx.conf) 未配置 `client_max_body_size`；[`docker-compose.yaml:121`](../docker-compose.yaml) 直接暴露 Console2 `8080`。
- 影响：常规 MP4 在到达 Platform 前返回 413，上传主流程不可用。
- 改进：冻结素材上限，并在 Console2 Nginx、外层入口、Platform、超时、磁盘配额同步配置；增加大于 1 MB 的真实代理集成测试。

### UAT-P1-03 测绘深链在任务读取失败时白屏【已关闭】

- 证据：[`console2/src/pages/SurveyPages.jsx:31`](../console2/src/pages/SurveyPages.jsx) 捕获错误后保留 `task=null`；同文件 129、194、258、301、334 在空态壳层生效前解引用 `task`。
- 影响：404、403、深链 ID 错误或短暂 503 会使五个测绘页面崩溃，无法恢复。
- 改进：统一处理 `loading/error/!task`，提供重试和返回列表；增加五页 403/404/503 测试及根 Error Boundary。

### UAT-P1-04 测绘技术复核清单不构成真实门禁【已关闭】

- 证据：[`console2/src/pages/SurveyPages.jsx:295`](../console2/src/pages/SurveyPages.jsx) 的通过请求不携带清单；301-302 的六项 checkbox 均 `defaultChecked`，不控制按钮，也未持久化。
- 影响：无需实际核对证据即可通过技术复核，页面呈现的审计含义不真实。
- 改进：清单默认不选、受控保存、全部满足才能提交；后端强制验证并记录复核人、时间、证据和规则版本。

### UAT-P1-05 集成治理页面把固定夹具和内存操作呈现为真实运行态【已关闭：UAT 默认物理隔离】

- 证据：[`console2/src/components/AppShell.jsx:77`](../console2/src/components/AppShell.jsx) 固定新鲜度和异常；[`console2/src/pages/AdminPages.jsx:114`](../console2/src/pages/AdminPages.jsx) 起的集成页使用固定 KPI/死信/证据；[`console2/src/state/AppState.jsx:42`](../console2/src/state/AppState.jsx) 的“重放”只改内存并显示成功。
- 影响：UAT 操作员会把演示数据和假成功误认为当前环境事实。
- 改进：接真实 read model 与重放 API；完成前通过 feature flag 隐藏并从 UAT 范围剔除，不能仅靠说明文字降级。

### UAT-P1-06 WebSocket JWT 会进入 Nginx 请求日志【已关闭】

- 证据：[`console2/src/hooks/useWebSocket.js:26`](../console2/src/hooks/useWebSocket.js) 把 JWT 放入 `access_token` query；[`console2/nginx.conf:19`](../console2/nginx.conf) 的 `/ws/` 未关闭或脱敏 access log。
- 影响：有日志读取权限的人可重放有效会话。
- 改进：立即禁用/脱敏 `/ws/` 请求日志并验证无 token；后续迁移到不会进入 URL 的受支持鉴权机制。

### UAT-P1-07 GPU 检测镜像排除了遥测实现，启用遥测后会静默降级【延期阻断】

- 证据：[`.dockerignore:8`](../.dockerignore) 排除整个 `services`；[`Dockerfile:22`](../Dockerfile) 只复制剩余上下文；[`nodes/VideoReader.py:45`](../nodes/VideoReader.py) 动态导入 `services.*`，异常只记 warning；[`docker-compose.yaml:239`](../docker-compose.yaml) 的 camera 3 明确启用 SRT。
- 影响：`gpu-only` 镜像缺少 SRT/MQTT/file reader，检测仍可能继续运行但没有遥测，世界坐标和证据质量失真。
- 改进：把遥测模块纳入镜像；启用遥测时初始化失败必须 fail-fast；为构建后的镜像增加 import 和 camera 3 启动 smoke。

### UAT-P1-08 `/ready` 可能在 Kafka 未配置时误报 ready【已关闭】

- 证据：[`platform/app/main.py:74`](../platform/app/main.py) Kafka 初始化异常会保留 `None`；233-260 报告 `not_configured`；267-270 将 `not_configured` 视为 ready。
- 影响：canonical 必需的 Kafka 不工作时，容器健康检查仍可能通过，UAT 得到假绿状态。
- 改进：按部署模式声明 required dependencies；canonical 模式下 Kafka/road9/TimescaleDB 必须均为 healthy，启动异常和 not_configured 均应 degraded。

### UAT-P1-09 视频/HLS 入口绕过身份认证【源码已关闭；新镜像运行复验延期】

- 证据：[`platform/app/middleware/auth.py:16`](../platform/app/middleware/auth.py) 将 `/video/` 与 `/api/v1/video/camera/` 设为 public；[`services/nginx/nginx.conf:13`](../services/nginx/nginx.conf) 直接公开 HLS 文件。
- 影响：只要能访问 UAT 网络即可查看实时/历史画面，可能泄露车辆、地点和案件素材。
- 改进：冻结视频访问模型；浏览器 `<img>` 需求不能替代鉴权，应使用短期签名 URL、受控 Cookie 或代理授权，并测试 viewer 数据范围。

### UAT-P1-10 UAT 发布制品不可复现且缺少干净基线【部分关闭，制品化延期阻断】

- 证据：初始工作树已有未提交 `D traffic-fly-console`；[`docker-compose.yaml:38`](../docker-compose.yaml)、52、170 等使用 `latest` 或漂移标签；[`platform/pyproject.toml:10`](../platform/pyproject.toml) 和根 `requirements.txt` 大量使用下界无锁定；Platform 还通过 [`docker-compose.yaml:108`](../docker-compose.yaml) 挂载当前源码树运行管道。仓库未发现 CI/CD 或发布清单。
- 影响：无法证明 UAT 测试的代码、部署代码和后续重建镜像完全相同。
- 改进：先确认并提交/恢复退役子模块删除；从干净 commit 构建带版本号和 digest 的前后端/检测镜像，生成 SBOM、迁移版本和配置摘要；UAT 只部署该制品，不绑定开发工作树。

### UAT-P1-11 共享 UAT 仍允许本机默认凭据和明文 Kafka【应用 fail-closed 已关闭，共享环境延期阻断】

- 证据：[`docker-compose.yaml:13`](../docker-compose.yaml) 使用 PLAINTEXT；57、82 默认 `traffic123`；89 默认固定 JWT secret；数据库、Kafka、Platform 端口直接发布到宿主机。
- 影响：若把本机 Compose 原样放入共享 UAT，弱凭据和可伪造 token 会放大前述越权风险。
- 改进：UAT 配置必须对 secret 使用“无值即失败”，轮换管理员密码，收紧端口和网段；至少为共享 UAT 启用 TLS/SASL 或放在受控内网入口。生产秘密/TLS/HA 门禁仍独立保留。

### UAT-P1-12 Kafka 新组与副作用恢复可能静默遗漏事实【已关闭】

- 证据：[`platform/app/kafka/consumer.py:70`](../platform/app/kafka/consumer.py) 对新消费组使用 `auto_offset_reset=latest`；199-218 的消息处理先持久化，重复消息随后直接返回。若数据库提交后、告警/WS 副作用完成前失败，重放会被 inbox 判重并继续提交 offset，副作用没有持久化恢复状态。
- 影响：新 consumer group 可能跳过已有积压；故障窗口内可能出现“事实已入库但告警/实时通知永久缺失”，且健康检查和幂等表都难以暴露遗漏。
- 改进：冻结新组的 earliest/latest 与回放策略；把告警、WS/外发 dispatch 状态纳入事务 outbox 或可重放状态机，增加“提交后副作用前崩溃”和新组积压故障注入测试。

## 5. P2 / P3 改进项复验

1. **已关闭：实时暂停语义**。暂停后冻结 WS、REST 轮询与可见时间，恢复后重新同步。
2. **已关闭：前端包体与缓存**。路由按业务域 lazy-load，vendor 分组；入口 `35.00 KiB`，最大业务 chunk `33.62 KiB`，最大 vendor `403.66 KiB`，满足 `350/750 KiB` 门禁。
3. **已关闭：浏览器安全头**。Console2 与外层 Nginx 配置 CSP、`frame-ancestors`、nosniff、Referrer/Permissions-Policy，并对 hash 资产和 `index.html` 使用不同缓存策略。
4. **已关闭：应用可访问性**。共享交互组件补键盘、焦点和 dialog 语义并加入自动化测试；完整读屏人工验收仍作为 UAT 执行项。
5. **延期：容器健康与最小权限**。属于本轮明确排除的 Docker/镜像范围。
6. **已关闭：静态质量门禁**。`ruff check platform/app platform/tests nodes services main_optimized.py` 全量通过，并新增 `.github/workflows/uat-code-gates.yml`。
7. **已关闭：文档契约漂移**。Architecture、Business Logic、API、Database、Project Structure 和 Tasks 已同步 canonical current-state。
8. **已关闭：告警确认审计身份**。统一使用中间件 actor，并覆盖非 admin 身份持久化。
9. **已关闭：页面标识**。`lang=zh-CN`、正式标题和内联 favicon 已配置。
10. **已关闭：窄屏支持**。1024×768、1366×768、1440×900 三档均无横向溢出。

## 6. 验证证据

| 验证 | 结果 |
|---|---|
| `python -m pytest platform/tests -q` | `123 passed, 5 skipped`；跳过项随后显式运行 |
| 显式 PostgreSQL/TimescaleDB integration | `5 passed`，使用当前 `road9` 且测试数据自清理 |
| `cd console2 && npm test` | `13 files / 72 tests passed` |
| `cd console2 && npm run build` | 成功；入口 `35.00 KiB`，最大 chunk `403.66 KiB`，无超预算 chunk |
| 根 canonical 契约组 | `16 passed` |
| `python test_pipeline_inter_xqh.py` | `56 PASS / 0 FAIL / 0 WARN` |
| `python scripts/audit_adr019_retirement.py --scope local --strict` | 通过 |
| ADR-019 本机报告 | 重新生成并 `passed=true`；Alembic 单 head `20260717_0013`；5 个 TimescaleDB hypertable；仅 canonical 容器/Topic |
| Nginx 运行复验 | 现有 `traffic_analyzer-nginx-1` 内 `nginx -t`、热加载通过；`/hls/...` 匿名 401、`/ready` 200；`/camera_10` 从 500 修复为无运行源时 404 |
| 浏览器 UAT | 1024×768、1366×768、1440×900 无横向溢出；禁用治理入口不可执行；测绘无效深链显示错误、返回与重试 |
| `python -m compileall -q ...` | 通过 |
| `ruff check platform/app platform/tests nodes services main_optimized.py` | 通过，0 finding |
| `git diff --check` | 通过；初始已有且本轮未触碰 `D traffic-fly-console` |
| CI | 新增前后端测试、构建预算、Ruff、canonical 契约、ADR strict 和 whitespace 门禁；远端尚未执行 |

## 7. 未覆盖与外部门禁

- 未执行全路由逐页读屏人工验收；本轮完成关键错误路径、多分辨率、键盘语义自动化与页面截图。
- 未重新传输 5GB 级 MP4；8GB 上限已在 Console2 Nginx、外层 Nginx、Platform 契约统一，并由代理配置测试覆盖。仓库既有六组大文件本机验收证据继续有效。
- 未对真实共享 UAT 执行破坏性权限探测；三角色矩阵、active-user、媒体/WS Cookie、query token 拒绝和控制面 allowlist 已由回归覆盖。
- 当前 Platform/Console2 容器仍是修复前构建，遵照范围未重建；因此源码中的媒体 Cookie 与最新 UI 不能用现有容器作为发布证明。外层 Nginx 已热加载并消除 camera 500，但完整媒体鉴权必须在新镜像 Gate C 重跑。
- Python 依赖未运行联网 CVE/许可证扫描；没有 SBOM、镜像签名、恶意软件或容器镜像漏洞报告。
- GPU 镜像遥测 import/camera 3 smoke、生产镜像 pin、秘密管理、TLS/SASL、HA、容量、保留/压缩、RPO/RTO、权威路网、主平台合同、统一身份、试点验收仍是明确的 `blocked_external`；本报告不将其误标为已完成。

## 8. 改进优先级与复验门禁

### Gate A：P0 清零【完成】

- 匿名管理员注册、WS 客户端 publish 与 SRT offset/tolerance 均已关闭并回归。

### Gate B：应用范围可用且可信【应用完成；镜像延期】

- Pipeline/视频/RBAC、Kafka 恢复、测绘、治理隔离、`/ready` 与 WS 日志均已关闭。
- 遥测镜像、干净可复现制品和共享 UAT secret/TLS 仍延期。

### Gate C：制品化复验【下一阶段】

1. 在干净提交上构建并固定前端、Platform、检测镜像 digest，不挂载开发工作树；
2. 验证 GPU 镜像 `services.*` import、SRT camera 3 fail-fast 与真实 smoke；
3. 注入共享 UAT secret，完成 TLS/SASL、端口收敛、非 root/只读根、healthcheck；
4. 生成 SBOM、签名、迁移版本和配置摘要，再运行本报告全部门禁；
5. 仅当延期项全部关闭后，把完整发布结论从 No-Go 改为 Go。

## 9. 当前可执行范围

可以开展基于源码和本机 canonical 栈的应用功能/契约 UAT，包括登录、工作台、实时读取、事故测绘、飞行任务、轨迹/事件、执法候选、标定、系统读写权限矩阵。`/admin/integration` 在默认构建中明确不可执行。该范围不等于镜像化共享 UAT 放行；涉及 GPU 镜像、制品来源、共享 secret/TLS/HA 的结论仍为 No-Go。

# DECISIONS.md — TrafficAnalyzer 架构决策记录

> 基于 commit `e69acee` 的真实代码分析。

## ADR-001: 使用 FrameElement 共享对象作为管道数据载体

**状态**：已采纳（历史决策）

**背景**：视频分析管道需要在线性节点链中传递和逐步增强数据。

**决策**：创建一个 FrameElement 类，包含所有可能的字段（原始帧、检测结果、跟踪结果、统计信息等），初始值为 None。每个节点读取上游字段、写入自己的字段。

**理由**：
- 视频管道是严格线性的，不需要分支或合并
- 共享对象避免了数据拷贝（numpy 帧数组很大）
- 简单直观，新节点只需知道需要读写哪些字段

**后果**：
- ✅ 简单、高效
- ❌ FrameElement 成为 God Object，字段持续膨胀
- ❌ 无法在编译时检查节点是否填充了必需字段
- ❌ 多进程 Queue 序列化整个对象（包括不需要的字段）

**替代方案**：
- 事件驱动架构（过重，不适合线性管道）
- dataclass + frozen 实例（会破坏渐进式填充模式）

---

## ADR-002: 使用 VideoEndBreakElement 哨兵模式终止管道

**状态**：已采纳（历史决策）

**背景**：在 multiprocessing.Queue 中需要一种机制来通知所有下游进程"视频已结束"。

**决策**：创建一个 VideoEndBreakElement 类（继承 FrameElement），作为哨兵对象通过队列传递。每个节点在 process() 开头检查 isinstance，如果是哨兵则执行清理并返回。

**理由**：
- Queue 没有内置的关闭信号
- Process.terminate() 不安全（可能丢失缓冲区中的数据）
- 哨兵对象可以被 pickle 序列化通过 Queue

**后果**：
- ✅ 优雅终止，所有节点都有机会清理资源
- ❌ 每个节点必须记得检查 isinstance（容易遗漏）
- ❌ VideoEndBreakElement 继承 FrameElement 但不初始化父类字段（可能导致属性错误）

---

## ADR-003: 硬编码 5 条道路

**状态**：已采纳（历史决策），**需要重新评估**

**背景**：原始项目针对一个特定的环形交叉路口，恰好有 5 条道路。

**决策**：在 CalcStatisticsNode 中硬编码 `roads_activity = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}`，在 KafkaProducerNode 中硬编码 `road_1` ~ `road_5` 字段。

**理由**：
- 快速原型开发，不需要考虑通用性
- Grafana 仪表盘也按 5 条道路设计

**后果**：
- ✅ 简单直接
- ❌ 增加或减少道路需要修改 4 个文件 + Grafana 仪表盘 + Telegraf 配置
- ❌ 不同路口有不同数量的道路（inter2_lanes.json 只有 2 条），但 Kafka 消息始终发送 5 个字段

**建议改进**：
- 从 `roads_info` 配置动态获取道路数量
- Kafka 消息使用数组格式 `"roads": [4.2, 3.8, null, 2.1, 1.5]`
- Grafana 使用变量化的查询

---

## ADR-004: 4 个入口点而非 1 个参数化入口

**状态**：已采纳（历史决策），**需要重新评估**

**背景**：项目有 4 个 main*.py 文件，分别对应不同的进程模型。

**决策**：保持 4 个独立文件，每个文件包含完整的进程启动逻辑。

**理由**：
- 每个入口点的进程划分和队列策略差异较大
- 独立文件便于理解和调试
- 项目是研究原型，不是生产系统

**后果**：
- ✅ 每个文件自包含，可以独立理解
- ❌ 大量代码重复（import 列表、环境变量设置、节点初始化）
- ❌ 修改管道节点顺序需要同时修改 4 个文件
- ❌ 新增运行模式需要创建新文件

**建议改进**：
- 统一的 `main.py` + `--mode` 参数（sequential/optimized/stream/stream_v2）
- 提取公共的节点初始化和环境变量设置到工厂函数

---

## ADR-005: 使用 InfluxDB 1.8 而非 2.x

**状态**：已采纳（历史决策）

**背景**：项目使用 InfluxDB 作为时序数据库。

**决策**：使用 InfluxDB 1.8（InfluxQL 查询语言）。

**理由**：
- Grafana 对 InfluxQL 的支持更成熟
- 1.8 版本的 API 更简单（不需要 token 认证）
- Telegraf 配置更直观

**后果**：
- ✅ 简单、稳定
- ❌ InfluxDB 1.x 已进入维护模式，不再有新功能
- ❌ 升级到 2.x 需要重写所有 Grafana 查询（InfluxQL → Flux）

---

## ADR-006: ByteTrack 移植而非使用 ultralytics 内置跟踪

**状态**：已采纳（历史决策）

**背景**：ultralytics 库从 8.x 版本开始内置了 ByteTrack 跟踪器。

**决策**：保持独立的 `byte_tracker/` 目录，使用自己移植的 ByteTrack 实现。

**理由**：
- 项目开始时 ultralytics 尚未内置跟踪
- 自定义实现允许更细粒度的控制（如双阈值、track_buffer 参数）
- 避免依赖 ultralytics 内部 API 的变化

**后果**：
- ✅ 完全控制跟踪参数
- ❌ 需要维护移植代码
- ❌ 可能错过上游的 bug 修复和性能优化

---

## ADR-007: Flask 而非 FastAPI 作为视频流服务

**状态**：已采纳（历史决策）

**背景**：需要一个 HTTP 服务来推送处理后的视频帧。

**决策**：使用 Flask + MJPEG（multipart/x-mixed-replace）。

**理由**：
- MJPEG 不需要 WebSocket 或复杂的流协议
- Flask 足够轻量，可以在守护线程中运行
- 浏览器原生支持 MJPEG（`<img src="/video"/>`）

**后果**：
- ✅ 简单、兼容性好
- ❌ Flask 的 GIL 限制了并发性能
- ❌ 帧更新无锁保护，可能出现画面撕裂
- ❌ 不支持自适应码率或分辨率切换

---

## ADR-008: 平台从微服务重构为单体架构

**状态**：已采纳（2026-05-29）

**背景**：`platform/` 最初设计为 4 个微服务（gateway、operations、vision、flight），每个服务独立部署。经过实际使用发现：
- 团队规模小，不需要独立部署和扩展
- 微服务增加了网络延迟、服务发现、分布式追踪等复杂度
- API 端点之间共享大量状态（Kafka 消费者缓存、WebSocket 连接池）
- 开发和调试成本高（需要同时启动多个容器）

**决策**：将 4 个微服务合并为单一 FastAPI 应用，保留所有原始 API 端点路径和响应格式。

**实现细节**：
- 统一配置类：`platform/app/core/config.py:Settings`（Pydantic Settings）
- 统一数据库连接：`platform/app/core/database.py`（SQLAlchemy async）
- JWT 库迁移：python-jose → PyJWT（ARM64 兼容性）
- Kafka 消费者：`platform/app/kafka/consumer.py`（aiokafka，模式订阅）
- WebSocket 管理：`platform/app/kafka/ws_manager.py`（channel-based pub/sub）
- 前端代理：`traffic-fly-console/nginx.conf` 更新为 `proxy_pass http://platform:8000`

**后果**：
- ✅ 开发和调试简化（单一进程，统一日志）
- ✅ 消除了服务间网络延迟
- ✅ 共享状态（Kafka 缓存、WebSocket 连接）更自然
- ✅ 部署简单（1 个容器 vs 5 个）
- ❌ 单一故障点（通过优雅降级缓解）
- ❌ 无法独立扩展某个 API（当前规模不需要）

**替代方案**：
- 保持微服务，引入服务网格（Istio/Linkerd）— 过重
- 合并为 2 个服务（API + WebSocket）— 仍有网络开销
- 使用 serverless 架构 — 不适合有状态服务

**验证**：
- 本地启动：✅ 通过（所有端点测试通过）
- Docker Compose：✅ 通过（完整栈启动，5 个容器）
- 前端集成：✅ 通过（nginx 代理正常工作）

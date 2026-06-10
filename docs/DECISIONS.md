# DECISIONS.md — TrafficAnalyzer 架构决策记录

> 基于 commit `84c6bd6` 的真实代码分析。

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

## ADR-003: ~~硬编码 5 条道路~~ → 已解决（见 ADR-013）

**状态**：已替代（2026-05-31，ADR-013）

**原始背景**：原始项目针对一个特定的环形交叉路口，恰好有 5 条道路。

**原始决策**：在 CalcStatisticsNode 中硬编码 `roads_activity = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}`。

**替代方案**：见 ADR-013（动态道路数 — 数组格式 + 向后兼容字段）

---

## ADR-004: ~~4 个入口点~~ → 2 个入口点（已整合）

**状态**：已部分解决（2026-06-09）

**原始背景**：项目曾有 4 个 main*.py 文件，分别对应不同的进程模型。

**解决**：`main_stream_optimized.py` 和 `main_stream_optimized_v2.py` 已删除，其 RTSP 流和健康检查特性整合到 `main_optimized.py`。当前仅保留 2 个入口：
- `main.py` — 单进程顺序模式（调试用）
- `main_optimized.py` — 三进程并行模式（唯一生产入口，含健康检查）

**残余技术债**：
- `main.py` 与 `main_optimized.py` 仍有代码重复（import 列表、环境变量设置）
- 建议提取公共初始化逻辑到工厂函数

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

---

## ADR-009: 混合运动补偿（GPS锚定 + 遥测速度积分）

**状态**：已采纳（2026-05-30）

**背景**：无人机巡飞时（最高12 m/s = 43 km/h），所有空间计算（车速、方向、轨迹、冲突TTC）都被无人机运动污染。

**决策**：采用混合方案——GPS锚定世界坐标系 + 帧间遥测速度矢量减法 + 悬停自动跳过。

**实现**：
- `MotionCompensationNode`：首10帧GPS均值作为世界锚点，每帧计算GPS增量位移
- `SpeedEstimationNode`：用当前帧H转换position_history（0.5s窗口），减去`drone_velocity_ms`
- `DirectionFlowNode`：转世界坐标系后计算heading，无人机>5m/s回退像素空间
- GPS丢失时保持上次位移（避免世界坐标跳变到原点）
- 云台偏航增量归一化到[-180,180]（避免±180°跳变）

**已知限制**：
- 轨迹世界坐标在快速巡飞时有误差（=无人机速度×轨迹时长，12m/s×8s=96m）
- 方向分类在无人机>5m/s时降级为像素空间heading

**后果**：
- ✅ 车速估计消除±43 km/h误差
- ✅ 悬停时自动跳过补偿（避免GPS抖动引入伪运动）
- ❌ 依赖MQTT遥测数据
- ❌ 首10帧需等待GPS锚点初始化

**替代方案**：
- 纯GPS积分（无速度减法）— 无法修正帧间速度误差
- 视觉光流法（EISNode）— 需额外计算，高频抖动有效但低频漂移无效
- 固定参考点标定 — 仅适用于固定摄像头

---

## ADR-010: 数据驱动车道分析（无配置开关）

**状态**：已采纳（2026-05-29）

**背景**：车道多边形标注是可选的（无人机巡飞无法标注），不应通过配置开关控制。

**决策**：`LaneAnalysisNode` 没有 `enabled` 开关，自动检测 `frame_element.lane_polygons` 是否存在：
- 有车道多边形 → 输出车道级统计
- 无车道多边形 → 透传（不报错）

**理由**：
- 简化配置（少一个开关）
- 避免"开关打开但无数据"的错误状态
- 与 VideoReader 的 JSON 加载逻辑自然耦合

**后果**：
- ✅ 零配置即可启用车道分析
- ❌ 无法临时关闭已有的车道分析（除非清空JSON中的lanes字段）

---

## ADR-011: 多Topic Kafka发布（统计/轨迹/冲突分离）

**状态**：已采纳（2026-05-29）

**背景**：交通态势感知产生3种不同结构的消息（周期统计、事件驱动轨迹、事件驱动冲突）。

**决策**：使用3个独立Kafka topic per camera：
- `statistics_{n}` — 周期性统计（1秒间隔）
- `track_complete_{n}` — 完成轨迹（事件驱动）
- `conflicts_{n}` — 冲突事件（事件驱动）

**理由**：
- 消息结构差异大，混合在同一topic使Telegraf解析复杂化
- 轨迹/冲突事件不规则（非周期性），不适合Telegraf的JSON flat解析
- Platform消费者可直接订阅特定topic

**后果**：
- ✅ Telegraf仅处理statistics topic（简单）
- ✅ Platform消费者可独立处理轨迹和冲突
- ❌ Kafka topic数量增加（3×摄像头数）
- ❌ 需要平台侧消费者写入InfluxDB（非Telegraf路径）

---

## ADR-012: KafkaProducerNode 异步发送（独立线程 + 有界队列）

**状态**：已采纳（2026-05-31，审查 T-101）

**背景**：原实现中 `self.kafka_producer.send(topic, value=data).get(timeout=1)` 同步等待 Kafka 确认。Kafka 不可用时每帧最多阻塞 3 秒（stats + track + conflict 各 1s），导致管道帧率从 30fps 降至 <1fps。

**决策**：采用独立后台发送线程 + Queue(maxsize=200) 方案：
- `process()` 方法通过 `put_nowait()` 非阻塞入队
- 后台线程循环取消息并发送，使用 callback 记录成功/失败
- 队列满时降级丢弃消息（比阻塞管道好）

**理由**：
- 完全隔离 Kafka IO 与管道计算线程
- 保持消息可靠性（Kafka acks=1）
- 队列满时优雅降级（计数器记录丢弃数）

**后果**：
- ✅ Kafka 抖动时管道帧率不受影响
- ✅ 队列容量 200 条可缓冲约 200 秒的 stats 消息
- ❌ 极端情况下可能丢弃消息（概率极低）

**替代方案**：
- fire-and-forget（acks=0）— 零可靠性
- 本地文件缓存 — 实现复杂，恢复困难

---

## ADR-013: 动态道路数（数组格式 + 向后兼容字段）

**状态**：已采纳（2026-05-31，审查 T-201）

**背景**：CalcStatisticsNode 和 KafkaProducerNode 硬编码 5 条道路。不同路口有不同数量的道路（2-8条）。

**决策**：
- CalcStatisticsNode 从 `roads_info.keys()` 动态构建 `roads_activity` 字典
- KafkaProducerNode 新增 `roads` 数组字段（`[{"id": 1, "activity": 4.2}, ...]`）
- 保留 `road_1..road_N` 字段（最多 max(实际道路数, 6) 条）向后兼容
- InfluxDB 动态写入 road_* 字段

**理由**：
- 数组格式完全动态，无上限
- 向后兼容字段保证旧版 Grafana 仪表盘和 Telegraf 不中断
- 一次迁移，长期收益

**后果**：
- ✅ 任意道路数的路口均可复用
- ✅ 旧消费者和 Grafana 面板继续工作
- ❌ Kafka 消息略增大（同时发数组和逐字段）

---

## ADR-014: Platform Consumer 直写 InfluxDB（track/conflict 持久化）

**状态**：已采纳（2026-05-31，审查 T-102）

**背景**：原实现中 `_handle_track_complete()` 和 `_handle_conflict()` 仅 WebSocket 广播，不持久化到 InfluxDB。导致 Trajectory API 返回空数据，GIS 轨迹回放无法工作。

**决策**：在 KafkaConsumerService 中注入 InfluxQuery 实例，在 track_complete 和 conflict handler 中直接调用 `write_track_event()` / `write_conflict_event()`。

**理由**：
- 当前消息量级（~1 track/min + ~0.1 conflict/min）适合直写
- 无需额外桥接服务
- InfluxDB 写入在 aiokafka 事件循环中同步执行（写入 <1ms，可接受）

**后果**：
- ✅ 轨迹和冲突数据持久化，历史查询可用
- ✅ Trajectory API 和 GIS 回放可工作
- ❌ Consumer 处理延迟略增（<1ms/事件）

**替代方案**：
- 独立 Kafka→InfluxDB 桥接服务 — 多一个服务，当前规模不需要
- Telegraf 路径 — 消息结构不适合 Telegraf flat JSON

---

## ADR-015: 速度估算线性回归（全点拟合替代首尾两点）

**状态**：已采纳（2026-05-31，审查 T-202）

**背景**：原实现仅使用 position_history 的首尾两点计算速度。bbox 中心抖动（±2px）在 15 帧窗口内可能引入 ±5km/h 噪声。

**决策**：使用 `np.polyfit(t, x, 1)` 和 `np.polyfit(t, y, 1)` 对 position_history 的全部数据点做线性回归，取斜率作为速度。

**理由**：
- 利用全部数据点，抗噪声能力最佳（随机误差被平均掉）
- 自然处理不等间距时间戳
- 计算量可忽略（~0.01ms/轨迹）

**后果**：
- ✅ bbox ±3px 抖动下车速波动 <2km/h（实测改善 3-5 倍）
- ✅ 世界坐标和像素坐标两种模式均适用
- ❌ 非线性运动（急转弯）时线性回归误差略大（但 EMA 平滑可缓解）

---

## ADR-016: 使用 supervision 库优化 ShowNode 可视化

**状态**：已采纳（2026-06-09）

**背景**：ShowNode 原实现使用纯 OpenCV `cv2.rectangle` + `cv2.putText` 循环绘制，存在以下问题：
- 每个目标单独循环调用 OpenCV 绘图函数，代码冗长且难以维护
- 标签为红色纯文本无背景，可读性差
- 边框为直角矩形，视觉风格较原始
- 着色使用 `random.seed(id)` 方式不可靠（可能影响其他随机逻辑）
- 352 行全部塞在一个 `process()` 方法中，无法拆分和测试

**决策**：引入 `supervision` 库（>=0.24.0，已在 requirements.txt 中）重构 ShowNode：
- `sv.RoundBoxAnnotator` — 圆角边框（替代 `cv2.rectangle`）
- `sv.LabelAnnotator` — 带圆角彩色背景的标签（替代 `cv2.putText`）
- `sv.TraceAnnotator` — 新增轨迹尾迹可视化
- `sv.MaskAnnotator` — 道路半透明遮罩（替代手动 `cv2.addWeighted`）
- `sv.ColorPalette` + `ColorLookup.TRACK` — 确定性着色（替代 `random.seed`）
- `sv.Detections` 统一数据结构 — 批量处理所有目标

**理由**：
- supervision 是 Roboflow 开源的专业 CV 可视化工具库（8k+ GitHub stars）
- 提供圆角边框、轨迹尾迹等高质量可视化效果
- `ColorPalette` 21色循环着色稳定可靠
- 批量绘制性能优于逐目标循环
- 代码量减少约 40%，可读性和可维护性大幅提升

**后果**：
- ✅ 可视化效果显著提升（圆角边框 + 标签背景 + 轨迹尾迹）
- ✅ 着色逻辑确定性（`ColorLookup.TRACK` + `ColorPalette`）
- ✅ `process()` 拆分为 10 个子方法（`_draw_detections`、`_draw_tracked`、`_draw_roads` 等）
- ✅ 新增 `show_trace_trails` 配置项
- ✅ 标签格式增强：`#id class_name speed km/h`
- ❌ 新增 supervision 运行时依赖（已存在于 requirements.txt）

**替代方案**：
- 保持纯 OpenCV — 代码冗长，效果差
- 使用 ultralytics 内置可视化 — 耦合度高，定制性差
- 自行封装 OpenCV 绘图工具 — 重复造轮子

---

## ADR-017: 自动车道推断替代人工标注（轨迹驱动聚类）

**状态**：已采纳（2026-06-09）

**背景**：车道级统计（流量/排队/车头时距）原先依赖人工标注的 ROI 线（`generate_lanes.py` 交互式标注的车道多边形）。无人机巡飞时视角和高度持续变化，标注线频繁失效，需要频繁人工干预。

**决策**：新增 `AutoLaneInferenceNode`，从已完成车辆轨迹数据中自动推断车道中心线和交通指标。**向下兼容**：如果存在车道标注数据（`lane_polygons`），以标注数据为准，自动推断自动跳过；无标注数据时才启用自动推断。

**算法**：
1. 维护已完成轨迹的滚动缓冲区（默认 3 分钟窗口）
2. 按方向类别（直行/左转/右转/掉头）分桶
3. 在每个桶内使用层次聚类（`scipy.cluster.hierarchy`），以入口/出口点最大距离为度量
4. 对每个聚类拟合中心线（重采样 + 均值）
5. 自动标签：入口朝向 → 中文方位词 + 方向类别
6. 匹配活跃轨迹到推断车道，计算实时指标

**理由**：
- 轨迹数据本身就是车道信息的天然表达——车辆行驶的路径定义了车道
- 无需人工标注，适应任何视角和高度变化
- 聚类间隔 5 秒（非每帧），性能开销极低
- `scipy` 已是项目依赖，无新增依赖
- 自动标签生成使结果对人类可读

**后果**：
- ✅ 向下兼容：有标注数据时以标注为准，无标注时自动推断
- ✅ 自动发现所有方向的车道（东→西 直行、南→东 左转 等）
- ✅ 输出与 `LaneAnalysisNode` 相同格式的指标（count, speed, queue, flow, headway）
- ✅ Kafka 统一输出 `lanes` 数组 + `lane_source` 字段（"manual"|"auto"|null）
- ✅ `FrameElement.inferred_lanes` 字段输出推断结果
- ✅ 前端直接读取 `lanes` 数组，无需区分数据来源
- ✅ ShowNode 可视化推断车道（中心线 + 方向箭头 + 统计面板）
- ❌ 聚类结果在前几分钟可能不稳定（需要足够的已完成轨迹）
- ❌ 车道 ID 在重新聚类时可能变化（非持久化）

**替代方案**：
- 保持人工标注 — 维护成本高，不适应视角变化
- 使用深度学习语义分割 — 需要额外训练数据，推理开销大
- 使用 OpenCV 车道线检测 — 无人机视角下车道线不可见
- 使用 GPS 轨迹聚类 — 需要高精度 GPS，像素空间已足够

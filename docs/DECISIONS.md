# DECISIONS.md — TrafficAnalyzer 架构决策记录

> 历史实现说明基于 commit `84c6bd6` 的真实代码分析；新决策会明确记录采纳日期、
> 实施状态和对历史 ADR 的替代关系。

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

**状态**：已替代（2026-07-13，由 ADR-019 替代）

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

**状态**：部分替代（2026-07-13；Topic 分流保留，命名和 Telegraf/InfluxDB 路径由 ADR-019 替代）

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

**状态**：部分替代（2026-07-13；动态数组保留，Grafana/Telegraf 兼容目标由 ADR-019 替代）

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

**状态**：已替代（2026-07-13，由 ADR-019 替代）

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

---

## ADR-018: YOLO 分割模型车道检测（三级优先级链）

**状态**：已采纳（2026-06-10）

**背景**：基于轨迹聚类的自动推断（ADR-017）虽然无需人工标注，但车道位置随车流变化而持续漂移，导致统计不稳定。需要一种基于图像视觉特征的方法，提供位置固定的车道区域。

**决策**：新增 `LaneDetectionNode`，使用 `weights/lane_detect.pt` YOLO 分割模型从图像中检测车道标线和路面区域，生成稳定的车道多边形。建立三级优先级链：

```
人工标注 (manual) > 模型检测 (model) > 轨迹推断 (auto)
```

- 有人工标注（`lane_polygons` 已从 JSON 加载）→ 标记 `lane_source="manual"`，跳过模型
- 无人工标注 → 运行 YOLO 分割模型 → 标记 `lane_source="model"`
- 模型未检测到任何车道 → 回退到 `AutoLaneInferenceNode`（`lane_source="auto"`）

**两种检测策略**：
1. **pavement 类（路面区域）**：直接使用分割 mask 提取多边形作为车道区域
2. **lane 类（车道标线）**：对 mask 做形态学膨胀（`buffer_pixels=50px`），将细线扩展为车道区域

**工作模式**：
- `first_frame_only=True`（默认）：仅首帧运行模型，后续帧复用结果。适合固定摄像头，最大化性能。
- `first_frame_only=False`：每 `detect_interval` 帧运行一次。适合无人机/移动摄像头。

**理由**：
- 模型检测的车道基于图像视觉特征（标线、路面），位置固定不随车流变化
- 首帧缓存机制使性能开销极低（仅首帧推理）
- 与人工标注和轨迹推断自然兼容，三级优先级链确保向下兼容
- YOLO 分割模型推理速度快（~20ms/帧），不影响管道帧率

**后果**：
- ✅ 三级优先级链：人工标注 > 模型检测 > 轨迹推断，完全向下兼容
- ✅ `lane_source` 字段从 `"manual"|"auto"|null` 扩展为 `"manual"|"model"|"auto"|null`
- ✅ 模型检测的车道多边形供 `LaneAnalysisNode` 进行车辆分配和指标统计
- ✅ 首帧缓存使固定摄像头场景下性能开销趋近于零
- ✅ Kafka 统一输出 `lanes` 数组 + `lane_source` 字段，前端无需区分来源
- ❌ 新增 YOLO 分割模型权重文件（~6MB）
- ❌ 新增 `lane_detection` 配置节（`app_config.yaml`）
- ❌ 模型检测的车道多边形可能与实际车道不完全吻合（依赖模型精度）

**替代方案**：
- 仅使用轨迹推断（ADR-017）— 车道位置随车流漂移，统计不稳定
- 仅使用人工标注 — 每个视频都需要标注，维护成本高
- 使用传统 CV 车道线检测（Hough 变换）— 无人机视角下车道线不可见或不清晰

---

## ADR-019: 统一使用 road9 PostgreSQL/TimescaleDB 并退役 InfluxDB/Telegraf/Grafana 链路

**状态**：Accepted（已采纳，2026-07-13；实施待完成）

**替代关系**：替代 ADR-005、ADR-014 中的 InfluxDB 决策；部分替代 ADR-011 的旧
Topic 命名和 Telegraf 路径、ADR-013 的 Grafana/Telegraf 兼容目标。Kafka 的异步传输
职责和按业务类型分流仍然保留。

### 背景

当前仓库同时维护 PostgreSQL 业务数据与 InfluxDB 时序数据，并通过
`Kafka → Telegraf → InfluxDB → Grafana` 展示周期指标。该结构带来多套连接、权限、
备份、查询语言和监控组件，复杂 JSON 经 Telegraf 扁平化后也难以保留完整业务语义。
无人机平台已有 React 前端和 FastAPI 查询层，继续维护 Grafana 形成重复展示入口。
同时，旧 Topic、WebSocket channel、消息类型和数据库表缺少统一命名空间，容易与智慧
交通大项目内其他子系统冲突。

### 决策

1. 无人机平台 PostgreSQL 连接的数据库固定选择 `road9`，即目标配置
   `DB_NAME=road9`。`road9` 是 database 名，不得在代码、迁移脚本或文档中自动解释为
   schema；旧 `ycx`/`road10` 调查只保留为历史证据，不能作为运行时默认值。
2. 在 `road9` 中安装并启用 TimescaleDB 扩展。PostgreSQL 同时承载关系业务数据和时序
   数据，复用事务、访问控制、备份、审计和 SQL 查询能力。
3. TimescaleDB hypertable 固定为 `uav_traffic_metrics`、`uav_system_metrics`、
   `uav_telemetry_metrics`、`uav_track_points`、`uav_conflict_events`。不同路口、路段和
   车道粒度的交通指标由 `uav_traffic_metrics` 的 `grain_type`、`grain_key` 统一承载：
   `grain_type` 取 `intersection`、`link`、`lane`，`grain_key` 分别对应权威
   `inter_id`、`link_id`、`lane_id`；不另建同义指标表。业务事件表固定为 `uav_track_events`、
   `uav_ai_events`；可靠投递使用 `uav_event_outbox`、`uav_event_delivery_attempts`、
   `uav_event_feedback`、`uav_dead_letters`；证据使用 `uav_evidence_packages`、
   `uav_evidence_items`；消费幂等使用 `uav_message_inbox`。最终列定义、索引、分块、压缩
   和保留期由数据库契约与容量测试冻结。
4. 无人机平台拥有的物理表、Kafka Topic、WebSocket channel 和 `msg_type` 统一使用
   `uav_` 前缀。目标 Topic 为 `uav_statistics_{camera_id}`、`uav_track_complete_{camera_id}`、
   `uav_conflicts_{camera_id}`、`uav_telemetry_{camera_id}`、`uav_system_metrics`，规划统一事件/反馈为
   `uav_ai_events`、`uav_ai_event_feedback`；目标 WebSocket channel 为
   `uav_intersection:{intersection_id}`、`uav_alerts`、`uav_alerts:{intersection_id}`、`uav_system`、
   `uav_telemetry:{drone_id}`、`uav_calibration`；canonical `msg_type` 分别使用
   `uav_stats`、`uav_track_complete`、`uav_conflict`、`uav_telemetry`、
   `uav_system_metrics`、`uav_ai_event`、`uav_ai_event_feedback`，告警使用
   `uav_alert_new`/`uav_alert_updated`，车道标注任务保留 `uav_lane_annotation_task`。
5. Kafka 继续作为检测管道与平台之间的异步消息总线。平台 Consumer 负责 schema 校验、
   幂等处理、路网权威 ID 关联和 PostgreSQL/TimescaleDB 持久化；持久化成功后再广播
   WebSocket，失败则重试或进入可观测的失败处理流程。
6. `uav_message_inbox` 是长期 canonical 消费幂等表，不是迁移临时表。以
   `(source_system, message_id)` 建立唯一约束，保存并校验 payload hash，同时保留 Topic、
   partition、offset、status 和事实引用；inbox 登记、事实写入及状态/引用更新必须在同一
   PostgreSQL 事务中提交。保留期必须覆盖最大重放窗口。TimescaleDB hypertable 唯一键因
   必须包含时间分区列，只作为第二层防重，不能取代 inbox 的跨时间消息幂等。
7. 废弃 Telegraf、InfluxDB 和 Grafana 生产链路。历史查询、时序聚合和页面可视化统一
   通过 PostgreSQL/TimescaleDB、FastAPI REST/WebSocket 与 `traffic-fly-console` 完成。
8. 本 ADR 描述目标态，并不代表仓库当前已经完成迁移。现有代码、测试和 Compose 中仍
   可能存在旧 Topic、`InfluxQuery`、InfluxDB、Telegraf、Grafana 及相关环境变量；这些
   均列为待迁移对象，完成验收前不得宣称新架构已落地。
9. 历史 InfluxDB `time` 不作统一业务时间解释。迁移器必须按 measurement 分支，保留
   `source_time_raw`、`source_time_semantics`、`time_quality`：`statistics`/`conflict`
   的 `time` 可能只是写入时刻，`track_complete` 还可能把流相对秒误当 Unix 秒而落在
   epoch 附近。无法证明的时间只作为 `ingested_at`，不得写成 `observed_at`/`occurred_at`；
   异常轨迹必须隔离，只有具备任务起点和视频时间轴证据时才可审计重建。
10. camera-scoped Topic 只能由统一 builder 根据消息类别和显式 `camera_id` 生成。禁止通过
    字符串替换从一个 Topic 推导另一个 Topic；全局 Topic 由 builder 的独立 canonical
    模板生成，不伪造 `camera_id`。
11. `track_complete`、`conflict`、AI event 和证据引用不得因内存队列满、进程退出或 send
    失败静默丢失，必须先进入持久化 spool/outbox，再异步发送并按稳定 `message_id` 重试。
    指标只有在契约明确允许有损时才能丢弃，同时必须上报 expected/sent/received/drop 与
    coverage，确保缺失不会被解释成零流量。
12. Consumer 关闭 Kafka auto commit。`uav_message_inbox`、payload hash 校验结果和事实数据
    同一 PostgreSQL 事务成功后才手动提交 offset；数据库失败时回滚且不提交，以便重放；
    数据库提交后、offset 提交前的崩溃重放由 inbox 幂等处理。
13. 历史 Telegraf 与 Platform Consumer 统计写入可能是同一观测的两条落库路径，迁移和
    对账必须按 source writer、Topic/partition/offset、message ID 或审计指纹去重，禁止
    简单相加。无法可靠关联时选择并记录权威来源，另一侧仅用于对账并降低质量标记。

### 边界与命名例外

- `uav_` 强制规则适用于无人机平台拥有和创建的业务对象。`road9` 中既有共享路网主数据、
  PostgreSQL 系统目录、TimescaleDB 扩展内部对象及第三方扩展对象不归无人机平台所有，
  不实施强制重命名。
- 路网主数据只读复用，平台业务表通过 `inter_id`、`link_id`、`lane_id` 和
  `road_data_version` 建立引用；不得复制或伪造权威 ID。
- 视频原文件、图片和大型证据文件可以继续由文件/对象存储承载；PostgreSQL 保存业务
  元数据、校验值和受控访问引用，不要求把大对象全部写进 hypertable。
- TimescaleDB 只解决时序存储和聚合，不改变无人机 AI 子项目与智慧交通主平台之间的
  业务边界；派警、处置、案件归档等闭环状态仍由主平台负责。

### 迁移方案

1. **盘点与备份**：冻结旧 measurement、查询、Topic、消费者和 Grafana 面板清单；备份
   PostgreSQL 与 InfluxDB，并记录消息量、数据保留期和基准查询结果。
2. **准备 road9**：确认连接实际进入 database `road9`，安装指定版本 TimescaleDB 扩展，
   通过受控迁移创建全部 `uav_` 表、hypertable、索引和最小权限账号；上线前执行恢复演练。
3. **消息命名迁移**：生产者通过统一 Topic builder 和显式 `camera_id` 发布 `uav_`
   Topic/`msg_type`，Consumer 短期双读新旧 Topic 并以统一幂等键去重；Consumer 关闭
   auto commit，数据库事务成功后手动提交 offset；WebSocket 与前端同步切换到 `uav_` channel。
4. **影子写入与回填**：在受控核验窗口把新消息写入 PostgreSQL/TimescaleDB，同时保留
   旧链路只用于对账。历史数据按 measurement 选择时间转换规则，并完整保存
   `source_time_raw`、`source_time_semantics`、`time_quality`；只有已验证或有证据可重建的
   时间才能进入业务时间列。无法证明的时间只作 `ingested_at`，epoch 异常轨迹进入隔离区；
   Telegraf 与 Platform Consumer 的重复统计按来源和消息身份去重、不得简单相加；同时
   禁止因重放造成重复流量、重复告警或重复交付。
5. **查询切换**：将 API、告警、历史轨迹、统计聚合和前端数据源切换到
   PostgreSQL/TimescaleDB，比较总量、分路口/车道聚合、抽样事件、迟到数据和查询延迟。
6. **下线旧链路**：验收通过且观察期结束后停止 InfluxDB 生产写入，禁用并最终移除
   Telegraf、InfluxDB、Grafana 服务、配置、健康检查和依赖；备份按约定期限留存。

### 回滚方案

- 在查询切换验收前保留旧链路的可恢复部署物和只读数据，并用功能开关控制新旧消费者与
  查询适配器；发生数据正确性或性能阻断时，可恢复旧 Topic 订阅和旧查询入口。
- 数据库迁移在观察期内不得直接删除旧数据或无备份地执行不可逆 DDL。回滚应用版本时，
  新 `uav_` 表保留为只读证据，避免丢失迁移窗口内的新事件。
- 若旧链路已正式下线，只能基于已验证备份和变更流程恢复，不得临时让生产者绕过 Kafka
  或直接写 InfluxDB。回滚后仍需以幂等键核对迁移窗口，防止双写重复。
- 回滚是临时恢复服务的措施，不撤销本 ADR；根因修复和数据对账完成后继续推进目标态。

### 影响

- **代码**：替换 `InfluxQuery` 及 InfluxQL，新增 PostgreSQL/TimescaleDB repository、
  写入批处理、幂等约束、Topic builder、持久化 spool/outbox、手动 offset 提交、覆盖率/
  丢弃指标、迟到数据处理和聚合查询；生产者、Consumer、WebSocket 和前端同步迁移
  `uav_` 名称。
- **数据库**：新增 TimescaleDB 扩展、受控 schema migration、hypertable 运维、备份恢复、
  数据保留/压缩/连续聚合策略和容量告警。这里的 schema migration 指数据库结构变更，
  不代表名为 `road9` 的 schema。
- **部署**：Compose 最终删除 Telegraf、InfluxDB、Grafana 及其 volume、端口、环境变量和
  健康依赖；PostgreSQL 镜像/服务必须具备与环境匹配的 TimescaleDB 扩展。
- **测试**：更新 Topic、WebSocket、数据库和前端契约测试；增加扩展可用性、幂等重放、
  时区/迟到数据、连续聚合、迁移回填、备份恢复和性能回归测试。
- **运维**：组件数量下降，但 PostgreSQL 成为更关键的数据底座，需要连接池、磁盘增长、
  WAL、慢查询、hypertable chunk 和备份恢复的专项监控。

### 完成门禁

- `current_database()` 返回 `road9`，TimescaleDB 扩展已启用且版本通过环境兼容性验证。
- 无人机平台自建物理表全部以 `uav_` 开头；目标 Topic、`msg_type` 和 WebSocket channel
  全部符合 `uav_` 命名，消费者幂等重放验证通过。
- `uav_message_inbox` 的 `(source_system, message_id)` 唯一约束、payload hash 冲突处理、
  Topic/partition/offset/status/fact references 均通过验证；inbox 与事实写入同事务，保留期
  覆盖最大重放窗口，hypertable 唯一键仅作为第二层防重。
- 所有 camera-scoped Topic 均由统一 builder 使用显式 `camera_id` 生成，静态检查和测试中
  不存在以字符串替换推导 Topic 的路径。
- `track_complete`、`conflict`、AI event 和证据引用在队列满、Kafka 不可用、进程重启和
  send 失败测试中均可由持久化 spool/outbox 恢复，无静默丢失；允许有损的指标具备完整
  expected/sent/received/drop/coverage 指标，缺失窗口不会被当作零流量。
- Consumer 已关闭 auto commit；只有 inbox 与事实同事务提交成功后才手动提交 offset。
  数据库失败、事务成功但 offset 未提交等故障注入场景均能重放且不重复生成事实。
- 迁移样本期内 PostgreSQL/TimescaleDB 与旧链路的事件总量、关键聚合和抽样明细对账通过，
  且查询延迟、写入吞吐和存储增长满足验收阈值。
- 每个历史 measurement 均有已评审的时间语义映射与样本证据；迁移记录完整保留
  `source_time_raw`、`source_time_semantics`、`time_quality`，无法证明的时间未进入
  `observed_at`/`occurred_at`，只作为 `ingested_at` 或隔离记录保留。
- 生产业务表中不存在因流相对秒误作 Unix 秒产生的 epoch 异常轨迹；所有命中项均已隔离，
  或已基于任务起始时间和视频时间轴完成可审计重建，且不会参与错误的聚合、排序和 SLA。
- 历史 Telegraf/Platform Consumer 双写统计已按来源与消息身份完成去重，对账结果不存在
  简单相加造成的翻倍；无法可靠关联的样本已隔离或明确标记低质量。
- 平台 API 和前端不再查询 InfluxDB 或 Grafana；生产 Compose 不再启动 Telegraf、
  InfluxDB、Grafana，相关凭据、volume 和健康检查均已按迁移计划处理。
- 备份恢复和回滚演练通过，迁移记录、异常差异和处置结果可审计。

### 待冻结参数

- TimescaleDB 版本、chunk 时间粒度、压缩/保留期、连续聚合刷新窗口和迟到数据容忍时间。
- 消息批量写入大小、重试退避、失败处理队列、最大可接受端到端延迟、历史回填范围，
  以及 `uav_message_inbox` 最大重放窗口和保留期。
- 旧 InfluxDB/Grafana 备份留存期限、停写观察期和最终销毁审批责任人。

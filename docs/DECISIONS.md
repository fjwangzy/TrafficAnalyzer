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

**状态**：已被 ADR-023 取代用于 `hover_cruise_v1`；仅作为 `hover_only_legacy` 历史回滚依据（2026-05-30）

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

**2026-07-24 补充**：巡航质量隔离引入 `formal_track_ids` 后，候选目标曾只绘制虚线框而被排除在 `sv.TraceAnnotator` 输入之外，造成检测输出视频中大部分尾迹消失。第一阶段恢复了候选琥珀虚线、紧凑 `#ID class C` 和统一图例，并以生产 `ShowNode.process` 差分形成显示门禁。后续真实数据排查又发现 MPS 非法框和正式/候选坐标基准混用；最终坐标与渲染决策由 ADR-022 取代第一阶段的 camera-warp递推和正式 `sv.TraceAnnotator` 历史方案。候选仍不进入正式业务，地理参考、地图覆盖和关联阈值均未放宽。

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

**状态**：Accepted（2026-07-13 采纳；2026-07-16 本机纯净切换完成；生产门禁待外部批准）

**2026-07-16 实施修订**：本机开发环境不迁移、不备份、不核验 PostgreSQL、旧时序库、
实验 TimescaleDB 或旧 Kafka 的任何历史数据。目标库使用首次创建的 `traffic_road9_data`，
从空白 `road9` 执行 Alembic 到 `20260715_0010`，只初始化管理员。旧容器已删除，指定旧
资产仅未挂载保留 7 天并由受保护脚本到期后人工清理。下文原“盘点/双读/影子写入/回填/
旧链路回滚”方案作为决策历史保留，但已取消，不得实现为兼容路径。

**替代关系**：替代 ADR-005、ADR-014 中的 InfluxDB 决策；部分替代 ADR-011 的旧
Topic 命名和 Telegraf 路径、ADR-013 的 Grafana/Telegraf 兼容目标。Kafka 的异步传输
职责和按业务类型分流仍然保留。

### 背景

本 ADR 决策时，仓库同时维护 PostgreSQL 业务数据与 InfluxDB 时序数据，并通过
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
7. 废弃旧观测生产链路。历史查询、时序聚合和页面可视化统一通过
   PostgreSQL/TimescaleDB、FastAPI REST/WebSocket 与 `console2` 完成。
8. 本机目标态已于 2026-07-16 落地：根 Compose、Platform、Console2、Nginx、依赖和
   活动测试中不保留旧运行兼容；生产范围继续由外部门禁控制。
9. 旧时间字段存在不可证明的业务语义，因此本机明确不执行历史迁移，也不创建迁移器、
   隔离表或对账路径。`source_time_raw`、`source_time_semantics`、`time_quality` 只服务于
   新 canonical 消息自身的可审计时间语义。
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
13. 旧统计双写数据不进入新库，不执行去重、对账或质量修复；新库只接收 canonical
    Topic/`msg_type` 并从空数据开始。

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

### 历史迁移方案（2026-07-16 已取消，不执行）

> 以下六步仅保存 2026-07-13 的原方案，不是当前任务、回滚路径或运行兼容依据。当前实施
> 采用空白新库，禁止盘点内容、备份、双读、影子写入、历史回填和旧数据对账。

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

### 历史回滚方案（2026-07-16 已取消，不执行）

> 以下内容仅保存原决策历史。本机失败时停止新栈排查，不恢复旧 Topic、旧查询入口或旧
> 数据挂载；修复后仍从纯净 `road9` 继续。

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
  时区/迟到数据、空库初始化、断库恢复和本机持续健康探测。
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
- 新 `road9` 只含管理员初始化记录，业务与时序表为空；不存在旧数据库、迁移审计表或隔离表。
- 平台 API 和 Console2 不查询旧存储；根 Compose 不启动旧服务，也不挂载旧卷或旧 bind 目录。
- 指定旧资产保留满 7 天、未被任何容器挂载，清理脚本具有固定 allowlist、到期校验、挂载
  检查、环境开关和精确确认串。
- 独立空栈、正式端口、断库恢复、30 分钟探测、全量回归和本机严格退役审计通过。
- 生产镜像、安全、HA、容量、RPO/RTO、试点和主平台联调继续 `blocked_external`。

### 待冻结参数

- TimescaleDB 版本、chunk 时间粒度、压缩/保留期、连续聚合刷新窗口和迟到数据容忍时间。
- 消息批量写入大小、重试退避、失败处理队列、最大可接受端到端延迟，以及
  `uav_message_inbox` 最大重放窗口和保留期。
- 生产镜像、安全、HA、容量、RPO/RTO、试点、主平台联调和生产退役审批责任人。

---

## ADR-020: Apple Silicon 开发态原生运行 Platform 与 MPS 检测

**状态**：Accepted（2026-07-21，本机开发态）

### 背景

Apple Metal/MPS 是 macOS 原生计算后端。Docker Desktop 在 Mac 上运行 Linux 虚拟机；即使
镜像选择 `linux/arm64`，容器仍没有 macOS 内核、Metal 驱动或 PyTorch MPS backend。此前
Platform 在容器内启动 YOLO 时只能走 CPU，真实任务常态 `inference_ms` 超过 2000ms。
将 Platform 留在容器、再通过宿主机 agent 执行检测虽然可行，但额外引入 token、路径映射、
双进程托管和 MJPEG 跨边界代理，开发态收益不足以抵消复杂度。

### 决策

1. Apple Silicon 开发态 Platform 必须使用原生 macOS arm64 `.venv-mps` 运行，不启动
   Docker Platform。Console2 使用 Vite 本地开发服务器。
2. `scripts/mac_local_platform.sh` 是正式开发入口：启动时 fail closed 校验 Darwin、arm64、
   `mps.is_built()` 和 `mps.is_available()`，再由用户级 `launchd` 托管 `run_platform.py`。
3. `PipelineManager` 只依赖本地 `start/inspect/stop` 执行边界，在 Platform 同一操作系统中
   创建检测进程组。Mac 启动配置固定注入 `.venv-mps`、`PIPELINE_DEVICE=mps`、
   `PIPELINE_IMGSZ=960` 与 `PYTORCH_ENABLE_MPS_FALLBACK=1`；设备预检失败不得回退 CPU。
4. 本地 Platform 和检测器通过 `127.0.0.1` 访问开发 road9/Kafka，文件仍受仓库
   `test_videos/` allowlist 约束，MJPEG/HLS 走本机回环，不存在 agent API 或路径翻译。
5. 根 `docker-compose.yaml` 仅作为生产发布拓扑。生产 Platform 与检测器在同一 Linux 容器
   环境中运行，由发布配置选择目标架构和 CPU/CUDA；不得携带 Mac remote-agent 特例。
6. NVIDIA CUDA MPS 与 Apple Metal/MPS 是不同能力，生产 `gpu-only` profile 不作为本机
   Apple MPS 开发入口。

### 验收证据

- 原生环境返回 Darwin/arm64、PyTorch 2.2.2、`mps_built=true`、`mps_available=true`。
- 原生 Platform REST 启动的进程命令含 `detection_node.device=mps`、`imgsz=960`；43 个
  Kafka `inference_ms` 样本为 P50 238.7ms、P95 388.1ms，仅 1 个首轮长尾超过 2000ms，
  验收结束后管道正常停止。
- Platform 回归为 149 passed、5 skipped；自动化覆盖本地执行器设备参数、进程组启停、
  路径 allowlist 与视频代理。

### 后果

- 开发态消除 Docker Linux VM 与宿主机 agent 边界，Platform、检测器和 MJPEG 生命周期更直接。
- 本机 Platform 由 `scripts/mac_local_platform.sh status|logs|stop|restart` 管理；road9 与 Kafka
  仍是外部依赖，启动脚本不会隐式创建或替换数据服务。
- `PYTORCH_ENABLE_MPS_FALLBACK=1` 只允许个别不受支持算子回退；设备预检和启动参数仍强制
  MPS，性能验收需持续观察 P95 和长尾，不能只看设备字符串。
- Docker Compose 不再承担开发启动职责，发布前必须单独执行生产镜像、secret、CPU/CUDA、
  健康检查和架构门禁。该 ADR 不代表 Linux 生产环境获得 Apple MPS。

### 拒绝的方案

- 仅设置 `platform: linux/arm64` 后在容器内使用 `device=mps`：缺少 macOS/Metal 后端。
- 容器 Platform 通过宿主机 HTTP agent 委派检测：可运行，但开发态引入不必要的鉴权、路径、
  媒体代理和双生命周期复杂度。
- 将 Docker socket 或任意宿主机命令执行能力暴露给 Platform：权限面过大。
- 在 MPS 不可用时自动回退 CPU：会重新引入 2000ms 以上常态延迟且掩盖部署错误。

## ADR-020：GCJ-02 + 高德地图两阶段重建（2026-07-21）

### 状态

已接受；四个已注册路口的影像拟合已通过技术演示质量门禁并发布 `lane_verified`。2026-07-22
视频回归按用户决定收敛为 2 条轨迹样本，不再等待九源全量跑完；此前已自然 EOF 的 5 源已
固化为 completed Mission，共 13,042 条轨迹。生产发布仍等待道路标线数据负责人的人工签署、
全源策略确认和不少于 100 条轨迹人工车道复核；技术演示通过不替代生产验收。

### 决策

1. GCJ-02 是唯一公共地理坐标系，高德 JS API 2.0 是唯一活动底图；ENU 仅用于米制计算。
2. 不迁移历史坐标或业务事实，不保留 OSM/OpenLayers、旧坐标字段或道路 JSON 运行时 fallback。
3. YCX 永远只读，仅在新路口本地无快照时按 `inter_id` 取该路口；WKT 文本在查询中由 PostGIS 转 geometry。road9/YCX 对象 ID 视为不透明 geomhash 字符串。
4. `lane_info` 是 Link 偏移候选，不是车道真值。真实正拍影像经 pixel↔ENU↔GCJ-02 配准、人工拟合和质量门禁后发布不可变 `lane_verified` 地图。
5. 该条已由 2026-07-30 的 ADR-025 修订：Mission 可选固定一个 Runtime Road Map Bundle，只有
   `lane_verified` 地图能生成正式 Lane/Link 匹配及车道级统计，运行中不热切换；地图和视觉配准
   不再控制车辆世界坐标、速度、方向或冲突。世界事实逐帧使用视频、相机参数和同步遥测，不能用
   地图制作配准或结束帧矩阵重算历史。
6. 第一阶段与第二阶段严格串行。未覆盖全部启用数据源绑定路口时，不启动正式全量重跑。
7. 测绘、轨迹、事件、Kafka 状态等历史业务数据已清除；仅保留可校验的原始 MP4/SRT/遥测/影像文件、SHA-256 清单与主数据，用于重新生成。

### 后果

- 清理后的业务行不能由系统直接恢复；需要外部备份或从保留原始素材重新生成。
- YCX lane 数与人工拟合数不一致时使用本地稳定车道键，YCX lane ID 可空。
- AMap Web Key 在容器启动时写入运行时配置；安全密钥为可选增强项，存在时浏览器通过
  `securityJsCode` 启用安全模式，不存在时仅使用 Web Key。Vite 与 Console Nginx 不提供
  `/_AMapService`。仅 Key 模式可能被高德警告或拒绝，这是 2026-07-22 用户明确接受的部署取舍；
  配置安全密钥时它会对浏览器可见，仍须以高德控制台域名白名单约束来源。
- 第二阶段验收必须完成 EOF、Kafka/数据库/前端对账、至少 100 条人工轨迹复核和 ≥95% 车道匹配准确率。
- 技术演示可先执行不少于 100 条的自动空间一致性与 GCJ-02/ENU 往返检查，但报告必须明确
  `operator_signoff_required`，不得把自动检查写成人工准确率。
- 用户可显式降低单次视频回归样本数；报告必须记录选择的 SourceProfile、最小样本数以及未跑
  来源，并继续保留默认 9 源/100 条严格模式。本次 2 条样本仅用于演示链验收。

## ADR-021：位姿感知 ByteTrack 位于逐帧地理参考之后（2026-07-23）

### 状态

已被 ADR-023 取代；本节仅保留 2026-07-23 首版世界关联的历史依据。

### 决策

将 YOLO 与 ByteTrack 从 `DetectionTrackingNodes` 拆开。YOLO 保持在进程 1；ByteTrack 关联迁至进程 2 的 `GroundTrajectoryTrackerNode`，严格位于 `FlightGeoReferenceNode` 之后。关联保留 ByteTrack 的高/低置信度双轮机制，同时使用相机补偿后 IoU、ENU Mahalanobis 距离、类别软约束和真实源时间。跟踪状态以时间制 2 秒丢失窗口管理，0.5 秒以上源时间断裂不续接。

地理参考质量是所有正式交通研判的前置条件。只有 `formal_analytics_eligible=true` 的 `formal_track_ids` 可以进入业务轨迹缓冲；候选 ID 可视化但永不进入统计/TCC。悬停正拍继续独占地图创建与发布权，巡航仅消费不可变 `lane_verified` Runtime Bundle。

### 回滚与后果

`tracking_profile=hover_only_legacy` 恢复旧悬停处理路径，但不回滚数据库迁移、不恢复旧 Topic、不删除质量事实。旧 ByteTrack 路径在生产门禁与稳定观察期完成前保留；之后删除，避免长期双实现。首版不引入神经 ReID；若正式标注集 IDF1 不达门禁，保持发布阻断并单独评审 ReID，不能放宽关联距离掩盖问题。

### 真实尾段验收补充

2026-07-23 使用 `inter_xqh` 的 840s–992.291s 真实 MP4+SRT、stride=4 和原生 MPS 执行工程验收。离场开始时先出现 `unsupported_pose`，没有经过普通 `transition`；这是姿态/速度质量越界优先于模式迟滞的安全结果。验收因此要求“悬停退出质量断点、正式轨迹以 `mode_transition_quality_break` 终止、之后业务泄漏为 0”，而不强制每个素材必须出现 `transition` 标签。

世界关联代价保持不变，但实现从每个 track×detection 都求一次 2×2 逆矩阵，改为每个 track 求逆一次并对 detections 向量化。该优化不改变阈值或匹配语义；标量/向量代价等价性由单元测试保护。真实尾段完整单进程帧 p95 为 383.11ms，工程吞吐门禁通过；无人工真值，ADR 状态仍为“已实施、生产准确率门禁阻断”。

## ADR-022：MPS 检测几何门禁与双坐标轨迹事实（2026-07-24）

### 状态

部分被 ADR-023 取代：MPS 安全检测几何继续有效；世界反投影显示与世界关联已废止。生产跟踪准确率仍受人工真值数据集阻断。

### 背景与决定

真实 xqh 悬停回放出现跨画面长线和局部折返。排查证明这不只是候选尾迹漏画：macOS 15.6、PyTorch 2.2.2 与 MPS 下，Ultralytics 选择的 sliced in-place `clamp_` 路径可静默产生零宽 bbox；同一帧 MPS 原路径有9个零宽框，MPS非原地裁剪与CPU均为0。这与 PyTorch 已记录的 [MPS sliced clamp correctness issue](https://github.com/pytorch/pytorch/issues/147510) 一致；Ultralytics 后续按系统版本恢复原地裁剪的 [PR 21878](https://github.com/ultralytics/ultralytics/pull/21878) 不能覆盖旧 Torch + 新 macOS 组合。

因此检测深模块在 Apple MPS 上固定选择非原地裁剪，并在 YOLO/ByteTrack 边界再次按行校验 bbox、置信度和类别。非法行永不进入关联；出现任一非法行时，剩余合法检测仍可预览，但该帧以 `invalid_detector_geometry` 阻断正式研判。新旧 tracking profile 共用这一边界，回滚不能恢复已知错误裁剪。

轨迹坐标同时保留但职责分离：`trajectory_px` 为源帧车辆接地点，`trajectory_enu_m/trajectory_gcj02` 为使用该帧矩阵得到的世界事实，`trajectory_bbox_center_px` 只保留旧中心锚点；四类坐标与源时间、帧号、质量谱系按同一索引保存。`trajectory_display_px` 是世界历史反投影到当前画面的派生缓存，只允许 ShowNode 使用，Kafka 发布前剔除。正式轨迹不再依赖 supervision 的隐式跨帧中心点缓存。

### 后果与证据

- 显示层可抑制小于交付尺度阈值的往返抖动，但不得改写任何图像或世界事实。
- `TrajectoryNode` 对长轨迹降采样必须对所有坐标和 lineage 使用同一索引。
- xqh 840s–EOF 原生MPS复验为24/24工程门禁：109899个检测、非法框0，active/completed/candidate对齐失败0，候选显示/世界残差P95 0.006px、最大0.007px，降级业务泄漏0，自然EOF通过。
- 对比图与机器报告分别为 `docs/test-screenshots/xqh-hover-trajectory-before-after-880.jpg` 和 `docs/generated/xqh-hover-departure-acceptance.json`。这些证据不等于IDF1/HOTA、位置RMSE或速度MAE生产验收。

## ADR-023：ByteTrack 前置纯图像关联，世界坐标只作 ID 后事实（2026-07-24）

### 状态

已实施并通过单元、真实 xqh 工程回归；其中“地理/地图质量中断结束正式业务分段”的生命周期
规则已由 ADR-025 取代。以下相关描述作为历史决策背景保留，当前实现以 ADR-025 为准。

### 背景

ADR-021 把 ByteTrack 放在逐帧地理参考之后，并将 ENU Mahalanobis 距离和 H 导出的相机 warp
写入关联代价。确定性反例证明：保持两帧图像、检测框和视觉 warp 完全相同，只给第二帧 H 增加
6m 平移，就会改变 ByteTrack 的匹配和 ID。H 来自遥测、相机模型、配准和视觉校正，误差不可避免；
因此世界坐标适合决定业务结果是否可信，不适合作为图像身份事实。

### 决策

`hover_cruise_v1` 的进程 2 固定为：

```text
ImageMotionEstimationNode
  → GroundTrajectoryTrackerNode（纯图像 ByteTrack）
  → HomographyCalibration/MotionCompensation/FlightGeoReference
  → PostTrackingWorldProjectionNode（ID 后世界事实与正式业务分段）
```

- `camera_motion_warp` 只允许来自排除目标检测框后的背景 LK/RANSAC 图像运动；H 导出的
  `pose_motion_warp` 只用于遥测/视觉一致性诊断。
- ByteTrack 公共接口不接受 H、ENU、世界位置、世界协方差、地图覆盖或地理参考质量；关联只使用
  视觉补偿后的 bbox IoU、高低置信两轮、类别软约束和真实源时间。
- `association_id` 是图像身份，在 H/遥测/地图质量中断时仍可连续用于候选显示；正式 `track_id`
  是通过世界投影和质量门禁的业务分段身份。质量中断立即结束正式分段，恢复时创建新正式 ID，
  用 `track_family_id/previous_track_id` 保留可审计关系。
- `trajectory_px` 保留各源帧接地点；`trajectory_display_px` 只由背景视觉 warp 递推；
  `trajectory_enu_m/trajectory_gcj02` 在 ID 确定后使用各点所属源帧 H 生成。ShowNode 禁止使用
  当前 H 重投影历史，世界误差不得反馈修改图像轨迹。
- `PostTrackingWorldProjectionNode` 独占新版像素→ENU→GCJ-02 转换，并让去畸变后的同一个接地点
  同时参与地图覆盖判断；`TrackerInfoUpdateNode` 只能消费该事实。`SpeedEstimationNode` 只回归逐帧
  ENU 历史，世界点不足时不使用当前 H 重投影历史像素；旧回退只保留在 `hover_only_legacy`。
- 源时间倒退或相邻处理帧超过0.5秒可以重置图像关联；遥测缺失、位姿越界、地图外和 H 抖动只能
  结束或降级正式业务分段，不能成为图像 ID 重置条件。

### 备选方案比较

1. **继续世界主关联**：在理想 H 下有利于高速相机运动，但把坐标误差直接转化为 ID switch，否决。
2. **图像主关联 + 弱世界提示**：可在歧义场景辅助，但仍无法保证 H 抖动不改变 ID，暂不采用。
3. **纯图像主关联 + 世界 shadow 审计**：边界最清晰；当前采用纯图像主关联，世界只做正式门禁和
   后验诊断。若正式数据集 IDF1 不达标，优先评审外观 ReID 或更强视觉运动模型，不放宽 H/世界权重。

### 证据与限制

- 单元测试固定“仅改变 H 不改变 ID”“H 只改变 ID 后世界点”“地理质量中断保持 association ID、
  新建正式业务 ID”“ShowNode 完全忽略当前 H”。
- 真实 xqh 840s–EOF 使用同一视频、SRT、模型和 stride 与世界关联版比较；观测 ID 数和寿命仅是
  无真值诊断，不能代替 IDF1/HOTA/ID switch。
- `hover_only_legacy` 回滚仍只恢复旧悬停业务，不恢复 ADR-021 的世界关联，也不回滚数据库迁移或
  canonical Topic。

## ADR-024：巡航跟踪采用自动化工程验收，不建设人工轨迹标注包（2026-07-25）

### 状态

已决定并实施。

### 决策

本项目不建设人工轨迹标注、AI预标注、标注任务分派或真值复核工作包。xqh和后续巡航视频只进入自动化工程回归，验证检测几何、图像关联代理、双坐标逐点对齐、质量断点、候选业务隔离、性能与自然EOF。IDF1、HOTA、正式ID switch、世界位置RMSE和速度MAE依赖独立真值；没有外部已批准真值时统一记为`not_evaluated`，不得把它们登记为内部交付待办或从观测ID、寿命、IoU、尾迹观感推导。

现有`uav.cruise-eval/v1`只保留为外部真值的可选只读评测入口，不生成或修改任何标注。该决定不改变悬停关键帧上的车道/地图人工复核，也不降低`degraded/unverified`业务泄漏必须为0、轨迹点列必须对齐、MPS吞吐和EOF等工程门禁。

### 后果

工程状态使用`local_engineering_acceptance_passed / production_accuracy_not_claimed`。它表示已验证的检测、候选跟踪、正式质量隔离与悬停流程可以交付，不等于宣称12m/s巡航精度。若未来外部项目提供经批准真值，可另行运行只读评测，但不扩大本项目范围。

## ADR-025：轨迹生命周期与路网匹配解耦（2026-07-28）

### 状态

已实施；取代 ADR-023 中“地图/地理质量中断结束正式 track_id”的部分。ADR-023 的纯图像前置关联、逐帧世界事实和显示隔离继续有效。

### 决策

- 图像轨迹是基础业务事实。ByteTrack 确认关联后立即分配稳定 `track_id`；只有关联消失、源时间断点、超时或自然 EOF 结束轨迹。
- `TrackerInfoUpdateNode.buffer_tracks` 定义为生命周期尚未结束的轨迹仓库，不再按 `buffer_analytics × 60 + min_time_life_track` 年龄清理。成熟状态对同一 `track_id` 单调；达到最短 2 秒和最少点数后保持成熟直至终止。
- `buffer_analytics=0.5` 只定义 30 秒道路入口事件窗口。成熟轨迹首次满足道路归属和 3 秒存在要求时登记一次；事件到期只影响辆/分钟，不得删除、完成、拆分或降级图像轨迹。
- 能力拆为 `trajectory_output_eligible`、`geo_analytics_eligible`、`road_analytics_eligible` 与 `tcc_analytics_eligible`。兼容字段 `formal_analytics_eligible` 只表示完整道路分析能力，不控制轨迹缓冲或完成事件。
- `uav_track_complete/v1` 不换 Topic 或版本，只在明确终止原因下产生。同一 `pipeline_id + track_id` 最多完成一次，消息 ID 由这两个字段确定性生成，使 inbox 拦截误重复。像素、源时间和帧号必填同索引；ENU/GCJ-02 等长且可逐点为 `null`。地图、车道、Link 与匹配置信度可空；Movement/方向属于轨迹自身世界运动事实，不由路网匹配赋值。
- 世界坐标由视频尺寸、相机参数和同步遥测形成的当前帧矩阵决定；不得增加独立注册输入或让地图矩阵覆盖该结果。地图 Bundle 可选，只为Lane/Link匹配提供独立地图锚点与几何。
- 速度/方向仅消费可信 ENU；road gate 只控制 Lane/Link ID 与匹配质量，且 RoadMapMatching 禁止创建或覆盖世界坐标和轨迹自身的方向/转向。通用车辆计数继续消费成熟图像轨迹；TCC 使用独立世界坐标、时间、跟踪和证据门禁。缺事实字段为空，禁止伪造零速度或零道路指标。

### 后果

无地图仍必须输出成熟像素轨迹；当前帧矩阵和遥测质量合格时，无地图也输出世界轨迹、速度、方向和TCC。只有Lane/Link及匹配质量依赖地图。候选只表示未成熟关联。该变更恢复轨迹事件不等于生产跟踪精度验收；无外部真值时 IDF1/HOTA、ID switch、位置 RMSE 与速度 MAE 仍为 `not_evaluated`。

`tracking_diagnostics.lifecycle` 向后兼容地报告 active/mature/candidate/completed 数量、终止原因和 `same_id_mature_to_candidate_count`；正常值必须为 0。历史 `road9` 只读审计发现的重复完成或缺少终止原因 Pipeline 只能保留为历史事实，不得用于正式统计，禁止自动清理或回写。

## ADR-026：固定时间步 Mahalanobis 门控退出生产关联（2026-07-29）

### 状态

已实施；生产关联恢复通过，Mahalanobis 保留为只读 shadow 诊断。

### 背景

2026-07-28 在 ByteTrack 第一轮高分关联中启用了
`gate_cost_matrix(..., only_position=True)`。Kalman 模型固定 `dt=1`，生产却默认每 5 个源帧处理一次。
对 8/10/15px 高的航拍小目标，该门控一次处理分别只允许约 2.69/3.36/5.04px 中心位移；
车辆正常穿越路口也会被置为无穷代价，随后形成短命 ID 和不成熟尾迹。

同一 xqh 400–430s、同一帧只执行一次 YOLO 的差分回归中，硬门控版本中心轨迹从旧版
20.84/帧降为 17.38/帧，中心 ID 从 63 增到 192，中位观测寿命从 37 降为 1。关闭硬门控并
保留相机运动补偿、类别策略、大目标初始化和 2 秒超时后，中心轨迹恢复为 19.81/帧、72 个 ID、
中位寿命 33。该代理只证明工程回归，不是 IDF1/HOTA。

### 决策

- 第一轮生产关联使用相机补偿后 IoU、检测置信度和类别软约束；Mahalanobis 不再改写匹配代价。
- 仍在代价副本上执行相同门控，并通过 `tracking_diagnostics.mahalanobis_gate` 输出有效候选数、
  本来会拒绝的有效候选数和会失去全部候选的轨迹数。
- 保留 2 秒真实时间丢失窗口、0.5 秒源时间断点、相机运动补偿、类别稳定和道路解耦。
- 只有取得外部批准的身份真值，并完成动态 dt、过程噪声和不同 stride 标定后，才能重新评审硬门控。

### 验收

`scripts/compare_xqh_bytetrack.py` 固化同检测输入回归。按 canonical 检测几何运行时，当前中心密度
为 7 月 15 日基线的 95.23%，中心碎片 ID 44、中位寿命 52，三项门禁通过；shadow 证明硬门控会
拒绝 1080 个本可匹配候选并使 671 条轨迹失去全部候选。完整 xqh 840s–自然 EOF 原生 MPS
25/25 通过，1142 帧、109899 个合法检测、61831 个关联、road/TCC 泄漏 0。

## ADR-027：AGL 三档推理尺寸与能力感知运行档（2026-07-29）

### 状态

已实施代码与自动化回归。xqh 动态策略 1142 帧全为 960 且零切档，但 YOLO p50=165.8ms，未过
100ms 性能门。按授权清空固定白名单中的历史轨迹/冲突事实并恢复 Docker 数据盘后，崇华路 v3
原生 MPS 自然 EOF，产生 6302 条完成轨迹和 56 条有效严格 TCC，88 个唯一证据文件通过 hash/size
校验。视频对齐 AGL 实为 156.35–178.15m，首帧进入 1280 后从未满足 `<152m` 下切条件，因此零切档
符合设计；整个遥测文件的 104–222m 范围不能替代对齐窗口。1280 档 YOLO p50=371.4ms，性能门仍失败。

### 决策

- `DetectionNode` 与 legacy `DetectionTrackingNodes` 共用一个只读遥测策略，只接受同步后的
  `altitude_agl` 或兼容 `height`。三档为 `<112m → 640`、`112–157m → 960`、`>=157m → 1280`；
  130m 的既有 928 实验归入 960。
- 2026-07-30 起，自适应在仓库配置、Platform 子进程启动和原生 MPS 回放入口全局默认开启；
  旧 `ADAPTIVE_IMGSZ_ENABLED=false` 不得静默改变生产配置。`--no-adaptive-imgsz` 只作为显式固定
  尺寸诊断入口保留，必须与生产验收产物隔离。
- 最近 5 个有效 AGL 取中位数，边界使用 5m 滞回，新档连续 5 个处理帧成立才切换；首帧立即选档。
  遥测缺失保持 2 秒源时间，之后回退固定 960。尺寸不得参与关联、世界坐标、道路或 TCC 门禁。
- FlightPlan/Mission 未显式指定 tracking profile 时固定选择 `hover_cruise_v1`；仅显式请求可选择
  `hover_only_legacy`。Mission snapshot 固化最终档与选择原因，运行/恢复不重选。
- `inference_ms` 定义为 YOLO 单处理帧耗时；另发 `pipeline_processing_ms` 和推理上下文。TCC 漏斗
  逐项记录过滤原因。`<100ms` 只能描述指定尺寸下的 YOLO 样本，不代表整帧 P95。
- `uav_stats` 追加向后兼容的 `recognition_diagnostics`：源画面合法检测、输出轨迹、未关联检测和
  `<=4096px²` 小目标覆盖分别计数。它只用于检测器→跟踪器工程归因；没有批准真值时不产生正式
  precision/recall，也不能把同帧转化率冒充跟踪准确率。
- Platform Kafka consumer 一次 poll 一条 canonical 消息，`max_poll_interval_ms=1800000`。这样密集
  Stats 在 Timescale 展开时不会因单条事务超过默认 5 分钟而触发 rebalance；数据库提交后再提交
  offset、inbox 幂等和消息契约均不改变。

### 后果

世界坐标、速度和TCC只按当前帧矩阵与遥测质量降级；地图缺失不再参与这些门禁。动态尺寸可改善不同高度的小目标覆盖，但在无外部批准真值时，IDF1/HOTA、正式 ID switch、
位置 RMSE 和速度 MAE 继续为 `not_evaluated`。

崇华路这份素材不能作为自然三档切换样本；三档实景延迟/检测/轨迹对比仍需一段对齐 AGL 真正跨越
107m、117m、152m、162m 滞回阈值的视频，不能通过修改阈值或使用未对齐遥测强行制造切档。

## ADR-028：检测-跟踪工程覆盖与正式精度分层（2026-07-30）

### 状态

已实施评估边界与只读复现工具；小目标关联增强保持后续独立任务。

### 决策

- `utils_local/detection_tracking_evaluation.py` 作为纯函数评估边界，只消费已捕获的 canonical Stats、
  Track Complete 和生命周期审计；`scripts/analyze_detection_tracking_coverage.py` 只负责文件适配。
- 同帧 `emitted_image_track_count / valid_yolo_detection_count` 及小目标/类别分层只叫工程覆盖率。
  ByteTrack 的确认、lost 保留和出画会改变分子，禁止称为 Precision、Recall 或正式跟踪率。
- 完整观测数与消息内序列化轨迹点分开统计；数字类别名单列为数据质量问题，不静默映射或回写历史。
- 没有批准外部真值时，Precision、Recall、IDF1、HOTA 和正式 ID switch 必须为
  `not_evaluated`。改进比较先使用同一帧、同一检测输入的 shadow/A-B，再决定是否进入生产关联。
- 小目标改进不得通过全局降低 YOLO/ByteTrack 阈值或放宽成熟门槛完成。优先补逐检测关联 lineage、
  实际 `dt`/目标尺度软代价、高运动采样与预算受控 ROI 二次检测。

### 后果

xqh 全量 1696 帧可以用于定位稳定悬停与离场阶段的工程差异，但不能作为生产准确率证明。完整数据、
根因树、分阶段实现和验收矩阵见 `docs/ADAPTIVE_DETECTION_TRACKING_ANALYSIS_20260730.md`。

## ADR-029：固定影像的参数化渠化编辑模型（2026-08-03）

### 状态

已实施。

### 决策

- 正拍证据图固定，路网覆盖层统一平移、绕像素中心旋转并等比缩放；原始单应矩阵只读。
- 服务端拥有最终矩阵组合权：`H_final = H_task × inverse(T_pose)`；携带姿态的客户端矩阵不一致即 422。旧矩阵-only请求继续有效。
- `editor_model` 与 `registration_pose` 均显式版本化，复用既有 JSON 列，不增加数据库迁移。曲线保存前确定性采样为 polygon，运行时不解释 Bézier 或模板参数。
- `editor_model.mode` 显式区分 `parameterized` 与 `freeform`；旧自由几何保存时不虚构进口骨架，但必须保留曲线控制点、人工要素和像素级重开状态。
- 人行横道、渠化岛、待转区、停止线、车道边界和分段标线升级为正式 Feature；影像叠加和干净渠化图共享同一视口和几何。局部调整以 `manual_override` 保护。
- 已发布地图只允许通过服务端 `derive-draft` 派生，来源版本写入 topology/quality，复核归零；Console 不拥有复制发布事实的权限。
- Runtime Bundle 剔除编辑器元数据，路网仍只增强 Lane/Link/Feature 匹配，不改变 trajectory/geo/tcc 独立能力。

### 后果

旧草稿和自由绘制无需预迁移，首次再次保存即补齐 `freeform` 编辑模型；已发布地图仍需派生新草稿。截图只作交互证据；生产精度仍由控制点残差、拓扑检查和人工复核决定。

## ADR-030：首页典型态势使用隔离的 YCX 只读模型（2026-08-04）

### 状态

已实施；仅用于本机普通模式首页演示与分析入口。

### 决策

- Platform 允许首页 `GET /api/v1/dashboard/situation` 通过独立连接只读访问 database=`ycx` 下的 `road9` 与 `xianchang` schema。每次查询必须处于 read-only transaction，不能执行 DDL/DML、复制服务器数据或写本地 `road9`。
- 该接口使用启用道路版本，将全量有效态势路口/Link 范围与所选星期、5 分钟时槽左联结；当槽缺指标仍返回灰色范围对象。响应明确标记 `typical_5min` 与 `Asia/Shanghai`，不得称为实时数据。
- 缓存键固定为道路版本、星期和时槽，TTL 为 5 分钟、最多 64 槽。只有同槽存在最近成功响应时，依赖失败才可返回 `stale=true`；首次失败必须结构化 503，Console 不回退态势 mock。
- 本地项目路口与服务器范围在 Console 合并，项目身份只增加外圈。启用视频源仅按真实 `inter_id` 匹配并按路口聚合；点击优先运行中 Pipeline，其次有效源、最后降级源。
- 此例外不改变 ADR-019 的 canonical 业务存储，也不扩大 ADR-020 的路网导入职责。检测管线、Mission、Kafka、无人机统计、事件、测绘和本地写事实继续只使用既有 canonical 链路。

### 后果

首页前三个 KPI、路口颜色和路段颜色来自服务器典型矩阵；机非冲突、事故测绘及治理复盘固定样例继续明确标记为演示数据。外部连接配置缺失或首次不可达时地图保留项目灰点和错误说明，不伪造生产态势。

## ADR-031：轨迹回放采用 Replay V2 shadow namespace（2026-08-04）

### 状态

已实施 shadow，五源工程基线与 XQH 全长自然 EOF/聚合/浏览器复验已完成；正式切换尚未批准。

### 决策

- 产品链路硬隔离：`实时监测 → BEV` 继续投放当前 Pipeline 的实时轨迹；`智能研判 → 轨迹回放` 只读取自然 EOF 后 sealed 的 Mission。监控页不得请求回放 API、建立回放时钟或混入历史 journey。
- 在线 ByteTrack ID 不变。终止 segment 先写外部 durable spool，Mission 自然 EOF 后才执行保守唯一 ReID、全序列速度冻结、行为派生和事件保真抽样；异常退出保持 incomplete，默认不进入回放。
- 同一 `road9` 内使用 `uav_replay_v2_*` 表和独立 `uav_replay_v2_alembic_version`；Kafka 使用 `uav_replay_v2_*_{source_key}` Topic 和独立消费者组。V2 Platform profile 只做 V2 迁移/消费并拒绝控制面写入。
- `/gis` 保留现有布局，但只按单 Mission T+ 时钟播放；“全部 Mission”只能汇总。无世界坐标时使用像素平面，明确质量 gap 不插值、不连线。
- shadow 默认端口为 Platform `8200`、Console `5273`、视频服务 `18101+`；大文件直接引用主工作树，spool、缓存、输出和证据写 `/private/tmp`。

### 后果

开发验证不会改写当前 `8000/5173` 演示实例、canonical 表、Topic 或 offset。所有 Kafka 发布节点（包括跨 Show 进程的 TCC 证据发布器）必须使用同一个 profile Topic 选择器；验收运行器要以前后 offset 捕获任何绕行，并等待 declared journey 与全部实际/典型聚合同时收敛。`uav_replay_v2_*` 是开发隔离命名，不是永久生产命名；五源基线及 XQH 全长自然 EOF、Kafka/PG 对账、容量/延迟、浏览器和既有回归已完成，但仍只有获得单独破坏性批准后才能暂停旧写入并评审迁回 canonical。没有批准真值时所有正式跟踪、位置、速度和 ReID 准确率保持 `not_evaluated`。

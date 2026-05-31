# TASKS.md — TrafficAnalyzer 任务追踪

> 基于 commit `e69acee` 的真实代码分析。

## 技术债清单

### 🔴 高优先级

#### TD-001: 硬编码 5 条道路
- **位置**：`nodes/CalcStatisticsNode.py:38-44`、`nodes/KafkaProducerNode.py:44-68`、`services/grafana/provisioning/dashboards/*.json`
- **问题**：道路数量硬编码为 5，不同路口有不同数量的道路（inter2 只有 2 条）
- **影响**：新增摄像头时如果道路数量不是 5，需要修改多个文件
- **建议**：从 `roads_info` 字典动态获取道路数量，Kafka 消息使用数组格式

#### TD-002: 4 个入口点代码重复
- **位置**：`main.py`、`main_optimized.py`
- **问题**：4 个文件共享相同的 import 列表、环境变量设置、节点初始化逻辑
- **影响**：修改管道节点顺序或新增节点需要同时修改 4 个文件
- **建议**：统一为一个入口 + `--mode` 参数

#### TD-003: 无测试
- **问题**：整个项目缺少自动化测试
- **影响**：无法验证重构的正确性，回归风险高
- **状态**：🟡 部分解决 — 已添加 `test_pipeline_inter_xqh.py`（49项端到端检查）、`test_pipeline_no_yolo.py`（无GPU CI测试）、`test_e2e_inter_xqh.py`（端到端集成测试）、`scripts/inject_test_data.py`（WebSocket数据注入）
- **建议**：继续为 `utils_local/utils.py` 和 `byte_tracker/` 编写单元测试

#### TD-004: Grafana 凭据硬编码
- **位置**：`export_dashboards.py:6`、`fetch_dashboard.py:5`、`update_dashboards.py:5`
- **问题**：`admin:admin` 凭据硬编码在脚本中
- **影响**：安全风险（虽然这些脚本仅用于开发环境）
- **建议**：从环境变量或 `.env` 文件读取

#### TD-013: Kafka 基础设施稳定性
- **位置**：`nodes/CalcStatisticsNode.py`
- **问题**：`roads_activity` 字典硬编码为 `{1:0, 2:0, 3:0, 4:0, 5:0}`，不从 `roads_info` 动态获取
- **影响**：不同路口道路数量不同时统计不完整
- **建议**：从 `frame_element.roads_info` 动态构建字典（与 TD-001 关联）

#### TD-014: congestion_index 未计算
- **位置**：`nodes/CalcStatisticsNode.py`
- **问题**：Kafka 消息格式中预留了 `congestion_index` 字段但从未计算
- **影响**：该字段始终为 0 或缺失
- **建议**：实现基于道路活跃度和车道排队长度的拥堵指数计算

#### TD-015: motion_compensation.py 死代码
- **位置**：`utils_local/motion_compensation.py`
- **问题**：`compensate_speed()`、`compensate_heading()`、`world_to_gps()` 函数已定义但未被任何节点调用
- **影响**：API表面积增大，可能误导后续开发者
- **建议**：删除死代码或明确标记为平台侧工具函数

#### TD-016: 轨迹世界坐标精度有限
- **位置**：`nodes/TrajectoryNode.py`、`nodes/TrackerInfoUpdateNode.py`
- **问题**：使用当前帧H+当前drone_displacement统一转换所有历史轨迹点，未存储每帧的独立位移
- **影响**：快速巡飞时（12m/s）长轨迹（8s）世界坐标误差达96m
- **建议**：在TrackElement中存储per-frame `(px, py, displacement_e, displacement_n)` 或接受限制（用于热力图足够）

#### TD-017: lane_history / segment_queues_by_gap 未使用
- **位置**：`elements/TrackElement.py:24`、`utils_local/lane_geometry.py`
- **问题**：`lane_history` 字段和 `segment_queues_by_gap()` 函数已实现但未被使用
- **影响**：代码冗余
- **建议**：删除或实现队列分段逻辑

#### TD-018: 遥测时间戳对齐需手动配置 time_offset_sec
- **位置**：`services/TelemetryFileReader.py`、`configs/app_config.yaml`
- **问题**：视频文件和遥测数据的起始时间不同步，需要手动计算并配置 `time_offset_sec`
- **影响**：每次使用新的视频+遥测对时需要手动计算偏移
- **状态**：🟡 部分解决 — SRT遥测(`SrtTelemetryParser`)支持逐帧1:1同步，无需时间偏移；JSON遥测仍需手动配置
- **建议**：优先使用SRT格式（从视频字幕提取），避免手动偏移计算

### 🟡 中优先级

#### TD-005: FrameElement 动态属性
- **位置**：`nodes/KafkaProducerNode.py:73`
- **问题**：`frame_element.send_to_kafka = True` 动态添加未声明的属性
- **影响**：FrameElement 的接口不明确，IDE 无法提供自动补全
- **建议**：在 FrameElement.__init__ 中声明 `send_to_kafka: bool = False`

#### TD-006: ShowNode 过于庞大
- **位置**：`nodes/ShowNode.py`（280 行）
- **问题**：渲染逻辑（绘制框、多边形、文本、统计面板）全部在一个文件中
- **影响**：难以维护和测试
- **建议**：拆分为 `BoxRenderer`、`RoadRenderer`、`StatsPanelRenderer` 等子组件

#### TD-007: VideoEndBreakElement 未初始化父类
- **位置**：`elements/VideoEndBreakElement.py`
- **问题**：继承 FrameElement 但只设置了 `video_source` 和 `timestamp`，其他字段（`frame`、`source` 等）未初始化
- **影响**：如果某个节点忘记 isinstance 检查就访问 FrameElement 字段，会抛出 AttributeError
- **建议**：调用 `super().__init__()` 传入空值，或不继承 FrameElement

#### TD-008: TrackerInfoUpdateNode 假设字典有序
- **位置**：`nodes/TrackerInfoUpdateNode.py:61`
- **问题**：`for key, track_element in sorted(self.buffer_tracks.items())` 后使用 `break` 假设后续元素都更新，但 sorted 按 key（ID）排序而非按时间戳排序
- **影响**：如果旧 ID 的轨迹比新 ID 的轨迹存活时间更长，可能不会被正确清理
- **建议**：不使用 break，遍历所有元素检查时间条件

#### TD-009: export_dashboards.py 硬编码 Windows 路径
- **位置**：`export_dashboards.py:25`
- **问题**：`out_dir = r"d:\ai\TrafficAnalyzer\..."` 硬编码了 Windows 路径
- **影响**：在非 Windows 环境下无法运行
- **建议**：使用相对路径或从参数读取

### 🟢 低优先级

#### TD-010: 注释语言混杂
- **问题**：代码注释混合中文、俄语和英语
- **影响**：阅读体验不一致
- **建议**：统一为中文（当前团队的主要语言）

#### TD-011: 无类型标注
- **问题**：大部分函数缺少类型标注
- **影响**：IDE 自动补全和静态检查效果差
- **建议**：逐步添加类型标注，优先标注公共接口

#### TD-012: Flask 帧更新无锁
- **位置**：`nodes/FlaskServerVideoNode.py:36,52-53`
- **问题**：`self._frame` 被主线程写入、Flask 线程读取，无锁保护
- **影响**：可能出现画面撕裂（一帧的上半部分和下一帧的下半部分）
- **状态**：✅ 已修复 — 使用 `self._frame_lock` 和预编码 JPEG bytes 方案

#### TD-013: Kafka 基础设施稳定性
- **位置**：`docker-compose.yaml`、`services/kafka/kafka_server_jaas.conf`、`platform/app/kafka/consumer.py`
- **问题**：
  - Kafka broker ID 不匹配（容器重启后 ID 变化，topic 分区 Leader:none）
  - SASL凭据通过空环境变量注入，JAAS配置无效
  - Platform Kafka consumer 无限重试阻塞 HTTP 服务
  - Kafka HOST listener advertised hostname 不支持本地 producer 路由
- **影响**：所有 Kafka 操作失败（LeaderNotAvailableError, GroupCoordinatorNotAvailableError），Platform HTTP 服务卡死
- **状态**：🟡 部分修复 — consumer 代码已修复（有限重试+降级模式）；docker-compose 配置已修复（固定 broker ID, HOST listener, PLAINTEXT EXTERNAL）；Kafka stale data 需手动清除
- **修复文件**：`docker-compose.yaml`, `services/kafka/kafka_server_jaas.conf`, `services/kafka/init-kafka-broker.sh`, `platform/app/kafka/consumer.py`, `services/nginx/nginx.conf`
- **修复脚本**：`scripts/fix_kafka_and_restart.sh`
- **建议**：开发环境优先使用 PLAINTEXT listener；生产环境需恢复 SASL 并创建 `.env`

---

## 待办事项

### 已完成 ✅
- [x] 管道端到端测试（`test_pipeline_inter_xqh.py`，49/49 PASS）
- [x] Kafka topic pattern 扩展（statistics + track_complete + conflicts + telemetry）
- [x] 平台 PipelineManager（管道生命周期管理）
- [x] 平台 Pipeline REST API（start/stop/monitor）
- [x] 平台 Kafka consumer 处理 conflict + telemetry 消息
- [x] drone_store 动态更新（Kafka stats + telemetry 双源）
- [x] SRT 遥测解析器（`SrtTelemetryParser`，逐帧同步）
- [x] docker-compose 统一（postgres + platform 服务加入主 compose）
- [x] 前端 WebSocket 事件处理（monitoring: conflict/track_complete, dashboard: 真实数据）
- [x] inter_xqh 道路多边形配置（4K 视频适配）
- [x] Kafka consumer 有限重试机制（防止阻塞 HTTP 服务）
- [x] Kafka 基础设施配置修复（固定 broker ID, PLAINTEXT listener）
- [x] Monitor 页面实时数据验证（WebSocket publish 注入 → 前端显示）
- [x] WebSocket 数据注入脚本（`scripts/inject_test_data.py`）
- [x] Kafka 修复脚本（`scripts/fix_kafka_and_restart.sh`）

### 近期（1-2 周）
- [ ] 清除 Kafka stale data（运行 `scripts/fix_kafka_and_restart.sh`）
- [ ] 验证本地 Kafka → Platform 完整数据流（HOST listener 路由修复后）
- [ ] 验证 MJPEG 视频流（管道 + Flask → nginx → Monitor 页面）
- [ ] 优化 inter_xqh 道路多边形（精确标注道路区域）
- [ ] 修复 TD-008：TrackerInfoUpdateNode 的字典排序问题
- [ ] 修复 TD-005：FrameElement 动态属性
- [ ] 修复 TD-009：export_dashboards.py 路径问题
- [ ] 为 `utils_local/utils.py` 添加单元测试
- [ ] Mission-Pipeline 绑定：创建任务时自动启动检测管道
- [ ] 前端 Drones 页面接入 `telemetry:{drone_id}` WebSocket 实时遥测
- [ ] 前端 Dashboard 的 `pipelines_active` 字段对接真实数据

### 中期（1-2 月）
- [ ] 解决 TD-001：道路数量配置化
- [ ] 解决 TD-002：统一入口点
- [ ] 解决 TD-006：ShowNode 拆分
- [ ] 为 ByteTrack 核心算法添加单元测试
- [ ] 合并 docker-compose 文件（统一 Kafka/InfluxDB/Nginx 实例）
- [ ] GIS 轨迹回放（基于 track_complete Kafka 消息）
- [ ] 管道健康监控面板（PipelineManager 状态 + 进程日志流）

### 远期（3-6 月）
- [ ] 评估是否升级到 InfluxDB 2.x
- [ ] 评估是否使用 ultralytics 内置跟踪替代 byte_tracker/
- [ ] 添加 RTSP 流的自动重连机制
- [ ] 支持任意数量的道路（动态 Grafana 仪表盘）
- [ ] 巡检报告自动生成（PDF/HTML）
- [ ] 多无人机任务调度
- [ ] VLM 语义分析旁路

---

## 已知 Bug

### BUG-001: ~~main_stream_optimized_v2.py 进程管理不一致~~ (已修复，文件已删除)
- **状态**：已修复。`main_stream_optimized.py` 和 `main_stream_optimized_v2.py` 已整合到 `main_optimized.py`，新入口包含完整的 `is_alive()` + 队列超时健康检查

### BUG-002: VideoSaverNode 在 VideoEndBreakElement 时可能崩溃
- **位置**：`nodes/VideoSaverNode.py:24`
- **描述**：如果视频的第一帧就是 VideoEndBreakElement（空视频），`self._cv2_writer` 为 None，调用 `.release()` 会抛出 AttributeError
- **修复**：添加 `if self._cv2_writer is not None:` 检查

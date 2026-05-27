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
- **位置**：`main.py`、`main_optimized.py`、`main_stream_optimized.py`、`main_stream_optimized_v2.py`
- **问题**：4 个文件共享相同的 import 列表、环境变量设置、节点初始化逻辑
- **影响**：修改管道节点顺序或新增节点需要同时修改 4 个文件
- **建议**：统一为一个入口 + `--mode` 参数

#### TD-003: 无测试
- **问题**：整个项目没有任何测试
- **影响**：无法验证重构的正确性，回归风险高
- **建议**：优先为 `utils_local/utils.py` 和 `byte_tracker/` 编写单元测试

#### TD-004: Grafana 凭据硬编码
- **位置**：`export_dashboards.py:6`、`fetch_dashboard.py:5`、`update_dashboards.py:5`
- **问题**：`admin:admin` 凭据硬编码在脚本中
- **影响**：安全风险（虽然这些脚本仅用于开发环境）
- **建议**：从环境变量或 `.env` 文件读取

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
- **建议**：使用 `threading.Lock` 保护帧更新

---

## 待办事项

### 近期（1-2 周）
- [ ] 修复 TD-008：TrackerInfoUpdateNode 的字典排序问题
- [ ] 修复 TD-005：FrameElement 动态属性
- [ ] 修复 TD-009：export_dashboards.py 路径问题
- [ ] 为 `utils_local/utils.py` 添加单元测试

### 中期（1-2 月）
- [ ] 解决 TD-001：道路数量配置化
- [ ] 解决 TD-002：统一入口点
- [ ] 解决 TD-006：ShowNode 拆分
- [ ] 为 ByteTrack 核心算法添加单元测试

### 远期（3-6 月）
- [ ] 评估是否升级到 InfluxDB 2.x
- [ ] 评估是否使用 ultralytics 内置跟踪替代 byte_tracker/
- [ ] 添加 RTSP 流的自动重连机制
- [ ] 支持任意数量的道路（动态 Grafana 仪表盘）

---

## 已知 Bug

### BUG-001: main_stream_optimized_v2.py 进程管理不一致
- **位置**：`main_stream_optimized_v2.py:88-107`
- **描述**：`proc_frame_reader` 在 Process 中启动，但 `proc_proceessor` 在主进程中运行。然而代码中 `processes[0].join()` 等待的是 reader 进程，如果 processor 先退出，reader 会继续运行
- **复现**：RTSP 流断开时 processor 退出，但 reader 进程不会自动终止
- **修复**：参考 `main_stream_optimized.py` 中的 `is_alive()` 检查模式

### BUG-002: VideoSaverNode 在 VideoEndBreakElement 时可能崩溃
- **位置**：`nodes/VideoSaverNode.py:24`
- **描述**：如果视频的第一帧就是 VideoEndBreakElement（空视频），`self._cv2_writer` 为 None，调用 `.release()` 会抛出 AttributeError
- **修复**：添加 `if self._cv2_writer is not None:` 检查

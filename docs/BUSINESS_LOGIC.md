# BUSINESS_LOGIC.md — TrafficAnalyzer 核心业务逻辑

> 当前实现说明基于 commit `84c6bd6` 的真实代码分析；标记为“目标态”的消息命名与
> 持久化逻辑依据 ADR-019（2026-07-13），尚未完成代码、数据库和 Compose 迁移。

## 核心业务流程

### 0. 视频读取与跳帧

**实现文件**：`nodes/VideoReader.py`

`VideoReader` 从 MP4、RTSP 或摄像头读取原始帧，并按视频时间戳注入遥测数据。为兼顾离线全帧分析和实时预览速度，提供两类抽帧参数：

- `video_reader.skip_secs`：按视频时间间隔抽帧，例如 `0.5` 表示相邻处理帧至少间隔 0.5 秒。
- `video_reader.frame_stride`：按原始帧号抽帧，例如 `12` 表示每 12 帧处理 1 帧；`FrameElement.frame_num` 保留原始帧号，`timestamp` 仍来自视频时间轴。低 FPS 本机实时预览时可通过 `FRAME_STRIDE=10~12` 让画面中的车辆运动速度接近正常，只是运动会更跳跃。

### 1. 车辆检测

**实现文件**：`nodes/DetectionTrackingNodes.py`

**流程**：
1. 从 FrameElement 取出原始帧（BGR numpy 数组）
2. 调用 `YOLO.predict(frame, imgsz=1280, conf=0.05, classes=[0,1,2,3,4,5,6,7,8,9])`
3. 提取检测框：`detected_conf`、`detected_cls`、`detected_xyxy`
4. 将检测结果转换为 ByteTracker 格式 `[x1, y1, x2, y2, conf, class_id]`
5. 调用 `BYTETracker.update(detections)` 进行多目标跟踪
6. 提取跟踪结果：`tracked_xyxy`、`tracked_cls`、`tracked_conf`、`id_list`

**关键细节**：
- VisDrone 全类别进入检测与跟踪，原始 `class_id` 保留到下游用于 motor/non_motor 分类。
- 航拍小目标非机动车置信度较低，默认使用 `imgsz=1280`、`confidence=0.05` 保留电动车/三轮车候选；代价是 CPU 推理变慢且误检增多。
- NMS IOU 阈值 0.7 较高，允许更多重叠框通过

**模型**：
- `weights/uav_best.pt` — 自定义无人机视角 YOLO11 模型，检测交通工具类别。
- `weights/yolo11l-visdrone.pt` — VisDrone 类别模型，类别为 `pedestrian/people/bicycle/car/van/truck/tricycle/awning-tricycle/bus/motor`。

**motor/non_motor 分类**：
- 由 `vehicle_classification` 配置驱动，只维护非机动车类别集合。
- 优先按模型返回的类别名匹配 `non_motor_class_names`，类别名缺失时按 `non_motor_class_ids` 兜底。
- 未命中的已知类别默认归类为 `motor`；完全缺失类别名和类别 ID 时保持 `unknown`。
- 由于摩托车和电动车无法稳定区分，`motor/motorcycle/motorbike/e-bike/electric-bike/electric-bicycle/ebike/scooter/electric-scooter` 默认归类为 `non_motor`。
- 当前 VisDrone 默认非机动车 ID 为 `[0, 1, 2, 6, 7, 9]`，覆盖 `pedestrian/people/bicycle/tricycle/awning-tricycle/motor`。

### 2. 多目标跟踪（ByteTrack）

**实现文件**：`byte_tracker/byte_tracker_model.py`

**算法流程**（每帧执行）：
```
输入：YOLO 检测结果 [bbox, score, class]

Step 1: 按分数分为高分组（> first_track_thresh=0.05）和低分组（> second_track_thresh=0.01）

Step 2: 第一轮关联（高分框）
  - 卡尔曼滤波预测已有轨迹新位置
  - 计算轨迹池与高分检测框的 IOU 距离矩阵
  - fuse_score 融合检测置信度
  - 线性分配（lap.lapjv 算法）

Step 3: 第二轮关联（低分框）
  - 未匹配的高分轨迹 + 低分检测框
  - IOU 距离矩阵 + 线性分配（阈值 0.5）
  - 这一步恢复了被遮挡或模糊的目标

Step 4: 处理未确认轨迹
  - 仅存活 1 帧的轨迹与剩余高分框再次匹配
  - 未匹配的标记为 Removed

Step 5: 初始化新轨迹
  - 剩余未匹配的高分检测框初始化为新 STrack
  - 当前实现还要求 `score >= first_track_thresh + second_track_thresh`，因此小目标阈值需联合调低，否则低分电动车/三轮车会有检测框但无法进入最终 tracked 输出。

Step 6: 清理超时轨迹
  - lost 状态超过 max_time_lost 帧的轨迹标记为 Removed

输出：当前帧的活跃轨迹列表 [STrack]
```

**卡尔曼滤波器**（`byte_tracker/utils/kalman_filter.py`）：
- 8 维状态空间：`[cx, cy, aspect_ratio, height, vx, vy, va, vh]`
- 恒速运动模型：`x(t+1) = x(t) + vx`
- 不确定性权重相对于 bbox 高度动态缩放（DeepSORT 风格）
- `shared_kalman` 类变量实现所有轨迹共享同一滤波器实例

### 3. 道路分配

**实现文件**：`nodes/TrackerInfoUpdateNode.py` + `utils_local/utils.py:intersects_central_point`

**流程**：
1. 遍历当前帧的所有跟踪 ID
2. 如果 ID 不在 `buffer_tracks` 中，创建新的 TrackElement
3. 如果 ID 已在缓冲区中，更新 `timestamp_last`
4. 如果 `start_road` 尚未确定：
   - 计算 bbox 中心点 `(cx, cy)`
   - 创建 `shapely.geometry.Point(cx, cy)`
   - 遍历所有道路多边形，检查 `Polygon.contains(Point)`
   - 如果匹配，记录 `start_road` 和 `timestamp_init_road`
5. 清理超过 `buffer_analytics` 时间的旧轨迹

**道路多边形格式**：
```json
{
  "1": [x1, y1, x2, y2, x3, y3, x4, y4],  // 4 个顶点的四边形
  "2": [...],
  ...
}
```
由 `generate_lanes.py` 交互式标注生成，或手动编辑。

### 4. 统计计算

**实现文件**：`nodes/CalcStatisticsNode.py`

**cars_amount（车辆总数）**：
```python
self.cars_buffer.append(len(frame_element.id_list))  # 当前帧检测到的车辆数
info["cars_amount"] = round(np.mean(self.cars_buffer))  # 滑动窗口平均
```
- 窗口大小：`count_cars_buffer_frames`（默认 25 帧）
- 使用 `deque(maxlen=25)` 自动丢弃旧值
- **为什么用滑动窗口**：单帧检测数量波动大（YOLO 漏检/误检），平均后更稳定

**roads_activity（道路活跃度）**：
```python
for track_element in buffer_tracks.items():
    if (track_element.timestamp_last - track_element.timestamp_init_road > min_time_life_track
        and track_element.start_road is not None):
        roads_activity[start_road] += 1

# 转换为 辆/分钟
for key in roads_activity:
    roads_activity[key] /= buffer_analytics  # buffer_analytics = 0.5 分钟
```
- 只统计存活时间超过 `min_time_life_track`（3 秒）且有明确起始道路的轨迹
- 除以时间窗口得到"辆/分钟"单位
- **为什么用 buffer_analytics 而不是实时窗口**：需要足够的时间窗口才能反映真实的交通流量

### 5. Kafka 消息发送（当前实现）

**实现文件**：`nodes/KafkaProducerNode.py`

**发送频率**：每 `how_often_sec`（默认 1 秒）发送一次

**消息格式**：
```json
{
  "camera_id": "id_1",
  "cars": 12,
  "road_1": 4.2,
  "road_2": 3.8,
  "road_3": null,
  "road_4": 2.1,
  "road_5": 1.5,
  "lane_source": "manual|auto|null",
  "lanes": [
    {
      "lane_id": "auto_1",
      "name": "东→西 直行",
      "direction": "straight",
      "flow_veh_per_min": 4.2,
      "avg_speed_kmh": 22.1,
      "queue_length_m": 45.2,
      "stopped_count": 3,
      "headway_sec": 14.3
    }
  ]
}
```
- `road_N` 为 `null` 当 `timestamp < buffer_analytics_sec`（缓冲区未充满时）
- `cars` 始终发送（不等待缓冲区）
- `lane_source`: `"manual"` (有人工标注) | `"model"` (YOLO分割模型检测) | `"auto"` (自动推断) | `null` (无车道数据)
- `lanes`: 统一格式数组，前端直接读取，无需区分来源

`send_to_kafka` 字段已在 FrameElement 中声明（TD-005 已修复），KafkaProducerNode 设置后由下游节点消费。

#### 5.1 目标消息命名

Kafka 继续承担检测管道到平台之间的异步传输与削峰，但所有无人机平台消息入口必须统一
使用 `uav_` 前缀：

| 业务消息 | 目标 Topic | 目标 `msg_type` 示例 |
|---|---|---|
| 周期态势指标 | `uav_statistics_{camera_id}` | `uav_stats` |
| 完成轨迹 | `uav_track_complete_{camera_id}` | `uav_track_complete` |
| 冲突事件 | `uav_conflicts_{camera_id}` | `uav_conflict` |
| 无人机遥测 | `uav_telemetry_{camera_id}` | `uav_telemetry` |
| 系统指标 | `uav_system_metrics` | `uav_system_metrics` |
| 统一 AI 事件（规划） | `uav_ai_events` | `uav_ai_event` |
| 主平台反馈（规划） | `uav_ai_event_feedback` | `uav_ai_event_feedback` |

当前代码中的 `statistics_*`、`track_complete_*`、`conflicts_*`、`telemetry_*` 和
`system_metrics` 均是待迁移旧名称。迁移期间可以短期双读或双发用于核验，但目标态不得
长期保留无 `uav_` 前缀的别名。

所有带相机维度的 Topic 必须通过统一 builder 以消息类别和显式 `camera_id` 生成，例如
输入 `statistics + camera_id` 选择 `uav_statistics_{camera_id}` 模板。业务代码不得使用
`str.replace()` 或其他字符串替换，从统计 Topic 推导轨迹、冲突或遥测 Topic。

#### 5.2 目标持久化业务规则

平台 Consumer 接收消息后按以下顺序处理：

1. 校验 Topic 与 `msg_type` 均符合 `uav_` 命名规则，并校验消息版本、事件时间、来源标识
   和幂等键；不合格消息进入可观测的失败处理流程，不直接写业务表。
2. 以 PostgreSQL 连接数据库 `road9` 为唯一平台持久化入口；`road9` 是 database 名，
   不能在实现中默认当作 schema 名。
3. 每条消息以 `(source_system, message_id)` 登记长期 canonical 表
   `uav_message_inbox`，保存 payload hash、Topic、partition、offset、处理 status 和事实
   引用。inbox 登记、hash 校验、事实写入与 fact references/status 更新必须在同一事务内
   完成：相同键且 hash 相同按重复消息返回，hash 不同视为冲突并进入审计/死信处理。
   inbox 保留期必须覆盖最大重放窗口，不能在重放仍可能发生时提前清理。
4. 不同路口/路段/车道粒度的交通指标通过 `grain_type`、`grain_key` 统一写入
   `uav_traffic_metrics`：`grain_type` 取 `intersection`、`link`、`lane`，`grain_key`
   分别对应权威 `inter_id`、`link_id`、`lane_id`；不再为不同粒度另建同义指标表。
   系统指标与遥测分别写入 `uav_system_metrics`、`uav_telemetry_metrics`。三者均为
   TimescaleDB hypertable，以业务观测时间为时序主时间，接收时间单独保留用于计算链路延迟。
5. 完成轨迹的摘要写入普通业务表 `uav_track_events`，轨迹采样点写入 hypertable
   `uav_track_points`；冲突时序事件写入 hypertable `uav_conflict_events`。
6. 统一 AI 事件写入 `uav_ai_events`；可靠投递、每次尝试、主平台反馈和死信分别写入
   `uav_event_outbox`、`uav_event_delivery_attempts`、`uav_event_feedback`、
   `uav_dead_letters`；证据包和证据条目分别写入 `uav_evidence_packages`、
   `uav_evidence_items`。反馈消息仍使用 `uav_ai_event_feedback` Topic/`msg_type`，消息名
   与物理表名不要求相同，但映射必须在契约中固定。
7. 全部事实写入完成后更新 inbox status/fact references，并提交同一 PostgreSQL 事务。
8. Consumer 必须配置 `enable_auto_commit=false`；仅在第 7 步事务提交成功后手动提交 Kafka
   offset。数据库失败时回滚且不提交 offset，等待重放；数据库已提交但 offset 提交前崩溃
   时，重放消息由 `uav_message_inbox` 幂等识别。
9. 事务提交后，再按业务范围向 `uav_intersection:{intersection_id}`、`uav_alerts`、
   `uav_alerts:{intersection_id}`、`uav_system`、`uav_telemetry:{drone_id}` 或
   `uav_calibration` 广播实时消息；告警新增/更新分别使用 `uav_alert_new`、
   `uav_alert_updated`，车道标注任务保留 `uav_lane_annotation_task`。写库失败时不得把
   未持久化数据伪装成已成功处理。
10. 平台自建物理表名统一以 `uav_` 开头。`road9` 内既有共享路网主数据、PostgreSQL
   系统对象及 TimescaleDB 扩展内部对象不归无人机平台所有，不要求重命名；业务记录通过
   `inter_id`、`link_id`、`lane_id` 和路网版本关联它们。

TimescaleDB hypertable 的唯一约束必须包含时间分区列，因此只能作为第二层防重；跨时间、
迟到和重放消息的第一层幂等必须由 `uav_message_inbox` 完成，不能只依赖事实表唯一键。

目标态不再写入 InfluxDB，也不再通过 Telegraf 转换指标；历史查询、聚合和运营页面均从
PostgreSQL/TimescaleDB 读取。分区粒度、压缩、保留期、连续聚合和数据降采样参数需要在
上线容量评估后冻结，不能沿用 InfluxDB 配置直接推定。

#### 5.3 生产发送可靠性与数据覆盖率

- 完成轨迹、冲突、AI 事件和证据引用必须先进入持久化 spool/outbox，再尝试放入内存发送
  队列。内存队列只是吞吐优化，不是可靠性边界；队列满或 Kafka send 失败时记录必须仍在
  持久层，并按稳定 `message_id` 重试，禁止只记日志后丢弃。
- 证据文件可仍由对象/文件存储承载，但其引用、哈希和关联事件进入可靠 outbox；不能出现
  事件已交付而证据引用因队列溢出永久缺失的状态。
- 周期指标若经容量评审明确允许有损，必须在 `uav_system_metrics` 中同时报告期望样本数、
  实际生成/发送/接收数、drop 数和 coverage，使查询方能够识别统计缺口；禁止把缺失窗口
  当作零流量。
- spool/outbox 持久化失败属于链路故障，必须触发健康降级和告警，不能继续返回“发送成功”。

#### 5.4 历史数据时间语义与双写去重规则

新消息应分别携带业务时间和接收时间：指标/遥测使用 `observed_at`，事件使用
`occurred_at`，平台另存 `ingested_at`。迁移旧 InfluxDB 数据时不得假设 point `time`
就是业务时间，处理规则如下：

1. 按 measurement 和历史写入代码分支转换，不允许一套通用映射覆盖
   `statistics`、`conflict`、`track_complete` 等不同来源。
2. 原始时间和值域判断结果必须随记录保存为 `source_time_raw`、
   `source_time_semantics`、`time_quality`；转换和重建过程必须可追溯。
3. `statistics` 与 `conflict` 的 Influx `time` 可能是写入时刻。只有 payload 中存在可验证
   的帧/事件时间并能与任务窗口对应时，才填充 `observed_at`/`occurred_at`；否则该时间只
   作为 `ingested_at`，业务时间保持未知并退出业务时序聚合。
4. `track_complete` 可能把流相对秒当成 Unix 秒，表现为时间落在 epoch 附近或明显超出
   无人机任务窗口。命中异常规则的轨迹必须隔离，禁止按错误时间写入生产 hypertable。
5. 只有同时具备任务开始时间、流相对秒及可核验视频/帧证据时，才可按
   `task_started_at + stream_relative_seconds` 重建轨迹时间，并标记
   `source_time_semantics=stream_relative`、`time_quality=inferred`；否则保留原始值并维持
   `invalid`/`unknown`，等待人工处置。
6. 数据查询和连续聚合默认只使用 `verified` 或经批准的 `inferred` 业务时间。只有
   `ingested_at` 的记录用于迁移审计和数量对账，不参与趋势、轨迹排序、告警时效或 SLA。
7. 历史统计可能由 Telegraf 与 Platform Consumer 同时写入；两路记录不得简单相加。优先
   使用 source writer、Topic/partition/offset、message ID 去重，缺失这些键时使用经过评审
   的业务指纹并选择一个权威来源；无法可靠判定的样本只进入对账/隔离结果并降低质量标记。

### 6. 模型车道检测（YOLO 分割）

**实现文件**：`nodes/LaneDetectionNode.py`

**目标**：当无人工标注车道数据时，使用 YOLO 分割模型从图像中检测车道标线和路面区域，生成稳定的车道多边形。与基于轨迹聚类的自动推断相比，模型检测的车道基于图像视觉特征，位置固定不随车流变化，统计更稳定可靠。

**优先级链**：`人工标注 (manual) > 模型检测 (model) > 轨迹推断 (auto)`
- 有人工标注（`lane_polygons` 已加载）→ 标记 `lane_source="manual"`，跳过模型
- 无人工标注 → 运行 YOLO 分割模型 → 标记 `lane_source="model"`
- 模型未检测到任何车道 → 回退到 `AutoLaneInferenceNode`（`lane_source="auto"`）

**模型**：`weights/lane_detect.pt` — YOLO 分割模型，类别 `{0: 'lane', 1: 'pavement'}`

**两种检测策略**：
1. **pavement 类（路面区域）**：直接使用分割 mask 作为车道多边形
2. **lane 类（车道标线）**：对 mask 做形态学膨胀（`buffer_pixels=50px`），将细线扩展为车道区域，再提取多边形

**工作模式**：
- `first_frame_only=True`（默认）：仅在首帧运行模型，后续帧复用结果。适合固定摄像头。
- `first_frame_only=False`：每 `detect_interval` 帧运行一次。适合无人机/移动摄像头。

**输出字段**：
- `FrameElement.lane_polygons` — `{lane_id: shapely.Polygon}` 字典，供下游 `LaneAnalysisNode` 使用
- `FrameElement.detected_lane_polygons` — 同上（独立字段，用于可视化区分）
- `FrameElement.lane_source` — `"manual"` | `"model"` | `"auto"` | `None`

**管道位置**：`DirectionFlowNode` → **`LaneDetectionNode`** → `LaneAnalysisNode`

### 7. 自动车道推断

**实现文件**：`nodes/AutoLaneInferenceNode.py` + `utils_local/auto_lane_inference.py`

**目标**：完全移除对人工标注线的依赖，从车辆轨迹数据中自动推断车道中心线和交通指标。

**向下兼容**：如果存在车道标注数据（`lane_polygons`）或模型已检测到车道（`lane_source` 为 `"manual"` 或 `"model"`），`AutoLaneInferenceNode` 自动跳过。仅在无任何车道数据时才启用自动推断。

**算法步骤**：

1. **收集已完成轨迹**：从 `completed_tracks` 中收集轨迹点序列、方向类别、车速等，存入滚动缓冲区（默认 3 分钟窗口）

2. **方向分桶**：按 `turn_behavior` 将轨迹分为 直行/左转/右转/掉头 四个桶

3. **空间聚类**：在每个桶内，使用层次聚类（scipy `fcluster`），以入口点和出口点的最大距离为距离度量，将空间邻近的轨迹归为同一车道

4. **中心线拟合**：对每个聚类内的所有轨迹重采样到等距点，取均值生成平滑中心线

5. **自动标签**：根据入口朝向角度自动转换为中文方位词（东/南/西/北），生成如 "东→西 直行" 的标签

6. **活跃轨迹匹配**：将当前帧的活跃跟踪匹配到最近的推断车道（基于 bbox 中心到中心线的最小距离）

7. **实时指标计算**：
   - **count**：当前车道内的活跃车辆数
   - **avg_speed_kmh**：平均车速
   - **stopped_count / queue_length_m**：排队车辆数和排队长度
   - **flow_per_min**：滑动窗口内的完成轨迹数（辆/分钟）
   - **avg_headway_sec**：连续完成轨迹之间的时间间隔（车头时距）

**聚类参数**（可通过 `configs/app_config.yaml` 的 `auto_lane` 部分调整）：
- `window_sec=180`：轨迹缓冲窗口
- `min_tracks_per_lane=3`：最少轨迹数（低于则不成簇）
- `entry_exit_threshold_px=120`：聚类距离阈值（像素）
- `recluster_interval_sec=5`：重新聚类间隔（避免每帧都聚类）

**输出**：`FrameElement.inferred_lanes` — `{lane_id: InferredLane}` 字典

### 8. 可视化渲染

**实现文件**：`nodes/ShowNode.py`（使用 supervision 库优化展示效果）

**渲染内容**：
1. 检测框或跟踪框（取决于 `show_only_yolo_detections` 配置）— 使用 `sv.BoxAnnotator` / `sv.RoundBoxAnnotator`
2. 跟踪 ID 标签 + 车速（km/h）— 使用 `sv.LabelAnnotator`（带圆角彩色背景）
3. 轨迹尾迹 — 使用 `sv.TraceAnnotator`（可通过 `show_trace_trails` 配置）
4. 道路多边形轮廓 + 可选透明遮罩（`sv.MaskAnnotator`）
5. 道路编号（在区域中心）
6. FPS 计数器
7. 方向流量统计叠加（S:/L:/R:/U: + Q:）
8. 车道多边形叠加（带标签背景）
9. 自动推断车道中心线 + 统计面板（入口/出口标记 + 方向箭头 + 各车道指标）

**MJPEG 输出清晰度**：
- `FlaskServerVideoNode` 默认输出 `[1280, 720]`，避免 4K 航拍画面被压缩到 800px 宽后目标和标签不可读。
- JPEG 编码质量默认 `92`，标签框线和文字按 720p 输出加粗。

**轨迹可视化过滤**：
- `ShowNode` 在绘制前会裁剪 bbox 到画面范围，并过滤 NaN/Inf、完全越界、面积过小的框，避免异常 Kalman 预测框被画到左上角。
- 跟踪模式只显示已分配道路或 bbox 中心落在道路 ROI 内的轨迹；低置信度小目标检测开启后，屋顶/树木/施工区域的误检轨迹不会继续堆积在画面边缘。
- 当未配置道路标注文件时，`roads_info={}`，可视化保留有效跟踪框，但道路分配、道路流量统计和人工道路 ROI 过滤不可用；自动推断车道仍可绘制中心线/箭头，但不绘制左上角车道统计黑底面板，避免无道路模式下的 overlay 堆积。
10. 统计面板（独立黑色窗口，拼接在主帧右侧）

**颜色逻辑**（通过 `ColorPalette` + `ColorLookup` 管理）：
- 默认 `show_class_different_colors=True`：按目标类别固定着色，`pedestrian/people`、`bicycle`、`car`、`van`、`truck`、`tricycle`、`awning-tricycle`、`bus`、`motor/motorcycle` 使用不同颜色；框、标签背景、轨迹尾迹保持同色。
- 如果关闭类别色且 `show_track_id_different_colors=True`：使用 `sv.ColorPalette.DEFAULT`（21色循环）+ `ColorLookup.TRACK`，按 tracker_id 自动着色
- 如果关闭类别色和 track id 色：构建自定义 `ColorPalette`（从 `colors_roads` BGR→RGB 转换）+ `np.ndarray` color_idx 数组，按 `start_road` 道路颜色着色
- 如果车辆尚未分配到道路：使用默认道路颜色索引显示，不再额外绘制黑色框

**代码结构**：
- `_draw_detections()` — 纯检测模式
- `_draw_tracked()` — 跟踪模式（圆角边框 + 标签 + 轨迹）
- `_draw_roads()` — 道路多边形（边框 + 遮罩 + 编号）
- `_draw_fps()` — FPS 信息
- `_draw_direction_overlay()` — 方向流量统计
- `_draw_lane_polygons()` — 车道多边形
- `_draw_inferred_lanes()` — 自动推断车道中心线 + 统计
- `_draw_stats_panel()` — 统计信息面板
- `_build_detections()` — 从列表构建 `sv.Detections` 对象
- `_configure_tracking_colors()` — 配置颜色方案
- `_class_color_indices()` — 将类别名归一化为稳定调色板索引

### 9. 机非冲突 near-miss 预测

**实现文件**：`nodes/ConflictDetectionNode.py`

冲突检测默认启用，但要求存在有效单应性矩阵；无米级世界坐标时自动跳过，避免像素距离误报。节点只比较 `motor` 与 `non_motor` 轨迹，两个机动车或两个非机动车不会生成机非冲突。

冲突不再等同于“未来轨迹几何交汇”。节点先使用双方世界坐标运动趋势，在 `0-5s` 预测窗口内生成候选交汇，再通过专项场景和 near-miss 证据过滤误报。有足够历史轨迹时，预测方向优先取最近一个有效轨迹段，速度大小沿用 `SpeedEstimationNode` 的米/秒估计；这样保留测速线性回归的平滑性，同时避免转弯或历史回归向量把未来轨迹拉向虚假交点。历史不足时才回退到 `track.velocity_ms`。

```
motor_future(t) = motor_pos + motor_velocity * t
non_motor_future(t) = non_motor_pos + non_motor_velocity * t
d(t) = |motor_future(t) - non_motor_future(t)|
```

候选交汇：

1. 路径交叉点：两条恒速预测轨迹在未来窗口内存在空间交点，双方到达该交点的时间差不超过 `arrival_time_tolerance_sec`（默认 `1.0s`），且在双方到达交点这段时间内连续同刻中心距必须进入 `same_time_collision_radius_m`（默认 `0.8m`）共同冲突区。这是默认业务口径，要求既有明确冲突点，也有同一时空占用概率；只有数学射线交点但同刻距离仍偏大的轨迹会被过滤。
2. 同刻 CPA 扩展：`enable_same_time_cpa` 默认关闭，避免只因中心点擦肩距离为 0.9m~1.7m 就判成相撞。显式开启后，对双方相对运动求最近接近点（CPA），只有最近距离进入 `same_time_collision_radius_m`（默认 `0.8m`）才作为 TTC 候选；`collision_radius_m` 不再直接用于同刻触发。CPA 候选中的 `pet_sec=0` 只表示同一预测时刻测距，不作为 PET 侵占证据。
3. 冲突角过滤：只保留 `30°~150°` 的横向/斜向交叉冲突，过滤同向并行、追尾类和近似正面对向场景。

前端业务回放只展示 `prediction_type=path_intersection` 且 `distance_m` 近似 `0.0` 的事件；旧格式 Kafka/WebSocket 消息仅在缺少 `prediction_type` 且 `distance_m` 近似 `0.0` 时按路径交点兼容，避免历史 0.9m/1.3m/1.7m CPA 擦肩事件或畸形 path 事件继续进入冲突列表。

专项场景：

- `suspected_right_turn_mv_nmv`：机动车历史轨迹呈右转，非机动车近似直行。
- `suspected_unprotected_left_turn`：机动车历史轨迹呈左转，非机动车近似直行。

机动车转弯不仅要求首尾 heading 差超过 `turn_angle_threshold_deg`（默认 `45°`），还要求转弯前后两段投影位移都不小于 `min_turn_leg_m`（默认 `2.0m`），避免短窗口抖动、小折线或近直行轨迹被误分为右转/左转。以上场景均为无车道标注下的轨迹几何近似，因此字段使用 `suspected_*`。不依赖道路/车道多边形；`ROADS_JSON=""` 时仍可运行。

near-miss 证据：

- `hard_ttc_sec`（默认 `1.5s`）以内视为极危险 TTC，可直接触发 `hard_ttc_or_pet`。
- `hard_pet_sec`（默认 `1.0s`）以内只表示极近 PET 抢行强度，需叠加至少一种避险行为证据才触发事件，避免仅凭数学路径交点把“近距离错位经过”报成 near-miss。
- 普通 TTC/PET 风险同样必须叠加至少一种避险行为证据：`hard_deceleration`（默认最大减速度 `<= -3.0m/s²`）、`hard_steering`（非机动车短窗口 heading 突变；机动车正常右/左转不计作避险急转向）、`stop_or_yield`（从移动降到低速停止/让行）。

`ttc_sec` 表示预测冲突时间；`pet_sec` 表示双方到达冲突点的时间差近似值；路径交叉点场景下同时输出 `motor_arrival_ttc_sec` / `non_motor_arrival_ttc_sec` 和 `arrival_time_delta_sec`。事件附加输出 `conflict_scene`、`conflict_angle_deg`、`evidence`、`risk_score`。`motor_id` / `non_motor_id` 轨迹对同级别事件不重复上报，但允许从 `warning` 升级为 `critical` 再次上报；直到任一轨迹从 `buffer_tracks` 清理后释放状态。

## 事故测绘业务闭环（S3）

1. 任务先完成任务上下文、作业授权、现场指挥、设备和存储五项前置核验；缺项进入 `precheck_failed`，不能开始采集。
2. MP4 与 DJI `.srt` 以内容寻址方式写入本地证据存储，保存 SHA-256、字节数和父子派生关系；服务器材料导入还必须通过 realpath allowlist。
3. `SurveyWorker` 从 `uav_capture_ingestion_jobs` 取出任务，提取 6 个关键帧，生成原始帧/BEV、遥测覆盖和清晰度/曝光观测；失败按可配置次数重试并保留错误。
4. 用户选择可用批次后进入量算。浏览器只提交图像像素几何，服务端使用该帧变换计算 ENU 米制点、长度、折线长度、面积和周长，并把每次修订保存为版本链。
5. 提交复核至少需要一项带 metric geometry 的当前量算；复核可通过或带原因退回“补拍/修订量算”。技术复核通过不等于法定事故认定。
6. 报告生成前重新计算全部引用材料的 SHA-256 和大小，输出 PDF、canonical JSON、GeoJSON 与 manifest hash；重复请求用 `Idempotency-Key` 返回同一业务结果。
7. 报告只有在 `survey_quality` 规则已批准且配置主平台 URL 后才创建 `survey_result` 事件和 outbox；worker 记录每次 HTTP 尝试，超过上限进入 dead letter。当前未冻结阈值保持 `unverified`，不得伪造“质量通过”或成功回执。

## 统计数据的完整生命周期

### 当前实现（待迁移）

```
帧 N 进入 VideoReader
  → 原始帧 + 道路坐标
帧 N 进入 DetectionTrackingNodes
  → YOLO 检测到 15 辆车 → ByteTrack 分配 ID [1,2,3,...,15]
帧 N 进入 TrackerInfoUpdateNode
  → buffer_tracks 新增 ID 16,17
  → ID 3 首次进入道路 2 的多边形 → start_road=2
  → 清理超过 33 秒的旧轨迹
帧 N 进入 LaneDetectionNode
  → 无人工标注 → YOLO 分割模型检测车道标线 → 膨胀为车道多边形
  → lane_source="model", lane_polygons={lane_1: Polygon, ...}
帧 N 进入 LaneAnalysisNode
  → lane_polygons 存在 → 车辆分配到车道 → 计算车道级流量/排队/车头时距
帧 N 进入 CalcStatisticsNode
  → cars_amount = mean([15,14,16,...]) = 15
  → roads_activity = {1: 8, 2: 12, 3: 6, 4: 4, 5: 2} / 0.5min
帧 N 进入 AutoLaneInferenceNode
  → lane_source="model" → 跳过（模型检测优先于轨迹推断）
帧 N 进入 KafkaProducerNode
  → 距离上次发送 > 1 秒 → 发送 JSON 到 statistics_1 topic
帧 N 进入 ShowNode
  → 绘制所有框 + 多边形 + 统计面板
  → frame_result 写入 FrameElement
帧 N 进入 VideoSaverNode / FlaskServerVideoNode
  → 写入文件或推流
```

当前生命周期只描述检测管道代码事实；其下游仍可能由 Telegraf 写 InfluxDB，并由 Grafana
展示。该旧链路已废弃，不能作为目标验收依据。

### 目标持久化生命周期

```text
帧/轨迹/冲突在检测管道形成业务结果
  → KafkaProducerNode 发布 uav_* Topic 和 uav_* msg_type
  → Platform Consumer 校验 schema_version / occurred_at / source_event_id / idempotency_key
  → 关联 road9 中的路口、路段、车道权威 ID 与 road_data_version
  → 在同一事务登记 uav_message_inbox 并写入 database=road9 内的 uav_* 事实表
      ├── 时序：uav_traffic_metrics / uav_system_metrics / uav_telemetry_metrics /
      │         uav_track_points / uav_conflict_events
      └── 业务：uav_track_events / uav_ai_events / uav_event_outbox / ...
  → PostgreSQL 事务提交成功后手动提交 Kafka offset
  → 广播 uav_* WebSocket channel
  → traffic-fly-console 展示实时状态，并通过 REST 查询 TimescaleDB 历史与聚合数据
```

业务失败语义：

- 重复消息以业务幂等键去重，不重复累计流量、不重复生成告警或交付记录。
- 数据库暂时不可用时，由 Consumer 重试或进入失败处理队列；恢复后按原事件时间补写，
  不得以接收恢复时间替代业务观测时间。
- 路网映射缺失时保留原始本地标识并标记 `unmapped`，不得伪造 `inter_id`、`link_id`、
  `lane_id`；后续补映射不得无审计地改写历史版本。
- PostgreSQL/TimescaleDB 是目标态唯一统计与事件查询源。InfluxDB 仅允许在迁移核验期
  只读对账或短期影子写入，完成切换后必须停止生产写入并下线 Grafana/Telegraf/InfluxDB。

# BUSINESS_LOGIC.md — TrafficAnalyzer 核心业务逻辑

> 2026-07-17 当前实现已完成 ADR-019 本机 canonical 切换；运行时仅使用
> `road9`/TimescaleDB、Kafka KRaft、`uav_*` 消息和 Console2。旧链路只作为明确标记的
> 历史背景保留，不得恢复兼容、双写或迁移。

## S4 执法候选业务边界（I4 本地工程实现）

- 当前实现支持本地 candidate 围栏/规则、AI 待复核线索事实、证据不可变引用/哈希、技术确认/驳回和追加审计；不执行未经批准的生产执法规则，不自动形成违法或处罚结论。
- 车辆分类契约仅为 `truck/non_truck/unknown`。unknown 或低质量事实不能被规则升级为高置信货车线索，也不能推导重/中/轻型、核载或法定车型。
- 视频、雷达和融合速度是三个独立来源字段。没有真实雷达设备 ID 和有效检定元数据时雷达值为空；没有独立视频/雷达测量和融合方法时融合值为空，禁止相互回填。
- 本地围栏与规则只保存版本化候选配置。权威 RoadContext、围栏发布和业务审批合同未冻结时，发布请求返回 503，页面必须明确 `unverified/blocked`。
- `platform/scripts/validate_i4_inter_xqh.py` 使用真实 MP4/SRT 的字节数和 SHA-256 验证证据/幂等/复核接缝，但固定 `validation_fixture=true`、`detected_enforcement_clue=false`；该样本不是检测算法产生的执法线索。

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

当前运行代码只接受表中的 canonical 名称。`statistics_*`、`track_complete_*`、
`conflicts_*`、`telemetry_*` 和 `system_metrics` 仅是历史名称；不得双读、双发、fallback
或增加适配器。

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
   监控页读取历史态势时必须同时限定 `inter_id` 与当前 `source_profile_id`，使用类型化指标列
   并按 `granularity` 降采样；转向图直接展示 `direction_flow` 中的直行、左转、右转计数，
   不得用不存在的车型字段补零。监控近期事件同样要求当前 SourceProfile lineage，无法证明
   来源的全局告警不能进入该视频源视图。
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

#### 5.4 历史数据时间语义与双写去重规则（历史分析，当前不执行）

新消息分别携带业务时间和接收时间：指标/遥测使用 `observed_at`，事件使用
`occurred_at`，平台另存 `ingested_at`。以下规则仅保存已取消的旧数据迁移风险分析；当前
本机不读取、不校验、不迁移旧 InfluxDB 数据：

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
- Pipeline 启动或外部进程登记时必须返回浏览器可达的 `video_stream_url`；实时监控屏和无人机回放屏共用该地址直连检测器，不经 Vite/Platform 转发视频字节。

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

前端业务回放只展示 canonical `prediction_type=path_intersection` 且 `distance_m` 近似
`0.0` 的事件；缺少 canonical 类型或使用旧 Kafka/WebSocket shape 的消息直接拒绝，不恢复
历史兼容。这样避免旧 0.9m/1.3m/1.7m CPA 擦肩事件或畸形 path 事件进入冲突列表。

专项场景：

- `suspected_right_turn_mv_nmv`：机动车历史轨迹呈右转，非机动车近似直行。
- `suspected_unprotected_left_turn`：机动车历史轨迹呈左转，非机动车近似直行。

机动车转弯不仅要求首尾 heading 差超过 `turn_angle_threshold_deg`（默认 `45°`），还要求转弯前后两段投影位移都不小于 `min_turn_leg_m`（默认 `2.0m`），避免短窗口抖动、小折线或近直行轨迹被误分为右转/左转。自动模型只产生候选；正式研判必须固定 `lane_verified` 地图并由 `RoadMapMatchingNode` 给出车道、Link、流向和置信度。

near-miss 证据：

- `hard_ttc_sec`（默认 `1.5s`）以内视为极危险 TTC，可直接触发 `hard_ttc_or_pet`。
- `hard_pet_sec`（默认 `1.0s`）以内只表示极近 PET 抢行强度，需叠加至少一种避险行为证据才触发事件，避免仅凭数学路径交点把“近距离错位经过”报成 near-miss。
- 普通 TTC/PET 风险同样必须叠加至少一种避险行为证据：`hard_deceleration`（默认最大减速度 `<= -3.0m/s²`）、`hard_steering`（非机动车短窗口 heading 突变；机动车正常右/左转不计作避险急转向）、`stop_or_yield`（从移动降到低速停止/让行）。

`ttc_sec` 表示预测冲突时间；`pet_sec` 表示双方到达冲突点的时间差近似值；路径交叉点场景下同时输出 `motor_arrival_ttc_sec` / `non_motor_arrival_ttc_sec` 和 `arrival_time_delta_sec`。事件附加输出 `conflict_scene`、`conflict_angle_deg`、`evidence`、`risk_score`。`motor_id` / `non_motor_id` 轨迹对同级别事件不重复上报，但允许从 `warning` 升级为 `critical` 再次上报；直到任一轨迹从 `buffer_tracks` 清理后释放状态。

冲突事件在 `KafkaProducerNode` 阶段、进入 `ShowNode` 之前调用 `utils_local/event_evidence.py`。该深模块只读取同一个 `FrameElement`，分别复制生成原始画面、带目标框/类别/轨迹 ID 的检测器输出画面，以及叠加同期 `buffer_tracks.trajectory_points`、高亮冲突 pair 的轨迹还原画面；它不修改共享内存原帧。三图以一个有序证据包可靠发布，Platform 必须完整校验三项后再登记内容地址和 SHA-256，检测图与轨迹图通过 `derived_from_id` 回指原图。旧事件若只存在 `conflict_keyframe` 仍可查询展示，但不会凭空补造缺失画面。

Console2 的事件证据展示按业务语义标注三图：`conflict_original_frame` 为“原始画面”，`conflict_detector_frame` 为“检测器输出的 TCC 画面帧”，`conflict_trajectory_reconstruction` 为“轨迹投放 BEV 视图”。显示名称不改变底层 kind、派生关系、内容哈希或证据访问契约。

节点每帧同时写入 `FrameElement.tcc_diagnostics`，记录检测开关、单应性有效性、motor/non_motor 输入数、双方合格轨迹数、候选配对、预测候选、证据通过、去重、正式路径交点事件和实验事件数量。诊断状态区分 `disabled`、`missing_calibration`、`no_eligible_candidates`、`no_prediction_candidates`、`no_evidence`、`deduplicated` 与 `events_emitted`。该漏斗随 `uav_stats.data.tcc_diagnostics` 发布，用于解释合法零检出；它只描述检测过程，不替代事件事实或召回率真值。

## 事故测绘业务闭环（S3）

1. 任务先完成任务上下文、作业授权、现场指挥、设备和存储五项前置核验；缺项进入 `precheck_failed`，不能开始采集。
2. 已登记 SourceProfile 的 MP4 与 DJI `.srt` / DJI Cloud JSON `.json/.txt` 不写入证据卷，而以 `server_asset` allowlist 相对键、SHA-256、字节数和 size/mtime/ctime 快速指纹形成不可变引用；派生关键帧/BEV/报告使用 `managed` 内容寻址对象。指纹未变化时快速确认，指纹变化时必须重新计算完整 SHA-256；绝对路径、路径穿越、allowlist 外文件、缺失或哈希变化均阻止可信处理。
3. `SurveyWorker` 从 `uav_capture_ingestion_jobs` 取出任务，按来源记录的遥测类型、时间偏移和容忍窗口提取 6 个关键帧，生成原始帧/BEV、遥测覆盖和清晰度/曝光观测；失败按可配置次数重试并保留错误。已知遥测缺口必须保留 `degraded`，不能用插值伪装连续。
4. 用户选择可用批次后进入量算。浏览器只提交图像像素几何，服务端使用该帧变换计算 ENU 米制点、长度、折线长度、面积和周长，并把每次修订保存为版本链。服务端同时只读下发 BEV→ENU 变换，画布在鼠标移动时把当前预览边换算为米并贴在线段中点；已保存折线、面积和对象的每条边使用持久化 `metric_geometry` 标长，浏览器计算值不替代服务端成果。
5. 提交复核至少需要一项带 metric geometry 的当前量算；复核可通过或带原因退回“补拍/修订量算”。技术复核通过不等于法定事故认定。
6. 报告生成前重新计算全部引用材料的 SHA-256 和大小；按量算关联帧生成带几何与逐边长度的标注 JPEG，将其作为派生证据嵌入 PDF，并随 canonical JSON、GeoJSON 与 manifest hash 输出。历史任务优先展示固化标注图；旧报告可由不可变 BEV 和版本化量算记录只读重绘，不回写旧版本。重复请求用 `Idempotency-Key` 返回同一业务结果。
7. 报告只有在 `survey_quality` 规则已批准且配置主平台 URL 后才创建 `survey_result` 事件和 outbox；worker 记录每次 HTTP 尝试，超过上限进入 dead letter。当前未冻结阈值保持 `unverified`，不得伪造“质量通过”或成功回执。
8. 场景标注只能关联已持久化关键帧，车辆、痕迹、散落物和其他对象的创建/修改/删除保留 revision 与统一审计；渠化车道标注从真实关键帧显式创建任务，发布后形成不可变 `lane_verified` 地图。Pipeline 有已验收地图时固定对应 Runtime Road Map Bundle；未绑定路网仍可启动目标检测、像素跟踪和 MJPEG，但不得把缺少地图匹配的结果作为正式车道、世界坐标轨迹或车道级研判事实。
9. 冲突节点实际产出事件时才保存研判关键帧并附到统一证据包；当前素材没有真实事件时应保存“未检出事件”事实，禁止为了验收制造冲突。

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
  → 距离上次发送 > 1 秒 → 发送 canonical JSON 到 uav_statistics_1 topic
帧 N 进入 ShowNode
  → 绘制所有框 + 多边形 + 统计面板
  → frame_result 写入 FrameElement
帧 N 进入 VideoSaverNode / FlaskServerVideoNode
  → 写入文件或推流
```

当前生命周期直接进入 canonical Kafka 与 `road9`；Telegraf、InfluxDB、Grafana 已从运行态
退役，仅在历史文档中保留背景。

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
  → Console2 展示实时状态，并通过 REST 查询 TimescaleDB 历史与聚合数据
```

业务失败语义：

- 重复消息以业务幂等键去重，不重复累计流量、不重复生成告警或交付记录。
- 数据库暂时不可用时，由 Consumer 重试或进入失败处理队列；恢复后按原事件时间补写，
  不得以接收恢复时间替代业务观测时间。
- 路网映射缺失时保留原始本地标识并标记 `unmapped`，不得伪造 `inter_id`、`link_id`、
  `lane_id`；后续补映射不得无审计地改写历史版本。
- PostgreSQL/TimescaleDB 是当前唯一统计与事件查询源；运行时禁止重新挂载、影子写入或
  对账旧 InfluxDB/Grafana/Telegraf 链路。
### S9 Mission 与 Pipeline 终态同步

- Mission 与 Pipeline 是两个状态机：PipelineManager 负责识别子进程 `running/stopped/error`，MissionOrchestrator 在 5 秒调度 tick 中持久化业务终态。
- 本地视频自然 EOF 必须先由三进程管道完整级联 `VideoEndBreakElement` 并以零退出码结束，随后 Mission 写 `completed/source_eof`；不得仅因时间窗口结束而伪造 EOF。
- 非零退出写 `failed/pipeline_error` 并保存脱敏错误尾部；运行窗口内找不到运行时写 `failed/pipeline_runtime_missing`。Pipeline 期望状态同步为 `stopped`，观察状态保留真实 `stopped/error`。
- 平台重启处于有效窗口时优先按持久化 Mission 恢复新 Pipeline；恢复流程不把旧进程句柄当业务真源。

### 真实事件与展示口径（2026-07-16）

- 持续拥堵只在拥堵指数连续 30 个发布样本超过 4.0 时生成事件，证据快照与触发样本同时定格。
- 完整性以 `expected_samples / actual_samples / dropped_samples / coverage_ratio / drop_reason` 表达；低覆盖数据保留事实但必须降质，不得伪装为完整时段。
- 事件中心不把告警、冲突、拥堵、质量下降和测绘成果压成同一指标；每类事件保留各自的规则、质量和证据。
- 当真实检测没有产生冲突时，轨迹研判显示 0 和真实空态，禁止为展示向正式 `road9` 注入伪冲突。

### 历史轨迹流向研判（2026-07-21）

完成轨迹首先保留 YOLO 原始 `class_id/name/model_id/class_mapping_version`，再独立形成
`motor/non_motor/unknown` 业务车型；原始类别用于模型核查和来源追溯，业务车型用于交通业务
研判，二者不得互相覆盖。

流向主键按证据强度降级：

1. 同时存在入口和出口道路：`entry:{start_road_id}|exit:{exit_road_id}`；
2. 缺少已验证车道匹配时只允许在测试质量辅助视图显示 ENU 方位候选，不产生正式统计；
3. 只有入口道路和转向：`entry:{start_road_id}|turn:{turn_behavior}`；
4. 只有转向：`turn:{turn_behavior}`；没有足够证据时进入 `unmapped`。

“流向排名”优先展示完整且可解释的流向，不简单按全表车辆数让 `unknown` 组占据榜首；同一
证据等级内再按车辆数、冲突数排序。车辆数按 lineage 去重后的 canonical 完成轨迹计数，业务车型、
YOLO、转向和质量筛选在去重后应用；速度只聚合非空有效值。冲突只在
SourceProfile、Mission、Pipeline 的可用 lineage 与 Track ID 同时匹配时归因；同一 lineage 的
重复完成记录只保留结束时间最新的一条。无法安全归因的事件只进入
`unattributed_conflicts`，不均摊到任一流向。

地图展示当前时间片与轨迹生命期相交的 GCJ-02 片段，计算仍使用对应 ENU 轨迹。时间片恰好只有一个采样点时补相邻点，
没有采样点但生命期相交时取离时间片中点最近的相邻段，以保持方向可读；缺锚点或少于两个 GCJ-02
坐标点的轨迹不画线，但仍计入总量和质量摘要。历史记录只有 YOLO ID 时，页面显示“名称未知”，
禁止加载当前模型字典进行猜填。

### GCJ-02 两阶段重建运行规则（2026-07-21）

第一阶段从 YCX 只读按需取得 Link 和 Lane 候选，按每个 SourceProfile 的正拍画面建立独立
pixel→ENU 配准；Lane 候选只有在影像残差、拓扑、方向、停止线、自交和重叠门禁全部通过后
才能进入不可变 `lane_verified` 地图。本地稳定车道键是运行时主键，YCX geomhash 仅作为可空
来源引用，不根据 Lane 数量强行绑定。

操作员在渠化车道标注工作台输入路口后，可从绑定该路口无人机、已启用且校验为 `valid` 的本地
SourceProfile 启动抽帧。五项测绘预检必须由操作员逐项确认；服务端在一个事务中创建
`source=lane_calibration` 任务、写入审计并复用 `SurveyWorker` 的原素材引用、遥测同步、质量观测和
六帧提取链路。浏览器只轮询 `queued/processing`，不得自行截图或伪造关键帧。

进入标注时只能从该路口已持久化的测绘任务选择采集批次和真实关键帧。关键帧必须同时具备已登记 SourceProfile 与 pixel→ENU 变换；创建标注任务时这两项
上下文与自然影像尺寸一起持久化，刷新页面后仍可恢复。编辑器按影像 `contain` 视口把屏幕点击
反算为自然像素坐标，黑边点击无效；车道面、边界、停止线、导流区和待转区可逐项完成、撤销或
移除。当前地图的 `geometry_enu_m` 车道面通过同一关键帧单应矩阵求逆后叠加为绿色虚线参考，
仅用于选择和拟合，不成为新的真值；操作员可点击参考车道复制为影像草稿，再拖动单个顶点或
整体平移，所有点都限制在自然影像边界内。`lane_verified` 等已发布版本必须先完整复制为新的
`draft` 才能拟合，禁止就地修改。最终几何仍只由服务端转换并执行自交、重叠和质量门禁。
关键帧任务必须把 DJI WGS-84 位置先归一化为 GCJ-02，再相对地图 `anchor_gcj02` 求位移并与
源影像 pixel→帧局部 ENU 单应矩阵相乘，形成 pixel→地图 ENU。源影像任务禁止再乘
`BEV view_transform⁻¹`；后者只属于 BEV 画布，混用会同时改变比例和中心点。

第二阶段逐源顺序执行。`RoadMapMatchingNode` 使用车辆框底边中心、车道面距离、航向、拓扑和
历史连续性给出车道候选；没有匹配的轨迹仍保留为路口事实，但不得进入正式车道级统计。每源
自然 EOF 后，以 `pipeline_id` 对账直接 Kafka 捕获数与数据库数，再创建 completed Mission 并
固化视频、遥测、模型哈希及地图/转换版本。失败只回滚该来源批次，不影响其他已验收来源。

技术演示可由用户显式指定 SourceProfile 和最小样本数；未指定时工具仍执行全目录/100 条默认
门禁。2026-07-22 的视频回归按用户要求抽查 2 条小清河北路轨迹，自动空间一致性为 100%，
GCJ-02/ENU 最大往返误差为 0.0068m。该口径不得写成 100 条人工车道准确率验收。

运行时的地图投影、车道匹配、速度、方向和完成轨迹必须共用同一个 SourceProfile verified
配准。轨迹 ENU 点按车辆底部接地点逐帧累积，速度和方向直接对带时间戳的 ENU 历史回归；禁止
用结束帧 H 统一重算历史像素，也禁止对已经是地图绝对 ENU 的速度再次扣除无人机速度。
# 路口项目与视频归属

路口渠化支持视频优先和路口优先，两条路径执行同一套悬停定位与候选匹配。路口优先并不构成跳过校验的授权：检测到其他正式路口或最近候选距离超过 80m 时必须阻止 `bind_expected_project`，由管理员转绑、建新项目或取消。多悬停段分别保存视频起止偏移；中心相距超过 250m 的片段不得合并。无有效遥测可保存为 `manual_unverified`，但发布仍需已验证 RoadContext、视觉配准、检查通过及既有几何质量门禁。

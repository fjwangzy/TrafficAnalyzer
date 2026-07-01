# BUSINESS_LOGIC.md — TrafficAnalyzer 核心业务逻辑

> 基于 commit `84c6bd6` 的真实代码分析。

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

### 5. Kafka 消息发送

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

### 9. 机非冲突未来轨迹预测

**实现文件**：`nodes/ConflictDetectionNode.py`

冲突检测默认启用，但要求存在有效单应性矩阵；无米级世界坐标时自动跳过，避免像素距离误报。节点只比较 `motor` 与 `non_motor` 轨迹，两个机动车或两个非机动车不会生成机非冲突。

冲突定义为未来轨迹碰撞预测，而不是当前距离临界值。节点使用双方当前世界坐标速度向量，在 `0-5s` 预测窗口内做两类判断：

```
motor_future(t) = motor_pos + motor_velocity * t
non_motor_future(t) = non_motor_pos + non_motor_velocity * t
d(t) = |motor_future(t) - non_motor_future(t)|
```

1. 同刻碰撞半径：双方未来位置在同一预测时刻进入 `collision_radius_m`（默认 `2.0m`）。
2. 路径交叉点：两条恒速预测轨迹在未来窗口内存在空间交点，且双方到达该交点的时间差不超过 `arrival_time_tolerance_sec`（默认 `1.0s`）。

当前距离较近但未来轨迹不会碰撞时不上报。`ttc_sec` 表示预测冲突时间；路径交叉点场景下同时输出 `motor_arrival_ttc_sec` / `non_motor_arrival_ttc_sec` 和 `arrival_time_delta_sec`。`0-3s` 预测碰撞标记为 `critical`，`3-5s` 标记为 `warning`。`motor_id` / `non_motor_id` 轨迹对同级别事件不重复上报，但允许从 `warning` 升级为 `critical` 再次上报；直到任一轨迹从 `buffer_tracks` 清理后释放状态。

## 统计数据的完整生命周期

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

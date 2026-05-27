# BUSINESS_LOGIC.md — TrafficAnalyzer 核心业务逻辑

> 基于 commit `e69acee` 的真实代码分析。

## 核心业务流程

### 1. 车辆检测

**实现文件**：`nodes/DetectionTrackingNodes.py`

**流程**：
1. 从 FrameElement 取出原始帧（BGR numpy 数组）
2. 调用 `YOLO.predict(frame, imgsz=640, conf=0.10, classes=[2,3,4,5,6,7,8,9])`
3. 提取检测框：`detected_conf`、`detected_cls`、`detected_xyxy`
4. 将检测结果转换为 ByteTracker 格式 `[x1, y1, x2, y2, conf, class_id=2]`
5. 调用 `BYTETracker.update(detections)` 进行多目标跟踪
6. 提取跟踪结果：`tracked_xyxy`、`tracked_cls`、`tracked_conf`、`id_list`

**关键细节**：
- 所有可检测类别（car, bus, truck 等）在送入 ByteTracker 时统一标记为 class_id=2（car），因为 ByteTracker 不区分类别
- 置信度阈值 0.10 较低，是为了捕获更多候选框供 ByteTracker 第二轮关联使用
- NMS IOU 阈值 0.7 较高，允许更多重叠框通过

**模型**：`weights/uav_best.pt` — 自定义无人机视角 YOLOv8 模型，检测 COCO 类别 2-9（各类交通工具，排除行人）

### 2. 多目标跟踪（ByteTrack）

**实现文件**：`byte_tracker/byte_tracker_model.py`

**算法流程**（每帧执行）：
```
输入：YOLO 检测结果 [bbox, score, class]

Step 1: 按分数分为高分组（> first_track_thresh=0.5）和低分组（> second_track_thresh=0.1）

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
  "road_5": 1.5
}
```
- `road_N` 为 `null` 当 `timestamp < buffer_analytics_sec`（缓冲区未充满时）
- `cars` 始终发送（不等待缓冲区）

**⚠️ 已知问题**：KafkaProducerNode 设置了 `frame_element.send_to_kafka = True`（第 73 行），但 FrameElement 类中没有定义这个属性。它被动态添加，不会被其他节点使用。

### 6. 可视化渲染

**实现文件**：`nodes/ShowNode.py`（280 行，最大的节点文件）

**渲染内容**：
1. 检测框或跟踪框（取决于 `show_only_yolo_detections` 配置）
2. 跟踪 ID 标签
3. 道路多边形轮廓 + 可选透明遮罩
4. 道路编号（在区域中心）
5. FPS 计数器
6. 统计面板（独立黑色窗口，拼接在主帧右侧）

**颜色逻辑**：
- 如果 `show_track_id_different_colors=True`：每个 ID 使用 `random.seed(id)` 生成固定随机颜色
- 否则：根据 `start_road` 使用预定义的道路颜色（BGR 格式）
- 如果车辆尚未分配到道路或已被清理：黑色框

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
帧 N 进入 CalcStatisticsNode
  → cars_amount = mean([15,14,16,...]) = 15
  → roads_activity = {1: 8, 2: 12, 3: 6, 4: 4, 5: 2} / 0.5min
帧 N 进入 KafkaProducerNode
  → 距离上次发送 > 1 秒 → 发送 JSON 到 statistics_1 topic
帧 N 进入 ShowNode
  → 绘制所有框 + 多边形 + 统计面板
  → frame_result 写入 FrameElement
帧 N 进入 VideoSaverNode / FlaskServerVideoNode
  → 写入文件或推流
```

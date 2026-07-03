# 检测器 FPS ~2 性能瓶颈分析报告

## 一、问题概述

当前启动脚本使用 `FRAME_STRIDE=3`（每 3 帧处理 1 帧），但实际 FPS 仍然只有 **~2**。正常预期至少应在 5-10 FPS 范围。

## 二、管道架构回顾

```
进程1: VideoReader → DetectionTrackingNodes (YOLO)
  ↓ queue_detect_out (maxsize=50, 阻塞put)
进程2: Homography → MotionComp → TrackerInfoUpdate → Speed → DirectionFlow →
       LaneDetection → LaneAnalysis → Trajectory → AutoLane → ConflictDetection →
       CalcStatistics → GeoJsonExport → KafkaProducer  (12个串行节点)
  ↓ queue_track_out (maxsize=50, 阻塞put)
进程3: ShowNode → VideoSaver / FlaskServer (MJPEG)
```

## 三、瓶颈排序（按影响程度）

### 🔴 瓶颈 #1: YOLO 推理 — 占比 ~60-70%

| 配置项 | 当前值 | 问题 |
|--------|--------|------|
| `detection_node.weight_pth` | [yolo11l-visdrone.pt](file:///d:/ai/TrafficAnalyzer/weights/yolo11l-visdrone.pt) (51MB) | **YOLO11-Large**，参数量极大 |
| `detection_node.imgsz` | **1280** | 是默认 640 的 **4倍面积** |
| `detection_node.confidence` | **0.05** | 极低，产生海量检测框进入 NMS 和 ByteTrack |

> [!IMPORTANT]
> **YOLO11-Large + imgsz=1280 在中端 GPU 上单帧推理约 300-500ms**，直接决定了 FPS 上限 ≤ 3。
> 这是绝对的性能瓶颈，即使其他所有环节都零开销，FPS 也不可能超过 3。

**代码位置**: [DetectionTrackingNodes.py:63-65](file:///d:/ai/TrafficAnalyzer/nodes/DetectionTrackingNodes.py#L63-L65)
```python
outputs = self.model.predict(frame, imgsz=self.imgsz, conf=self.conf, verbose=False,
                             iou=self.iou, classes=self.classes_to_detect,
                             device=self.device)
```

另外 L60 有一个不必要的 **4K 帧拷贝** (`frame.copy()`)，浪费 ~24MB 内存拷贝：
```python
frame = frame_element.frame.copy()  # 3840×2160×3 = ~24MB
```

---

### 🔴 瓶颈 #2: 跨进程 Queue 序列化 — 占比 ~15-25%

> [!WARNING]
> `multiprocessing.Queue` 通过 **pickle 序列化** 传输 `FrameElement` 对象。
> 每个 FrameElement 包含：
> - `frame`: 4K np.ndarray (~24MB)
> - `frame_result`: 渲染后帧 (~24MB)
> - `buffer_tracks`: 含所有 track 的 position_history / trajectory_points
> - 其他大量元数据
>
> **每帧经历 2 次 Queue 序列化/反序列化**，估计每次 50-100ms。

**代码位置**:
- [main_optimized.py:147](file:///d:/ai/TrafficAnalyzer/main_optimized.py#L147): `queue_out.put(frame_element)`（进程1→2）
- [main_optimized.py:211](file:///d:/ai/TrafficAnalyzer/main_optimized.py#L211): `queue_out.put(frame_element)`（进程2→3）

---

### 🟡 瓶颈 #3: ShowNode 渲染 — 占比 ~5-10%

[ShowNode.py](file:///d:/ai/TrafficAnalyzer/nodes/ShowNode.py) 752 行的可视化渲染节点：

- L306: `frame_result = frame_element.frame.copy()` — **又一次** 4K 帧拷贝
- L352: `cv2.resize(frame_result.copy(), ...)` — **再次** copy + 缩放
- supervision 标注器（RoundBox + Label + Trace）对 4K 帧的渲染
- 估计: **20-50ms/帧**

---

### 🟡 瓶颈 #4: 进程2 串行 12 节点 — 占比 ~5-15%

进程2 串行执行 12 个节点，累计耗时 50-100ms：

| 节点 | 估计耗时 | 备注 |
|------|----------|------|
| HomographyCalibrationNode | <1ms | 矩阵运算 |
| MotionCompensationNode | <1ms | GPS 增量 |
| TrackerInfoUpdateNode | 3-5ms | Shapely point-in-polygon（每次重建 Polygon 对象） |
| SpeedEstimationNode | 5-15ms | np.polyfit × 2 × N_tracks |
| DirectionFlowNode | 5-10ms | pixel_to_world + heading |
| LaneDetectionNode | <1ms | **默认禁用** |
| LaneAnalysisNode | 3-5ms | Shapely + 统计 |
| TrajectoryNode | <1ms | 仅处理 completed_tracks |
| AutoLaneInferenceNode | <5ms | 5秒间隔重聚类 |
| ConflictDetectionNode | **10-30ms** | O(motor × non_motor) 矩阵运算 |
| CalcStatisticsNode | <1ms | 简单统计 |
| KafkaProducerNode | 2-5ms | 异步发送（已优化） |

---

### 🟡 瓶颈 #5: VideoReader 帧解码

即使 `FRAME_STRIDE=3`，`cv2.VideoCapture.read()` 仍然 **解码每一帧**（只是跳过不 yield）。4K H.264 解码约 5-10ms/帧。

**代码位置**: [VideoReader.py:130-152](file:///d:/ai/TrafficAnalyzer/nodes/VideoReader.py#L130-L152)
```python
ret, frame = self.stream.read()  # 每帧都解码
...
if (source_frame_number - 1) % self.frame_stride != 0:
    continue  # 解码了但不处理
```

---

## 四、时间分布总结

以 4K 视频 + YOLO11-Large + imgsz=1280（中端 GPU）估算：

```
YOLO 推理:         ~400ms   ████████████████████████████████████████  (57%)
Queue 序列化 ×2:   ~150ms   ███████████████                          (21%)
ShowNode 渲染:     ~40ms    ████                                     (6%)
进程2 节点串行:    ~70ms    ███████                                  (10%)
VideoReader:       ~30ms    ███                                      (4%)
其他开销:          ~15ms    ██                                       (2%)
────────────────────────────────────────────────────────────────────
总计:              ~705ms   → ~1.4 FPS (frame_stride=1)
                   → ~2 FPS (frame_stride=3, 跳帧减少排队)
```

## 五、分层优化建议

### 🚀 速效优化（仅改配置，无需改代码，预期 5-10 FPS）

| 优化项 | 修改方式 | 预期提升 |
|--------|----------|----------|
| **使用更轻模型** | `weight_pth: weights/uav_best.pt` (40MB, 可能是 medium) | 推理时间 -40~60% |
| **降低 imgsz** | `imgsz: 640` 或 `imgsz: 960` | 推理时间 -50~75% |
| **提高 confidence** | `confidence: 0.15~0.25` | 减少 NMS + ByteTrack 负担 |
| **增大 frame_stride** | `FRAME_STRIDE=5` 或更大 | 直接按比例提升 |

> [!TIP]
> 最简单的一步：将 `imgsz` 从 1280 改为 640，**单项就能提升 3-4 倍 FPS**。
> 但代价是航拍小目标（非机动车）召回率可能下降。折中方案: `imgsz: 960`。

### ⚙️ 中期优化（需要改代码，预期额外 +30-50%）

1. **TensorRT 导出** — 将 `.pt` 模型导出为 `.engine`（TensorRT），推理提速 2-3 倍
   - 仓库已有 [YOLOv8_TensorRT_converter.ipynb](file:///d:/ai/TrafficAnalyzer/weights/YOLOv8_TensorRT_converter.ipynb)
   - `yolo export model=yolo11l-visdrone.pt format=engine imgsz=1280 half=True`

2. **消除不必要的 frame.copy()** — 3 处（节省 ~30-60ms/帧）
   - [DetectionTrackingNodes.py:60](file:///d:/ai/TrafficAnalyzer/nodes/DetectionTrackingNodes.py#L60)
   - [ShowNode.py:306](file:///d:/ai/TrafficAnalyzer/nodes/ShowNode.py#L306)
   - [ShowNode.py:352](file:///d:/ai/TrafficAnalyzer/nodes/ShowNode.py#L352)

3. **Queue 传输优化** — 用 `multiprocessing.shared_memory` 或 `mp.Array` 替代 pickle
   - 避免 4K 帧的序列化/反序列化开销
   - 或者降低传输帧分辨率（进程1传 resize 后的帧）

4. **VideoReader 真实跳帧** — 用 `stream.set(CAP_PROP_POS_FRAMES)` 跳过解码
   ```python
   # 替代当前的 read() + continue
   if self.frame_stride > 1:
       self.stream.set(cv2.CAP_PROP_POS_FRAMES, source_frame_number + self.frame_stride - 1)
   ```

### 🏗️ 长期优化（架构调整）

1. **YOLO Half-Precision (FP16)** — `model.predict(..., half=True)`
2. **进程2 进一步拆分** — 将 ConflictDetectionNode 等计算密集节点分到独立进程
3. **异步 ShowNode** — 显示进程不影响管道吞吐（当前已是独立进程，但 Queue 阻塞仍有影响）

## 六、推荐的立即行动

修改启动脚本和配置，不改代码即可验证效果：

```powershell
$env:VIDEO_SRC = "test_videos/inter_xqh/DJI_20260403142902_0001_V小清河北路与水屯路路口.mp4"
$env:TOPIC_NAME = "statistics_1"
$env:CAMERA_ID = "1"
$env:KAFKA_BOOTSTRAP = "localhost:9092"
$env:FRAME_STRIDE = "3"
python main_optimized.py `
  pipeline.send_info_kafka=True `
  telemetry.enabled=true `
  telemetry.source=srt `
  telemetry.file_path=test_videos/inter_xqh/telemetry.srt `
  detection_node.imgsz=640 `
  detection_node.confidence=0.2
```

> [!NOTE]
> 仅修改 `imgsz=640` + `confidence=0.2` 两项配置，预期 FPS 可从 ~2 提升至 **6-10**。
> 如需保留小目标召回率，可用 `imgsz=960` 作为折中。

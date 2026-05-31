# RTSP + MQTT遥测 无标注交通态势感知系统方案

> 日期：2026-05-29
> 状态：Draft
> 分支：feature/influx

## Context

当前 TrafficAnalyzer 系统仅支持 MP4/RTSP 输入，仅提供粗粒度统计（5条道路的车辆/分钟），无车速、排队长度、车头时距、车道级流量、轨迹还原和冲突检测能力。本方案在不改变核心架构的前提下，扩展出完整的交通态势感知和事件检测能力。

**"无标注"含义**：
- 不做像素级分割标注
- **不需要地面标定参考点**：利用无人机飞行遥测（高度、角度、GPS）+ 相机内参自动计算像素↔世界坐标映射
- **不需要车道多边形标注**（默认模式）：方向流量统计基于轨迹运动方向自动分类（左转/直行/右转）
- 车道多边形标注为**可选项**：仅在悬停拍摄等已标注场景下启用车道级分析
- 无需训练分割模型

**输入源**：
- **视频流**：RTSP拉流（无人机推流到RTSP服务器，系统拉流）
- **飞行遥测**：MQTT消息（独立的遥测通道，含GPS、高度、云台角度等）
- 仍兼容MP4本地文件和传统RTSP固定摄像头

---

## 架构总览

### 扩展后的数据流

```
视频源 (无人机/固定摄像头)
  │
  ├── RTSP视频流 ──────────────────────────────────┐
  │                                                 │
  └── MQTT遥测 (GPS/高度/云台角度/缩放) ──────────┐ │
                                                   │ │
  TelemetrySubscriber [新] ─────────────────────┐  │ │
                                                 │  │ │
  VideoReader (RTSP/MP4) ─────────────────────┐  │  │ │
                                               ↓  ↓  ↓ ↓
  DetectionTrackingNodes (保留YOLO原始类别)
    → HomographyCalibrationNode [新] (遥测→单应性矩阵 像素↔米)
    → TrackerInfoUpdateNode [改] (扩展TrackElement字段，发出完成轨迹)
    → SpeedEstimationNode [新] (单目车速 km/h)
    → DirectionFlowNode [新] (方向流量统计：左转/直行/右转，始终运行)
    → LaneAnalysisNode [新] (数据驱动：有标注+命中时输出车道级指标)
    → TrajectoryNode [新] (轨迹还原+转向分类)
    → ConflictDetectionNode [新] (机非冲突TTC检测)
    → CalcStatisticsNode [改] (动态道路数+车道统计聚合)
    → KafkaProducerNode [改] (扩展消息格式)
    → ShowNode [改] (车速标签+车道多边形+轨迹尾迹+冲突标记)
```

### 关键设计

**遥测↔视频帧同步**：
- `TelemetrySubscriber` 在独立线程中订阅MQTT，维护一个按时间戳排序的遥测缓冲区
- `VideoReader` 每帧产出时，从缓冲区中查找时间戳最接近的遥测记录（容忍窗口 ±50ms）
- 遥测数据注入 `FrameElement.telemetry` 字段，供下游节点使用

**两种标定模式自动切换**：
| 模式 | 触发条件 | 标定方式 |
|------|----------|----------|
| `telemetry` | 检测到MQTT遥测数据可用 | 自动：高度+云台角度+GPS+相机内参→单应性矩阵 |
| `reference_points` | 无遥测（传统固定摄像头） | 手动：配置文件中的4个像素↔世界坐标对应点 |

### 新增文件清单

| 文件 | 类型 | 用途 |
|------|------|------|
| `nodes/HomographyCalibrationNode.py` | 新 | 遥测驱动单应性矩阵计算与注入 |
| `nodes/SpeedEstimationNode.py` | 新 | 透视变换+帧间位移→车速 |
| `nodes/DirectionFlowNode.py` | 新 | 方向流量统计（左转/直行/右转，始终运行） |
| `nodes/LaneAnalysisNode.py` | 新 | 车道级流量/排队/车头时距（数据驱动：有标注+命中时输出） |
| `nodes/TrajectoryNode.py` | 新 | 轨迹构建+出口道路+转向分类 |
| `nodes/ConflictDetectionNode.py` | 新 | 机非冲突检测(TTC+距离) |
| `services/TelemetrySubscriber.py` | 新 | MQTT遥测订阅+时间戳缓冲+帧同步 |
| `utils_local/homography.py` | 新 | 单应性矩阵计算（遥测模式+标定点模式）、像素↔世界坐标变换 |
| `utils_local/lane_geometry.py` | 新 | 车道多边形操作、排队长度计算 |
| `utils_local/trajectory_classifier.py` | 新 | 转向行为分类(左转/右转/直行/掉头) |
| `configs/generate_zones.py` | 新 | 扩展版车道多边形标注工具 |

### 修改文件清单

| 文件 | 改动 |
|------|------|
| `elements/TrackElement.py` | 新增字段：速度、车道、轨迹、车辆类别、冲突状态 |
| `elements/FrameElement.py` | 新增字段：homography_matrix、direction_stats、lane_stats、lane_polygons、conflict_events、completed_tracks |
| `nodes/VideoReader.py` | 遥测帧同步接口、加载扩展JSON配置、填充lane_polygons字段 |
| `nodes/DetectionTrackingNodes.py` | 保留YOLO原始class_id(不再强制为2)、motor/non_motor分类 |
| `nodes/TrackerInfoUpdateNode.py` | 填充扩展TrackElement（含heading_angle、direction_class）、轨迹点累积、完成轨迹发射 |
| `nodes/CalcStatisticsNode.py` | 动态道路数(移除硬编码5)、聚合方向流量统计 |
| `nodes/KafkaProducerNode.py` | 扩展消息格式(方向流量、车道统计、车速、冲突、轨迹) |
| `nodes/ShowNode.py` | 渲染车速标签、方向流量统计、车道多边形（有标注时叠加）、轨迹尾迹、冲突标记 |
| `main_optimized.py` | 插入新节点到管道 |
| `configs/app_config.yaml` | 新增calibration/speed/direction_flow/lane_analysis/trajectory/conflict配置段 |
| `Dockerfile` | 添加 `paho-mqtt` 依赖 |
| `services/telegraf/telegraf.conf` | 新增measurement和字段 |
| `platform/app/kafka/consumer.py` | 处理track_complete和conflict消息类型 |
| `platform/app/services/alert_engine.py` | 新增冲突/超速告警规则 |
| `platform/app/api/v1/conflicts.py` | 新：冲突事件REST API |

---

## 模块设计

### 1. RTSP视频流 + MQTT遥测输入

**架构**：视频和遥测走两条独立通道

```
无人机 ──→ RTSP服务器 ──→ VideoReader (cv2.VideoCapture拉流)
  │
  └──→ MQTT Broker ──→ TelemetrySubscriber (paho-mqtt)
```

- **视频流**：标准RTSP拉流，沿用现有 `cv2.VideoCapture` 路径，无需额外依赖
- **遥测流**：MQTT订阅，在独立线程中接收，按时间戳与视频帧同步

#### TelemetrySubscriber 实现

```python
import paho.mqtt.client as mqtt
import threading
import time
from collections import deque

class TelemetrySubscriber:
    """MQTT遥测订阅器，维护时间戳排序的遥测缓冲区。"""

    def __init__(self, config: dict) -> None:
        self.broker = config.get("mqtt_broker", "mqtt://localhost:1883")
        self.topic = config.get("mqtt_topic", "drone/+/osd")
        self.buffer_size = config.get("buffer_size", 100)
        self._buffer: deque[dict] = deque(maxlen=self.buffer_size)
        self._lock = threading.Lock()
        self._client: mqtt.Client | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """在后台线程启动MQTT订阅。"""
        self._client = mqtt.Client()
        self._client.on_message = self._on_message
        # 解析 broker URL: mqtt://host:port
        host, port = self._parse_broker_url(self.broker)
        self._client.connect(host, port, keepalive=60)
        self._client.subscribe(self.topic)
        self._thread = threading.Thread(target=self._client.loop_forever, daemon=True)
        self._thread.start()

    def _on_message(self, client, userdata, msg) -> None:
        """接收遥测消息，解析并加入缓冲区。"""
        try:
            payload = json.loads(msg.payload.decode())
            telemetry = self._extract_telemetry(payload)
            telemetry["_received_at"] = time.time()
            with self._lock:
                self._buffer.append(telemetry)
        except (json.JSONDecodeError, KeyError):
            pass  # 丢弃格式错误的消息

    def _extract_telemetry(self, payload: dict) -> dict:
        """从DJI OSD消息中提取关键字段。"""
        osd = payload.get("99-0-0", payload)  # 兼容不同格式
        return {
            "timestamp": payload.get("timestamp", time.time()),
            "latitude": payload.get("latitude"),
            "longitude": payload.get("longitude"),
            "height": payload.get("height"),        # 海拔高度(m)
            "elevation": payload.get("elevation"),   # 地面海拔(m)
            "altitude_agl": payload.get("height", 0) - payload.get("elevation", 0),
            "attitude_head": payload.get("attitude_head", 0),   # 机头朝向(度)
            "attitude_pitch": payload.get("attitude_pitch", 0), # 机身俯仰(度)
            "gimbal_pitch": osd.get("gimbal_pitch", -90),       # 云台俯仰(度, -90=正下方)
            "gimbal_yaw": osd.get("gimbal_yaw", 0),             # 云台偏航(度)
            "gimbal_roll": osd.get("gimbal_roll", 0),
            "zoom_factor": osd.get("zoom_factor", 1.0),         # 变焦倍率
            "horizontal_speed": payload.get("horizontal_speed", 0),
            "vertical_speed": payload.get("vertical_speed", 0),
        }

    def get_nearest(self, frame_timestamp: float, tolerance_sec: float = 0.05) -> dict | None:
        """查找与视频帧时间戳最接近的遥测记录。

        Args:
            frame_timestamp: 视频帧的时间戳（秒，单调递增）
            tolerance_sec: 最大允许时间差（默认50ms）

        Returns:
            最匹配的遥测字典，或 None（若超出容忍范围）
        """
        with self._lock:
            if not self._buffer:
                return None
            # 二分查找最近时间戳
            best = None
            best_diff = float("inf")
            for entry in self._buffer:
                diff = abs(entry["timestamp"] - frame_timestamp)
                if diff < best_diff:
                    best_diff = diff
                    best = entry
            if best_diff <= tolerance_sec:
                return best
            return None

    def stop(self) -> None:
        if self._client:
            self._client.disconnect()
```

#### VideoReader 遥测注入

```python
# nodes/VideoReader.py __init__ 中添加:
self.telemetry_subscriber = None
if config.get("telemetry", {}).get("enabled", False):
    self.telemetry_subscriber = TelemetrySubscriber(config["telemetry"])
    self.telemetry_subscriber.start()

# process() 方法中，每帧产出后注入遥测:
frame_element = FrameElement(...)
if self.telemetry_subscriber:
    frame_element.telemetry = self.telemetry_subscriber.get_nearest(timestamp)
else:
    frame_element.telemetry = None
yield frame_element
```

#### MQTT遥测消息格式（DJI Cloud API OSD）

基于实际飞行日志样例（`test_videos/srt/堤口路胜利庄北路早高峰0520.txt`）：

```json
{
  "latitude": 36.67543492,
  "longitude": 116.97336790,
  "height": 172.4,           // 海拔高度(m)
  "elevation": 120,          // 地面海拔(m) → AGL = 52.4m
  "attitude_head": 168.4,    // 机头航向(度, 正北=0, 顺时针)
  "attitude_pitch": -5.1,
  "attitude_roll": 0,
  "horizontal_speed": 12.04,
  "vertical_speed": -0.1,
  "99-0-0": {                // 云台/相机OSD
    "gimbal_pitch": -90,     // -90=正下方, 0=水平
    "gimbal_yaw": 167.58,
    "gimbal_roll": 0,
    "zoom_factor": 0.5678    // 变焦倍率(影响FOV)
  }
}
```

**实际观测数据特征**：
- AGL高度极稳定（52±1m），有利于GSD精确计算
- `gimbal_pitch` 主要两个模式：-90°（正下方，47%时间）和 0°（水平，35%时间）
- `zoom_factor` 恒定 0.5678，说明未变焦
- GPS精度 RTK 级（`is_fixed: 2, quality: 5`），位置误差 < 2m

### 2. 遥测驱动单应性标定与车速估计

**核心问题**：摄像头像素坐标 → 世界坐标(米) → 速度(km/h)

**方案**：基于飞行遥测的自动单应性矩阵计算（无需地面标定参考点）

- 无人机飞行遥测提供每帧的高度（AGL）、云台角度（pitch/yaw/roll）、GPS位置、缩放因子
- 结合预配置的相机内参（焦距+传感器尺寸，一次性从无人机型号获取），自动计算单应性矩阵H
- 每帧H矩阵随遥测数据实时更新，支持无人机运动中的动态标定
- **回退方案**：若无遥测数据（传统固定摄像头），使用配置文件中的4个像素↔世界坐标参考点

#### 数学模型

**Nadir模式（gimbal_pitch ≈ -90°，正下方视角）**：

简化为2D相似变换，仅需高度和航向：

```
GSD = altitude_agl × sensor_width_mm / (focal_length_mm × image_width_px)
      [米/像素]

H = T(ground_offset) × R(heading_rad) × S(GSD)
```

其中：
- `GSD`：Ground Sample Distance，每像素对应的地面米数
- `heading_rad`：gimbal_yaw（或 attitude_head + gimbal_yaw_offset）
- `T`：平移矩阵，将图像中心映射到无人机正下方地面坐标
- `S`：缩放矩阵，像素→米

**Oblique模式（gimbal_pitch ≠ -90°，斜视视角）**：

完整透视变换：

```
R = Rz(yaw) × Ry(pitch) × Rx(roll)    # 云台旋转矩阵
K = [[f, 0, cx], [0, f, cy], [0, 0, 1]]  # 相机内参矩阵
P = K × [R | t]                          # 投影矩阵（t = 无人机位置）
H = P[:2, :]                             # 取前两行作为地面平面单应性
```

**模式自动切换阈值**：|gimbal_pitch| > 80° → nadir模式，否则 → oblique模式

#### 关键工具 `utils_local/homography.py`

```python
import numpy as np
import math

def compute_homography_from_telemetry(
    telemetry: dict,
    camera_intrinsics: dict,
    image_size: tuple[int, int]
) -> np.ndarray:
    """
    从飞行遥测自动计算单应性矩阵。

    Args:
        telemetry: 遥测字典 (altitude_agl, gimbal_pitch/yaw/roll, zoom_factor, ...)
        camera_intrinsics: 相机内参 (focal_length_mm, sensor_width_mm, sensor_height_mm)
        image_size: (width, height) 像素

    Returns:
        3×3 单应性矩阵 H（像素→地面米坐标）
    """
    img_w, img_h = image_size
    fl = camera_intrinsics["focal_length_mm"]
    sw = camera_intrinsics["sensor_width_mm"]
    sh = camera_intrinsics.get("sensor_height_mm", sw * img_h / img_w)
    zoom = telemetry.get("zoom_factor", 1.0)

    # 变焦影响等效焦距
    effective_fl = fl / zoom if zoom > 0 else fl

    agl = telemetry["altitude_agl"]  # 离地高度(米)
    g_pitch = math.radians(telemetry.get("gimbal_pitch", -90))
    g_yaw = math.radians(telemetry.get("gimbal_yaw", 0))
    g_roll = math.radians(telemetry.get("gimbal_roll", 0))

    # GSD (m/pixel) — 基于有效焦距和高度
    gsd_x = agl * sw / (effective_fl * img_w)
    gsd_y = agl * sh / (effective_fl * img_h)

    if abs(g_pitch + math.pi / 2) < math.radians(10):
        # === Nadir 模式：简化 2D 相似变换 ===
        cx, cy = img_w / 2.0, img_h / 2.0
        cos_y = math.cos(g_yaw)
        sin_y = math.sin(g_yaw)

        H = np.array([
            [gsd_x * cos_y,  -gsd_x * sin_y, 0],
            [gsd_y * sin_y,   gsd_y * cos_y,  0],
            [0,               0,               1]
        ])
        # 设置平移：图像中心 (cx,cy) 映射到世界原点 (0,0)
        offset = H @ np.array([cx, cy, 1.0])
        H[0, 2] = -offset[0] / offset[2] if offset[2] != 0 else 0
        H[1, 2] = -offset[1] / offset[2] if offset[2] != 0 else 0
    else:
        # === Oblique 模式：完整透视变换 ===
        # 相机内参矩阵
        fx = effective_fl * img_w / sw
        fy = effective_fl * img_h / sh
        K = np.array([
            [fx, 0,  img_w / 2.0],
            [0,  fy, img_h / 2.0],
            [0,  0,  1.0]
        ])
        # 旋转矩阵（云台角度）
        Rz = _rotation_z(g_yaw)
        Ry = _rotation_y(g_pitch + math.pi / 2)  # 修正：-90°为正下方
        Rx = _rotation_x(g_roll)
        R = Rz @ Ry @ Rx

        # 无人机在相机坐标系下的地面投影
        t = np.array([0, 0, agl])  # 简化：无人机正下方

        # 投影矩阵 P = K @ [R | t]
        Rt = np.hstack([R, t.reshape(3, 1)])
        P = K @ Rt

        # 单应性矩阵（取地面平面 z=0 的投影）
        H = np.array([P[0, :], P[1, :], P[2, :]])

    return H


def compute_homography_from_reference_points(
    reference_points: list[list[float]]
) -> np.ndarray:
    """
    传统方式：从像素↔世界坐标对应点计算单应性矩阵。
    用于无遥测数据的固定摄像头场景。
    """
    pts_pixel = np.array([[p[0], p[1]] for p in reference_points], dtype=np.float64)
    pts_world = np.array([[p[2], p[3]] for p in reference_points], dtype=np.float64)
    H, status = cv2.findHomography(pts_pixel, pts_world, cv2.RANSAC, 5.0)
    return H


def pixel_to_world(points_px: np.ndarray, H: np.ndarray) -> np.ndarray:
    """Transform Nx2 pixel coordinates to Nx2 world coordinates in meters."""
    ones = np.ones((points_px.shape[0], 1))
    pts_h = np.hstack([points_px, ones])
    pts_world_h = (H @ pts_h.T).T
    pts_world = pts_world_h[:, :2] / pts_world_h[:, 2:3]
    return pts_world


def pixels_per_meter_at(point_px: np.ndarray, H: np.ndarray) -> float:
    """Compute local pixel-to-meter ratio at a specific image location."""
    H_inv = np.linalg.inv(H)
    world_pt = pixel_to_world(point_px.reshape(1, 2), H)[0]
    offset_world = world_pt + np.array([1.0, 0.0])
    h1 = np.array([point_px[0], point_px[1], 1.0])
    h2 = np.array([offset_world[0], offset_world[1], 1.0])
    px1 = H_inv @ h1; px1 /= px1[2]
    px2 = H_inv @ h2; px2 /= px2[2]
    return np.linalg.norm(px2[:2] - px1[:2])


def _rotation_x(angle): return np.array([[1,0,0],[0,math.cos(angle),-math.sin(angle)],[0,math.sin(angle),math.cos(angle)]])
def _rotation_y(angle): return np.array([[math.cos(angle),0,math.sin(angle)],[0,1,0],[-math.sin(angle),0,math.cos(angle)]])
def _rotation_z(angle): return np.array([[math.cos(angle),-math.sin(angle),0],[math.sin(angle),math.cos(angle),0],[0,0,1]])
```

#### HomographyCalibrationNode 实现

```python
class HomographyCalibrationNode:
    """根据遥测数据或配置参考点，计算并注入单应性矩阵到 FrameElement。"""

    def __init__(self, config):
        cal = config.get("calibration", {})
        self.mode = cal.get("mode", "auto")  # "auto" | "telemetry" | "reference_points"
        self.camera_intrinsics = cal.get("camera_intrinsics", {})
        self.reference_points = cal.get("reference_points", [])
        self._static_H = None

        # 预计算静态H（reference_points模式）
        if self.mode == "reference_points" and len(self.reference_points) >= 4:
            self._static_H = compute_homography_from_reference_points(self.reference_points)

    def process(self, frame_element):
        if isinstance(frame_element, VideoEndBreakElement):
            return frame_element

        telemetry = getattr(frame_element, "telemetry", None)

        if self.mode == "auto":
            # 自动选择：有遥测用遥测，否则用参考点
            if telemetry and telemetry.get("altitude_agl", 0) > 0:
                frame_element.homography_matrix = compute_homography_from_telemetry(
                    telemetry, self.camera_intrinsics,
                    (frame_element.frame.shape[1], frame_element.frame.shape[0])
                )
                frame_element.calibration_mode = "telemetry"
            else:
                frame_element.homography_matrix = self._static_H
                frame_element.calibration_mode = "reference_points" if self._static_H is not None else None

        elif self.mode == "telemetry":
            if telemetry and telemetry.get("altitude_agl", 0) > 0:
                frame_element.homography_matrix = compute_homography_from_telemetry(
                    telemetry, self.camera_intrinsics,
                    (frame_element.frame.shape[1], frame_element.frame.shape[0])
                )
                frame_element.calibration_mode = "telemetry"

        elif self.mode == "reference_points":
            frame_element.homography_matrix = self._static_H
            frame_element.calibration_mode = "reference_points"

        return frame_element
```

#### SpeedEstimationNode 实现

```python
class SpeedEstimationNode:
    def __init__(self, config):
        self.enabled = config.get("speed_estimation", {}).get("enabled", True)
        self.history_frames = config.get("speed_estimation", {}).get("history_frames", 15)
        self.smoothing_window = config.get("speed_estimation", {}).get("smoothing_window", 5)
        self.min_displacement_px = config.get("speed_estimation", {}).get("min_displacement_px", 2.0)

    def process(self, frame_element):
        H = frame_element.homography_matrix
        for i, track_id in enumerate(frame_element.id_list):
            track = frame_element.buffer_tracks.get(track_id)
            if not track:
                continue
            bbox = frame_element.tracked_xyxy[i]
            cx = (bbox[0] + bbox[2]) / 2.0
            cy = (bbox[1] + bbox[3]) / 2.0
            ts = frame_element.timestamp

            track.position_history.append((cx, cy, ts))
            if len(track.position_history) > self.history_frames:
                track.position_history.pop(0)
            if len(track.position_history) < 3:
                continue

            p_old = track.position_history[0]
            p_new = track.position_history[-1]
            dt = p_new[2] - p_old[2]
            if dt < 0.05:
                continue

            if H is not None:
                pts_px = np.array([[p_old[0], p_old[1]], [p_new[0], p_new[1]]])
                pts_world = pixel_to_world(pts_px, H)
                dist_m = np.linalg.norm(pts_world[1] - pts_world[0])
                track.speed_kmh = (dist_m / dt) * 3.6
            else:
                dist_px = np.sqrt((p_new[0]-p_old[0])**2 + (p_new[1]-p_old[1])**2)
                track.speed_kmh = 0.0 if dist_px < self.min_displacement_px else (dist_px/dt)*3.6

            # EMA smoothing
            alpha = 2.0 / (self.smoothing_window + 1)
            track.avg_speed_kmh = alpha * track.speed_kmh + (1-alpha) * track.avg_speed_kmh
            track.max_speed_kmh = max(track.max_speed_kmh, track.speed_kmh)
        return frame_element
```

### 3. 方向流量统计 + 车道级增强

**问题**：原方案的车道级分析需要人工标注车道多边形和停车线，在无人机巡飞场景下不现实。

**方案**：**方向流量始终运行**（零标注），当配置中存在车道多边形数据且车辆点位命中时，**自动叠加输出车道级指标**。

#### 数据驱动逻辑

```
每帧处理流程：

1. DirectionFlowNode 始终执行 → 输出 direction_flow（方向流量统计）

2. LaneAnalysisNode 检查：
   ├── lane_polygons 为空？ → 跳过（无车道标注数据）
   └── lane_polygons 非空？ → 遍历车辆 bbox 中心点
       ├── 命中车道多边形？ → 记录 current_lane，输出 lane_stats
       └── 未命中任何车道？ → 仅保留 direction_flow 输出
```

**核心规则**：不靠配置开关，靠数据驱动——有车道标注且点位命中 → 输出车道级指标，否则仅输出方向流量。

| 场景 | lane_polygons | 命中 | direction_flow | lane_stats |
|------|---------------|------|----------------|------------|
| 无人机巡飞（无标注） | 空 | — | ✅ | ❌ |
| 悬停拍摄（有标注，部分命中） | 非空 | 部分 | ✅ | ✅（仅命中的车道） |
| 固定摄像头（有标注，全部命中） | 非空 | 全部 | ✅ | ✅（全部车道） |

#### 3A. DirectionFlowNode（方向流量，始终运行）

**核心思路**：不依赖空间标注，通过车辆轨迹的运动方向变化自动分类为左转/直行/右转。

**方向分类算法**：

```python
def classify_direction(entry_heading: float, exit_heading: float,
                        thresholds: dict | None = None) -> str:
    """
    根据入口方向和出口方向的夹角分类行驶方向。

    Args:
        entry_heading: 轨迹前N帧的运动方向角度（度，atan2）
        exit_heading:  轨迹后N帧的运动方向角度（度，atan2）
        thresholds:    角度阈值配置

    Returns:
        "straight" | "left_turn" | "right_turn" | "u_turn" | "unknown"
    """
    if thresholds is None:
        thresholds = {"straight": 25, "turn": 120}

    # 计算方向变化角度（-180° ~ 180°）
    delta = exit_heading - entry_heading
    delta = ((delta + 180) % 360) - 180  # 归一化

    abs_delta = abs(delta)
    if abs_delta <= thresholds["straight"]:
        return "straight"
    elif abs_delta >= thresholds["turn"]:
        return "u_turn"
    elif delta > 0:
        return "left_turn"
    else:
        return "right_turn"
```

**heading计算**：基于 `position_history` 中最近N帧的位移向量

```python
def compute_heading(position_history: list[tuple], n_frames: int = 5) -> float | None:
    """从轨迹点序列计算运动方向角度（度）。"""
    if len(position_history) < n_frames:
        return None
    # 取首尾点计算位移向量
    x0, y0 = position_history[0][0], position_history[0][1]
    x1, y1 = position_history[-1][0], position_history[-1][1]
    dx, dy = x1 - x0, y1 - y0
    if dx == 0 and dy == 0:
        return None  # 静止车辆
    return math.degrees(math.atan2(dy, dx))
```

**DirectionFlowNode 实现**：

```python
class DirectionFlowNode:
    """方向流量统计节点：左转/直行/右转，无需车道多边形标注。"""

    def __init__(self, config: dict) -> None:
        cfg = config.get("direction_flow", config.get("lane_analysis", {}))
        self.enabled = cfg.get("enabled", True)
        self.min_track_duration_sec = cfg.get("min_track_duration_sec", 2.0)
        self.min_position_points = cfg.get("min_position_points", 8)
        self.heading_window = cfg.get("heading_window", 5)  # 用于heading计算的帧数
        self.queue_speed_threshold_kmh = cfg.get("queue_speed_threshold_kmh", 5.0)
        self.turn_thresholds = cfg.get("turn_thresholds", {
            "straight": 25,
            "turn": 120,
        })
        # 方向级车头时距跟踪
        self._last_passage_time: dict[str, float] = {}  # direction → last passage timestamp
        self._headway_accumulator: dict[str, list[float]] = {
            "straight": [], "left_turn": [], "right_turn": []
        }
        self._headway_window_sec = 300  # 5分钟滑动窗口

    def process(self, frame_element: FrameElement) -> FrameElement:
        if isinstance(frame_element, VideoEndBreakElement):
            return frame_element

        if not self.enabled:
            return frame_element

        buffer_tracks = frame_element.buffer_tracks

        # 1. 对每条活跃轨迹计算当前方向（用于实时计数）
        direction_counts = {"straight": 0, "left_turn": 0, "right_turn": 0, "u_turn": 0, "unknown": 0}
        direction_speeds: dict[str, list[float]] = {d: [] for d in direction_counts}
        queue_count = 0

        for track_id, track in buffer_tracks.items():
            # 排队检测：速度 < 阈值
            if track.speed_kmh < self.queue_speed_threshold_kmh and track.speed_kmh >= 0:
                queue_count += 1
                continue

            # 方向分类：需要足够的轨迹点
            if len(track.position_history) < self.min_position_points:
                direction_counts["unknown"] += 1
                continue

            # 计算入口方向（轨迹前半段）和出口方向（轨迹后半段）
            mid = len(track.position_history) // 2
            entry_heading = compute_heading(track.position_history[:mid+1], self.heading_window)
            exit_heading = compute_heading(track.position_history[mid:], self.heading_window)

            if entry_heading is None or exit_heading is None:
                direction_counts["unknown"] += 1
                continue

            direction = classify_direction(entry_heading, exit_heading, self.turn_thresholds)
            direction_counts[direction] += 1
            direction_speeds[direction].append(track.speed_kmh)

        # 2. 计算方向级车头时距（同方向连续车辆的时间差）
        # 使用完成轨迹的方向分类结果更新车头时距
        for ct in (frame_element.completed_tracks or []):
            direction = ct.get("turn_behavior", "unknown")
            if direction in self._last_passage_time:
                headway = ct["timestamp_last"] - self._last_passage_time[direction]
                if 0 < headway < 60:  # 合理的车头时距范围
                    self._headway_accumulator[direction].append(headway)
            self._last_passage_time[direction] = ct["timestamp_last"]

        # 清理超出窗口的旧数据
        cutoff = frame_element.timestamp - self._headway_window_sec
        for d in self._headway_accumulator:
            self._headway_accumulator[d] = [
                h for h in self._headway_accumulator[d][-100:]
            ]

        # 3. 汇总输出
        direction_stats = {}
        for d in ["straight", "left_turn", "right_turn", "u_turn"]:
            speeds = direction_speeds[d]
            headways = self._headway_accumulator.get(d, [])
            direction_stats[d] = {
                "count": direction_counts[d],
                "avg_speed_kmh": round(sum(speeds) / len(speeds), 1) if speeds else 0,
                "avg_headway_sec": round(sum(headways) / len(headways), 2) if headways else None,
                "min_headway_sec": round(min(headways), 2) if headways else None,
            }
        direction_stats["unknown"] = {"count": direction_counts["unknown"]}

        frame_element.direction_stats = direction_stats
        frame_element.queue_count = queue_count
        return frame_element
```

**方向流量指标汇总**：

| 指标 | 说明 | 精度 |
|------|------|------|
| `direction_flow` | 各方向当前活跃车辆数 {straight, left_turn, right_turn, u_turn} | 高（轨迹>2秒即可分类） |
| `queue_count` | 排队车辆数（速度<5km/h） | 高 |
| `avg_speed_by_direction` | 各方向平均车速(km/h) | 高 |
| `headway_sec` | 各方向平均车头时距(秒) | 中（基于完成轨迹，有延迟） |
| `min_headway_sec` | 各方向最小车头时距(秒) | 中 |

**限制**：
- 方向分类需要轨迹存活 ≥ 2秒（约6帧@30fps），短轨迹归入"unknown"
- 车头时距基于完成轨迹的时间差，比停车线法有约2-3秒延迟
- 不区分具体车道（如"入口1左转"和"入口2左转"合并为"left_turn"）

#### 3B. LaneAnalysisNode（车道级增强，数据驱动）

**启用条件**：运行时自动判断——配置中存在车道多边形数据（`lane_polygons` 非空）且车辆 bbox 中心点命中车道多边形 → 输出车道级指标。无标注数据时自动跳过。

**车道定义**：扩展JSON配置，每条入口道路细分为1-3个车道多边形

```json
{
  "roads": {"1": {"polygon": [...], "type": "entry"}, ...},
  "lanes": {
    "L1_1": {"polygon": [...], "road_id": 1, "lane_index": 0, "direction": "entry"},
    "L1_2": {"polygon": [...], "road_id": 1, "lane_index": 1, "direction": "entry"}
  },
  "calibration": {
    "stop_lines": {"L1": [[x1,y1],[x2,y2]]},
    "reference_points": []
  }
}
```

**向后兼容**：若JSON仅含扁平道路多边形格式，所有条目视为道路，无子车道

#### `LaneAnalysisNode` 算法

1. **车道分配**：每辆车的bbox中心点与车道多边形做point-in-polygon测试(shapely)
2. **车道级流量**：统计每个车道多边形内的车辆数
3. **排队长度**：
   - 识别速度 < 5km/h 的车辆为排队车辆
   - 若有停车线配置：排队车辆到停车线的最大距离（世界坐标）
   - 若无停车线：排队车辆间最大距离
   - 间隙分段：相邻排队车辆间距 > 8m 视为不同队列
4. **车头时距**：
   - 方法A（默认）：同车道内连续车辆的`timestamp_init_road`差值
   - 方法B（更精确）：车辆穿越停车线的精确时刻差（需停车线配置）

**LaneAnalysisNode 实现**（数据驱动）：

```python
class LaneAnalysisNode:
    """车道级分析节点：数据驱动，有标注且点位命中时输出车道级指标。"""

    def __init__(self, config: dict) -> None:
        cfg = config.get("lane_analysis", {})
        self.queue_speed_threshold_kmh = cfg.get("queue_speed_threshold_kmh", 5.0)
        self.queue_gap_threshold_m = cfg.get("queue_gap_threshold_m", 8.0)
        self._lane_polygons: dict | None = None  # 延迟加载

    def _load_lane_polygons(self, frame_element: FrameElement) -> dict:
        """从配置或roads_info中提取车道多边形。空则返回空dict。"""
        if self._lane_polygons is not None:
            return self._lane_polygons
        lanes = getattr(frame_element, "lane_polygons", None)
        self._lane_polygons = lanes if lanes else {}
        return self._lane_polygons

    def process(self, frame_element: FrameElement) -> FrameElement:
        if isinstance(frame_element, VideoEndBreakElement):
            return frame_element

        lane_polygons = self._load_lane_polygons(frame_element)
        if not lane_polygons:
            # 无车道标注数据 → 跳过，DirectionFlowNode已处理方向流量
            return frame_element

        H = frame_element.homography_matrix
        lane_stats = {}

        for lane_id, poly in lane_polygons.items():
            # 统计命中该车道的车辆
            vehicles_in_lane = []
            for i, track_id in enumerate(frame_element.id_list):
                bbox = frame_element.tracked_xyxy[i]
                lane_hit = assign_vehicle_to_lane(bbox, {lane_id: poly})
                if lane_hit == lane_id:
                    track = frame_element.buffer_tracks.get(track_id)
                    cx = (bbox[0] + bbox[2]) / 2
                    cy = (bbox[1] + bbox[3]) / 2
                    vehicles_in_lane.append({
                        "track_id": track_id,
                        "bbox_center_px": (cx, cy),
                        "speed_kmh": track.avg_speed_kmh if track else 0,
                    })

            if not vehicles_in_lane:
                continue  # 该车道无车辆命中，不输出

            # 车道级流量
            count = len(vehicles_in_lane)
            avg_speed = sum(v["speed_kmh"] for v in vehicles_in_lane) / count

            # 排队检测：速度 < 阈值
            stopped = [v for v in vehicles_in_lane if v["speed_kmh"] < self.queue_speed_threshold_kmh]
            queue_length_m = 0.0
            if stopped and H is not None:
                queue_length_m = _compute_queue_extent(stopped, H)

            lane_stats[lane_id] = {
                "count": count,
                "avg_speed_kmh": round(avg_speed, 1),
                "queue_length_m": round(queue_length_m, 1),
                "stopped_count": len(stopped),
            }

        frame_element.lane_stats = lane_stats if lane_stats else None
        return frame_element
```

#### 排队长度计算 `utils_local/lane_geometry.py`

```python
def assign_vehicle_to_lane(bbox_xyxy, lane_polygons):
    cx = (bbox_xyxy[0] + bbox_xyxy[2]) / 2
    cy = (bbox_xyxy[1] + bbox_xyxy[3]) / 2
    pt = Point(cx, cy)
    for lane_id, poly in lane_polygons.items():
        if poly.contains(pt):
            return lane_id
    return None

def compute_queue_extent(stopped_vehicles, stop_line, H):
    """Distance from stop line to furthest stopped vehicle (meters)."""
    if not stopped_vehicles:
        return 0.0
    max_dist = 0.0
    for v in stopped_vehicles:
        cx, cy = v["bbox_center_px"]
        if H is not None:
            world_pt = pixel_to_world(np.array([[cx, cy]]), H)[0]
            sl_pts = np.array(stop_line.coords)
            sl_world = pixel_to_world(sl_pts, H)
            sl_world_line = LineString(sl_world)
            dist_m = sl_world_line.distance(Point(world_pt[0], world_pt[1]))
            max_dist = max(max_dist, dist_m)
        else:
            dist_px = stop_line.distance(Point(cx, cy))
            max_dist = max(max_dist, dist_px)
    return max_dist

def segment_queues_by_gap(queued_vehicles_world, gap_threshold_m=8.0):
    """Segment queued vehicles into distinct queues based on gap."""
    if not queued_vehicles_world:
        return []
    sorted_v = sorted(queued_vehicles_world, key=lambda v: v["dist_to_stopline"])
    queues = [[sorted_v[0]]]
    for i in range(1, len(sorted_v)):
        gap = sorted_v[i]["dist_to_stopline"] - sorted_v[i-1]["dist_to_stopline"]
        if gap > gap_threshold_m:
            queues.append([])
        queues[-1].append(sorted_v[i])
    return queues
```

#### 两种模式与模块4（轨迹还原）的关系

| | 模块3A: DirectionFlowNode | 模块3B: LaneAnalysisNode | 模块4: TrajectoryNode |
|---|---|---|---|
| 目的 | 实时方向流量统计 | 实时车道级统计（数据驱动） | 完整轨迹记录+可视化 |
| 时机 | 每帧（始终运行） | 每帧（有标注+命中时输出） | 轨迹完成时（事后记录） |
| 方向分类 | 简化3类（左转/直行/右转） | 不适用 | 精确4类（含掉头）+角度值 |
| 标注需求 | 无 | 车道多边形（可选，有则用） | 无 |
| 输出条件 | 始终输出 | 仅当点位命中车道时输出 | 始终输出（轨迹完成时） |
| 输出 | Kafka统计消息 | Kafka统计消息（叠加） | 平台存储+WebSocket推送 |

方向分类逻辑共享 `utils_local/trajectory_classifier.py`，模块3A调用简化版，模块4调用完整版。

### 4. 车辆轨迹还原

**轨迹构建**：
- `TrackerInfoUpdateNode` 每帧将bbox中心追加到 `track.trajectory_points`
- 出口道路检测：车辆从一个道路多边形移动到另一个，或离开所有多边形时记录 `exit_road`

#### 转向分类 `utils_local/trajectory_classifier.py`

```python
def classify_turning_movement(trajectory_points, entry_road_center, exit_road_center,
                               roundabout_center=None, thresholds=None):
    """
    Classify turning movement based on entry→exit geometry.
    Returns: "left_turn" | "right_turn" | "straight" | "u_turn"
    """
    if not trajectory_points or len(trajectory_points) < 5:
        return "unknown"
    p_entry = np.array(trajectory_points[0])
    p_exit = np.array(trajectory_points[-1])
    center = np.array(roundabout_center) if roundabout_center else np.mean(np.array(trajectory_points), axis=0)

    v_entry = p_entry - center
    v_exit = p_exit - center
    dot = np.dot(v_entry, v_exit)
    cross = np.cross(v_entry, v_exit)
    angle_deg = math.degrees(math.atan2(cross, dot))
    abs_angle = abs(angle_deg)

    if abs_angle <= thresholds.get("straight", 30):
        return "straight"
    elif abs_angle >= thresholds.get("u_turn", [150, 180])[0]:
        return "u_turn"
    elif angle_deg > 0:
        return "left_turn"
    else:
        return "right_turn"
```

#### 完成轨迹发射

`TrackerInfoUpdateNode` 修剪旧轨迹时发射完整数据：

```python
for key in keys_to_remove:
    track = self.buffer_tracks[key]
    duration = track.timestamp_last - track.timestamp_first
    if duration >= self.min_track_duration and len(track.trajectory_points) > 5:
        track.turn_behavior = classify_turning_movement(
            track.trajectory_points, None, None, thresholds=self.turn_thresholds
        )
        completed_track_data = {
            "track_id": track.id,
            "start_road": track.start_road,
            "exit_road": track.exit_road,
            "turn_behavior": track.turn_behavior,
            "vehicle_class": track.vehicle_class,
            "duration_sec": round(duration, 2),
            "avg_speed_kmh": round(track.avg_speed_kmh, 1),
            "max_speed_kmh": round(track.max_speed_kmh, 1),
            "trajectory_px": track.trajectory_points,
            "timestamp_first": track.timestamp_first,
            "timestamp_last": track.timestamp_last,
        }
        frame_element.completed_tracks.append(completed_track_data)
    self.buffer_tracks.pop(key)
```

**存储**：发布到独立Kafka topic `track_complete_{n}`，平台消费者写入InfluxDB `track_events` measurement

### 5. 机非冲突检测

**车辆分类**：
- `DetectionTrackingNodes` 保留YOLO原始class_id（不再强制为2）
- motor类：`{2(car), 5(bus), 7(truck), 8}`
- non_motor类：`{0(person), 1(bicycle)}`
- 需确认uav_best.pt模型是否包含这些类别，若否则需微调

#### 冲突检测算法 `ConflictDetectionNode`

```python
class ConflictDetectionNode:
    def __init__(self, config):
        cfg = config.get("conflict_detection", {})
        self.enabled = cfg.get("enabled", True)
        self.proximity_threshold_m = cfg.get("proximity_threshold_m", 3.0)
        self.ttc_threshold_sec = cfg.get("ttc_threshold_sec", 2.0)
        self.severity_levels = cfg.get("severity_levels", {
            "critical": {"ttc": 1.0, "distance_m": 1.5},
            "warning": {"ttc": 2.0, "distance_m": 3.0},
            "info": {"ttc": 3.0, "distance_m": 5.0},
        })
        self._pair_cooldown = {}  # (min_id, max_id) → timestamp
        self.cooldown_sec = 5.0

    def process(self, frame_element):
        H = frame_element.homography_matrix
        if H is None:  # 无标定时跳过（避免误报）
            frame_element.conflict_events = []
            return frame_element

        motor_tracks, non_motor_tracks = [], []
        for i, track_id in enumerate(frame_element.id_list):
            track = frame_element.buffer_tracks.get(track_id)
            if not track:
                continue
            bbox = frame_element.tracked_xyxy[i]
            cx = (bbox[0]+bbox[2])/2.0
            cy = (bbox[1]+bbox[3])/2.0
            entry = {"track_id": track_id, "center_px": (cx,cy),
                     "speed_kmh": track.avg_speed_kmh, "vehicle_class": track.vehicle_class}
            if track.vehicle_class == "motor":
                motor_tracks.append(entry)
            elif track.vehicle_class == "non_motor":
                non_motor_tracks.append(entry)

        conflict_events = []
        for motor in motor_tracks:
            for non_motor in non_motor_tracks:
                pair_key = (min(motor["track_id"], non_motor["track_id"]),
                           max(motor["track_id"], non_motor["track_id"]))
                if pair_key in self._pair_cooldown:
                    if frame_element.timestamp - self._pair_cooldown[pair_key] < self.cooldown_sec:
                        continue

                pts = pixel_to_world(np.array([motor["center_px"], non_motor["center_px"]]), H)
                dist_m = np.linalg.norm(pts[0] - pts[1])
                if dist_m > self.proximity_threshold_m:
                    continue

                speed_ms = motor["speed_kmh"] / 3.6
                ttc = dist_m / speed_ms if speed_ms > 0.5 else None

                severity = self._classify_severity(dist_m, ttc)
                if severity:
                    conflict_events.append({
                        "motor_id": motor["track_id"], "non_motor_id": non_motor["track_id"],
                        "distance_m": round(dist_m, 2), "ttc_sec": round(ttc, 2) if ttc else None,
                        "severity": severity, "motor_speed_kmh": motor["speed_kmh"],
                    })
                    self._pair_cooldown[pair_key] = frame_element.timestamp

        frame_element.conflict_events = conflict_events
        return frame_element
```

**严重度分级**：

| 级别 | TTC阈值 | 距离阈值 | 告警等级 |
|------|---------|----------|----------|
| critical | < 1.0s | < 1.5m | P1 |
| warning | < 2.0s | < 3.0m | P2 |
| info | < 3.0s | < 5.0m | P3 |

**限制**：需要单应性标定才能准确计算米级距离。无标定时跳过冲突检测（避免误报）

---

## 数据Schema变更

### TrackElement 新增字段

```python
class TrackElement:
    # ── 现有字段（保持不变）──
    id: int
    timestamp_first: float
    timestamp_last: float
    start_road: int | None
    timestamp_init_road: float

    # ── 新增：速度 ──
    position_history: list[tuple[float,float,float]]  # [(cx,cy,timestamp)] 最近15帧
    speed_kmh: float = 0.0
    avg_speed_kmh: float = 0.0
    max_speed_kmh: float = 0.0

    # ── 新增：车道（可选，仅lane模式使用）──
    current_lane: str | None = None
    lane_history: list[tuple[str, float]] = []

    # ── 新增：方向 ──
    heading_angle: float | None = None  # 当前运动方向角度（度）
    direction_class: str | None = None  # "straight"|"left_turn"|"right_turn"|"u_turn"

    # ── 新增：轨迹 ──
    exit_road: int | None = None
    turn_behavior: str | None = None  # "left_turn"|"right_turn"|"straight"|"u_turn"
    trajectory_points: list[tuple[float,float]] = []

    # ── 新增：分类 ──
    vehicle_class: str = "unknown"  # "motor"|"non_motor"
    yolo_class_id: int | None = None

    # ── 新增：冲突 ──
    in_conflict: bool = False
    conflict_events: list[dict] = []
```

### FrameElement 新增字段

```python
class FrameElement:
    # ── 新增 ──
    telemetry: dict | None = None          # MQTT遥测数据（与帧同步后的）
    calibration_mode: str | None = None    # "telemetry" | "reference_points" | None
    homography_matrix: np.ndarray | None = None
    analysis_mode: str = "direction"       # 保留字段但值由数据决定：lane_polygons非空且有命中时为"lane"，否则为"direction"
    direction_stats: dict | None = None    # 方向流量统计（DirectionFlowNode始终输出）
    lane_stats: dict | None = None         # 车道级统计（LaneAnalysisNode，仅点位命中车道时输出）
    lane_polygons: dict | None = None      # 车道多边形数据（VideoReader加载，空则LaneAnalysisNode跳过）
    queue_count: int = 0                   # 当前排队车辆数
    headway_stats: dict | None = None
    conflict_events: list[dict] | None = None
    completed_tracks: list[dict] | None = None
    traffic_situation: dict | None = None
```

### Kafka消息扩展

**统计消息 `statistics_{n}`（向后兼容扩展）**：

direction_flow 始终输出，lane_stats 仅在有标注且点位命中时输出：

```json
{
  "camera_id": "id_1",
  "cars": 12,
  "road_1": 4.2, "road_2": 3.8, "road_3": null, "road_4": 2.1, "road_5": 1.5,
  "msg_type": "stats",
  "intersection_id": "INT_camera_1",
  "direction_flow": {
    "straight": {"count": 5, "avg_speed_kmh": 28.3, "avg_headway_sec": 2.1, "min_headway_sec": 1.0},
    "left_turn": {"count": 3, "avg_speed_kmh": 22.1, "avg_headway_sec": 3.5, "min_headway_sec": 1.8},
    "right_turn": {"count": 2, "avg_speed_kmh": 18.7, "avg_headway_sec": 4.2, "min_headway_sec": 2.5},
    "u_turn": {"count": 0, "avg_speed_kmh": 0, "avg_headway_sec": null, "min_headway_sec": null},
    "unknown": {"count": 2}
  },
  "queue_count": 3,
  "lane_stats": {
    "L1_1": {"count": 3, "avg_speed_kmh": 25.4, "queue_length_m": 12.3, "stopped_count": 1},
    "L1_2": {"count": 2, "avg_speed_kmh": 30.1, "queue_length_m": 0.0, "stopped_count": 0}
  },
  "avg_speed_kmh": 28.5,
  "congestion_index": 1.8,
  "conflict_count": 0,
  "conflicts": []
}
```

**无车道标注时**（无人机巡飞）：`lane_stats` 为 `null`，其余字段不变。
```

**完成轨迹消息 `track_complete_{n}`（新topic）**：
```json
{
  "msg_type": "track_complete",
  "intersection_id": "INT_camera_1",
  "track_id": 142,
  "start_road": 1,
  "exit_road": 3,
  "turn_behavior": "left_turn",
  "vehicle_class": "motor",
  "duration_sec": 8.4,
  "avg_speed_kmh": 22.3,
  "max_speed_kmh": 35.1,
  "trajectory_px": [[100,200], [105,210], ...]
}
```

**冲突事件消息 `conflicts_{n}`（新topic）**：
```json
{
  "msg_type": "conflict",
  "intersection_id": "INT_camera_1",
  "motor_id": 142,
  "non_motor_id": 156,
  "distance_m": 2.3,
  "ttc_sec": 1.5,
  "severity": "warning",
  "motor_speed_kmh": 25.0
}
```

### InfluxDB新measurements

| Measurement | Tags | Fields | 写入方 |
|-------------|------|--------|--------|
| `camera_{N}` (扩展) | host | +avg_speed_kmh, +congestion_index, +conflict_count, +queue_count, +dir_straight_count, +dir_left_count, +dir_right_count, +dir_straight_speed, +dir_left_speed, +dir_right_speed, +lane_stats_* (有标注时) | Telegraf |
| `track_events` (新) | intersection_id, turn_behavior, vehicle_class | track_id, start_road, exit_road, duration_sec, avg_speed_kmh, trajectory_px | Platform消费者 |
| `conflict_events` (新) | intersection_id, severity | motor_id, non_motor_id, distance_m, ttc_sec, motor_speed_kmh | Platform消费者 |

---

## 平台侧变更

### Kafka消费者 (`platform/app/kafka/consumer.py`)
- 订阅模式扩展为 `(statistics|track_complete|conflicts)_.*`
- 新增 `_handle_conflict()` 和 `_handle_track_complete()` 处理器
- 冲突事件广播到 `conflicts:{id}` WebSocket通道
- 完成轨迹写入InfluxDB `track_events`

### 告警引擎 (`platform/app/services/alert_engine.py`)
新增告警类型：

| 告警类型 | 严重级别 | 触发条件 | 状态 |
|----------|----------|----------|------|
| `queue_overflow` | P2 | queue_length_m > threshold | 已有 |
| `congestion` | P2 | congestion_index > threshold | 已有 |
| `calibration_drift` | P3 | lane_match_rate < threshold | 已有 |
| `motor_non_motor_conflict` | P1/P2/P3 | proximity + TTC | 新增 |
| `high_avg_speed` | P3 | avg_speed > 60km/h | 新增 |
| `multiple_conflicts` | P2 | conflict_count > 3 | 新增 |
| `speeding` | P2 | 单车速度 > 阈值 | 新增 |

### 新API端点
- `GET /api/v1/conflicts/{intersection_id}` — 冲突事件列表
- `GET /api/v1/conflicts/{intersection_id}/summary` — 冲突统计摘要

### 新WebSocket通道
- `conflicts:{id}` — 实时冲突事件
- `trajectories:{id}` — 完成轨迹

---

## 配置新增 (`configs/app_config.yaml`)

```yaml
calibration:
  mode: "auto"             # "auto" | "telemetry" | "reference_points"
  # 相机内参（一次性配置，从无人机型号获取）
  camera_intrinsics:
    focal_length_mm: 4.5      # 镜头焦距(mm)
    sensor_width_mm: 6.4      # 传感器宽度(mm)，1/2"传感器
    sensor_height_mm: 3.6     # 传感器高度(mm)
  # 回退：固定摄像头无遥测时使用传统标定点
  reference_points: []    # [[px, py, world_x_m, world_y_m], ...]

telemetry:
  enabled: true
  mqtt_broker: "mqtt://mqtt:1883"
  mqtt_topic: "drone/+/osd"
  buffer_size: 100           # 遥测缓冲区大小（条）
  sync_tolerance_sec: 0.05   # 帧↔遥测时间戳同步容忍窗口(秒)

speed_estimation:
  enabled: true
  history_frames: 15      # 速度计算所基于的历史帧数
  smoothing_window: 5      # EMA平滑窗口
  min_displacement_px: 2.0 # 最小位移阈值(像素)

direction_flow:
  enabled: true
  min_track_duration_sec: 2.0    # 轨迹最短存活时间（方向分类需要足够长的轨迹）
  min_position_points: 8         # 轨迹最少位置点
  heading_window: 5              # 计算heading的帧窗口
  queue_speed_threshold_kmh: 5.0 # 低于此速度视为排队
  turn_thresholds:
    straight: 25                 # |delta| ≤ 25° → 直行
    turn: 120                    # |delta| ≥ 120° → 掉头

lane_analysis:
  # 无开关：有车道多边形标注数据且点位命中时自动输出车道级指标
  queue_speed_threshold_kmh: 5.0 # 低于此速度视为排队
  queue_gap_threshold_m: 8.0     # 队列间隙阈值(米)

trajectory:
  enabled: true
  min_track_duration_sec: 2.0     # 轨迹最短存活时间
  turn_angle_thresholds:
    straight: 30
    left_turn: [30, 150]
    right_turn: [-150, -30]
    u_turn: [150, 180]

conflict_detection:
  enabled: true
  proximity_threshold_m: 3.0
  ttc_threshold_sec: 2.0
  severity_levels:
    critical: {ttc: 1.0, distance_m: 1.5}
    warning: {ttc: 2.0, distance_m: 3.0}
    info: {ttc: 3.0, distance_m: 5.0}
```

---

## 扩展道路/车道JSON格式

现有格式（`configs/entry_exit_lanes.json`）：
```json
{"1": [x1,y1,x2,y2,x3,y3,x4,y4], ...}
```

新格式（`configs/inter1_zones.json`）：
```json
{
  "roads": {
    "1": {"polygon": [x1,y1,...], "type": "entry"},
    "2": {"polygon": [x1,y1,...], "type": "entry"},
    "3": {"polygon": [x1,y1,...], "type": "exit"}
  },
  "lanes": {
    "L1_1": {"polygon": [x1,y1,...], "road_id": 1, "lane_index": 0, "direction": "entry"},
    "L1_2": {"polygon": [x1,y1,...], "road_id": 1, "lane_index": 1, "direction": "entry"}
  },
  "calibration": {
    "stop_lines": {
      "L1": [[x1,y1],[x2,y2]],
      "L2": [[x1,y1],[x2,y2]]
    },
    "reference_points": []
  }
}
```

**向后兼容**：若JSON仅含扁平道路多边形格式（无"roads"/"lanes"/"calibration"键），系统将所有条目视为道路，无子车道，保持当前行为。

---

## 分阶段实施计划

### Phase 1: 基础设施（Week 1-2）
- [ ] 扩展 TrackElement + FrameElement 字段（含 `telemetry`、`calibration_mode`）
- [ ] DetectionTrackingNodes 保留原始YOLO类别
- [ ] TrackerInfoUpdateNode 添加 motor/non_motor 分类
- [ ] 创建 `utils_local/homography.py`（遥测模式 + 参考点模式）
- [ ] 创建 `HomographyCalibrationNode`（auto/telemetry/reference_points 三模式）
- [ ] 扩展 `configs/app_config.yaml`（calibration + telemetry 配置段）
- [ ] 创建 `configs/generate_zones.py` 标注工具

**验证**：管道正常运行，新节点全部透传，现有Grafana仪表盘不受影响

### Phase 2: 车速估计（Week 3-4）
- [ ] 创建 `SpeedEstimationNode`
- [ ] 插入节点到所有 `main*.py` 入口
- [ ] ShowNode 显示车速标签
- [ ] Kafka消息新增 `avg_speed_kmh`
- [ ] Telegraf + Grafana 新增车速面板

**验证**：视频叠加显示km/h车速，Kafka消息含车速字段，Grafana显示车速时序

### Phase 3: 方向流量统计 + 车道级增强（Week 5-6）
- [ ] 创建 `DirectionFlowNode`（方向流量：左转/直行/右转，始终运行）
- [ ] 创建 `utils_local/lane_geometry.py`
- [ ] 创建 `LaneAnalysisNode`（数据驱动：有标注+命中时输出车道级指标）
- [ ] VideoReader 加载扩展JSON格式，填充 `lane_polygons` 字段
- [ ] 插入两个节点到管道 + CalcStatisticsNode 聚合方向流量
- [ ] Kafka消息新增 `direction_flow`、`queue_count`、`lane_stats`
- [ ] ShowNode 渲染方向流量统计 + 车道多边形（有标注时叠加显示）
- [ ] Telegraf + Grafana 方向流量面板

**验证**：
- 无标注场景：视频显示方向流量统计，Kafka含direction_flow，lane_stats为null
- 有标注场景：加载含车道多边形的JSON后，命中的车辆自动输出车道级指标，lane_stats非空

### Phase 4: 轨迹还原（Week 7-8）
- [ ] 创建 `utils_local/trajectory_classifier.py`
- [ ] 创建 `TrajectoryNode`
- [ ] TrackerInfoUpdateNode 发射完成轨迹 + 出口道路检测
- [ ] KafkaProducerNode 发送 track_complete 消息
- [ ] 平台消费者处理 + InfluxDB写入
- [ ] ShowNode 显示轨迹尾迹

**验证**：视频显示彩色轨迹尾迹，`/api/v1/trajectories` 返回含turn_behavior的数据

### Phase 5: RTSP + MQTT遥测输入（Week 9）
- [ ] 创建 `services/TelemetrySubscriber.py`（MQTT订阅+缓冲+帧同步）
- [ ] `VideoReader` 集成遥测注入接口
- [ ] `HomographyCalibrationNode` 遥测模式集成测试
- [ ] docker-compose 添加 MQTT broker 服务（或使用现有MQTT基础设施）
- [ ] 飞行日志回放验证（使用 `test_videos/srt/堤口路胜利庄北路早高峰0520.txt` 作为遥测数据源）

**验证**：RTSP视频流 + MQTT遥测同步运行，HomographyCalibrationNode 自动计算每帧H矩阵，车速估计输出合理km/h值

### Phase 6: 冲突检测（Week 10-11）⚠️ 依赖模型微调

**前置条件**：uav_best.pt 当前仅检测交通工具类(COCO 2-9)，不含 person(0)/bicycle(1)。需先微调模型加入行人和自行车类别。

**6.0 模型微调（前置）**：
- [ ] 收集包含行人和自行车的训练数据（从现有视频或公开数据集）
- [ ] 在 uav_best.pt 基础上 fine-tune，新增 person + bicycle 类别
- [ ] 验证新模型在无人机视角下的检测精度
- [ ] 更新 `classes_to_detect` 配置为 `[0,1,2,3,4,5,6,7,8,9]`

**6.1-6.5 冲突检测实现**（模型就绪后）：
- [ ] 创建 `ConflictDetectionNode`
- [ ] 插入管道 + Kafka发布冲突消息
- [ ] ShowNode 渲染冲突标记（红色闪烁）
- [ ] 平台消费者 + 告警引擎新增冲突处理
- [ ] 冲突REST API

**验证**：视频显示冲突标记，平台生成P1-P3级告警，`/api/v1/conflicts` 返回数据

**临时方案**：在模型微调完成前，Phase 1-5 可正常实施。冲突检测的代码框架可先实现但 `enabled: false`，待模型就绪后启用。

### Phase 7: 清理与集成（Week 12）
- [ ] 移除硬编码5条道路限制（解决TD-001）
- [ ] Kafka消息向后兼容（旧road_N + 新roads数组并存）
- [ ] 集成测试多摄像头配置
- [ ] 更新文档

### 依赖关系

```
Phase 1 (基础)
├── Phase 2 (车速) ← Phase 3 (方向流量+车道增强) 依赖车速做排队检测和方向平均车速
├── Phase 4 (轨迹) ← 依赖Phase 2获取轨迹中的车速信息
├── Phase 5 (RTSP+MQTT遥测) ← 独立，但增强Phase 2标定精度
└── Phase 6 (冲突) ← 依赖Phase 1(分类) + Phase 2(车速→TTC)
Phase 7 (清理) ← 所有功能阶段之后
```

---

## 关键设计决策

| 决策 | 理由 |
|------|------|
| 遥测驱动单应性标定（非地面参考点） | 无人机场景无法在地面标4个点；遥测（高度+云台角度+GPS）+相机内参可自动计算H矩阵，零运行时手动操作 |
| RTSP视频 + MQTT遥测双通道（非SRT内嵌元数据） | 无人机推流架构的标准模式；RTSP兼容性最好，MQTT遥测可独立消费和存储 |
| 自动模式切换（nadir/oblique） | gimbal_pitch > 80° 时用简化2D相似变换（计算快、精度高），否则用完整透视变换 |
| 方向流量始终运行（零标注） | 无人机巡飞无法标注车道多边形；轨迹首尾向量夹角可自动分类左转/直行/右转 |
| 车道级指标数据驱动（非配置开关） | 有车道标注+点位命中 → 自动输出车道级指标；无标注时自动跳过，无需操作员切换模式 |
| 独立Kafka topic（轨迹/冲突） | 消息结构不同，混合在同一topic使Telegraf解析复杂化 |
| 平台直写track_events到InfluxDB | 轨迹事件不规则（非周期性），不适合Telegraf的JSON flat解析 |
| 保留YOLO原始class_id | motor/non_motor分类需要真实检测类别，ByteTrack基于IoU匹配不受多类别影响 |
| EMA平滑车速 | 原始帧间车速因bbox抖动噪声大，EMA(窗口=5)提供平滑读数无明显延迟 |
| 冲突检测延迟至模型微调后 | 当前uav_best.pt仅检测交通工具类(2-9)，不含person(0)/bicycle(1)；需先微调模型加入行人和自行车类别，Phase 6方可启用 |

## 验证方案

1. **单元测试**：homography（遥测模式+标定点模式）、trajectory_classifier（方向分类）、lane_geometry 工具函数
2. **集成测试**：使用现有 test_videos/ 视频验证完整管道
3. **方向流量验证**：对比方向分类结果与人工标注的行驶方向，确认准确率 > 85%
4. **遥测回放验证**：将 `test_videos/srt/堤口路胜利庄北路早高峰0520.txt` 转为MQTT消息流，与视频帧同步回放，验证H矩阵计算精度
5. **GSD精度验证**：在视频中量取已知长度的地面标线（如车道线3.5m），对比遥测计算的GSD与实际像素距离
6. **Grafana验证**：新增面板显示车速/方向流量/排队计数/车头时距
7. **平台验证**：WebSocket实时推送轨迹和冲突事件，REST API可查询
8. **告警验证**：模拟冲突场景确认P1-P3告警正确生成

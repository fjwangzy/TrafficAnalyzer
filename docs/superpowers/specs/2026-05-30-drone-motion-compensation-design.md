# 无人机巡飞运动补偿 + 事件世界坐标输出

> **架构替代声明（2026-07-13）**：本文保留运动补偿、世界坐标和算法输出设计；其中旧 Kafka/InfluxDB 消息与存储示例已由 [ADR-019](../../DECISIONS.md) 替代。现行契约以 [API_CONTRACTS.md](../../API_CONTRACTS.md) 和 [DATABASE_SCHEMA.md](../../DATABASE_SCHEMA.md) 为准。

## 问题

当前交通态势感知系统的所有空间计算（车速、方向、轨迹、冲突检测）都假设**静态摄像头**。H矩阵将像素映射到**以无人机正下方为原点**的无人机相对坐标系。无人机巡飞时：

1. **车速估计被污染**：无人机速度（可达12 m/s = 43 km/h）直接叠加到车辆表观速度上，误差 ±43 km/h
2. **方向分类被污染**：云台偏航旋转导致所有像素空间航向同步旋转，直行车辆可能被判为转弯
3. **轨迹分类被污染**：像素空间轨迹受无人机平移+旋转双重影响
4. **冲突TTC失效**：基于被污染的车速计算碰撞时间
5. **事件输出无世界坐标**：track_complete和conflict消息仅含像素坐标，无法在地图上定位

## 现状审查

| 模块 | 是否处理运动补偿 | 缺陷 |
|------|:---:|------|
| `HomographyCalibrationNode` | 否 | 每帧独立计算H，无帧间一致性，无位移跟踪 |
| `SpeedEstimationNode` | 否 | 用当前帧H转换所有历史点，不减去无人机速度 |
| `DirectionFlowNode` | 否 | 像素空间atan2，不修正云台偏航增量 |
| `TrajectoryNode` | 否 | 像素空间转向分类，不转换世界坐标 |
| `ConflictDetectionNode` | 否 | 单帧内距离正确，但TTC使用被污染的车速 |
| `TelemetrySubscriber` | — | 已收集horizontal_speed/GPS/attitude_head，但下游未使用 |
| 事件输出(Kafka) | — | track_complete仅含trajectory_px，conflict无位置坐标 |

**已收集的遥测字段**（14个，其中9个未被使用）：

| 字段 | 已使用 | 用途 |
|------|:---:|------|
| altitude_agl | ✓ | H矩阵GSD计算 |
| gimbal_pitch | ✓ | H矩阵模式切换 |
| gimbal_yaw | ✓ | H矩阵旋转 |
| gimbal_roll | ✓ | H矩阵旋转 |
| zoom_factor | ✓ | H矩阵等效焦距 |
| latitude | **否** | 可用于GPS锚定 |
| longitude | **否** | 可用于GPS锚定 |
| horizontal_speed | **否** | 可用于无人机速度矢量 |
| vertical_speed | **否** | 可用于高度补偿 |
| attitude_head | **否** | 可用于无人机速度方向 |
| attitude_pitch | **否** | — |
| height | **否** | 仅用于AGL计算 |
| elevation | **否** | 仅用于AGL计算 |
| timestamp | ✓ | 帧↔遥测同步 |

---

## 解决方案：混合运动补偿

### 核心思路

1. **GPS锚定世界坐标系**：首帧GPS为世界原点，后续帧通过GPS增量确定无人机位置
2. **帧间遥测速度平滑**：用`horizontal_speed × dt`沿`attitude_head`积分平滑GPS噪声
3. **悬停自动跳过**：`horizontal_speed < 1 m/s`时跳过补偿，避免GPS抖动引入伪运动
4. **事件输出补充世界坐标**：所有Kafka事件消息携带`(easting_m, northing_m)`世界坐标

### 坐标系定义

```
世界坐标系（东北天 ENU）：
  原点 = 首帧GPS位置（或配置的anchor点）
  +X = 东
  +Y = 北
  单位 = 米

无人机相对坐标系：
  原点 = 无人机正下方地面投影点
  +X/+Y = 由云台偏航决定的方向
  单位 = 米

像素坐标系：
  原点 = 图像左上角
  +X = 右, +Y = 下
  单位 = 像素
```

### 坐标变换链

```
像素 → [H⁻¹] → 无人机相对(米) → [旋转-gimbal_yaw] → 东北对齐(米) → [+drone_displacement] → 世界坐标(米)
```

三步变换：

```python
# 1. 像素→无人机相对（H矩阵）
pt_drone = H @ [px, py, 1]  # 齐次坐标，除以第3分量

# 2. 旋转对齐东北方向（云台偏航已在H中体现，此处为文档说明）
# H矩阵的旋转分量已包含gimbal_yaw，无需额外旋转

# 3. 叠加无人机位移
pt_world = pt_drone[:2] + drone_displacement_m
```

---

## 模块设计

### 新增：`utils_local/motion_compensation.py`

```python
"""无人机运动补偿工具函数。"""

import math
import numpy as np

def gps_to_enu_meters(
    lat: float, lon: float,
    anchor_lat: float, anchor_lon: float,
) -> tuple[float, float]:
    """GPS坐标→东北偏移（米），简化平面近似。
    
    Returns: (easting_m, northing_m) 相对anchor的偏移
    """
    EARTH_RADIUS_M = 6_371_000
    d_lat = lat - anchor_lat
    d_lon = lon - anchor_lon
    northing = math.radians(d_lat) * EARTH_RADIUS_M
    easting = math.radians(d_lon) * EARTH_RADIUS_M * math.cos(math.radians(anchor_lat))
    return easting, northing


def compute_drone_displacement(
    telemetry_current: dict,
    anchor_lat: float,
    anchor_lon: float,
) -> np.ndarray:
    """计算无人机相对世界锚点的东北偏移（米）。
    
    Args:
        telemetry_current: 当前帧遥测
        anchor_lat/lon: 世界锚点GPS
    
    Returns:
        np.array([easting_m, northing_m])
    """
    lat = telemetry_current["latitude"]
    lon = telemetry_current["longitude"]
    easting, northing = gps_to_enu_meters(lat, lon, anchor_lat, anchor_lon)
    return np.array([easting, northing], dtype=np.float64)


def compute_drone_velocity_vector(
    telemetry: dict,
) -> np.ndarray:
    """从遥测计算无人机速度矢量（m/s，东北坐标系）。
    
    使用 horizontal_speed（标量）和 attitude_head（航向角，度）。
    
    Returns:
        np.array([v_east, v_north]) m/s
    """
    speed_ms = telemetry.get("horizontal_speed", 0)
    heading_deg = telemetry.get("attitude_head", 0)
    heading_rad = math.radians(heading_deg)
    v_east = speed_ms * math.sin(heading_rad)
    v_north = speed_ms * math.cos(heading_rad)
    return np.array([v_east, v_north], dtype=np.float64)


def pixel_to_world_compensated(
    points_px: np.ndarray,
    H: np.ndarray,
    drone_displacement_m: np.ndarray,
) -> np.ndarray:
    """像素→世界坐标（含运动补偿）。
    
    Args:
        points_px: Nx2 像素坐标
        H: 3x3 单应性矩阵
        drone_displacement_m: [easting, northing] 无人机世界位移(m)
    
    Returns:
        Nx2 世界坐标（米，东北坐标系）
    """
    from utils_local.homography import pixel_to_world
    pts_drone = pixel_to_world(points_px, H)  # Nx2, drone-relative meters
    return pts_drone + drone_displacement_m  # broadcast add


def is_hovering(telemetry: dict, threshold_ms: float = 1.0) -> bool:
    """检测无人机是否处于悬停状态。"""
    return abs(telemetry.get("horizontal_speed", 0)) < threshold_ms


def compensate_speed(
    apparent_speed_vector: np.ndarray,
    drone_velocity: np.ndarray,
) -> np.ndarray:
    """从表观速度中减去无人机速度，得到真实地面速度。
    
    Args:
        apparent_speed_vector: [v_east, v_north] 表观速度(m/s, 世界坐标系)
        drone_velocity: [v_east, v_north] 无人机速度(m/s)
    
    Returns:
        [v_east, v_north] 真实地面速度(m/s)
    """
    return apparent_speed_vector - drone_velocity


def compensate_heading(
    heading_pixel_deg: float,
    gimbal_yaw_current: float,
    gimbal_yaw_initial: float,
) -> float:
    """修正像素空间航向角，去除云台偏航旋转影响。
    
    Args:
        heading_pixel_deg: 像素空间计算得到的航向（度）
        gimbal_yaw_current: 当前帧云台偏航角（度）
        gimbal_yaw_initial: 首帧云台偏航角（度）
    
    Returns:
        修正后的世界参考系航向角（度），归一化到[-180, 180]
    """
    yaw_delta = gimbal_yaw_current - gimbal_yaw_initial
    corrected = heading_pixel_deg - yaw_delta
    # 归一化到[-180, 180]
    while corrected > 180:
        corrected -= 360
    while corrected < -180:
        corrected += 360
    return corrected
```

### 新增：`nodes/MotionCompensationNode.py`

```python
"""运动补偿节点：注入世界锚点、无人机位移、速度矢量到FrameElement。

位置：HomographyCalibrationNode之后，SpeedEstimationNode之前。
仅在有遥测数据时生效；无遥测/reference_points模式时透传。
"""

class MotionCompensationNode:
    def __init__(self, config):
        cfg = config.get("motion_compensation", {})
        self.enabled = cfg.get("enabled", True)
        self.hover_threshold_ms = cfg.get("hover_threshold_ms", 1.0)
        self._world_anchor: tuple[float, float] | None = None  # (lat, lon)
        self._gimbal_yaw_initial: float | None = None
        self._logged_init = False

    @profile_time
    def process(self, frame_element):
        if isinstance(frame_element, VideoEndBreakElement):
            return frame_element
        if not self.enabled:
            return frame_element

        telemetry = getattr(frame_element, "telemetry", None)
        if not telemetry:
            return frame_element

        # 初始化世界锚点（首帧GPS）
        if self._world_anchor is None:
            lat = telemetry.get("latitude")
            lon = telemetry.get("longitude")
            if lat is not None and lon is not None:
                self._world_anchor = (lat, lon)
                self._gimbal_yaw_initial = telemetry.get("gimbal_yaw", 0)
                logger.info(f"MotionCompensation: 世界锚点 = ({lat:.6f}, {lon:.6f})")

        if self._world_anchor is None:
            return frame_element

        # 计算无人机世界位移
        drone_disp = compute_drone_displacement(telemetry, *self._world_anchor)
        drone_vel = compute_drone_velocity_vector(telemetry)
        hovering = is_hovering(telemetry, self.hover_threshold_ms)
        gimbal_yaw = telemetry.get("gimbal_yaw", 0)
        yaw_delta = gimbal_yaw - self._gimbal_yaw_initial

        # 悬停时置零位移增量（避免GPS抖动引入伪运动）
        if hovering:
            drone_vel = np.zeros(2)

        # 注入FrameElement
        frame_element.world_anchor_lat_lon = self._world_anchor
        frame_element.drone_displacement_m = drone_disp
        frame_element.drone_velocity_ms = drone_vel
        frame_element.gimbal_yaw_delta = yaw_delta
        frame_element.gimbal_yaw_initial = self._gimbal_yaw_initial
        frame_element.is_hovering = hovering

        return frame_element
```

### 修改：`elements/FrameElement.py`

新增字段：

```python
# ── 新增：运动补偿 ──
self.world_anchor_lat_lon: tuple[float, float] | None = None  # (lat, lon) 世界锚点
self.drone_displacement_m: np.ndarray | None = None  # [easting, northing] 米
self.drone_velocity_ms: np.ndarray | None = None  # [v_east, v_north] m/s
self.gimbal_yaw_delta: float = 0.0  # 当前云台偏航 - 首帧云台偏航（度）
self.gimbal_yaw_initial: float | None = None  # 首帧云台偏航角（度）
self.is_hovering: bool = False  # 是否悬停
```

### 修改：`nodes/SpeedEstimationNode.py`

**当前问题**：所有position_history点用同一H转换 → 得到的是无人机相对速度，不是地面真实速度。

**修改方案**：
1. 用当前帧H转换所有历史点 → 得到无人机相对坐标（同一参考系，因为H包含了当前帧的所有旋转）
2. 计算表观速度矢量（无人机相对坐标系，已含H的旋转，所以方向是世界对齐的）
3. 减去无人机速度矢量 → 得到真实地面速度
4. 悬停时跳过补偿（无人机静止，速度误差 < 1 m/s）

```python
# 修改后的速度计算核心逻辑：

if has_H:
    pts_px = np.array([[p_old[0], p_old[1]], [p_new[0], p_new[1]]])
    pts_world = pixel_to_world(pts_px, H)  # drone-relative meters
    # 注意：由于H包含gimbal_yaw旋转，pts_world的方向已经与世界坐标系对齐
    # 只差一个平移（无人机位移），但在计算速度时平移抵消
    displacement = pts_world[1] - pts_world[0]
    apparent_vel = displacement / dt  # m/s, 无人机相对速度

    # 运动补偿：减去无人机速度
    drone_vel = getattr(frame_element, "drone_velocity_ms", None)
    is_hovering = getattr(frame_element, "is_hovering", False)

    if drone_vel is not None and not is_hovering:
        true_vel = apparent_vel - drone_vel
        speed_ms = float(np.linalg.norm(true_vel))
    else:
        speed_ms = float(np.linalg.norm(apparent_vel))

    track.speed_kmh = speed_ms * 3.6
```

**关键洞察**：H矩阵已包含gimbal_yaw旋转，所以`pixel_to_world`输出的方向与世界坐标系对齐。计算位移差时，无人机平移在两个点之间抵消，但无人机速度（位移随时间的变化率）不抵消 → 需要减去。

### 修改：`nodes/DirectionFlowNode.py`

**当前问题**：像素空间`atan2(dy, dx)`计算的heading受云台偏航旋转影响。

**修改方案**：从`heading_angle`减去`gimbal_yaw_delta`。

```python
# 在classify之前修正heading
if hasattr(frame_element, "gimbal_yaw_delta"):
    # compute_heading返回的是像素空间角度
    # 减去云台偏航增量得到世界参考系角度
    entry_heading = compensate_heading(
        entry_heading, gimbal_yaw_current, gimbal_yaw_initial
    )
    exit_heading = compensate_heading(
        exit_heading, gimbal_yaw_current, gimbal_yaw_initial
    )
```

实际上更简单的做法：heading是在position_history内计算的相对角度，只要减去gimbal_yaw_delta即可。因为position_history窗口内的点共享同一H（当前帧），但轨迹跨越的帧之间H的旋转分量在变化。

**更精确的方案**：对每个轨迹点应用H转换到世界坐标后计算heading。但这要求每个轨迹点都有对应的世界坐标，增加TrackElement的存储。

**推荐折中方案**：用当前帧H转换position_history的首尾点 → 世界坐标 → 计算heading → 不再需要yaw修正（因为已转换到世界坐标系）。

```python
# 修改后的方向计算：
if has_H:
    # 转换position_history首尾到世界坐标
    p_old_px = np.array([[track.position_history[0][0], track.position_history[0][1]]])
    p_new_px = np.array([[track.position_history[-1][0], track.position_history[-1][1]]])
    
    drone_disp = getattr(frame_element, "drone_displacement_m", None)
    if drone_disp is not None:
        p_old_w = pixel_to_world(p_old_px, H)[0] + drone_disp
        p_new_w = pixel_to_world(p_new_px, H)[0] + drone_disp
    else:
        p_old_w = pixel_to_world(p_old_px, H)[0]
        p_new_w = pixel_to_world(p_new_px, H)[0]
    
    heading = math.degrees(math.atan2(p_new_w[1] - p_old_w[1], p_new_w[0] - p_old_w[0]))
```

### 修改：`nodes/TrajectoryNode.py`

**当前**：输出`trajectory_px`（像素坐标），降采样到50点。

**新增**：转换轨迹到世界坐标，输出`trajectory_world_m`。

```python
# 在转向分类和降采样之后，新增世界坐标转换：
H = frame_element.homography_matrix
drone_disp = getattr(frame_element, "drone_displacement_m", None)

if is_valid_homography(H) and drone_disp is not None:
    pts_px = np.array(ct["trajectory_px"])  # Nx2
    pts_world = pixel_to_world_compensated(pts_px, H, drone_disp)
    ct["trajectory_world_m"] = [
        [round(float(p[0]), 2), round(float(p[1]), 2)]
        for p in pts_world
    ]
```

**精度说明**：降采样后的轨迹点（最多50个）用当前帧H统一转换。对于短轨迹（2-10秒），无人机位移在1-2米级别，误差可接受。对于平台侧的轨迹回放，使用`world_anchor_lat_lon`可还原绝对GPS位置。

### 修改：`nodes/ConflictDetectionNode.py`

**新增**：冲突事件补充世界坐标。

```python
# 在conflict_events.append中新增：
drone_disp = getattr(frame_element, "drone_displacement_m", None)
if drone_disp is not None:
    motor_world = pts[0] + drone_disp
    non_motor_world = pts[1] + drone_disp
    event["motor_position_m"] = [round(float(motor_world[0]), 2), round(float(motor_world[1]), 2)]
    event["non_motor_position_m"] = [round(float(non_motor_world[0]), 2), round(float(non_motor_world[1]), 2)]
```

### 修改：`nodes/TrackerInfoUpdateNode.py`

completed_tracks发射时补充世界坐标入口点：

```python
# 新增：入口/出口点世界坐标
H = frame_element.homography_matrix
drone_disp = getattr(frame_element, "drone_displacement_m", None)
if is_valid_homography(H) and drone_disp is not None and track.trajectory_points:
    entry_px = np.array([track.trajectory_points[0]])
    exit_px = np.array([track.trajectory_points[-1]])
    entry_world = pixel_to_world_compensated(entry_px, H, drone_disp)[0]
    exit_world = pixel_to_world_compensated(exit_px, H, drone_disp)[0]
    completed_track_data["entry_point_m"] = [round(float(entry_world[0]), 2), round(float(entry_world[1]), 2)]
    completed_track_data["exit_point_m"] = [round(float(exit_world[0]), 2), round(float(exit_world[1]), 2)]
```

### 修改：`nodes/KafkaProducerNode.py`

统计消息新增无人机位置：

```python
# 在data字典中新增：
anchor = getattr(frame_element, "world_anchor_lat_lon", None)
drone_disp = getattr(frame_element, "drone_displacement_m", None)
if anchor and drone_disp is not None:
    data["drone_position"] = {
        "anchor_lat": round(anchor[0], 6),
        "anchor_lon": round(anchor[1], 6),
        "easting_m": round(float(drone_disp[0]), 2),
        "northing_m": round(float(drone_disp[1]), 2),
    }
data["is_hovering"] = getattr(frame_element, "is_hovering", False)
```

---

## 事件输出格式（含世界坐标）

### track_complete_{n} 消息

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
    "trajectory_px": [[100,200], [105,210], ...],
    "trajectory_world_m": [[12.3, -5.2], [12.8, -4.9], ...],
    "entry_point_m": [10.1, -6.5],
    "exit_point_m": [18.4, 2.1],
    "world_anchor_lat_lon": [31.234567, 121.456789],
    "timestamp_first": 120.5,
    "timestamp_last": 128.9
}
```

| 新增字段 | 类型 | 说明 |
|----------|------|------|
| `trajectory_world_m` | `[[e, n], ...]` | 轨迹点东北偏移（米，相对world_anchor） |
| `entry_point_m` | `[e, n]` | 轨迹起点世界坐标（米） |
| `exit_point_m` | `[e, n]` | 轨迹终点世界坐标（米） |
| `world_anchor_lat_lon` | `[lat, lon]` | 世界锚点GPS坐标 |

**GPS还原**：`lat = anchor_lat + northing_m / 111320`, `lon = anchor_lon + easting_m / (111320 × cos(anchor_lat_rad))`

### conflicts_{n} 消息

```json
{
    "msg_type": "conflict",
    "intersection_id": "INT_camera_1",
    "motor_id": 142,
    "non_motor_id": 156,
    "motor_position_m": [12.3, -5.2],
    "non_motor_position_m": [12.8, -4.9],
    "distance_m": 0.6,
    "ttc_sec": 0.86,
    "severity": "critical",
    "motor_speed_kmh": 25.0,
    "world_anchor_lat_lon": [31.234567, 121.456789],
    "timestamp": 125.3
}
```

| 新增字段 | 类型 | 说明 |
|----------|------|------|
| `motor_position_m` | `[e, n]` | 机动车位置（米，世界坐标） |
| `non_motor_position_m` | `[e, n]` | 非机动车位置（米，世界坐标） |
| `world_anchor_lat_lon` | `[lat, lon]` | 世界锚点GPS坐标 |
| `timestamp` | `float` | 冲突发生时刻 |

### statistics_{n} 消息（新增字段）

```json
{
    "camera_id": "id_1",
    "cars": 12,
    "msg_type": "stats",
    "intersection_id": "INT_camera_1",
    "road_1": 4.2, "road_2": 3.8, "road_3": null, "road_4": 2.1, "road_5": 1.5,
    "avg_speed_kmh": 28.5,
    "drone_position": {
        "anchor_lat": 31.234567,
        "anchor_lon": 121.456789,
        "easting_m": 15.3,
        "northing_m": -8.2
    },
    "is_hovering": false,
    ...
}
```

---

## 配置

`configs/app_config.yaml` 新增：

```yaml
motion_compensation:
  enabled: true
  hover_threshold_ms: 1.0    # 低于此速度视为悬停，跳过补偿
  world_anchor: null          # null=自动取首帧GPS，或手动 [lat, lon]
```

---

## 管道位置

```
VideoReader
  → DetectionTrackingNodes
  → HomographyCalibrationNode     # 计算每帧H矩阵
  → MotionCompensationNode  [新]  # 注入世界锚点、位移、速度
  → TrackerInfoUpdateNode
  → SpeedEstimationNode           # [改] 减去无人机速度
  → DirectionFlowNode             # [改] 世界坐标系航向
  → LaneAnalysisNode
  → TrajectoryNode                # [改] 输出trajectory_world_m
  → ConflictDetectionNode         # [改] 输出position_world_m
  → CalcStatisticsNode
  → KafkaProducerNode             # [改] 输出drone_position
  → ShowNode
```

MotionCompensationNode在HomographyCalibrationNode之后、TrackerInfoUpdateNode之前。它在进程2（proc_tracker_update_and_calc）中实例化，与所有其他处理节点在同一进程。

---

## 回退行为

| 场景 | 行为 |
|------|------|
| 遥测启用 + GPS有效 + 巡飞中 | 完整运动补偿，事件输出世界坐标 |
| 遥测启用 + GPS有效 + 悬停中 | 跳过速度补偿（误差 < 1 m/s），世界坐标正常 |
| 遥测启用 + GPS丢失 | 降级为速度积分（短期可用），日志警告 |
| 遥测未启用 | 跳过补偿，行为与当前一致 |
| reference_points模式 | 跳过补偿（固定摄像头假设），事件输出参考点世界坐标 |

---

## 精度分析

| 因素 | 影响 | 缓解 |
|------|------|------|
| GPS精度（±2-5m） | 世界锚点定位误差 | 首帧GPS取10帧均值 |
| 遥测延迟（50ms同步窗口） | H矩阵与帧不完全对齐 | `sync_tolerance_sec=0.05`已在TelemetrySubscriber中处理 |
| 车速估计窗口内无人机位移 | 用当前帧H统一转换 | 15帧≈0.5s，位移差在速度减法中抵消（数学正确） |
| **方向分类世界坐标近似** | 用当前帧H+当前位移转换历史点 | **无人机速度 > 5 m/s 时回退像素空间heading** |
| **轨迹世界坐标近似** | 用当前帧H转换整条轨迹 | 悬停/慢速时误差1-2m；**快速巡飞时误差=无人机速度×轨迹时长**（12m/s×8s=96m） |
| 云台偏航抖动 | H矩阵旋转分量不稳定 | 机械云台已做物理稳定，高频抖动极小 |
| GPS丢失 | 位移回退到上次值 | MotionCompensationNode缓存`_last_displacement` |
| 云台偏航±180°跳变 | yaw_delta计算错误 | 归一化到[-180, 180] |

### 已知限制

**轨迹世界坐标在快速巡飞时精度有限**：`trajectory_world_m`使用当前帧的H和drone_displacement转换所有历史轨迹点，未存储每帧的独立位移。悬停或低速飞行（<3 m/s）时误差1-2m，可用于热力图；快速巡飞时误差与无人机位移同量级。精确轨迹还原需要存储per-frame位移（技术债）。

**方向分类在高速巡飞时降级**：无人机速度 > 5 m/s时自动回退到像素空间heading，此时方向分类受云台旋转影响（与无补偿时行为一致）。

---

## 实现计划

### Phase 1: 核心补偿（优先）
1. 创建 `utils_local/motion_compensation.py`
2. 创建 `nodes/MotionCompensationNode.py`
3. 扩展 `FrameElement` 新增6个运动补偿字段
4. 修改 `SpeedEstimationNode` 减去无人机速度
5. 修改 `DirectionFlowNode` 使用世界坐标系航向
6. 更新所有 `main*.py` 插入 MotionCompensationNode
7. 更新 `configs/app_config.yaml` 新增 `motion_compensation:` 段

### Phase 2: 事件世界坐标输出
8. 修改 `TrackerInfoUpdateNode` completed_tracks 新增 `entry_point_m` / `exit_point_m`
9. 修改 `TrajectoryNode` 新增 `trajectory_world_m` 和 `world_anchor_lat_lon`
10. 修改 `ConflictDetectionNode` 新增 `motor_position_m` / `non_motor_position_m`
11. 修改 `KafkaProducerNode` 统计消息新增 `drone_position` / `is_hovering`

### 验证
12. 悬停测试：`horizontal_speed < 1 m/s` 时补偿跳过，车速不变
13. 巡飞测试：模拟无人机12 m/s匀速飞行，验证静止车辆显示0 km/h
14. 世界坐标验证：对比轨迹world_m与实际GPS轨迹（若有ground truth）

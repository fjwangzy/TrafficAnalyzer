# 无人机交通态势感知系统 — 总体技术设计方案

> **版本**：v1.0  
> **日期**：2026-05-31  
> **状态**：Draft — 待评审  
> **作者**：系统架构组  
> **适用分支**：feature/influx

---

## 目录

1. [项目背景与业务定位](#1-项目背景与业务定位)
2. [系统总体架构](#2-系统总体架构)
3. [核心算法与模型设计](#3-核心算法与模型设计)
4. [数据架构与存储设计](#4-数据架构与存储设计)
5. [平台与前端设计](#5-平台与前端设计)
6. [关键技术难点与创新方案](#6-关键技术难点与创新方案)
7. [实施路径与里程碑规划](#7-实施路径与里程碑规划)
8. [技术风险与应对策略](#8-技术风险与应对策略)
9. [演进路线与远期展望](#9-演进路线与远期展望)

---

## 1. 项目背景与业务定位

### 1.1 行业痛点

城市环形交叉路口是交通拥堵和事故的高发区域。传统的固定摄像头方案存在三大瓶颈：

| 痛点 | 表现 | 影响 |
|------|------|------|
| **视角受限** | 固定摄像头覆盖范围有限，存在大量盲区 | 无法全面感知路口态势 |
| **部署成本高** | 每个路口需立杆、布线、供电 | 建设周期长，维护困难 |
| **智能化不足** | 仅提供视频回放，无实时分析能力 | 无法支撑主动管控和应急响应 |

### 1.2 解决方案：无人机空中感知

利用无人机（UAV）高空俯拍视角 + AI视觉分析，构建一套**移动、灵活、智能**的交通态势感知系统：

```
┌─────────────────────────────────────────────────────────────────┐
│                    核心价值主张                                    │
│                                                                 │
│  ① 全景覆盖：100m+高空俯拍，单架无人机覆盖整个环形路口            │
│  ② 零基建部署：无需立杆布线，起飞即感知                           │
│  ③ 实时智能：边缘推理 + 流式计算，秒级延迟输出交通指标             │
│  ④ 应急灵活：事件驱动快速起飞，10分钟内抵达任意路口               │
│  ⑤ 数据沉淀：时序数据库 + 轨迹还原，支撑交通规划决策              │
└─────────────────────────────────────────────────────────────────┘
```

### 1.3 业务目标

| 目标维度 | 具体指标 | 目标值 |
|----------|----------|--------|
| **检测精度** | 车辆检测 mAP@0.5 | ≥ 85% |
| **跟踪连续性** | MOTA（多目标跟踪精度） | ≥ 75% |
| **处理实时性** | 端到端延迟（视频帧→指标输出） | < 500ms |
| **处理吞吐** | 4K@30fps 视频处理帧率 | ≥ 25fps |
| **指标覆盖** | 交通指标维度数 | ≥ 8 维（流量/车速/排队/方向/轨迹/冲突...） |
| **系统可用** | 服务可用率 | ≥ 99.5% |

### 1.4 系统边界

**系统负责**：
- 视频流接入（MP4/RTSP/无人机推流）
- 飞行遥测接入（MQTT/SRT/JSON文件）
- 车辆检测、多目标跟踪、态势分析
- 时序数据存储与可视化
- 事件检测与告警推送
- 管理控制台（路口/无人机/管道/告警管理）

**系统不负责**：
- 无人机飞行控制（由DJI Pilot / 飞控系统负责）
- 交通信号控制联动（二期扩展）
- 多路口级交通仿真（远期扩展）

---

## 2. 系统总体架构

### 2.1 架构全景图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              数据采集层                                      │
│                                                                             │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐                │
│  │  DJI 无人机   │   │  固定摄像头   │   │  视频文件回放     │                │
│  │  M300/M30T   │   │  RTSP Stream │   │  MP4 + SRT遥测   │                │
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────────┘                │
│         │                   │                   │                           │
│    RTSP视频流          RTSP视频流          MP4文件读取                        │
│    MQTT遥测流          (无遥测)            SRT/JSON遥测                       │
│         │                   │                   │                           │
└─────────┼───────────────────┼───────────────────┼───────────────────────────┘
          │                   │                   │
          ▼                   ▼                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           边缘计算层（核心管道）                               │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    三进程并行管道（main_optimized.py）                 │    │
│  │                                                                     │    │
│  │  ┌─────────────────────┐    Queue(50)    ┌──────────────────────┐   │    │
│  │  │  进程1: 读取+检测    │ ──────────────→ │  进程2: 分析+计算     │   │    │
│  │  │                     │                 │                      │   │    │
│  │  │  VideoReader        │                 │  HomographyCalib     │   │    │
│  │  │       ↓              │                 │  MotionCompensation  │   │    │
│  │  │  YOLO11 检测         │                 │  TrackerInfoUpdate   │   │    │
│  │  │       ↓              │                 │  SpeedEstimation     │   │    │
│  │  │  ByteTrack 跟踪      │                 │  DirectionFlow       │   │    │
│  │  │                     │                 │  LaneAnalysis        │   │    │
│  │  └─────────────────────┘                 │  Trajectory          │   │    │
│  │                                           │  ConflictDetection   │   │    │
│  │                                           │  CalcStatistics      │   │    │
│  │                                           │  KafkaProducer       │   │    │
│  │                                           └──────────┬───────────┘   │    │
│  │    Queue(50)               ┌─────────────────────────┘              │    │
│  │  ┌─────────────────────────▼──────────────────────────┐             │    │
│  │  │  进程3: 渲染+输出                                   │             │    │
│  │  │  ShowNode → VideoSaver / FlaskServer(MJPEG)        │             │    │
│  │  └────────────────────────────────────────────────────┘             │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
└────────────────────────────────────┬────────────────────────────────────────┘
                                     │ Kafka
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           消息中间件层                                        │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                         Apache Kafka                                 │    │
│  │                                                                     │    │
│  │  Topic: statistics_{N}     — 实时统计（1Hz）                         │    │
│  │  Topic: track_complete_{N} — 完成轨迹（事件驱动）                    │    │
│  │  Topic: conflicts_{N}      — 冲突事件（事件驱动）                    │    │
│  │  Topic: telemetry_{N}      — 无人机遥测（5-10Hz）                   │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
└─────────┬───────────────────────────────────┬───────────────────────────────┘
          │                                   │
          ▼                                   ▼
┌──────────────────────┐          ┌───────────────────────────────────────────┐
│  Telegraf             │          │  平台 Kafka Consumer（aiokafka）           │
│  kafka_consumer input │          │                                           │
│       ↓               │          │  statistics_* → WebSocket推送 + 告警检查   │
│  InfluxDB 1.8         │          │  track_complete_* → 轨迹存储 + 推送        │
│  (时序数据库)          │          │  conflicts_* → 告警引擎 + 推送             │
│       ↓               │          │  telemetry_* → 无人机状态更新              │
│  Grafana              │          │                                           │
│  (可视化仪表盘)        │          └───────────────────┬───────────────────────┘
└──────────────────────┘                              │
                                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           管理控制台层                                        │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  平台后端（FastAPI + Uvicorn :8000）                                  │    │
│  │                                                                     │    │
│  │  ┌──────────┐ ┌──────────────┐ ┌────────────┐ ┌──────────────┐     │    │
│  │  │ 路口管理  │ │ 无人机管理    │ │ 管道管理    │ │ 告警管理      │     │    │
│  │  └──────────┘ └──────────────┘ └────────────┘ └──────────────┘     │    │
│  │  ┌──────────┐ ┌──────────────┐ ┌────────────┐ ┌──────────────┐     │    │
│  │  │ 轨迹查询  │ │ 视频流管理    │ │ 系统监控    │ │ JWT认证      │     │    │
│  │  └──────────┘ └──────────────┘ └────────────┘ └──────────────┘     │    │
│  │                                                                     │    │
│  │  PostgreSQL (结构化)  │  InfluxDB (时序)  │  WebSocket (实时推送)    │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                     ▲                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  前端（React SPA + Vite + Tailwind）:8080                            │    │
│  │                                                                     │    │
│  │  Dashboard │ Monitoring │ Drones │ GIS │ Alerts │ Pipelines         │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 管道节点链详细设计

核心管道采用 **Node-based Pipeline** 架构，每帧数据（`FrameElement`）顺序流经 14 个处理节点，每个节点职责单一、可独立开关：

```
VideoReader
    │ 原始帧 + 道路多边形 + 遥测数据
    ▼
DetectionTrackingNodes
    │ YOLO11 检测框 + ByteTrack 跟踪 ID
    ▼
HomographyCalibrationNode
    │ 单应性矩阵 H（像素↔世界坐标映射）
    ▼
MotionCompensationNode
    │ 无人机位移/速度/悬停状态（GPS锚定ENU坐标系）
    ▼
TrackerInfoUpdateNode
    │ 轨迹状态更新 + 道路分配 + motor/non_motor分类 + 完成轨迹发射
    ▼
SpeedEstimationNode
    │ 单车速度(km/h)，减去无人机速度矢量
    ▼
DirectionFlowNode
    │ 方向流量统计（左转/直行/右转/掉头）+ 排队检测
    ▼
LaneAnalysisNode
    │ 车道级流量/排队长度/车头时距（数据驱动，有标注时自动输出）
    ▼
TrajectoryNode
    │ 轨迹转向分类 + 世界坐标轨迹输出
    ▼
ConflictDetectionNode
    │ 机非冲突 TTC 检测 + 严重度分级
    ▼
CalcStatisticsNode
    │ 聚合统计（车辆数 + 道路活跃度 + 方向流量）
    ▼
KafkaProducerNode
    │ 多 Topic 消息发送（statistics + track_complete + conflicts）
    ▼
ShowNode
    │ OpenCV 渲染（检测框 + ID + 速度 + 方向 + 轨迹 + 冲突标记）
    ▼
VideoSaverNode / FlaskServerVideoNode
    └ 视频文件保存 / MJPEG Web 串流
```

### 2.3 进程模型与并行策略

| 进程 | 绑定资源 | 核心操作 | 典型耗时 |
|------|----------|----------|----------|
| **Proc 1** | GPU + CPU | 视频解码 + YOLO推理 + ByteTrack | 20-30ms/帧 |
| **Proc 2** | CPU | 坐标变换 + 轨迹更新 + 统计分析 | 5-10ms/帧 |
| **Proc 3** | CPU + IO | OpenCV渲染 + MJPEG编码 + 网络发送 | 10-15ms/帧 |

**设计决策**：将 GPU 推理（Proc1）、CPU 计算（Proc2）、IO 操作（Proc3）分离，利用硬件并行，总吞吐受限于最慢进程（通常是 Proc1 的 YOLO 推理），理论峰值约 30-35fps@4K。

**健壮性设计**：
- 队列容量 `maxsize=50`（约 1.5s@30fps 的缓冲）
- 下游进程通过 `get(timeout=10s)` + `is_alive()` 检测上游崩溃
- `VideoEndBreakElement` 哨兵对象级联终止所有进程

---

## 3. 核心算法与模型设计

### 3.1 车辆检测：YOLO11 无人机视角定制模型

**模型**：`weights/uav_best.pt` — 基于 YOLO11 架构，在无人机高空视角数据集上微调。

| 参数 | 值 | 说明 |
|------|------|------|
| 检测类别 | COCO 2-9 | car, motorcycle, bicycle, bus, truck, train, boat, traffic light |
| 推理尺寸 | 640×640 | 平衡精度与速度 |
| 置信度阈值 | 0.10 | 低阈值保留更多候选框供 ByteTrack 二次关联 |
| NMS IoU | 0.7 | 高阈值允许密集场景重叠框通过 |
| 推理设备 | auto (cuda>mps>cpu) | 自动选择最优设备 |

**设计考量**：
- 置信度阈值极低（0.10）是刻意为之：ByteTrack 的核心优势在于利用低分框进行第二轮关联，恢复被遮挡目标
- 当前模型不含 person(0)/bicycle(1) 类别，冲突检测需后续微调模型

### 3.2 多目标跟踪：ByteTrack

**算法核心**：双阈值两阶段关联

```
检测框 [x1,y1,x2,y2,conf,class]
    │
    ├─ 按 conf 分组
    │   ├─ 高分组 (>0.5): 用于第一轮关联
    │   └─ 低分组 (>0.1): 用于第二轮关联（恢复被遮挡目标）
    │
    ▼
第一轮关联：高分框 × 已有轨迹
    │ 卡尔曼预测 + IOU距离矩阵 + fuse_score
    │ 线性分配（lap.lapjv）
    │
    ├─ 匹配成功 → 更新轨迹
    ├─ 未匹配轨迹 ──┐
    └─ 未匹配检测   │
                    ▼
第二轮关联：未匹配轨迹 × 低分框
    │ IOU距离矩阵（阈值0.5）
    │ 线性分配
    │
    ├─ 匹配成功 → 恢复被遮挡轨迹
    └─ 仍未匹配 → 初始化新轨迹 / 标记丢失

卡尔曼滤波器：
    状态空间: [cx, cy, aspect_ratio, height, vx, vy, va, vh] (8维)
    运动模型: 恒速模型 x(t+1) = x(t) + vx
    不确定性: 相对于 bbox 高度动态缩放（DeepSORT 风格）
```

**关键参数**：
- `track_buffer=125`：目标消失后保持 125 帧（约 4s@30fps），适应无人机视角下的频繁遮挡
- 跟踪完全基于 IoU，不依赖外观特征，推理速度快但在长时间遮挡后可能丢失 ID

### 3.3 遥测驱动单应性标定

**核心问题**：将像素坐标映射到世界坐标（米），以计算真实车速、距离、冲突 TTC。

**创新方案**：利用无人机飞行遥测自动计算每帧的单应性矩阵 H，**无需地面标定参考点**。

#### 两种模式自动切换

| 模式 | 触发条件 | 精度 | 计算量 |
|------|----------|------|--------|
| **Nadir（正下方）** | \|gimbal_pitch\| > 80° | 高（GSD误差<2%） | 低（2D相似变换） |
| **Oblique（斜视）** | \|gimbal_pitch\| ≤ 80° | 中（透视畸变） | 中（完整透视变换） |

#### Nadir 模式数学推导

```
GSD_x = altitude_agl × sensor_width_mm / (focal_length_mm × image_width_px)  [米/像素]
GSD_y = altitude_agl × sensor_height_mm / (focal_length_mm × image_height_px)

H = T(center_offset) × R(gimbal_yaw) × S(GSD)

其中:
  T: 平移矩阵，将图像中心映射到无人机正下方地面点
  R: 旋转矩阵，由 gimbal_yaw 决定
  S: 缩放矩阵，像素→米
```

#### Oblique 模式数学推导

```
R = Rz(yaw) × Ry(pitch+90°) × Rx(roll)     # 云台旋转矩阵
K = [[fx, 0, cx], [0, fy, cy], [0, 0, 1]]   # 相机内参
P = K × [R | t]                               # 投影矩阵
H = P                                          # 取地面平面 z=0 的单应性
```

**实际精度**（基于济南小清河北路实测数据）：
- AGL高度：52±1m（极稳定）
- GPS精度：RTK级（<2m）
- GSD误差：<5cm/pixel（Nadir模式）
- 距离误差：<5%@50m范围内

### 3.4 无人机运动补偿

**问题**：无人机巡飞速度可达 12m/s（43km/h），如不减去无人机自身运动，车速估计误差可达 ±43km/h。

**混合补偿方案**：

```
┌─────────────────────────────────────────────────────────┐
│               GPS锚定世界坐标系                          │
│                                                         │
│  世界锚点 = 首10帧GPS均值（lat₀, lon₀）                  │
│                                                         │
│  每帧:                                                   │
│    drone_displacement_m = GPS增量 → ENU(东,北)米        │
│    drone_velocity_ms = 遥测速度矢量（east, north分量）    │
│    is_hovering = |drone_velocity_ms| < 1.0 m/s          │
│    gimbal_yaw_delta = 云台偏航增量（修正方向分类）        │
│                                                         │
│  SpeedEstimationNode:                                    │
│    vehicle_speed = pixel_displacement - drone_velocity   │
│    → 真实地面车速(km/h)                                  │
│                                                         │
│  DirectionFlowNode:                                      │
│    IF drone_speed > 5m/s:                                │
│      使用像素空间heading（GPS噪声大）                     │
│    ELSE:                                                  │
│      使用世界坐标系heading（精确）                        │
└─────────────────────────────────────────────────────────┘
```

### 3.5 方向流量分类

**零标注方案**：基于轨迹运动方向变化自动分类，无需车道多边形标注。

```python
# 算法核心
entry_heading = compute_heading(trajectory[:mid])   # 轨迹前半段方向
exit_heading  = compute_heading(trajectory[mid:])   # 轨迹后半段方向

delta = exit_heading - entry_heading  # 方向变化角度（归一化到 -180°~180°）

分类规则:
  |delta| ≤ 25°           → "straight"（直行）
  25° < delta ≤ 120°      → "left_turn"（左转）
  -120° ≤ delta < -25°    → "right_turn"（右转）
  |delta| > 120°           → "u_turn"（掉头）
```

**精度保障**：
- 最少需要 8 个轨迹点 + 2秒存活时间
- 使用世界坐标系航向（无人机低速时）或像素空间航向（无人机高速时）
- 短轨迹归入 "unknown" 避免误分类

### 3.6 冲突检测：未来轨迹碰撞预测

**算法**：

```
对于每对 (机动车, 非机动车):
  1. 像素坐标 → 世界坐标（通过 H 矩阵）
  2. 读取双方世界坐标速度向量 velocity_ms
  3. 在 prediction_horizon_sec=5.0 秒内按 sample_interval_sec 采样未来位置
  4. 当同一预测时刻双方距离 <= collision_radius_m 时生成候选事件
  5. 当前距离较近但未来不碰撞时不上报
  6. 严重度分级:
     critical: 0-3 秒内进入碰撞半径 → P1 告警
     warning:  3-5 秒内进入碰撞半径 → P2 告警
  7. 配对 confirmed 去重（避免同一对重复告警）
```

**前提条件**：需要单应性标定（无 H 矩阵时自动跳过，避免误报）。

---

## 4. 数据架构与存储设计

### 4.1 数据流全链路

```
视频帧(30fps) ──→ [边缘管道处理] ──→ Kafka(1Hz) ──→ Telegraf ──→ InfluxDB
                                                                │
                                                                ▼
                                                          Grafana 仪表盘
                                                          (实时可视化)

完成轨迹(事件) ──→ Kafka ──→ Platform Consumer ──→ InfluxDB(track_events)
                                                       │
冲突事件(事件) ──→ Kafka ──→ Platform Consumer ──→ AlertEngine ──→ WebSocket推送
                              │                                      │
                              ▼                                      ▼
                          PostgreSQL                              前端实时显示
                          (告警历史)
```

### 4.2 Kafka 消息契约

#### 统计消息 `statistics_{N}`（1Hz 周期发送）

```json
{
  "camera_id": "id_1",
  "intersection_id": "INT_camera_1",
  "msg_type": "stats",
  "cars": 12,
  "road_1": 4.2, "road_2": 3.8, "road_3": null, "road_4": 2.1, "road_5": 1.5,
  "direction_flow": {
    "straight":    {"count": 5, "avg_speed_kmh": 28.3, "avg_headway_sec": 2.1},
    "left_turn":   {"count": 3, "avg_speed_kmh": 22.1, "avg_headway_sec": 3.5},
    "right_turn":  {"count": 2, "avg_speed_kmh": 25.0, "avg_headway_sec": null},
    "u_turn":      {"count": 0, "avg_speed_kmh": 0,    "avg_headway_sec": null},
    "unknown":     {"count": 1}
  },
  "queue_count": 2,
  "avg_speed_kmh": 26.5,
  "lane_stats": null,
  "conflict_count": 0,
  "drone_position": {
    "anchor_lat": 31.234567,
    "anchor_lon": 121.456789,
    "easting_m": 15.3,
    "northing_m": -8.2
  },
  "is_hovering": false
}
```

#### 完成轨迹 `track_complete_{N}`（事件驱动）

```json
{
  "msg_type": "track_complete",
  "intersection_id": "INT_camera_1",
  "track_id": 142,
  "start_road": 1, "exit_road": 3,
  "turn_behavior": "left_turn",
  "vehicle_class": "motor",
  "duration_sec": 8.4,
  "avg_speed_kmh": 22.3, "max_speed_kmh": 35.1,
  "trajectory_px": [[100,200], [105,210], ...],
  "trajectory_world_m": [[12.3,-5.2], [12.8,-4.9], ...],
  "world_anchor_lat_lon": [31.234567, 121.456789]
}
```

#### 冲突事件 `conflicts_{N}`（事件驱动）

```json
{
  "msg_type": "conflict",
  "intersection_id": "INT_camera_1",
  "motor_id": 142, "non_motor_id": 156,
  "distance_m": 2.3, "ttc_sec": 1.5,
  "severity": "warning",
  "motor_speed_kmh": 25.0,
  "motor_position_m": [12.3, -5.2],
  "non_motor_position_m": [12.8, -4.9]
}
```

### 4.3 存储架构

| 存储引擎 | 用途 | 数据特征 | 保留策略 |
|----------|------|----------|----------|
| **InfluxDB 1.8** | 时序统计 | 1Hz 写入，按时间查询 | 30天自动删除 |
| **InfluxDB** (track_events) | 轨迹事件 | 不规则事件写入 | 90天 |
| **InfluxDB** (conflict_events) | 冲突事件 | 稀疏事件写入 | 365天 |
| **PostgreSQL** | 结构化业务数据 | 用户/路口/告警/任务 | 永久 |
| **drone_store** (内存) | 无人机实时状态 | Kafka双源更新 | 会话级 |

### 4.4 世界坐标体系

所有世界坐标使用 **东北天(ENU)** 坐标系：

```
原点: 世界锚点 GPS 位置（首10帧均值）
+X: 东向 (easting_m)
+Y: 北向 (northing_m)
单位: 米

GPS还原公式:
  lat = anchor_lat + northing_m / 111320
  lon = anchor_lon + easting_m / (111320 × cos(radians(anchor_lat)))
```

---

## 5. 平台与前端设计

### 5.1 平台架构（单体 FastAPI）

```
┌─────────────────────────────────────────────────────────────┐
│                  FastAPI + Uvicorn (:8000)                   │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │                JWT 认证中间件                           │  │
│  │    公开端点: /health, /ready, /auth/*, /docs           │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  43 条 REST API 路由                                        │
│  ├── /api/v1/auth          — 认证（注册/登录/当前用户）      │
│  ├── /api/v1/intersections — 路口管理（CRUD + 统计）        │
│  ├── /api/v1/drones        — 无人机管理（状态 + 遥测）       │
│  ├── /api/v1/pipelines     — 管道生命周期（启动/停止/监控）  │
│  ├── /api/v1/trajectories  — 轨迹查询（InfluxDB）           │
│  ├── /api/v1/alerts        — 告警管理（规则 + 历史）         │
│  ├── /api/v1/video         — 视频流管理                      │
│  └── /api/v1/system        — 系统监控（健康/GPU/Kafka）      │
│                                                             │
│  WebSocket /ws/{channel}                                    │
│  ├── intersection:{id} — 实时统计+轨迹+冲突                  │
│  ├── alerts            — 系统告警                            │
│  ├── telemetry:{id}    — 无人机遥测                          │
│  └── system            — 系统指标                            │
│                                                             │
│  核心服务                                                    │
│  ├── PipelineManager — 子进程管理（python main_optimized.py）│
│  ├── AlertEngine     — 规则引擎（冲突/超速/拥堵/排队）       │
│  └── KafkaConsumer   — aiokafka 消费 + WebSocket 广播        │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 PipelineManager 设计

```python
class PipelineManager:
    """检测管道生命周期管理器"""

    async def start_pipeline(drone_id, intersection_id, video_src, roads_json):
        """
        1. 分配 camera_id 和 topic_name
        2. 启动子进程: python main_optimized.py
           环境变量: VIDEO_SRC, ROADS_JSON, TOPIC_NAME, CAMERA_ID
        3. 后台健康监控（每5s检查进程状态）
        返回: pipeline_id, status
        """

    async def stop_pipeline(pipeline_id):
        """
        1. SIGTERM → 等待10s优雅退出
        2. 超时 → SIGKILL 强制终止
        3. 清理资源
        """

    async def get_status(pipeline_id):
        """返回: running/stopped/error + uptime + FPS"""
```

### 5.3 告警引擎

| 告警类型 | 严重级别 | 触发条件 | 动作 |
|----------|----------|----------|------|
| `motor_non_motor_conflict` | P1 | TTC < 1.0s | 即时推送 + 声音告警 |
| `motor_non_motor_conflict` | P2 | TTC < 2.0s | WebSocket推送 |
| `high_avg_speed` | P3 | avg_speed > 60km/h | 记录 |
| `multiple_conflicts` | P2 | conflict_count > 3/min | 推送 |
| `queue_overflow` | P2 | queue_length > threshold | 推送 |
| `congestion` | P2 | congestion_index > threshold | 推送 |

### 5.4 前端页面结构

```
traffic-fly-console/ (React + Vite + TypeScript + Tailwind)
├── Dashboard     — 系统总览（路口统计 + 告警 + 管道状态）
├── Monitoring    — 实时监控（视频流 + 实时指标 + WebSocket）
├── Drones        — 无人机管理（状态 + 遥测 + GIS轨迹）
├── Intersections — 路口管理（配置 + 历史统计）
├── Alerts        — 告警中心（规则配置 + 历史告警）
├── Pipelines     — 管道管理（启停 + 健康状态）
└── Settings      — 系统设置（用户 + 权限）
```

**实时数据流**：
- `useWebSocket` hook 订阅 `intersection:{id}` 频道
- React Query 管理 REST API 数据缓存
- 组件根据 WebSocket 消息实时更新 UI

---

## 6. 关键技术难点与创新方案

### 6.1 难点一：无人机运动中的车辆速度估计

**挑战**：无人机自身运动（12m/s巡飞）+ 云台旋转 会严重污染像素空间的位移测量。

**创新方案**：三层补偿

```
Layer 1: GPS锚定世界坐标系
    → 消除无人机位移对轨迹坐标的影响

Layer 2: 遥测速度矢量减法
    → vehicle_speed = pixel_speed_world - drone_velocity_vector
    → 消除无人机平移速度对车速的影响

Layer 3: 云台偏航修正
    → gimbal_yaw_delta 修正方向分类
    → 消除云台旋转对运动方向的污染
```

**效果**：悬停时车速误差 <5%，巡飞时车速误差 <15%（优于无补偿的 ±43km/h）。

### 6.2 难点二：零标注条件下的方向流量统计

**挑战**：无人机巡飞场景无法预先标注车道多边形和停车线。

**创新方案**：轨迹运动学方向分类

- **核心洞察**：车辆行驶方向可通过轨迹首尾向量的夹角自动判定，无需空间标注
- **DirectionFlowNode** 始终运行，零配置即可输出 left/straight/right/u_turn 流量
- **LaneAnalysisNode** 数据驱动：有标注自动叠加车道级指标，无标注优雅降级

| 场景 | 方向流量 | 车道级指标 | 标注需求 |
|------|----------|------------|----------|
| 无人机巡飞 | ✅ | ❌ | 无 |
| 悬停+有标注 | ✅ | ✅ | 车道多边形 |
| 固定摄像头 | ✅ | ✅ | 参考点+车道多边形 |

### 6.3 难点三：多源遥测数据的帧级同步

**挑战**：视频帧（30fps）和遥测数据（5-10Hz）来自不同时钟源，需要精确同步。

**三种遥测源适配**：

| 源 | 格式 | 同步方式 | 精度 | 场景 |
|------|------|----------|------|------|
| **SRT字幕** | DJI视频字幕 | 逐帧1:1对应 | 帧级精确 | 离线回放 |
| **MQTT实时** | DJI Cloud API | 时间戳最近匹配(±50ms) | ~50ms | 生产直播 |
| **JSON文件** | DJI Cloud API导出 | 手动偏移+最近匹配 | ~200ms | 离线回放 |

**统一接口**：三种源均实现 `get_nearest(timestamp) -> dict`，VideoReader 透明切换。

### 6.4 难点四：FrameElement 共享数据载体

**设计决策**：所有节点通过读写同一个 `FrameElement` 对象协作。

```python
class FrameElement:
    # 基础层（VideoReader注入）
    frame: np.ndarray          # 原始BGR帧
    timestamp: float           # 帧时间戳
    roads_info: dict           # 道路多边形

    # 检测层（DetectionTrackingNodes注入）
    detected_xyxy: list        # YOLO检测框
    tracked_xyxy: list         # ByteTrack跟踪框
    id_list: list              # 跟踪ID列表

    # 标定层（HomographyCalibrationNode注入）
    homography_matrix: np.ndarray  # 单应性矩阵
    calibration_mode: str          # "telemetry" | "reference_points"

    # 运动补偿层（MotionCompensationNode注入）
    drone_displacement_m: tuple    # (east_m, north_m)
    drone_velocity_ms: tuple       # (east_ms, north_ms)
    is_hovering: bool

    # 分析层（多个节点逐步注入）
    direction_stats: dict       # 方向流量
    lane_stats: dict           # 车道级统计
    conflict_events: list      # 冲突事件
    completed_tracks: list     # 完成轨迹

    # 输出层（ShowNode注入）
    frame_result: np.ndarray   # 渲染后的帧
```

**优势**：避免数据拷贝，线性管道简洁高效。  
**代价**：字段膨胀，新节点需理解上游字段（通过文档和类型标注缓解）。

### 6.5 难点五：多摄像头水平扩展

**架构支持**：

```
docker-compose.yaml:
  traffic_analyzer_camera_1:  VIDEO_SRC=rtsp://... ROADS_JSON=configs/inter1.json
  traffic_analyzer_camera_2:  VIDEO_SRC=rtsp://... ROADS_JSON=configs/inter2.json
  ...
  traffic_analyzer_camera_N:  VIDEO_SRC=rtsp://... ROADS_JSON=configs/interN.json

每个摄像头独立:
  - YOLO推理实例（独立GPU显存分配）
  - Kafka topic（statistics_N, track_complete_N, conflicts_N）
  - Grafana仪表盘（camera_N measurement）
  - Nginx路由（/camera_N → Flask:8100）
```

**瓶颈**：GPU 显存。每个 YOLO11 实例约需 2GB 显存（640×640 推理），4卡 GPU 可支撑 4 路并发。

**扩展方案**：Triton Inference Server（已在 `feature/triton` 分支实现），将推理集中到单一服务，后端容器仅需 CPU。

---

## 7. 实施路径与里程碑规划

### 7.1 已完成阶段（基线）

```
✅ Phase 0: 基础架构（已完成）
   ├── YOLO11 车辆检测 + ByteTrack 跟踪
   ├── 5道路统计 + Kafka + InfluxDB + Grafana
   ├── Docker Compose 全栈部署
   ├── 多摄像头水平扩展
   └── FastAPI 管理平台（单体架构）

✅ Phase 1: 交通态势感知（已完成）
   ├── 遥测驱动单应性标定（HomographyCalibrationNode）
   ├── 无人机运动补偿（MotionCompensationNode）
   ├── 车速估计（SpeedEstimationNode）
   ├── 方向流量统计（DirectionFlowNode）
   ├── 车道级分析（LaneAnalysisNode，数据驱动）
   ├── 轨迹还原（TrajectoryNode）
   ├── 冲突检测（ConflictDetectionNode，默认启用）
   ├── SRT遥测解析（逐帧精确同步）
   └── 端到端测试（2026-07-02: 56 PASS / 0 FAIL / 0 WARN）

✅ Phase 2: 平台整合（已完成）
   ├── Kafka topic pattern 扩展（4类消息）
   ├── PipelineManager（管道生命周期管理）
   ├── drone_store 实时更新（stats + telemetry 双源）
   ├── WebSocket 实时推送（4个频道）
   ├── docker-compose 统一（平台服务加入主 compose）
   └── 前端实时数据验证
```

### 7.2 近期里程碑（1-2 周）

```
🎯 Milestone A: 生产就绪
   ├── [ ] Kafka 基础设施稳定性修复（清除 stale data）
   ├── [ ] MJPEG 视频流端到端验证（管道 → Flask → Nginx → 前端）
   ├── [ ] 前端 Drones 页面对接 telemetry WebSocket
   ├── [ ] Mission-Pipeline 绑定（创建任务 → 自动启动管道）
   ├── [ ] 道路多边形精确标注（inter_xqh 视频）
   └── [ ] TD-005/008/009 技术债修复

验收标准:
   - 平台可启动管道 → 实时显示视频流 + 统计指标
   - 无人机遥测实时更新 → 地图显示位置
   - 56 PASS / 0 FAIL / 0 WARN 管道测试 PASS
```

### 7.3 中期里程碑（1-2 月）

```
🎯 Milestone B: 功能完善
   ├── [ ] 模型微调：uav_best.pt 新增 person + bicycle 类别
   ├── [ ] 冲突检测启用（ConflictDetectionNode.enabled = true）
   ├── [ ] GIS 轨迹回放（基于 track_complete 消息 + 世界坐标）
   ├── [ ] 道路数量动态化（解决 TD-001，移除硬编码 5）
   ├── [ ] 管道健康监控面板（进程状态 + 日志流 + FPS 曲线）
   ├── [ ] 告警规则完善（冲突/超速/排队联动）
   └── [ ] InfluxDB 2.x 评估与迁移

验收标准:
   - 冲突检测准确率 > 80%（标注验证集）
   - 动态道路数支持（2-8条）
   - GIS 地图可回放完整轨迹
```

### 7.4 远期里程碑（3-6 月）

```
🎯 Milestone C: 智能化升级
   ├── [ ] VLM 语义分析旁路（自然语言交通态势描述）
   ├── [ ] 多无人机协同巡检（任务调度 + 区域覆盖优化）
   ├── [ ] 交通信号联动（与信号控制系统对接）
   ├── [ ] 巡检报告自动生成（PDF/HTML）
   ├── [ ] 历史数据交通规划分析（OD矩阵 + 拥堵热点）
   └── [ ] 边缘部署优化（TensorRT + 嵌入式GPU）
```

### 7.5 依赖关系图

```
                    ┌─────────────────┐
                    │  Phase 0: 基础   │ ✅
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  Phase 1: 态势   │ ✅
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  Phase 2: 平台   │ ✅
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
     ┌────────▼─────┐ ┌─────▼──────┐ ┌────▼────────┐
     │ A: 生产就绪   │ │ B: 功能完善│ │ C: 智能化   │
     │ (1-2周)      │ │ (1-2月)   │ │ (3-6月)    │
     └──────────────┘ └────────────┘ └─────────────┘
              │              │
              │    ┌─────────▼─────────┐
              │    │ 模型微调(person)  │
              │    │ → 冲突检测启用    │
              │    └───────────────────┘
              │
     ┌────────▼─────────┐
     │ Kafka修复 + 视频  │
     │ 流验证 + 遥测对接 │
     └──────────────────┘
```

---

## 8. 技术风险与应对策略

### 8.1 风险矩阵

| # | 风险 | 概率 | 影响 | 等级 | 应对策略 |
|---|------|------|------|------|----------|
| R1 | YOLO 模型在复杂天气下精度下降 | 高 | 中 | 🔴 | 数据增强 + 多模型融合 + 在线学习 |
| R2 | GPS 信号丢失导致坐标漂移 | 中 | 高 | 🔴 | 帧间速度积分兜底 + GPS恢复重锚定 |
| R3 | Kafka 基础设施不稳定 | 中 | 高 | 🟡 | 有限重试 + 降级模式 + 本地缓存 |
| R4 | 无人机续航限制（25min） | 高 | 中 | 🟡 | 多机接力 + 关键时段部署 |
| R5 | 多路并发 GPU 显存不足 | 中 | 中 | 🟡 | Triton集中推理 + 动态批处理 |
| R6 | ByteTrack 长时间遮挡丢 ID | 中 | 低 | 🟢 | 外观特征辅助 + 短轨迹合并 |

### 8.2 关键风险详细应对

#### R1: 检测模型鲁棒性

```
正常天气: mAP > 85% → 直接使用
雨雾天气: mAP 降至 60-70% → 触发降级策略:
  1. 提高置信度阈值至 0.3（减少误检）
  2. 增大 track_buffer 至 200（补偿漏检导致的轨迹断裂）
  3. 在 Kafka 消息中标注 quality="degraded"
  4. 告警引擎降低灵敏度（避免误报）

夜间场景: 需近红外/热成像相机 → 二期扩展
```

#### R2: GPS 丢失处理

```
GPS可用: 使用 GPS 增量计算 drone_displacement（精确）
GPS丢失: 切换为遥测速度积分（累积误差 ~0.5m/s²）
GPS恢复: 平滑过渡回 GPS 锚定（EMA 滤波，α=0.3）

悬停检测: |velocity| < 1.0m/s → 跳过运动补偿（避免噪声）
```

---

## 9. 演进路线与远期展望

### 9.1 技术演进路线

```
当前（v1.0）                    近期（v1.5）                   远期（v2.0）
─────────────                   ────────────                  ────────────
YOLO11 单模型检测        →      多模型融合 + 在线学习    →    VLM 语义理解
ByteTrack IoU跟踪        →      DeepSORT + 外观特征      →    多相机Re-ID
单应性矩阵(2D)           →      3D 场景重建              →    NeRF 场景建模
规则型告警引擎           →      ML 异常检测              →    预测性告警
手工方向分类             →      图神经网络轨迹分类        →    端到端行为预测
InfluxDB 1.8             →      InfluxDB 2.x             →    数据湖（Parquet）
单体 FastAPI             →      微服务拆分(如需)          →    Serverless
Docker Compose           →      K8s 编排                 →    边缘-云协同
```

### 9.2 业务演进路线

```
当前: 单路口实时监控
  → 多路口协同感知
  → 区域交通态势大脑
  → 城市级交通数字孪生

当前: 人工巡检触发
  → 定时自动巡检
  → 事件驱动智能调度
  → 与交通管控中心联动
```

### 9.3 核心竞争壁垒

| 壁垒 | 说明 |
|------|------|
| **无人机+AI 融合** | 业内少有将无人机感知与实时交通分析深度融合的方案 |
| **零标注方向分类** | 无需地面标定和车道标注即可输出方向流量，部署成本极低 |
| **运动补偿算法** | GPS锚定+遥测速度+云台修正三层补偿，巡飞中精确测速 |
| **端到端闭环** | 从数据采集→边缘分析→平台管理→前端展示全链路打通 |
| **开源基础设施** | 基于 Kafka/InfluxDB/Grafana 成熟生态，降低运维成本 |

---

## 附录 A：技术栈总览

| 层级 | 技术 | 版本 | 用途 |
|------|------|------|------|
| **检测模型** | YOLO11 (ultralytics) | latest | 车辆检测 |
| **跟踪算法** | ByteTrack | 自实现 | 多目标跟踪 |
| **深度学习** | PyTorch | 2.3.1 | 推理框架 |
| **视频处理** | OpenCV | 4.x | 帧读取/渲染/编码 |
| **配置管理** | Hydra | latest | 分层配置 |
| **消息队列** | Apache Kafka | 3.x | 异步消息传递 |
| **时序数据库** | InfluxDB | 1.8 | 时序数据存储 |
| **数据管道** | Telegraf | latest | Kafka→InfluxDB |
| **可视化** | Grafana | latest | 实时仪表盘 |
| **Web框架** | FastAPI + Uvicorn | latest | REST API + WebSocket |
| **关系数据库** | PostgreSQL | 15 | 结构化业务数据 |
| **ORM** | SQLAlchemy (async) | 2.x | 数据库访问 |
| **认证** | PyJWT + bcrypt | latest | JWT 认证 |
| **Kafka客户端** | aiokafka | latest | 异步消费者 |
| **前端框架** | React + Vite + TypeScript | latest | SPA 应用 |
| **UI组件** | Tailwind CSS + Shadcn | latest | 组件库 |
| **容器编排** | Docker Compose | v2 | 服务编排 |
| **反向代理** | Nginx | latest | 视频流聚合 |
| **数学计算** | NumPy + Shapely | latest | 矩阵运算/几何计算 |

## 附录 B：关键文件索引

| 文件 | 说明 |
|------|------|
| `main_optimized.py` | 唯一生产入口（三进程并行管道） |
| `nodes/DetectionTrackingNodes.py` | YOLO11 + ByteTrack |
| `nodes/HomographyCalibrationNode.py` | 遥测驱动单应性标定 |
| `nodes/MotionCompensationNode.py` | 无人机运动补偿 |
| `nodes/SpeedEstimationNode.py` | 车速估计（减去无人机速度） |
| `nodes/DirectionFlowNode.py` | 方向流量分类（零标注） |
| `nodes/LaneAnalysisNode.py` | 车道级分析（数据驱动） |
| `nodes/TrajectoryNode.py` | 轨迹还原 + 世界坐标输出 |
| `nodes/ConflictDetectionNode.py` | 机非冲突 TTC 检测 |
| `utils_local/homography.py` | 单应性矩阵计算（双模式） |
| `utils_local/motion_compensation.py` | GPS→ENU + 速度矢量 |
| `utils_local/trajectory_classifier.py` | 转向行为分类 |
| `elements/FrameElement.py` | 帧数据载体 |
| `elements/TrackElement.py` | 轨迹状态 |
| `services/SrtTelemetryParser.py` | SRT遥测解析（逐帧同步） |
| `platform/app/main.py` | FastAPI 平台入口 |
| `platform/app/kafka/consumer.py` | Kafka 消费者（4类消息） |
| `platform/app/services/pipeline_manager.py` | 管道生命周期管理 |
| `configs/app_config.yaml` | Hydra 主配置 |

## 附录 C：测试矩阵

| 测试类型 | 脚本 | 覆盖范围 | 状态 |
|----------|------|----------|------|
| 管道E2E（含YOLO） | `test_pipeline_inter_xqh.py` | 56项检查 | ✅ 56 PASS / 0 FAIL / 0 WARN |
| 管道E2E（无YOLO） | `test_pipeline_no_yolo.py` | CI无GPU场景 | ✅ PASS |
| 平台集成 | `test_e2e_inter_xqh.py` | API + WebSocket | ✅ PASS |
| MPS流媒体 | `test_e2e_mps_streaming.py` | Apple Silicon | ✅ PASS |
| 实时API | `test_live_api.py` | 平台REST API | ✅ PASS |

---

> **文档结束**  
> 本方案基于 TrafficAnalyzer feature/influx 分支的真实代码分析，覆盖系统架构、核心算法、数据架构、平台设计和实施路径。  
> 方案追求**业务高度**（从行业痛点到价值主张）、**技术深度**（从数学推导到工程实现）、**思考全面性**（从已完成到远期演进）、**技术前沿**（无人机+AI融合、零标注方向分类、运动补偿）。

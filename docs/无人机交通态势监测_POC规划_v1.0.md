# 无人机路口交通态势监测 — POC 完整规划

> 基础项目：[Koldim2001/TrafficAnalyzer](https://github.com/Koldim2001/TrafficAnalyzer)  
> 检测主链：YOLO11 + ByteTrack　|　语义旁路：Qwen-VL 7B（异步）  
> 数据栈：Kafka → Telegraf → InfluxDB → Grafana  
> 已有飞行数据：小清河北路×水屯路（2026-04-03）、堤口路×胜利庄北路（2026-05-20）  
> 文档版本：v1.0 | 综合两轮规划评审

---

## 目录

1. [项目背景与目标](#1-项目背景与目标)
2. [现有资产评估](#2-现有资产评估)
3. [整体三层架构](#3-整体三层架构)
4. [数据模型扩展](#4-数据模型扩展)
5. [核心新增模块](#5-核心新增模块)
   - 5.1 [标定参数库（CalibDB）](#51-标定参数库calibdb)
   - 5.2 [标注工具（Annotation UI）](#52-标注工具annotation-ui)
   - 5.3 [IPM 透视变换节点](#53-ipm-透视变换节点)
   - 5.4 [EIS 画面稳定节点](#54-eis-画面稳定节点)
   - 5.5 [Qwen-VL 语义旁路](#55-qwen-vl-语义旁路)
6. [现有模块改造清单](#6-现有模块改造清单)
7. [POC 功能优先级](#7-poc-功能优先级)
8. [双受众演示策略](#8-双受众演示策略)
9. [已有飞行数据使用规划](#9-已有飞行数据使用规划)
10. [关键参数速查](#10-关键参数速查)
11. [三期交付路线图](#11-三期交付路线图)
12. [风险与应对](#12-风险与应对)
13. [待确认事项](#13-待确认事项)

---

## 1 项目背景与目标

### 1.1 核心价值主张

| 价值点 | 说明 |
|---|---|
| 无死角机动覆盖 | 无人机 5 分钟抵达任意路口，固定摄像头盲区即时接管 |
| 数据即证据 | 流量 / 排队 / 拥堵指数全程时序留存，支持信号配时优化与执法举证 |
| 秒级异常告警 | 事故 / 逆行 / 异常停车 AI 识别，比人工巡查响应提速 3~5 分钟 |
| 全天候检测 | 热成像 + 可见光双通道融合，夜间 / 大雾场景继续工作 |

### 1.2 第一客户：总集 CTO（技术决策）

关注点：系统可扩展性、工程实现质量、集成能力、精度指标、降级策略。  
**演示核心**：标定工具现场操作 + 架构图 + 精度数字 + API 接口草稿。

### 1.3 第二客户：交警/交管部门（业务决策）

关注点：大屏数字实时跳动、告警推到手机、自动报告 PDF、操作门槛低。  
**演示核心**：Grafana 大屏 + 手机震动告警 + 早高峰分析报告。

---

## 2 现有资产评估

### 2.1 TrafficAnalyzer 可直接复用（免改写）

| 模块 | 文件 | 状态 |
|---|---|---|
| RTSP 流输入 | `nodes/VideoReader.py` | `"://"` 判断已兼容无人机图传 |
| 多进程流式管道 | `main_optimized.py` | 直接复用（已整合旧 stream 变体） |
| 检测→追踪链路 | `DetectionTrackingNode` | 调参即用 |
| 统计计算节点 | `CalcStatisticsNode` | 扩展字段即用 |
| 数据推送栈 | Kafka + Telegraf + InfluxDB + Grafana | 直接复用 |

**关键瓶颈**（必须修复，否则所有指标系统性偏差）：

1. `configs/entry_exit_lanes.json` 写死固定机位像素坐标，无人机换高度/角度即失效
2. `utils_local/utils.py::intersects_central_point()` 用 bbox 几何中心做像素域 point-in-polygon，透视畸变下远端误判率 >15%

### 2.2 已有飞行数据

| 数据集 | 时间 | 时长 | 质量 | 用途 |
|---|---|---|---|---|
| 小清河北路×水屯路 | 2026-04-03 14:27~14:48 | 20 min | ✅ 优（RTK 固定解、云台 −90°、悬停 453 帧） | 主力：标定 + 检测演示 + 车道分析 |
| 堤口路×胜利庄北路 | 2026-05-20 07:29~07:37 | 8 min | ⚠️ 受限（超限高 +27.8m、超区预警、悬停仅 16 帧） | 热成像演示 + 视频画面（SRT 不对客户展示） |

**小清河路口标定参数（可直接写入 calibration_db.json）**：

```json
{
  "intersection_id": "INT_小清河水屯",
  "altitude_agl": 163.4,
  "gimbal_pitch": -90.0,
  "gimbal_roll": 0.0,
  "center_lat": 36.7029103,
  "center_lon": 117.0222766,
  "gps_type": "RTK_FIXED",
  "hover_frames": 453,
  "calib_key": "INT_小清河水屯__H164__P-90"
}
```

---

## 3 整体三层架构

```
┌──────────────────────────────────────────────────────────────┐
│  任务规划层 (Mission Planner)                                  │
│  mission.json → intersection_id / 航点 / 悬停参数 / 云台角     │
└───────────────────────────┬──────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────┐
│  飞行控制层 (Flight Controller)                                │
│  GPS+气压计定高(P-GPS) │ 三轴云台机械防抖 │ 姿态实时回传(SRT)  │
└───────────────────────────┬──────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────┐
│  标定匹配层 (Calibration Engine)          ← 核心新增           │
│  SRT姿态查表 → H_mat → IPM → BEV 车道多边形 → ROI 判定        │
│  标注工具 Web UI → calibration_db.json CRUD                   │
└───────────────────────────┬──────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────┐
│  现有 TrafficAnalyzer 管道（最小化改动）                        │
│  VideoReader → EIS → IPM → Detection → Tracking → Stats → …  │
└──────────────────────────────────────────────────────────────┘
```

### 3.1 完整数据流

```
无人机 RTSP 流 + SRT 元数据（intersection_id / alt_agl / gimbal_pitch / GPS）
    │
    ▼
[新] EISNode              ← ORB 特征点匹配 → 帧间仿射变换 → 滑窗平滑
    │
    ▼
[新] CalibrationEngine    ← 查 calibration_db → H_mat + lane_polygons_bev
    │                        三级命中：精确 → 插值 → 重标定告警
    ▼
VideoReader（已有，ROI 坐标系迁移至 BEV）
    │
    ├─────────────────────────────────── 每 N 帧（旁路）─────────────┐
    ▼（每帧，主链路）                                               ▼
DetectionTrackingNode                                   [新] VLMBypassNode
YOLO11 → ByteTrack → BBox + track_id                   Qwen-VL 7B 异步推理
    │                                                               │
    ▼                                                               ▼
[改] TrackerInfoUpdateNode                             语义 JSON（异常/拥堵/车道）
bbox 底边中心 → H_mat → BEV → point-in-polygon                     │
    │                                                               │
    ▼                                                               │
[改] CalcStatisticsNode ←────────── 时间戳对齐合并 ────────────────┘
    │
    ▼
Kafka  topic: drone_{drone_id}_intersection_{id}
    │
    ▼
Telegraf → InfluxDB → Grafana 大屏 / 告警 / PDF 报告
```

### 3.2 双 GPU 部署方案

```
GPU A：YOLO11 + ByteTrack（主链路，~15ms/帧，实时不间断）
GPU B：Qwen-VL 7B（旁路，2~8s/帧，异步，崩溃不影响主链路）
```

单卡降级：旁路改为每 120 帧 + 时间片调度，延迟约 30s，适合事后分析而非实时告警。

---

## 4 数据模型扩展

### 4.1 新建 `elements/DroneTelemetry.py`

```python
from dataclasses import dataclass

@dataclass
class DroneTelemetry:
    """从 DJI SRT 文件或 SDK 实时注入的逐帧遥测数据"""
    intersection_id: str
    lat: float
    lon: float
    alt_agl: float           # 相对地面高度（米）
    gimbal_pitch: float      # 云台俯仰角（°，向下为负，正射为 -90）
    gimbal_roll: float
    gimbal_yaw: float
    drone_pitch: float       # 机身姿态
    drone_roll: float
    drone_yaw: float
    timestamp: float
    wind_speed: float = 0.0  # m/s
    battery_pct: int = 100

    def calib_key(self) -> str:
        """生成标定参数库查询键：高度 2m 分档，俯仰角 2° 分档"""
        h = int(self.alt_agl / 2) * 2
        p = int((self.gimbal_pitch + 90) / 2) * 2 - 90
        return f"{self.intersection_id}__H{h}__P{p}"
```

### 4.2 扩展 `elements/FrameElement.py`

新增字段（在 `__init__` 末尾追加）：

```python
self.drone_telemetry: DroneTelemetry | None = None
self.H_mat: np.ndarray | None = None          # 当前生效的 3×3 单应矩阵
self.lane_polygons_bev: dict | None = None     # BEV 世界坐标下的车道多边形（米）
self.calib_quality: str = "ok"                 # ok / interpolated / degraded / missing
self.lane_match_rate: float = 1.0              # 当前帧车道匹配率
```

### 4.3 扩展 `elements/TrackElement.py`

```python
self.bev_x: float | None = None        # BEV 世界坐标 X（米）
self.bev_y: float | None = None        # BEV 世界坐标 Y（米）
self.start_road_bev: int | None = None # BEV 判定的车道 ID（替代原像素域判定）
```

---

## 5 核心新增模块

### 5.1 标定参数库（CalibDB）

#### 5.1.1 `configs/calibration_db.json` 结构

```json
{
  "calibration_db": {
    "INT_小清河水屯": {
      "H_164__P-90": {
        "H_mat": [[...], [...], [...]],
        "altitude_agl": 163.4,
        "gimbal_pitch": -90.0,
        "output_size": [1280, 720],
        "pixel_scale": 0.05,
        "lane_polygons_bev": {
          "1": [[0.0,0.0],[3.5,0.0],[3.5,50.0],[0.0,50.0]],
          "2": [[3.5,0.0],[7.0,0.0],[7.0,50.0],[3.5,50.0]],
          "3": [[-3.5,0.0],[0.0,0.0],[0.0,50.0],[-3.5,50.0]],
          "4": [[-7.0,0.0],[-3.5,0.0],[-3.5,50.0],[-7.0,50.0]],
          "5": [[7.0,0.0],[10.5,0.0],[10.5,50.0],[7.0,50.0]]
        },
        "calibrated_at": "2026-04-03T14:29:00Z",
        "calibrated_by": "interactive",
        "source_flight": "小清河北路水屯路路口交通数据收集航线快速计划20260403"
      }
    }
  }
}
```

#### 5.1.2 查表三级命中策略

```
输入: intersection_id + alt_agl + gimbal_pitch
     ↓
精确命中？→ 直接加载（calib_quality = "ok"）
     ↓ 否
偏差 ≤ ±4m / ±4°？→ 距离加权插值（calib_quality = "interpolated"）
     ↓ 否
超出范围 → 返回 None，触发重标定告警（calib_quality = "missing"）
```

**键设计**：`key = f"{intersection_id}__H{int(alt/2)*2}__P{int((pitch+90)/2)*2-90}"`

#### 5.1.3 重标定自动触发条件（三选一即触发）

| 指标 | 阈值 | 说明 |
|---|---|---|
| 云台俯仰偏差 | > 3° | 相对上次标定时的俯仰角 |
| 高度变化 | > 2m | 相对上次标定时的 AGL |
| 车道匹配率 | < 80% | 落在任意车道多边形内的检测框比例 |

#### 5.1.4 降级应急策略（四步）

```python
# 1. 暂停该机位统计数据写入 Kafka / InfluxDB
frame_element.calib_quality = "degraded"

# 2. Grafana 面板标灰（通过 InfluxDB tag 实现）
kafka_msg["calib_quality"] = "degraded"

# 3. 尝试自动重标定（车道线检测 + 先验车道宽度约束）
try_auto_recalibrate(frame_element)

# 4. 自动标定失败 → 等无人机回到预设航点后重新加载标定参数
if auto_calib_failed:
    send_return_to_waypoint_command()
```

---

### 5.2 标注工具（Annotation UI）

> **CTO 演示重点**：证明系统有自适应新路口的完整闭环，新路口标定 5 分钟完成。

#### 5.2.1 三个子功能

**子功能 1：透视标定工具（Homography Calibrator）**
- 在原始无人机视频帧上，鼠标依次点击 4 个路面基准点（斑马线角点 / 停车线端点）
- 实时渲染右侧鸟瞰图预览，确认后写入 `calibration_db.json`
- 技术栈：Flask / Streamlit + `cv2.findHomography(RANSAC)`

**子功能 2：车道多边形标注（Lane Polygon Editor）**
- 在 **BEV 坐标系** 下绘制各车道多边形（世界坐标 / 米）
- 支持拖拽调节顶点、命名车道、设置进出方向属性
- 保存为 `lane_polygons_bev` 写入标定库
- 技术栈：Fabric.js / Konva.js

**子功能 3：标定参数管理面板（Calibration DB Manager）**
- 展示所有路口标定条目（intersection_id / 高度 / 俯仰角 / 标定时间 / 来源 / 质量）
- 插值覆盖率热图：直观显示当前参数库对高度×俯仰角空间的覆盖情况
- 支持查询 / 更新 / 删除

#### 5.2.2 标注工具使用流程

```
1. 上传视频帧（或从回放中截帧）
2. 从 SRT 元数据自动填充 alt_agl / gimbal_pitch / intersection_id
3. 点选 4 个地面基准点 → 自动计算 H_mat → 即时预览 BEV
4. 在 BEV 上绘制车道多边形（从路口先验 CAD 图导入或手动绘制）
5. 确认 → 写入 calibration_db.json → 触发管道热更新
```

---

### 5.3 IPM 透视变换节点

**文件**：`nodes/IPMNode.py`（新建）

**核心职责**：
- 从 `CalibrationEngine` 查表获取 `H_mat` 和 `lane_polygons_bev`
- 调用 `cv2.warpPerspective` 将原始帧转换为鸟瞰图
- 回写 `frame_element.H_mat` 和 `frame_element.lane_polygons_bev`
- 检测姿态突变，触发重标定告警

**`utils_local/utils.py` 新增两个函数**（替代原 `intersects_central_point`）：

```python
def ipm_transform(bbox: list, H_mat: np.ndarray) -> tuple[float, float]:
    """
    将 YOLO bbox 底边中心点变换到 BEV 世界坐标。
    用底边中心而非 bbox 中心的原因：
      底边中心更接近车辆地面接地投影点，透视变换误差更小。
    """
    x1, y1, x2, y2 = bbox
    u, v = (x1 + x2) / 2.0, float(y2)          # 底边中心点
    src = np.array([u, v, 1.0])
    dst = H_mat @ src
    return float(dst[0] / dst[2]), float(dst[1] / dst[2])

def intersects_central_point_bev(bev_x, bev_y, lane_polygons_bev) -> int | None:
    """在 BEV 世界坐标系下判定车辆所属车道（替代像素域判定）"""
    from shapely.geometry import Point, Polygon
    pt = Point(bev_x, bev_y)
    for lane_id, coords in lane_polygons_bev.items():
        if Polygon(coords).contains(pt):
            return int(lane_id)
    return None
```

---

### 5.4 EIS 画面稳定节点

**文件**：`nodes/EISNode.py`（新建）  
**插入位置**：`VideoReader.process()` 读帧后第一步

**原理**：ORB 特征点匹配 → 估计帧间仿射变换（平移+旋转，不含缩放）→ 滑动窗口平均平滑

**硬件优先**：三轴云台机械防抖为主，EIS 软件层作兜底补偿。

**参数建议**：
- `smooth_window = 30`（帧数）：越大越稳，延迟越高
- `max_features = 500`：ORB 特征点数量

> 注意：小清河路口飞行数据中，机身 roll 最大偏达 −19.3°（6 级阵风），  
> 超出 EIS 常规补偿范围（±10°）。云台已成功补偿到 −90°，但建议下次飞行选风速 <6m/s 窗口期。

---

### 5.5 Qwen-VL 语义旁路

**文件**：`nodes/VLMBypassNode.py`（新建）

**架构定位**：

| 维度 | YOLO11 主链路 | Qwen-VL 旁路 |
|---|---|---|
| 触发频率 | 每帧（~15ms） | 每 45 帧（异步，2~8s） |
| GPU | GPU A | GPU B（14~18GB VRAM） |
| 输出 | BBox + track_id | 语义 JSON |
| 崩溃影响 | 主链路停止 | 语义事件暂停，流量统计照常 |

**Prompt 模板（JSON 输出，禁止输出其他内容）**：

```
这是一张无人机俯拍路口图。以 JSON 回答：
{
  "accident": false,           // 是否存在疑似交通事故或异常停车
  "congestion_level": 0,       // 0=畅通 1=轻度 2=中度 3=严重
  "visible_lanes": 4,          // 可见清晰车道线数量（用于标定质量自检）
  "anomaly": null,             // 异常描述，无则 null
  "summary": "路口畅通"        // 一句话路况描述（中文）
}
```

**三个补充场景**（YOLO 无法处理，VLM 零样本解决）：

1. 交通异常识别（事故 / 逆行 / 违停）
2. 标定质量自检（`visible_lanes` 与配置车道数对比，触发重标定）
3. 自然语言路况报告，对接早高峰自动分析 PDF

---

## 6 现有模块改造清单

| 文件 | 操作 | 主要内容 |
|---|---|---|
| `elements/DroneTelemetry.py` | **新建** | 逐帧遥测数据类 + `calib_key()` |
| `elements/FrameElement.py` | **扩展** | 新增 4 个字段（telemetry / H_mat / lane_polygons_bev / calib_quality） |
| `elements/TrackElement.py` | **扩展** | 新增 3 个字段（bev_x / bev_y / start_road_bev） |
| `nodes/EISNode.py` | **新建** | ORB + 仿射变换 + 滑窗平滑 |
| `nodes/IPMNode.py` | **新建** | 查标定库 → warpPerspective → 重标定告警 |
| `nodes/VLMBypassNode.py` | **新建** | Qwen-VL 7B 异步推理 + 结果队列 |
| `nodes/VideoReader.py` | **改造** | 前插 EIS → IPM，解析 SRT 注入 DroneTelemetry |
| `nodes/TrackerInfoUpdateNode.py` | **改造** | 改用 `ipm_transform` + `intersects_central_point_bev` |
| `nodes/CalcStatisticsNode.py` | **扩展** | 融合 VLM 结果 + 写入 `calib_quality` tag |
| `utils_local/utils.py` | **扩展** | 新增 `ipm_transform()` / `intersects_central_point_bev()` |
| `calibration/calib_db.py` | **新建** | 标定库 CRUD + 三级查表 + 距离加权插值 |
| `calibration/calib_monitor.py` | **新建** | 三指标监控 + 四步降级策略 |
| `annotation/app.py` | **新建** | 标注工具 Web UI（Flask/Streamlit） |
| `configs/calibration_db.json` | **新建** | 标定参数存储（世界坐标车道多边形） |
| `configs/app_config_drone.yaml` | **新建** | 无人机专用参数配置 |
| `missions/INT_xxx.json` | **新建** | 每个路口的航点 + 悬停参数 |
| `deploy/start_pipelines.sh` | **新建** | 多实例启动脚本 |
| `docker-compose.drone.yml` | **新建** | 多机容器编排 |

---

## 7 POC 功能优先级

### P0 — 必须有（演示核心，第 1 个月）

| 功能 | 说明 | 关键文件 |
|---|---|---|
| 视频回放接入 | FFmpeg 将录制视频转 RTSP 流模拟实时图传，SRT 元数据同步注入 | `VideoReader.py` |
| 车辆实时检测与追踪 | YOLO11（imgsz=1280）+ ByteTrack，输出带 track_id 的检测框 | `DetectionTrackingNode` |
| IPM 透视变换 + 车道归属 | 小清河路口标定数据写入库，BEV 坐标系车道判定 | `IPMNode.py` / `calib_db.py` |
| Grafana 实时大屏 | 路口流量时序 / 各车道 evts/m / 拥堵色块 / 无人机状态 | Grafana 面板 |
| **标注工具（CTO 必看）** | Web UI 现场标定演示：5 分钟完成新路口接入 | `annotation/app.py` |

### P1 — 应该有（演示亮点，第 2 个月）

| 功能 | 说明 |
|---|---|
| 异常事件告警 | 规则层（排队超限）+ VLM 语义层，推送企业微信/钉钉 Webhook |
| 热成像双通道融合 | 堤口路 IR + RGB 双通道叠加，展示全天候检测能力 |
| 早高峰自动分析报告 | VLM 逐段分析 → PDF 导出（拥堵时段 / 异常清单 / 信号配时建议） |

### P2 — 加分项（演示完整性，第 3 个月）

| 功能 | 说明 |
|---|---|
| 多路口一张图 | GIS 底图叠加拥堵色块 + 无人机位置，对领导层视觉冲击力最强 |
| 飞行轨迹回放面板 | SRT 数据在 GIS 上回放轨迹，点击轨迹跳转对应视频帧 |
| EIS 画面稳定 | 提升强风场景下检测稳定性 |
| 精度基准评估 | 离线跑小清河数据：mAP@0.5 / 车道误判率 / 端到端延迟 |

---

## 8 双受众演示策略

### 8.1 CTO 演示（35 分钟）

```
1. 架构全貌（5 min）
   → 三层架构图 + 改造量表（绿=复用 / 黄=改造 / 红=新增）
   → 强调：80% 代码来自成熟开源项目，新增风险集中在 3 个节点

2. 标注工具现场操作（8 min）⭐ 核心亮点
   → 打开 Web UI，在小清河视频帧上现场点 4 个基准点
   → 实时渲染鸟瞰图，绘制 5 条车道多边形
   → 展示 calibration_db.json 插值覆盖率热图
   → 强调：新路口标定从 0 到完成只需 5 分钟

3. 实时检测精度（6 min）
   → 视频 + 实时推理 + 精度面板（FPS / 置信度分布 / 车道匹配率）
   → IPM 前后对比：像素域误判率 >15% vs BEV <5%（需离线评估得出）

4. 双路并联架构说明（5 min）
   → YOLO 主链路 + VLM 旁路解耦设计
   → 重点：VLM 崩溃时主链路不受影响（降级策略）

5. 扩展性演示（4 min）
   → Docker Compose 配置：再加一架无人机 = 再加一个 service block
   → Kafka topic 命名：drone_{id}_intersection_{id}
   → 10 路口 = 10 容器，共享同一套 Qwen-VL 服务

6. API 接口草稿（4 min）
   → POST /calibration/intersections  上传标定参数
   → GET  /stats/realtime?intersection_id=  实时流量
   → POST /alerts/subscribe  Webhook 告警订阅

7. 开放提问 + 路线图（3 min）
   → 预备回答：mAP 数字 / 与固定摄像头方案精度对比 / 交付里程碑
```

### 8.2 交管部门演示（25 分钟）

```
1. 开场痛点共鸣（3 min）
   → 固定摄像头盲区 vs 无人机机动覆盖
   → 堤口路早高峰 07:33 瞬时流量爆表截图（真实数据）

2. 视频接入 → 实时检测（5 min）
   → 小清河路口视频 + YOLO 实时框渲染
   → 右屏 Grafana 流量曲线随视频同步跳动
   → 关键画面：让客户看到数字在动

3. 车道级流量分离（4 min）
   → 展示 BEV 变换效果，5 条车道独立流量柱状图
   → 说明比固定摄像头更准，无透视畸变误判

4. 异常告警演示（5 min）
   → 堤口路早高峰视频，注入"逆行"事件
   → 触发告警 → Grafana 弹红色警报 → 手机收到企业微信推送
   → 关键画面：手机震动那一刻

5. 热成像全天候（3 min）
   → 堤口路热成像帧，82.1°C 车辆发动机高亮
   → 说明夜间/大雾场景适用

6. 自动报告（3 min）
   → 展示预生成早高峰分析 PDF（拥堵时段 / 异常清单 / 信号配时建议）

7. 多路口一张图收尾（2 min）
   → GIS 底图两路口拥堵色块 + 无人机图标
   → "接入全市只需增加无人机数量，代码不变"
```

> ⚠️ **注意**：交管演示中不要展示标注工具、架构图、SRT 原始遥测数据。  
> ⚠️ 堤口路飞行数据存在超限高（+27.8m）和全程超区预警，演示时只展示视频画面和热成像效果。

---

## 9 已有飞行数据使用规划

### 9.1 小清河北路×水屯路（主力数据集）

- **用途**：透视标定 / YOLO 检测演示 / 车道级分析 / 精度基准评估
- **标定参数**：AGL 163.4m / 云台 −90° / RTK 固定解 / 悬停 14 分钟
- **可直接写入**：`calibration_db.json`，key = `INT_小清河水屯__H164__P-90`
- **SRT 解析字段**：
  ```
  intersection_id: INT_小清河水屯
  center: 36.7029°N, 117.0223°E
  alt_agl: 163.4m（稳定，偏差 <0.3m）
  gimbal_pitch: -90°（全程锁定）
  wind_max: 13.4 m/s（6 级阵风，机身 roll 最大 -19.3°，云台已补偿）
  battery: 90% → 35%
  gps: RTK 固定解，32/45 颗
  ```

### 9.2 堤口路×胜利庄北路（补充数据集）

- **用途**：热成像演示 / 异常告警演示 / 早高峰场景视频
- **限制**：SRT 不对客户展示；悬停仅 16 帧，不做车道标定
- **热成像参数**：
  ```
  thermal_max: 82.1°C（早高峰发动机热特征，07:33 最高）
  thermal_min: 7.5°C
  场景: 早高峰 07:29~07:37
  ```
- **需要重飞**：正式项目前需采集合规飞行数据（高度 ≤160m，无超区预警）

---

## 10 关键参数速查

### 10.1 `configs/app_config_drone.yaml`

```yaml
video_reader:
  skip_secs: 0.5              # 原 0；降低图传带宽压力
  eis_smooth_window: 30       # EIS 平滑窗口（帧数）

tracker:
  track_buffer: 250           # 原 125；容忍无人机抖动导致的目标丢失
  confidence: 0.18            # 原 0.10；俯视角目标更小，适当提高阈值
  imgsz: 1280                 # 原 640；俯视角需更高分辨率检测小目标

ipm:
  output_size: [1280, 720]    # 鸟瞰图输出分辨率
  calib_alt_step: 2           # 高度分档步长（米）
  calib_pitch_step: 2         # 俯仰角分档步长（°）

calibration_monitor:
  pitch_dev_thresh: 3.0       # °，超限触发重标定
  alt_dev_thresh: 2.0         # m，超限触发重标定
  match_rate_thresh: 0.80     # 低于此值触发重标定

vlm_bypass:
  sample_every: 45            # 每 N 帧采样一次（约 1 次/3s @ 15fps）
  result_ttl_sec: 30          # 语义结果有效期（时间戳容差）
  device: "cuda:1"            # VLM 独占 GPU B
```

### 10.2 固定摄像头 vs 无人机参数对比

| 参数 | 固定摄像头 | 无人机建议值 | 原因 |
|---|---|---|---|
| `skip_secs` | 0 | 0.5~1.0 | 降低图传带宽压力 |
| `track_buffer` | 125 | 200~300 | 容忍抖动导致目标丢失 |
| `confidence` | 0.10 | 0.15~0.20 | 俯视角目标更小 |
| `imgsz` | 640 | 960~1280 | 俯视角需更高分辨率 |
| 标定高度分档 | — | 2m/档 | 减少标定工作量 |
| 标定俯仰角分档 | — | 2°/档 | 键值离散化，支持插值 |
| VLM 采样间隔 | — | 30~60 帧 | 异步旁路，不阻塞主链路 |

---

## 11 三期交付路线图

```
阶段   内容                                    工期    依赖
──────────────────────────────────────────────────────────────
P0-1   DroneTelemetry + FrameElement 扩展       W1      —
P0-2   SRT 元数据解析 + FFmpeg RTSP 回放        W1~W2   —
P0-3   小清河路口标定 + calibration_db 写入      W2      P0-1
P0-4   IPMNode + BEV 车道判定替换               W3      P0-3
P0-5   标注工具 Web UI（3 个子功能）             W3~W4   P0-3
P0-6   Grafana 大屏定制（4 个面板）             W4      P0-4
P0-7   端到端联调 + M1 验收                     W4      P0-1~6
──────────────────────────────────────────────────────────────
P1-1   VLMBypassNode + 结果融合                 W5~W6   P0-7
P1-2   告警规则引擎 + Webhook 推送              W6      P1-1
P1-3   热成像双通道融合（堤口路数据）           W7      P0-7
P1-4   早高峰自动分析报告（PDF）                W8      P1-1
P1-5   演示剧本彩排 + M2 验收                   W8      P1-1~4
──────────────────────────────────────────────────────────────
P2-1   GIS 多路口一张图                         W9~W10  P0-7
P2-2   飞行轨迹回放面板                         W9~W10  P0-2
P2-3   EISNode + VideoReader 改造               W11     P0-7
P2-4   精度基准离线评估（mAP / 误判率 / 延迟）  W11     P0-4
P2-5   完整演示彩排 ×2 + 缓冲修复               W12     全部
──────────────────────────────────────────────────────────────
```

### 串并行关系

- P0 全部串行（强依赖链）
- P1-1 和 P1-3 可并行启动
- P2-1 和 P2-2 可与 P2-3 并行

### 里程碑验收标准

| 里程碑 | 时间 | 验收条件 |
|---|---|---|
| M1 | W4 末 | 视频→检测→Grafana 全链路跑通；标注工具可演示新路口标定 |
| M2 | W8 末 | 告警 <30s 推送到手机；自动报告含拥堵时段+异常清单 |
| M3 | W12 末 | 25 分钟 CTO 演示无卡顿；GIS 多路口图可缩放；精度数字就绪 |

---

## 12 风险与应对

| 风险 | 等级 | 应对措施 |
|---|---|---|
| 堤口路超限高合规风险 | 🔴 高 | 演示只展示视频画面，SRT 遥测不展示；正式项目前重飞 |
| GPU 显存不足（VLM 需 14~18GB） | 🔴 高 | POC 阶段 VLM 降频至每 120 帧，或预推理关键帧 |
| 堤口路悬停帧不足，无法标定 | 🟡 中 | POC 只演示小清河路口完整分析，堤口路只演示热成像 |
| 演示现场网络不稳定 | 🟡 中 | 准备离线 Docker Compose 单机版，全程走局域网 |
| 机身抖动超出 EIS 补偿范围 | 🟡 中 | 优先硬件三轴云台；下次飞行选风速 <6m/s 窗口期 |
| CTO 问精度数字无法回答 | 🟡 中 | W11 完成离线评估，提前备好 mAP / 误判率 / 延迟数字 |

---

## 13 待确认事项

在继续开发之前，需要确认以下信息：

1. **演示现场 GPU 配置？**（显存规格决定 VLM 是否能实时运行）
2. **客户是否有指定路口？**（可提前采集合规飞行数据补充标定）
3. **告警推送渠道偏好？**（企业微信 / 钉钉 / 短信 / 大屏弹窗）
4. **是否需要中文界面？**（Grafana 面板文字、标注工具 UI、报告格式均需本地化）
5. **精度基准数字**：W11 需要完成小清河数据离线评估，得出：
   - 检测 mAP@0.5
   - 车道误判率（像素域 vs BEV）
   - 端到端延迟（视频帧 → Grafana 更新）

---

*文档版本：v1.0 | 2026-05 | 综合两轮规划评审*  
*下一步：将本文档提供给 Claude，可直接基于此规划落地任意模块的代码实现*

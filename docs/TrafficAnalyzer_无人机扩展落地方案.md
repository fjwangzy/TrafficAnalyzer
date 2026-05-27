# 基于 TrafficAnalyzer 的无人机路口交通态势监测扩展方案

> 项目基础：[Koldim2001/TrafficAnalyzer](https://github.com/Koldim2001/TrafficAnalyzer)  
> 模型主链：YOLO11 + ByteTrack  
> 语义旁路：Qwen-VL 7B（异步，每 N 帧）  
> 数据栈：Kafka → Telegraf → InfluxDB → Grafana

---

## 目录

1. [现有项目资产评估](#1-现有项目资产评估)
2. [整体架构设计](#2-整体架构设计)
3. [第一期：透视变换与标定参数库（IPM）](#3-第一期透视变换与标定参数库ipm)
4. [第二期：画面稳定与图传接入（EIS）](#4-第二期画面稳定与图传接入eis)
5. [第三期：Qwen-VL 语义旁路](#5-第三期qwen-vl-语义旁路)
6. [第四期：多机多路口调度](#6-第四期多机多路口调度)
7. [关键参数速查](#7-关键参数速查)
8. [实施路线图](#8-实施路线图)

---

## 1 现有项目资产评估

### 1.1 可直接复用（免改写）

| 模块 | 文件 | 状态 |
|---|---|---|
| RTSP 流输入 | `nodes/VideoReader.py` | `"://"` 判断已兼容无人机图传 |
| 多进程流式管道 | `main_stream_optimized_v2.py` | 直接复用 |
| 检测→追踪链路 | `DetectionTrackingNodes` | 调参即用 |
| 统计计算节点 | `CalcStatisticsNode` | 增加拥堵指数字段 |
| 数据推送栈 | Kafka + Telegraf + InfluxDB + Grafana | 直接复用 |

### 1.2 需要改造

| 模块 | 改造内容 |
|---|---|
| `entry_exit_lanes.json` | ROI 坐标系从像素坐标改为鸟瞰图坐标 |
| `app_config.yaml` | 调整 `skip_secs` / `track_buffer` / `confidence` / `imgsz` |
| `VideoReader.py::process()` | 前插 EIS → IPM 两个新节点 |

### 1.3 需要新增开发

```
新增节点 1：EIS 画面稳定（nodes/EISNode.py）
新增节点 2：IPM 透视变换 + 标定参数库（nodes/IPMNode.py + calibration/）
新增节点 3：Qwen-VL 语义旁路（nodes/VLMBypassNode.py）
```

---

## 2 整体架构设计

### 2.1 完整管道

```
无人机 RTSP 流（含 SRT 元数据：intersection_id / 姿态 / GPS）
    │
    ▼
[新] EISNode — ORB 特征点匹配 → 帧间仿射变换 → 滑动窗口平滑
    │
    ▼
[新] IPMNode — 查标定参数库 → 单应矩阵 H_mat → cv2.warpPerspective
    │          └─ 若超出阈值 → 触发重标定 alert
    ▼
VideoReader（适配鸟瞰图 ROI，从 entry_exit_lanes.json 读取）
    │
    ├────────────────────────────────────────────────────┐
    ▼（每帧，主链路）                                    │（每 N 帧，旁路）
DetectionTrackingNode                               [新] VLMBypassNode
YOLO11 → ByteTrack → BBox + track_id                   Qwen-VL 7B 异步推理
    │                                                    │
    ▼                                                    ▼
CalcStatisticsNode ←─── 时间戳对齐合并 ─────────── 语义结果 JSON
（流量 / 排队 / 速度 / 拥堵指数）           （异常 / 拥堵等级 / 车道可见性）
    │
    ▼
Kafka  topic: drone_{drone_id}_intersection_{id}
    │
    ▼
Telegraf → InfluxDB → Grafana（按路口聚合）
```

### 2.2 双 GPU 部署方案

```
GPU A：YOLO11 + ByteTrack（主链路，~15ms/帧，实时）
GPU B：Qwen-VL 7B（旁路，2~8s/帧，异步）
```

单卡降级方案：旁路降频至每 120 帧 + 时间片调度，延迟上升至 30s 级，适合事后巡检报告而非实时告警。

---

## 3 第一期：透视变换与标定参数库（IPM）

> 优先级最高，是所有下游指标精度的基础。工期建议 3 周。

### 3.1 标定参数库设计

**键值策略**：对高度和俯仰角做分档离散化，避免对每个精确值都单独标定。

```python
# calibration/calib_db.py

import json, numpy as np
from pathlib import Path

CALIB_PATH = Path("calibration/calib_store.json")

def make_key(intersection_id: str, alt_m: float, pitch_deg: float) -> str:
    """2m 分档 / 2° 分档，生成可查询键"""
    h = round(alt_m / 2) * 2
    p = round(pitch_deg / 2) * 2
    return f"{intersection_id}__H{h}__P{p}"

def load_homography(intersection_id: str, alt_m: float, pitch_deg: float
                    ) -> np.ndarray | None:
    """
    三级命中策略：
      1. 精确命中 → 直接返回
      2. 偏差在档内（±1档）→ 双线性插值
      3. 超出范围 → 返回 None，触发重标定告警
    """
    db = json.loads(CALIB_PATH.read_text()) if CALIB_PATH.exists() else {}
    key = make_key(intersection_id, alt_m, pitch_deg)

    if key in db:
        return np.array(db[key])

    # 尝试插值：找最近 4 个已标定档位
    candidates = _find_neighbors(db, intersection_id, alt_m, pitch_deg)
    if candidates:
        return _bilinear_interp(candidates, alt_m, pitch_deg)

    return None  # 触发重标定

def save_homography(intersection_id: str, alt_m: float, pitch_deg: float,
                    H_mat: np.ndarray):
    db = json.loads(CALIB_PATH.read_text()) if CALIB_PATH.exists() else {}
    key = make_key(intersection_id, alt_m, pitch_deg)
    db[key] = H_mat.tolist()
    CALIB_PATH.write_text(json.dumps(db, indent=2))

def _find_neighbors(db, intersection_id, alt_m, pitch_deg, tol=3):
    """在 ±tol 米 / ±tol 度 范围内查找已有标定点"""
    results = []
    for key, mat in db.items():
        if not key.startswith(intersection_id):
            continue
        try:
            parts = key.split("__")
            h = float(parts[1][1:])
            p = float(parts[2][1:])
            if abs(h - alt_m) <= tol and abs(p - pitch_deg) <= tol:
                results.append((h, p, np.array(mat)))
        except Exception:
            continue
    return results

def _bilinear_interp(candidates, alt_m, pitch_deg):
    """简单距离加权插值"""
    weights, mats = [], []
    for h, p, mat in candidates:
        d = ((h - alt_m) ** 2 + (p - pitch_deg) ** 2) ** 0.5 + 1e-6
        weights.append(1.0 / d)
        mats.append(mat)
    w = np.array(weights)
    w /= w.sum()
    return sum(wi * mi for wi, mi in zip(w, mats))
```

### 3.2 IPM 节点实现

```python
# nodes/IPMNode.py

import cv2, numpy as np
from calibration.calib_db import load_homography, save_homography
from utils.drone_meta import parse_srt_meta  # 解析无人机 SRT 元数据

# 重标定触发阈值
RECALIB_PITCH_DEG  = 3.0   # 姿态偏差超过 3° 触发
RECALIB_ALT_M      = 2.0   # 高度变化超过 2m 触发
RECALIB_MATCH_RATE = 0.80  # 车道匹配率低于 80% 触发

class IPMNode:
    def __init__(self, output_size=(1280, 720)):
        self.output_size = output_size
        self._last_meta = {}   # 上一帧元数据，用于检测突变
        self._H = None         # 当前生效的单应矩阵

    def process(self, frame: np.ndarray, srt_meta: dict) -> tuple[np.ndarray, bool]:
        """
        返回：(鸟瞰图帧, 是否触发重标定)
        """
        recalib_needed = self._check_recalib(srt_meta)

        if recalib_needed or self._H is None:
            H = load_homography(
                srt_meta["intersection_id"],
                srt_meta["alt_m"],
                srt_meta["pitch_deg"]
            )
            if H is None:
                # 无可用标定，发出告警，原帧透传
                self._emit_recalib_alert(srt_meta)
                return frame, True
            self._H = H

        bev = cv2.warpPerspective(frame, self._H, self.output_size)
        self._last_meta = srt_meta
        return bev, False

    def _check_recalib(self, meta: dict) -> bool:
        if not self._last_meta:
            return False
        pitch_delta = abs(meta.get("pitch_deg", 0) - self._last_meta.get("pitch_deg", 0))
        alt_delta   = abs(meta.get("alt_m", 0)     - self._last_meta.get("alt_m", 0))
        return pitch_delta > RECALIB_PITCH_DEG or alt_delta > RECALIB_ALT_M

    def _emit_recalib_alert(self, meta: dict):
        print(f"[IPM ALERT] 重标定触发 | 路口={meta['intersection_id']} "
              f"高度={meta['alt_m']:.1f}m 俯仰={meta['pitch_deg']:.1f}°")
        # 可扩展：推送 Kafka 告警 topic


def interactive_calibrate(frame: np.ndarray, intersection_id: str,
                           alt_m: float, pitch_deg: float,
                           output_size=(1280, 720)) -> np.ndarray:
    """
    人工交互标定工具：
    鼠标依次点击图像中 4 个路面基准点（斑马线角点）→ 计算单应矩阵 → 写入数据库
    """
    src_pts = []

    def on_click(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and len(src_pts) < 4:
            src_pts.append([x, y])
            cv2.circle(frame, (x, y), 5, (0, 255, 0), -1)
            cv2.imshow("标定 - 依次点击4个路面角点", frame)

    cv2.namedWindow("标定 - 依次点击4个路面角点")
    cv2.setMouseCallback("标定 - 依次点击4个路面角点", on_click)
    cv2.imshow("标定 - 依次点击4个路面角点", frame)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

    if len(src_pts) < 4:
        raise ValueError("需要至少 4 个基准点")

    w, h = output_size
    dst_pts = np.float32([[0,0],[w,0],[w,h],[0,h]])
    H, _ = cv2.findHomography(np.float32(src_pts), dst_pts)
    save_homography(intersection_id, alt_m, pitch_deg, H)
    print(f"[标定完成] key={intersection_id} H={alt_m}m P={pitch_deg}°")
    return H
```

### 3.3 ROI 重新定义

`entry_exit_lanes.json` 的坐标需要在鸟瞰图坐标系下重新标注：

```json
{
  "intersection_001": {
    "coordinate_system": "bird_eye_view",
    "output_size": [1280, 720],
    "lanes": {
      "道路1": {
        "type": "entry",
        "polygon": [[120,100],[380,100],[380,360],[120,360]],
        "direction": "south_to_north"
      },
      "道路2": {
        "type": "entry",
        "polygon": [[420,100],[680,100],[680,360],[420,360]],
        "direction": "north_to_south"
      }
    }
  }
}
```

---

## 4 第二期：画面稳定与图传接入（EIS）

> 工期建议 2 周，可与第三期并行。

### 4.1 EIS 节点实现

```python
# nodes/EISNode.py

import cv2, numpy as np
from collections import deque

class EISNode:
    """
    电子图像稳定（Electronic Image Stabilization）
    原理：ORB 特征点匹配 → 帧间仿射变换 → 滑动窗口平滑
    """
    def __init__(self, smooth_window: int = 30):
        self.smooth_window = smooth_window
        self._transforms = deque(maxlen=smooth_window)
        self._prev_gray  = None
        self._orb        = cv2.ORB_create(nfeatures=500)
        self._bf         = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        self._cumulative = np.zeros(3)  # [dx, dy, da]

    def process(self, frame: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        if self._prev_gray is None:
            self._prev_gray = gray
            return frame

        # ORB 特征点检测与匹配
        kp1, des1 = self._orb.detectAndCompute(self._prev_gray, None)
        kp2, des2 = self._orb.detectAndCompute(gray, None)

        if des1 is None or des2 is None or len(des1) < 10:
            self._prev_gray = gray
            return frame

        matches = self._bf.match(des1, des2)
        matches = sorted(matches, key=lambda x: x.distance)[:50]

        if len(matches) < 8:
            self._prev_gray = gray
            return frame

        src = np.float32([kp1[m.queryIdx].pt for m in matches])
        dst = np.float32([kp2[m.trainIdx].pt for m in matches])

        # 计算仿射变换（只允许平移+旋转，不允许缩放）
        M, _ = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC)
        if M is None:
            self._prev_gray = gray
            return frame

        dx = M[0, 2]
        dy = M[1, 2]
        da = np.arctan2(M[1, 0], M[0, 0])
        self._transforms.append(np.array([dx, dy, da]))

        # 滑动窗口平均，计算平滑目标
        if len(self._transforms) < 2:
            self._prev_gray = gray
            return frame

        smooth = np.mean(self._transforms, axis=0)
        self._cumulative += self._transforms[-1]
        diff = smooth - self._cumulative

        # 应用补偿变换
        h, w = frame.shape[:2]
        M_smooth = np.array([
            [np.cos(diff[2]), -np.sin(diff[2]), diff[0]],
            [np.sin(diff[2]),  np.cos(diff[2]), diff[1]]
        ], dtype=np.float32)

        stabilized = cv2.warpAffine(frame, M_smooth, (w, h),
                                    flags=cv2.INTER_LINEAR,
                                    borderMode=cv2.BORDER_REFLECT)
        self._prev_gray = gray
        return stabilized
```

### 4.2 VideoReader 改造

在 `VideoReader.py` 的 `process()` 方法中，RTSP 读帧后立即插入两个节点：

```python
# nodes/VideoReader.py 改造片段

from nodes.EISNode import EISNode
from nodes.IPMNode import IPMNode
from utils.drone_meta import parse_srt_meta

class VideoReader:
    def __init__(self, config):
        ...
        self.eis = EISNode(smooth_window=config.get("eis_smooth_window", 30))
        self.ipm = IPMNode(output_size=tuple(config.get("bev_size", [1280, 720])))
        self.srt_reader = SRTReader(config.get("srt_path"))  # 解析无人机 SRT 元数据

    def process(self):
        ret, frame = self.cap.read()
        if not ret:
            return None

        # 解析当前帧元数据（intersection_id / alt_m / pitch_deg / GPS）
        meta = self.srt_reader.read(self.frame_idx)

        # 1. 画面稳定
        frame = self.eis.process(frame)

        # 2. 透视变换（鸟瞰图）
        frame, recalib_needed = self.ipm.process(frame, meta)

        # 元数据透传到下游
        return {"frame": frame, "meta": meta, "recalib_needed": recalib_needed}
```

### 4.3 图传链路关键配置

```yaml
# configs/app_config.yaml 无人机专用参数

video_reader:
  skip_secs: 0.5          # 原固定摄像头为 0；无人机降为 0.5~1.0 以适应带宽
  eis_smooth_window: 30   # EIS 平滑窗口帧数
  bev_size: [1280, 720]   # 鸟瞰图输出尺寸

tracker:
  track_buffer: 250       # 原 125；无人机抖动需要更长的目标保持窗口
  confidence: 0.18        # 原 0.10；俯视角目标更小，适当提高阈值
  imgsz: 1280             # 原 640；俯视角需更高分辨率检测小目标
```

---

## 5 第三期：Qwen-VL 语义旁路

> 工期建议 3 周。不影响主链路，可与第二期并行启动。

### 5.1 架构定位

```
主链路：YOLO11 → ByteTrack  （每帧，~15ms，精确 BBox + track_id）
旁路：  Qwen-VL 7B          （每 N 帧，2~8s，语义事件 + 自然语言描述）
```

VLM 旁路补充 YOLO 的三个盲区：

| 场景 | YOLO | Qwen-VL 旁路 |
|---|---|---|
| 交通事故/异常停车识别 | 只知道"有辆车" | 零样本理解"横停路口，疑似事故" |
| 标定质量自检 | 无感知 | 输出当前帧可见车道线数量，辅助重标定决策 |
| 路况自然语言报告 | 无 | 直接输出可读文字，对接管理平台/微信推送 |

### 5.2 VLM 旁路节点实现

```python
# nodes/VLMBypassNode.py

import queue, threading, time, base64, json
import numpy as np
import cv2
from transformers import AutoTokenizer, AutoProcessor, Qwen2VLForConditionalGeneration

PROMPT_TEMPLATE = """
这是一张无人机俯拍路口图。请以 JSON 格式回答（不要输出其他内容）：
{
  "accident": false,          // 是否存在疑似交通事故或异常停车
  "congestion_level": 0,      // 拥堵等级：0=畅通 1=轻度 2=中度 3=严重
  "visible_lanes": 4,         // 可见清晰车道线数量
  "anomaly": null,            // 异常描述，无则 null
  "summary": "路口畅通"       // 一句话路况描述
}
"""

class VLMBypassNode:
    def __init__(self, model_path: str, sample_every: int = 45,
                 device: str = "cuda:1"):
        self.sample_every = sample_every
        self.device = device
        self._frame_count = 0
        self._result_queue = queue.Queue(maxsize=10)
        self._input_queue  = queue.Queue(maxsize=5)
        self._last_result  = {}

        # 在独立线程中加载模型，不阻塞主链路启动
        self._worker = threading.Thread(target=self._inference_loop,
                                        args=(model_path,), daemon=True)
        self._worker.start()

    def push(self, frame: np.ndarray, meta: dict):
        """主链路每帧调用，仅每 sample_every 帧采样一次"""
        self._frame_count += 1
        if self._frame_count % self.sample_every != 0:
            return

        if not self._input_queue.full():
            # 压缩为 JPEG 减少队列内存占用
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            self._input_queue.put_nowait(
                {"img_bytes": buf.tobytes(), "meta": meta,
                 "ts": time.time()}
            )

    def get_latest(self) -> dict:
        """获取最新语义结果（非阻塞）"""
        while not self._result_queue.empty():
            self._last_result = self._result_queue.get_nowait()
        return self._last_result

    def _inference_loop(self, model_path: str):
        model = Qwen2VLForConditionalGeneration.from_pretrained(
            model_path, torch_dtype="auto", device_map=self.device
        )
        processor = AutoProcessor.from_pretrained(model_path)

        while True:
            try:
                item = self._input_queue.get(timeout=2.0)
            except queue.Empty:
                continue

            result = self._run_inference(model, processor, item)
            if not self._result_queue.full():
                self._result_queue.put_nowait({**result, "ts": item["ts"],
                                               "meta": item["meta"]})

    def _run_inference(self, model, processor, item: dict) -> dict:
        img_b64 = base64.b64encode(item["img_bytes"]).decode()
        messages = [{"role": "user", "content": [
            {"type": "image", "image": f"data:image/jpeg;base64,{img_b64}"},
            {"type": "text",  "text": PROMPT_TEMPLATE}
        ]}]

        text = processor.apply_chat_template(messages, tokenize=False,
                                             add_generation_prompt=True)
        inputs = processor(text=[text], return_tensors="pt").to(model.device)

        with __import__("torch").no_grad():
            output_ids = model.generate(**inputs, max_new_tokens=256)

        raw = processor.batch_decode(output_ids, skip_special_tokens=True)[0]

        try:
            # 提取 JSON 片段
            start = raw.find("{")
            end   = raw.rfind("}") + 1
            return json.loads(raw[start:end])
        except Exception:
            return {"accident": False, "congestion_level": 0,
                    "visible_lanes": -1, "anomaly": None,
                    "summary": "解析失败", "raw": raw[:200]}
```

### 5.3 结果融合与推送

```python
# nodes/CalcStatisticsNode.py 扩展片段

class CalcStatisticsNode:
    def process(self, detection_result: dict, vlm_result: dict) -> dict:
        stats = self._calc_yolo_stats(detection_result)

        # 融合 VLM 语义结果（以时间戳容差 30s 对齐）
        if vlm_result and abs(time.time() - vlm_result.get("ts", 0)) < 30:
            stats["congestion_vlm"]  = vlm_result.get("congestion_level", -1)
            stats["accident_flag"]   = vlm_result.get("accident", False)
            stats["visible_lanes"]   = vlm_result.get("visible_lanes", -1)
            stats["anomaly_desc"]    = vlm_result.get("anomaly")
            stats["summary"]         = vlm_result.get("summary", "")

            # 车道匹配率监控：若 VLM 检测到的车道数与配置差异大，触发重标定
            configured_lanes = self._get_configured_lane_count()
            if stats["visible_lanes"] > 0:
                match_rate = min(configured_lanes, stats["visible_lanes"]) \
                           / max(configured_lanes, stats["visible_lanes"])
                if match_rate < 0.80:
                    self._emit_recalib_alert("车道匹配率低", match_rate)

        return stats
```

---

## 6 第四期：多机多路口调度

> 工期建议 2 周。

### 6.1 任务规划配置

每个路口预存航点文件，无人机起飞时加载：

```json
// missions/intersection_001.json
{
  "intersection_id": "intersection_001",
  "waypoint": {
    "lat": 39.9042,
    "lon": 116.4074,
    "alt_agl": 60.0,
    "gimbal_pitch": -85.0
  },
  "hover_duration_min": 30,
  "rtsp_port": 8554,
  "kafka_topic": "drone_001_intersection_001"
}
```

### 6.2 多实例编排

每架无人机独立启动一个管道进程，复用现有 `CAMERA_ID` 机制：

```bash
# 启动脚本：deploy/start_drone_pipelines.sh

#!/bin/bash
DRONES=("drone_001:intersection_001" "drone_002:intersection_002" "drone_003:intersection_003")

for entry in "${DRONES[@]}"; do
    drone_id="${entry%%:*}"
    intersection_id="${entry##*:}"
    echo "启动 $drone_id → $intersection_id"
    python main_stream_optimized_v2.py \
        --camera_id "$drone_id" \
        --mission "missions/${intersection_id}.json" \
        --config "configs/app_config_drone.yaml" \
        --log "logs/${drone_id}.log" &
done

wait
```

### 6.3 Docker Compose 扩展

```yaml
# docker-compose.drone.yml

version: "3.8"
services:
  pipeline_drone_001:
    build: .
    environment:
      - CAMERA_ID=drone_001
      - INTERSECTION_ID=intersection_001
      - RTSP_URL=rtsp://192.168.1.101:8554/live
      - KAFKA_TOPIC=drone_001_intersection_001
    runtime: nvidia
    devices:
      - /dev/nvidia0        # GPU A：YOLO 主链路
    volumes:
      - ./calibration:/app/calibration
      - ./missions:/app/missions

  vlm_service:
    build: .
    command: python services/vlm_server.py
    runtime: nvidia
    devices:
      - /dev/nvidia1        # GPU B：Qwen-VL 7B 旁路
    ports:
      - "50051:50051"       # gRPC 接口，供所有管道实例共享

  kafka:
    image: confluentinc/cp-kafka:7.4.0
    environment:
      KAFKA_AUTO_CREATE_TOPICS_ENABLE: "true"
```

### 6.4 Grafana 面板规范

Kafka topic 命名：`drone_{drone_id}_intersection_{id}`

InfluxDB 查询示例（按路口聚合）：

```sql
SELECT mean("evts_per_min") AS "平均流量"
FROM "traffic_stats"
WHERE "intersection_id" = 'intersection_001'
  AND time > now() - 5m
GROUP BY time(10s), "lane_id"
```

---

## 7 关键参数速查

| 参数 | 固定摄像头默认值 | 无人机建议值 | 说明 |
|---|---|---|---|
| `skip_secs` | 0 | 0.5 ~ 1.0 | 降低带宽和处理压力 |
| `track_buffer` | 125 | 200 ~ 300 | 容忍无人机抖动导致的目标丢失 |
| `confidence` | 0.10 | 0.15 ~ 0.20 | 俯视角目标更小，降低误检 |
| `imgsz` | 640 | 960 ~ 1280 | 俯视角需更高分辨率 |
| `eis_smooth_window` | — | 20 ~ 40 | EIS 平滑窗口，越大越稳但延迟越高 |
| 标定高度分档 | — | 2 m/档 | 减少标定工作量 |
| 标定俯仰角分档 | — | 2°/档 | 键值离散化，支持插值 |
| 重标定阈值·姿态偏差 | — | > 3° | 触发重标定告警 |
| 重标定阈值·高度变化 | — | > 2 m | 触发重标定告警 |
| 重标定阈值·车道匹配率 | — | < 80% | 触发重标定告警 |
| VLM 采样间隔 | — | 30 ~ 60 帧 | 异步旁路，不阻塞主链路 |
| VLM 时间对齐容差 | — | 30 s | 语义结果与 YOLO 帧时间戳对齐窗口 |

---

## 8 实施路线图

```
周次   工作内容                                          依赖
─────────────────────────────────────────────────────────────
W1-2   标定参数库设计 + interactive_calibrate 工具开发    —
W3     IPMNode 实现 + VideoReader 改造 + ROI 坐标系迁移  W1-2
W4-5   EISNode 实现 + 图传参数调优 + 单路口端到端联调    W3
W5-7   Qwen-VL 旁路开发 + VLMBypassNode + 融合层改造     W3（可并行）
W8     多路口标定 + Kafka topic 规范 + Grafana 面板扩展   W4-5
W9-10  多机编排 + Docker Compose + 压力测试              W8
─────────────────────────────────────────────────────────────
```

### 串并行关系

- W3（IPM）→ W4-5（EIS + 联调）：强依赖，串行
- W5-7（VLM旁路）与 W4-5 并行：互不依赖，可同步推进
- W8-10：在单路口验证通过后展开

### 里程碑验收标准

| 里程碑 | 验收条件 |
|---|---|
| M1（W3末）| 单路口鸟瞰图正确渲染，车道 ROI 精确对应实际车道 |
| M2（W5末）| 无人机悬停 10 分钟内 ROI 漂移 < 5px，YOLO 检测 mAP 不低于固定摄像头的 85% |
| M3（W7末）| VLM 旁路事故识别准确率 > 80%（人工抽检 50 帧），不影响主链路帧率 |
| M4（W10末）| 3 架无人机同时接入，Grafana 面板正确区分路口，数据延迟 < 5s |

---

*文档版本：v1.0 | 基于 Koldim2001/TrafficAnalyzer + YOLO11 + Qwen-VL 7B*

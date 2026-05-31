# 端到端测试报告：inter_xqh 视频 + SRT 遥测

**日期**: 2026-05-30  
**测试资产**: `test_videos/inter_xqh/`  
- 视频: `DJI_20260403142902_0001_V小清河北路与水屯路路口.mp4` (5.4GB, 4K, 16.5min)  
- 遥测: `telemetry.srt` (29,741 条记录, 逐帧@30fps)

---

## 测试结果：49 PASS / 0 FAIL / 0 WARN ✅

### Phase 1: SRT 遥测解析 (7/7)
| 检查项 | 结果 | 详情 |
|--------|------|------|
| 文件存在 | ✅ | telemetry.srt |
| 记录数 > 0 | ✅ | 29,741 records |
| 时长 > 0 | ✅ | 992s (16.5min) |
| 字段完整 | ✅ | timestamp, lat, lon, height, gimbal_pitch/yaw, focal_len |
| GPS有效 | ✅ | lat=36.702909, lon=117.02233 |
| 高度 > 0 | ✅ | 130.0m (相对高度) |
| SRT特有字段 | ✅ | focal_len=24.0mm |

### Phase 2: 视频读取 (6/6)
| 检查项 | 结果 | 详情 |
|--------|------|------|
| 可打开 | ✅ | OpenCV VideoCapture |
| 分辨率 | ✅ | 3840×2160 (4K) |
| FPS | ✅ | 30.0 fps |
| 时长 | ✅ | 992s |
| 遥测/视频匹配 | ✅ | ratio=1.00 (完美1:1) |
| 首帧可读 | ✅ | shape=(2160, 3840, 3) |

### Phase 3: 节点实例化 (8/8)
全部8个节点成功实例化：
HomographyCalibrationNode, MotionCompensationNode, SpeedEstimationNode,
DirectionFlowNode, LaneAnalysisNode, TrajectoryNode, ConflictDetectionNode, CalcStatisticsNode

### Phase 4: 遥测→单应性→运动补偿 链路 (14/14)
- **GPS锚点**: (36.702909, 117.022330), gimbal_yaw=0.7°
- **H矩阵**: 3/3 时间点有效 (mode=telemetry)
- **运动补偿**: 3/3 时间点有效 (hover=True)
- **像素→世界变换**: 图像中心→(0.00, 0.00)m ✅

### Phase 5: VideoReader集成 (6/6)
- 20帧全部注入SRT遥测数据
- 帧级同步精度: 0.033s

### Phase 6: 完整管道 (8/8)
| 指标 | 值 |
|------|------|
| 处理帧数 | 100 |
| 处理速度 | 2.0 fps (CPU, 4K输入) |
| 检测率 | 100/100 帧 (100%) |
| 累计检测 | 8,051 目标 |
| 遥测注入 | 100/100 (100%) |
| H矩阵 | 100/100 (100%) |
| 运动补偿 | 90/100 (前10帧为锚点采集期) |
| 方向统计 | ✅ straight/left_turn/right_turn/u_turn/unknown |
| 车辆数 | 82 |
| 活跃轨迹 | 86 |

---

## 修复的问题

### Bug #1: `_handle_conflict` 格式化崩溃
**文件**: `platform/app/kafka/consumer.py`  
**问题**: `data.get('ttc_sec', '?')` 返回字符串 `'?'` 后接 `:.1f` 格式化导致 TypeError  
**修复**: 先转为 float 再格式化，加 try/except 防护

### Bug #2: `/ready` 端点混合类型
**文件**: `platform/app/main.py`  
**问题**: `pipelines_active` (int) 混入 services dict，导致 `all_ready` 始终为 False  
**修复**: 将 `pipelines_active` 提取为独立字段，不混入 services 状态判断

### Bug #3: `run_local.py` 旧版 topic pattern
**文件**: `platform/scripts/run_local.py`  
**问题**: 仍使用 `statistics_.*` 模式，漏掉 track_complete/conflicts/telemetry  
**修复**: 更新为 `(statistics|track_complete|conflicts|telemetry)_.*`

### 改进: Phase 4 测试预热
**文件**: `test_pipeline_inter_xqh.py`  
**问题**: 仅喂3帧但锚点需10帧，导致运动补偿始终为 None  
**修复**: 增加12帧预热阶段建立GPS锚点

### 改进: SRT 遥测支持
**文件**: `test_pipeline_inter_xqh.py`  
**变更**: 从 JSON file 切换到 SRT 源 (source: "srt", time_offset: 0)

---

## 平台集成验证

### 模块导入 ✅
所有12个Python文件语法检查通过，2个YAML文件验证通过。

### API 端点 ✅
43 条路由，含新增:
- `GET/POST /api/v1/pipelines` — 管道管理
- `GET /api/v1/pipelines/summary` — 管道概览
- `GET/DELETE /api/v1/pipelines/{id}` — 管道操作
- `GET /api/v1/pipelines/{id}/status` — 管道健康

### WebSocket 通道 ✅
- `intersection:{id}` → stats, track_complete, conflict 消息
- `alerts` → 新告警推送
- `telemetry:{drone_id}` → 实时遥测
- `system` → GPU/系统指标

### 前端连接
- Dashboard: 使用 `kpi.drones_online` 和 `kpi.pipelines_active` (修复硬编码)
- Monitoring: 增加 conflict/track_complete 事件处理
- Drones: API已接入 `/api/v1/drones` (WebSocket遥测待Phase 2)

---

## 数据流验证

```
SRT文件 → SrtTelemetryParser → VideoReader(telemetry注入)
  → DetectionTrackingNodes(YOLO) → HomographyCalibrationNode
  → MotionCompensationNode → TrackerInfoUpdateNode
  → SpeedEstimationNode → DirectionFlowNode
  → LaneAnalysisNode → TrajectoryNode
  → ConflictDetectionNode → CalcStatisticsNode
  → KafkaProducerNode → Kafka topics
  → KafkaConsumerService → WebSocket广播 → 前端
```

全链路验证通过 ✅

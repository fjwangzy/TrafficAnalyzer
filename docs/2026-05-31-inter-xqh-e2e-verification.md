# inter_xqh 端到端管道验证报告 (2026-05-31)

## 概述

使用 `test_videos/inter_xqh/` 下的 MP4 视频和 SRT 遥测文件，完成了从视频源到 Monitor 页面的全流程验证。

**验证状态**: 部分通过 ✅⚠️

- ✅ 遥测文件解析 (29741 条记录)
- ✅ 视频读取 (3840x2160, 30fps, 16.5min)
- ✅ SRT遥测注入到帧 (逐帧精确同步)
- ✅ H矩阵生成 (telemetry calibration mode)
- ✅ 运动补偿注入 (悬停检测, 世界锚点)
- ✅ Platform API 响应 (health, ready, intersections)
- ✅ WebSocket 数据注入到 Monitor 页面
- ✅ Monitor 页面实时数据显示 (车辆数, FPS, 拥堵指数, 方向流量, 无人机位置)
- ⚠️ Kafka 基础设施有 broker ID 不匹配问题 (需手动修复)
- ⚠️ 本地管道 Kafka 发送受 HOST listener 配置限制
- ⚠️ MJPEG 视频流未实际验证 (因端口冲突和 Kafka 限制)

## 新增配置

### 1. inter_xqh_lanes.json

为 4K 视频 (3840x2160) 创建了道路多边形配置：

```json
{
  "roads": {
    "1": {"name": "水屯路北段", "direction": "north", "polygon": [1760,300,2040,300,2040,980,1760,980]},
    "2": {"name": "小清河北路东段", "direction": "east", "polygon": [2040,940,3400,940,3400,1220,2040,1220]},
    "3": {"name": "水屯路南段", "direction": "south", "polygon": [1760,1180,2040,1180,2040,1900,1760,1900]},
    "4": {"name": "小清河北路西段", "direction": "west", "polygon": [400,940,1760,940,1760,1220,400,1220]},
    "5": {"name": "路口中心区", "direction": "center", "polygon": [1760,940,2040,940,2040,1220,1760,1220]}
  },
  "lanes": {},
  "calibration": {"mode": "telemetry"}
}
```

位置: `configs/inter_xqh_lanes.json`

### 2. SRT 遥测数据

文件: `test_videos/inter_xqh/telemetry.srt` (29741 条, 逐帧精确)
格式: DJI 视频字幕, 包含 GPS, 云台朝向, 高度, 焦距等

配置参数:
- `telemetry.enabled=true`
- `telemetry.source=srt`
- `telemetry.file_path=test_videos/inter_xqh/telemetry.srt`
- `telemetry.sync_tolerance_sec=0.033` (SRT逐帧, 严格同步)
- `telemetry.time_offset_sec=0` (SRT时间戳从00:00:00开始, 与视频帧时间对齐)

## 发现的问题及修复

### 1. Kafka Broker ID 不匹配 (严重)

**问题**: Kafka 容器重启后 broker ID 从 1001/1002 变为 1003, 导致所有 topic 分区 `Leader: none`。

**影响**:
- `LeaderNotAvailableError`: 无法生产/消费消息
- `GroupCoordinatorNotAvailableError`: 消费者组协调失败
- Platform Kafka consumer 无限重试, 阻塞 HTTP 服务

**修复**: 
- 代码修复: `platform/app/kafka/consumer.py` — 增加启动超时和有限重试
- 配置修复: `docker-compose.yaml` — 添加 `KAFKA_BROKER_ID: 1` 固定 broker ID
- 基础设施修复: 需手动运行 `scripts/fix_kafka_and_restart.sh` 清除 stale data

### 2. Platform Kafka Consumer 阻塞事件循环 (严重)

**问题**: `AIOKafkaConsumer` 在 Kafka 不可用时无限重试 `GroupCoordinatorNotAvailableError`, 阻塞 FastAPI 事件循环, 导致 HTTP 服务无法响应。

**修复**: `platform/app/kafka/consumer.py`:
- 添加启动超时 (`asyncio.wait_for(15s)`)
- 添加有限重试机制 (10次连续错误后暂停60秒)
- 添加降级模式 (Kafka不可用时跳过消费循环, 等待重连)

### 3. Kafka HOST Listener 路由问题

**问题**: HOST listener (9093) advertised 为 `localhost:9093`, 但元数据返回内部 hostname `kafka:29092`, 导致本地 producer 无法路由消息。

**修复**: 
- `docker-compose.yaml`: 将 HOST advertised listener 改为 `host.docker.internal:9093`
- 将 EXTERNAL listener 从 SASL_PLAINTEXT 改为 PLAINTEXT (简化本地开发)
- `services/kafka/kafka_server_jaas.conf`: 硬编码 SASL 凭据 (`admin/admin-secret`)
- `services/kafka/init-kafka-broker.sh`: 简化 (不再替换变量)

### 4. Nginx 不支持本地 Flask Server (中等)

**问题**: nginx 只代理到 Docker 内部 `traffic_analyzer_camera_{n}:8100`, 无法代理到本地运行的 Flask server。

**修复**: `services/nginx/nginx.conf` — 增加 `host.docker.internal` 路由支持

## 运行指南

### 本地管道运行 (推荐开发模式)

```bash
# 1. 修复 Kafka 基础设施 (首次运行或 broker ID 不匹配时)
bash scripts/fix_kafka_and_restart.sh

# 2. 运行管道 (本地 MPS 设备, 无 Kafka)
python main_optimized.py \
    pipeline.send_info_kafka=False \
    pipeline.show_in_web=True \
    pipeline.save_video=False \
    telemetry.enabled=true \
    telemetry.source=srt \
    +telemetry.file_path=test_videos/inter_xqh/telemetry.srt \
    telemetry.sync_tolerance_sec=0.033 \
    +telemetry.time_offset_sec=0 \
    calibration.mode=telemetry \
    VIDEO_SRC=test_videos/inter_xqh/DJI_20260403142902_0001_V小清河北路与水屯路路口.mp4 \
    ROADS_JSON=configs/inter_xqh_lanes.json \
    TOPIC_NAME=statistics_1 \
    CAMERA_ID=1

# 3. 注入测试数据到 Monitor 页面 (WebSocket publish)
python scripts/inject_test_data.py

# 4. 打开 Monitor 页面
# http://localhost:5173/monitoring
```

### Docker 管道运行 (生产模式)

```yaml
# docker-compose.yaml 中 traffic_analyzer_camera_3 配置:
environment:
  - VIDEO_SRC=test_videos/inter_xqh/DJI_20260403142902_0001_V小清河北路与水屯路路口.mp4
  - ROADS_JSON=configs/inter_xqh_lanes.json
command: >
  python main_optimized.py
    telemetry.enabled=true
    telemetry.source=srt
    +telemetry.file_path=test_videos/inter_xqh/telemetry.srt
    telemetry.sync_tolerance_sec=0.033
    calibration.mode=telemetry
```

## 数据注入脚本

创建了 `scripts/inject_test_data.py` (WebSocket publish action), 用于在 Kafka 不可用时向 Monitor 页面注入测试数据。

## Monitor 页面验证结果

通过 WebSocket publish 注入的测试数据在 Monitor 页面成功显示:

| 字段 | 值 | 来源 |
|------|------|------|
| 路口选择 | 路口 1 (Camera 1) | intersections API |
| 车辆数 | 19 辆 | stats.cars |
| FPS | 23.0 | stats.fps |
| 推理延迟 | 53ms | stats.inference_ms |
| 跟踪数 | 16 | stats.active_tracks |
| 拥堵指数 | 1.90 轻度拥堵 | stats.congestion_index |
| 无人机位置 | 36.702909°N 117.02233°E | stats.drone_position |
| 悬停状态 | 悬停 | stats.is_hovering |
| 方向流量 | 直行67% 左转20% 右转13% | stats.direction_flow |
| 平均车速 | 18.5 km/h | stats.avg_speed_kmh |

## 待完成

1. **修复 Kafka stale data**: 运行 `scripts/fix_kafka_and_restart.sh` 清除旧 broker ID 的 topic metadata
2. **验证本地 Kafka 生产**: HOST listener 路由修复后, 验证管道 → Kafka → Platform 完整数据流
3. **验证 MJPEG 视频流**: 运行管道 + Flask server, 验证 Monitor 页面显示视频
4. **优化道路多边形**: 使用帧图像精确标注道路多边形 (当前为粗略估计)
5. **添加 inter_xqh 交叉路口到 Platform DB**: 配置车道级统计数据


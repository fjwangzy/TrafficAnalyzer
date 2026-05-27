# ARCHITECTURE.md — TrafficAnalyzer 系统架构

> 基于 commit `e69acee` 的真实代码分析。

## 系统总览

TrafficAnalyzer 是一个环形交叉路口交通分析系统。核心功能：从视频流（MP4 文件或 RTSP 实时流）中检测车辆、跟踪轨迹、计算每条道路的拥堵统计，并通过 Grafana 仪表盘可视化结果。

```
┌─────────────────────────────────────────────────────────┐
│                    视频源（MP4/RTSP/摄像头）                │
└─────────────────────┬───────────────────────────────────┘
                      │ cv2.VideoCapture
                      ▼
┌─────────────────────────────────────────────────────────┐
│                   VideoReader (生成器)                    │
│  逐帧产出 FrameElement(source, frame, timestamp, roads)  │
└─────────────────────┬───────────────────────────────────┘
                      │ FrameElement
                      ▼
┌─────────────────────────────────────────────────────────┐
│             DetectionTrackingNodes                       │
│  YOLOv8 检测 → detected_* 字段                           │
│  ByteTrack 跟踪 → tracked_* + id_list 字段               │
└─────────────────────┬───────────────────────────────────┘
                      │ FrameElement（带检测结果）
                      ▼
┌─────────────────────────────────────────────────────────┐
│             TrackerInfoUpdateNode                        │
│  维护 buffer_tracks 字典（TrackElement）                  │
│  通过 shapely 判断车辆所属道路（start_road）               │
│  清理超时轨迹（> buffer_analytics 分钟）                  │
└─────────────────────┬───────────────────────────────────┘
                      │ FrameElement（带 buffer_tracks）
                      ▼
┌─────────────────────────────────────────────────────────┐
│             CalcStatisticsNode                           │
│  cars_amount = 滑动窗口平均车辆数                         │
│  roads_activity = 每条道路的车辆/分钟                     │
└─────────────────────┬───────────────────────────────────┘
                      │ FrameElement（带 info 字典）
                      ▼
┌─────────────────────────────────────────────────────────┐
│             KafkaProducerNode（可选）                     │
│  每 N 秒发送 JSON → Kafka topic (statistics_{n})          │
└─────────────────────┬───────────────────────────────────┘
                      │ FrameElement
                      ▼
┌─────────────────────────────────────────────────────────┐
│             ShowNode                                     │
│  绘制检测框 + 跟踪 ID + 道路多边形 + FPS + 统计面板       │
│  输出 → frame_result 字段                                │
└─────────────────────┬───────────────────────────────────┘
                      │ FrameElement（带 frame_result）
                      ▼
┌──────────────────────────┐  ┌──────────────────────────┐
│  VideoSaverNode（可选）    │  │ FlaskServerVideoNode     │
│  写入 MP4 文件             │  │ MJPEG 流 → /video        │
└──────────────────────────┘  └──────────────────────────┘
```

## 进程模型（4 种入口）

### main.py — 单进程顺序模式
- **用途**：调试、理解管道逻辑
- **特点**：所有节点在同一进程内顺序执行
- **缺点**：YOLO 推理阻塞后续节点，吞吐量最低

### main_optimized.py — 三进程并行模式（推荐）
- **进程 1**：VideoReader + DetectionTrackingNodes（CPU 读取 + GPU 推理）
- **进程 2**：TrackerInfoUpdate + CalcStatistics + KafkaProducer（CPU 密集）
- **进程 3**：ShowNode + VideoSaver + FlaskServer（渲染 + IO）
- **队列**：maxsize=50，进程间通过 `multiprocessing.Queue` 传递 FrameElement
- **为什么这样设计**：将 GPU 推理、CPU 计算、IO 操作分离到不同进程，利用多核并行

### main_stream_optimized.py — 双进程 RTSP 模式 v1
- **进程 1**（daemon）：VideoReader，队列满时丢弃旧帧（put_nowait）
- **主进程**：所有其他节点顺序执行
- **队列**：maxsize=2，保证处理最新帧
- **为什么这样设计**：RTSP 流不能暂停，必须优先保证实时性

### main_stream_optimized_v2.py — 双进程 RTSP 模式 v2
- 与 v1 相同架构，但增加了 `process.is_alive()` 双向健康检查
- 读取进程异常退出时，处理进程自动终止
- **为什么有 v1 和 v2**：v1 是快速原型，v2 修复了进程联动问题

## 微服务数据路径

```
Backend (KafkaProducerNode)
  │ JSON: {camera_id, cars, road_1..5}
  ▼
Kafka topic: statistics_{n}
  │
  ▼
Telegraf (kafka_consumer input, json data_format)
  │ name_override: camera_{n}
  ▼
InfluxDB 1.8 (database: "influx")
  │ measurement: camera_{n}
  │ fields: cars(float), road_1..5(float), camera_id(string)
  ▼
Grafana (provisioned dashboards)
  │ InfluxQL queries: SELECT mean("cars") FROM "camera_1"
  │                   SELECT road_1..5 FROM "camera_1"
  ▼
Dashboard panels: 车辆数时序图 + 道路拥堵条形图 + 趋势折线图
```

### Nginx 视频流聚合
```
http://localhost:8009/camera_{n}
  → proxy_pass http://traffic_analyzer_camera_{n}:8100/video
```
使用正则 `~ ^/camera_(\d+)$` 动态路由到对应摄像头容器的 Flask MJPEG 端点。

## 配置系统

使用 **Hydra** 分层配置管理：
- 主配置：`configs/app_config.yaml`
- 日志配置：`configs/hydra/job_logging/custom.yaml`
- 环境变量覆盖：`${oc.env:VIDEO_SRC}`、`${oc.env:TOPIC_NAME}` 等
- CLI 覆盖：`python main_optimized.py pipeline.save_video=True`

**为什么选择 Hydra**：原始项目来自俄罗斯团队，Hydra 提供了灵活的配置组合能力，允许通过环境变量为不同摄像头容器复用同一配置文件。

## 关键设计决策

### 1. FrameElement 作为共享数据载体
**决策**：所有节点通过读写同一个 FrameElement 对象来协作，而不是返回值或事件驱动。
**原因**：视频处理管道是严格线性的，每个节点只需要在上一节点的输出上追加数据。共享对象避免了数据拷贝和复杂的消息路由。
**代价**：FrameElement 的字段随节点增多而膨胀，新节点需要理解所有上游字段。

### 2. VideoEndBreakElement 哨兵模式
**决策**：使用特殊的 VideoEndBreakElement 类（继承 FrameElement）作为流结束信号，每个节点通过 `isinstance()` 检查来传递它。
**原因**：在 multiprocessing.Queue 中，无法发送 Python 异常或关闭信号。哨兵对象可以被序列化通过队列，每个节点看到后执行清理并退出。
**代价**：每个节点的 process() 方法开头都需要 isinstance 检查。

### 3. ByteTrack 而非 DeepSORT
**决策**：使用 ByteTrack 作为多目标跟踪算法。
**原因**：ByteTrack 利用低置信度检测框进行第二轮关联，在车辆密集场景（环形路口）中跟踪精度更高。不需要外观特征提取网络，推理更快。
**代价**：跟踪完全基于 IOU，当车辆被遮挡超过 track_buffer 帧后会丢失 ID。

### 4. 硬编码 5 条道路
**决策**：CalcStatisticsNode 和 KafkaProducerNode 中硬编码了 5 条道路（road_1..5）。
**原因**：原始项目针对特定的环形交叉路口设计，恰好有 5 条道路。
**代价**：增加或减少道路数量需要修改多个文件和 Grafana 仪表盘。这是最大的技术债之一。

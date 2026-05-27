# PROJECT_STRUCTURE.md — TrafficAnalyzer 项目结构

> 基于 commit `e69acee` 的真实代码分析。

## 目录结构

```
TrafficAnalyzer/
├── main.py                        # 单进程顺序入口（调试用）
├── main_optimized.py              # 三进程并行入口（MP4 推荐）
├── main_stream_optimized.py       # 双进程入口（RTSP v1）
├── main_stream_optimized_v2.py    # 双进程入口（RTSP v2，带健康检查）
├── generate_lanes.py              # 交互式道路多边形标注工具
├── export_dashboards.py           # Grafana 仪表盘导出脚本
├── fetch_dashboard.py             # Grafana 仪表盘获取脚本
├── update_dashboards.py           # Grafana 仪表盘翻译/更新脚本
├── requirements.txt               # Python 依赖清单（7 个）
├── Dockerfile                     # GPU 容器镜像构建
├── docker-compose.yaml            # 完整微服务栈编排
├── dashboard_backup.json          # Grafana 仪表盘 JSON 备份
│
├── elements/                      # 数据模型层
│   ├── FrameElement.py            #   帧数据载体（管道核心数据结构）
│   ├── TrackElement.py            #   单条轨迹状态
│   └── VideoEndBreakElement.py    #   视频流结束哨兵
│
├── nodes/                         # 管道节点层
│   ├── VideoReader.py             #   视频帧读取（MP4/RTSP/摄像头）
│   ├── DetectionTrackingNodes.py  #   YOLOv8 检测 + ByteTrack 跟踪
│   ├── TrackerInfoUpdateNode.py   #   轨迹缓冲区管理 + 道路分配
│   ├── CalcStatisticsNode.py      #   统计计算（车辆数 + 道路活跃度）
│   ├── KafkaProducerNode.py       #   Kafka 消息发送
│   ├── ShowNode.py                #   OpenCV 可视化渲染
│   ├── VideoSaverNode.py          #   视频文件保存
│   └── FlaskServerVideoNode.py    #   Flask MJPEG 视频流服务
│
├── byte_tracker/                  # ByteTrack 跟踪算法（第三方移植）
│   ├── byte_tracker_model.py      #   STrack + BYTETracker 核心
│   └── utils/
│       ├── basetrack.py           #   轨迹基类 + TrackState 枚举
│       ├── kalman_filter.py       #   8 维恒速卡尔曼滤波器
│       └── matching.py            #   IOU 计算 + 线性分配（lap 库）
│
├── utils_local/                   # 工具层
│   ├── utils.py                   #   环境变量、FPS 计数器、几何判定
│   └── templates/
│       └── index.html             #   Flask 视频流页面模板
│
├── configs/                       # 配置层
│   ├── app_config.yaml            #   Hydra 主配置（中文版）
│   ├── app_config copy.yaml       #   Hydra 主配置（俄语备份）
│   ├── entry_exit_lanes.json      #   路口 A 道路多边形（5 条路）
│   ├── inter1_lanes.json          #   路口 1 道路多边形（5 条路）
│   ├── inter2_lanes.json          #   路口 2 道路多边形（2 条路）
│   └── hydra/
│       └── job_logging/
│           └── custom.yaml        #   Hydra 日志格式配置
│
├── weights/                       # 模型权重
│   ├── uav_best.pt                #   自定义无人机视角 YOLOv8 模型
│   ├── yolov8m.pt                 #   YOLOv8 Medium 预训练模型
│   └── YOLOv8_TensorRT_converter.ipynb
│
├── services/                      # 微服务配置
│   ├── kafka/
│   │   ├── kafka_server_jaas.conf #   Kafka JAAS 认证
│   │   └── init-kafka-broker.sh   #   Kafka 初始化脚本
│   ├── telegraf/
│   │   └── telegraf.conf          #   Telegraf Kafka→InfluxDB 配置
│   ├── nginx/
│   │   └── nginx.conf             #   Nginx 视频流反向代理
│   └── grafana/
│       └── provisioning/
│           └── dashboards/
│               ├── dashboard.yaml #   Grafana provisioning 配置
│               ├── camera-1.json  #   摄像头 1 仪表盘
│               └── camera-2.json  #   摄像头 2 仪表盘
│
├── test_videos/                   # 测试数据
│   ├── rtsp_streaming/            #   RTSP 流测试环境
│   │   ├── docker-compose.yaml    #     MediaMTX 容器
│   │   ├── mediamtx.yml           #     MediaMTX 配置
│   │   └── ffmpeg_rtsp.ipynb      #     FFmpeg 推流 notebook
│   └── 交通路口数据采集2/          #   济南路口采集记录
│
└── content_for_readme/            # README 素材
    └── architecture.drawio        #   架构图源文件
```

## 文件数量统计

| 类别 | 数量 | 说明 |
|------|------|------|
| Python 源码 | 24 | 核心业务逻辑 |
| 配置文件 | 12 | YAML/JSON/CONF |
| 文档 | 7 | README + 设计文档 |
| 基础设施 | 4 | Dockerfile + Compose + 服务配置 |
| 工具脚本 | 4 | 标注/导出/获取/更新 |
| 模型权重 | 2 | .pt 二进制文件 |
| 测试数据 | 4+ | 视频 + 采集记录 |

## 核心依赖关系

```
main*.py → elements/* → nodes/* → byte_tracker/*
                                  ↓
                          utils_local/utils.py
                                  ↓
                     configs/*.yaml + configs/*.json
```

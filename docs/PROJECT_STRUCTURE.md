# PROJECT_STRUCTURE.md — TrafficAnalyzer 项目结构

> 基于 commit `84c6bd6` 的真实代码分析。

## 目录结构

```
TrafficAnalyzer/
├── main.py                        # 单进程顺序入口（调试用）
├── main_optimized.py              # 多进程并行入口（唯一生产入口，含健康检查）
├── generate_lanes.py              # 交互式道路多边形标注工具
├── export_dashboards.py           # Grafana 仪表盘导出脚本
├── fetch_dashboard.py             # Grafana 仪表盘获取脚本
├── update_dashboards.py           # Grafana 仪表盘翻译/更新脚本
├── requirements.txt               # Python 依赖清单（11 个）
├── create_ppt.py                  # 项目汇报PPT自动生成（PPTX格式）
├── create_ppt_v3.py               # PPT生成v3（简化版）
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
│   ├── VideoReader.py             #   视频帧读取（MP4/RTSP/摄像头）+ 遥测注入
│   ├── DetectionTrackingNodes.py  #   YOLO11 检测 + ByteTrack 跟踪（保留YOLO原始类别）
│   ├── HomographyCalibrationNode.py # 单应性矩阵计算（遥测/参考点/auto模式）
│   ├── MotionCompensationNode.py  #   无人机运动补偿（GPS锚定+位移+速度+悬停检测）
│   ├── TrackerInfoUpdateNode.py   #   轨迹缓冲区 + 道路分配 + motor/non_motor + 完成轨迹发射
│   ├── SpeedEstimationNode.py     #   车速估计（km/h，减去无人机速度）
│   ├── DirectionFlowNode.py       #   方向流量分类（左转/直行/右转/掉头）
│   ├── LaneAnalysisNode.py        #   车道级分析（流量/排队/车头时距，数据驱动）
│   ├── LaneDetectionNode.py       #   YOLO分割模型车道检测（标线/路面→稳定车道多边形）
│   ├── TrajectoryNode.py          #   轨迹转向分类 + 世界坐标轨迹输出
│   ├── AutoLaneInferenceNode.py   #   自动车道推断（轨迹聚类→中心线→各方向指标，无需标注）
│   ├── ConflictDetectionNode.py   #   机非未来轨迹碰撞预测（默认启用）
│   ├── CalcStatisticsNode.py      #   统计计算（车辆数 + 道路活跃度）
│   ├── KafkaProducerNode.py       #   Kafka 多topic消息发送
│   ├── ShowNode.py                #   supervision 可视化渲染（圆角边框/标签/轨迹尾迹/道路遮罩/统计面板）
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
│   ├── homography.py              #   单应性矩阵计算（遥测/参考点）、像素↔世界坐标变换
│   ├── motion_compensation.py     #   无人机运动补偿（GPS→ENU、速度矢量、补偿变换）
│   ├── trajectory_classifier.py   #   转向行为分类（直行/左转/右转/掉头）
│   ├── lane_geometry.py           #   车道多边形操作、排队长度计算
│   ├── auto_lane_inference.py     #   自动车道推断（轨迹聚类、中心线拟合、标签生成）
│   └── templates/
│       └── index.html             #   Flask 视频流页面模板
│
├── services/                      # 微服务配置 + 运行时服务
│   ├── TelemetrySubscriber.py     #   MQTT遥测订阅器（paho-mqtt v2，时间戳同步缓冲区）
│   ├── TelemetryFileReader.py     #   文件遥测加载器（DJI Cloud API JSON，离线回放）
│   └── SrtTelemetryParser.py      #   SRT遥测解析器（DJI视频字幕，逐帧同步）
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
│   ├── uav_best.pt                #   自定义无人机视角 YOLO11 模型
│   ├── lane_detect.pt             #   YOLO 分割模型（车道标线/路面检测）
│   ├── yolov8m.pt                 #   YOLOv8 Medium 预训练模型（旧版，已弃用）
│   └── YOLOv8_TensorRT_converter.ipynb  # TensorRT 转换工具（旧版）
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
│   ├── inter_xqh/                 #   济南小清河北路无人机采集（4K+SRT遥测）
│   │   ├── DJI_*.mp4              #     4K@30fps, 16.5min 飞行视频
│   │   ├── telemetry.srt          #     29,741 条逐帧遥测记录
│   │   └── 航线计划*.txt           #     DJI 飞行计划
│   └── 交通路口数据采集2/          #   济南路口采集记录
│
├── test_pipeline_inter_xqh.py     # 管道端到端测试（4K视频+SRT遥测，49项检查）
├── test_pipeline_no_yolo.py       # 管道测试（无YOLO，CI用）
│
├── platform/                      # Web 管理平台（FastAPI 单体应用）
│   ├── app/
│   │   ├── main.py                #   FastAPI 入口 + lifespan
│   │   ├── api/v1/
│   │   │   ├── pipelines.py       #   管道管理 REST API
│   │   │   ├── drones.py          #   无人机管理
│   │   │   ├── intersections.py   #   路口管理（含无人机分配）
│   │   │   └── system.py          #   系统健康 + GPU 指标
│   │   ├── kafka/
│   │   │   ├── consumer.py        #   Kafka 消费者（stats/track/conflict/telemetry）
│   │   │   └── ws_manager.py      #   WebSocket 频道 pub/sub
│   │   ├── services/
│   │   │   ├── pipeline_manager.py #  管道生命周期管理（子进程）
│   │   │   └── alert_engine.py    #   告警规则引擎
│   │   └── models/
│   │       └── drone_store.py     #   无人机状态存储（Kafka双源更新）
│   ├── scripts/
│   │   └── run_local.py           #   本地开发启动脚本
│   └── pyproject.toml             #   平台依赖清单
│
└── content_for_readme/            # README 素材
    └── architecture.drawio        #   架构图源文件
```

## 文件数量统计

| 类别 | 数量 | 说明 |
|------|------|------|
| Python 源码 | 52 | 核心业务逻辑（含14个节点+工具+测试+PPT生成脚本） |
| 配置文件 | 12 | YAML/JSON/CONF |
| 文档 | 22 | README + 设计文档 + 架构文档 + 测试报告 + POC规划 |
| 基础设施 | 4 | Dockerfile + Compose + 服务配置 |
| 平台 | 32 | FastAPI 单体应用（API/Kafka/Services/Models + 遗留微服务） |
| 工具脚本 | 4 | 标注/导出/获取/更新 |
| 模型权重 | 3 | .pt 二进制文件（目标检测 + 车道分割） |
| 测试数据 | 6+ | 视频 + SRT遥测 + 采集记录 |

## 核心依赖关系

```
main*.py → elements/* → nodes/* → byte_tracker/*
                                  ↓
                          utils_local/utils.py
                                  ↓
                     configs/*.yaml + configs/*.json
```

---

## 平台目录结构（platform/）

> 2026-05-29 从微服务重构为单体架构。

```
platform/
├── app/                             # 单体应用
│   ├── main.py                      #   FastAPI 应用入口 + lifespan
│   ├── __init__.py
│   │
│   ├── core/                        #   核心配置
│   │   ├── config.py                #     Pydantic Settings（统一配置）
│   │   └── database.py              #     SQLAlchemy async engine + session
│   │
│   ├── api/                         #   API 路由层
│   │   └── v1/
│   │       ├── auth.py              #     认证端点（register/login/me）
│   │       ├── intersections.py     #     路口管理
│   │       ├── drones.py            #     无人机管理
│   │       ├── trajectories.py      #     车辆轨迹查询
│   │       ├── alerts.py            #     告警规则和告警历史
│   │       ├── video.py             #     视频流管理
│   │       ├── calibration.py       #     摄像头标定
│   │       └── system.py            #     系统健康检查
│   │
│   ├── kafka/                       #   Kafka 集成
│   │   ├── consumer.py              #     Kafka 消费者（aiokafka）
│   │   └── ws_manager.py            #     WebSocket pub/sub 管理器
│   │
│   ├── middleware/                  #   中间件
│   │   └── auth.py                  #     JWT 认证中间件
│   │
│   ├── services/                    #   业务逻辑层
│   │   ├── auth_service.py          #     用户认证（PyJWT + bcrypt）
│   │   ├── alert_engine.py          #     告警规则引擎
│   │   ├── lane_annotation_store.py #     悬停生成车道标注任务 + 人工标注参数持久化
│   │   └── pipeline_manager.py      #     检测管道生命周期管理
│   │
│   ├── models/                      #   数据模型
│   │   ├── user.py                  #     User SQLAlchemy 模型
│   │   └── drone_store.py           #     无人机内存存储
│   │
│   ├── schemas/                     #   Pydantic 模式
│   │   └── auth.py                  #     认证相关 schema
│   │
│   └── utils/                       #   工具函数
│       └── influx_query.py          #     InfluxDB 查询封装
│
├── docker/                          # Docker 配置
│   └── docker-compose.platform.yml  #   平台完整栈（platform + postgres + kafka + influxdb + frontend）
│
├── scripts/                         # 开发脚本
│   ├── run_local.py                 #   本地启动脚本（设置默认环境变量）
│   ├── fix_kafka_and_restart.sh     #   Kafka 基础设施修复脚本（清除 stale data + 重建 topics）
│   └── inject_test_data.py          #   WebSocket 测试数据注入（Kafka 不可用时验证前端）
│
├── Dockerfile                       # 平台容器镜像
├── pyproject.toml                   # 依赖清单（hatchling 构建）
├── README.md                        # 平台说明文档
├── MONOLITH.md                      # 单体架构迁移说明
└── REFACTORING_SUMMARY.md           # 重构总结
```

### 遗留目录（待删除）

以下目录是微服务架构遗留代码，已不再使用：

```
platform/
├── gateway/                         # [已弃用] API 网关
├── services/                        # [已弃用] 微服务（flight/vision/operations）
├── shared/                          # [已弃用] 共享库
└── frontend/                        # [已弃用] 前端（已迁移至 traffic-fly-console/）
```

### 前端目录（traffic-fly-console/）

```
traffic-fly-console/
├── nginx.conf                       # Nginx 反向代理配置
│                                    #   /api/ → platform:8000
│                                    #   /ws/  → platform:8000
│                                    #   /camera_1..3 → 对应检测容器 MJPEG
├── Dockerfile                       # 前端容器镜像
├── README.md                        # Console 本地/Docker 启动与验证命令
└── src/features/                    # 主导航业务页面（Dashboard/Monitoring/GIS/Drones/Reports/Admin/Users 等）
```

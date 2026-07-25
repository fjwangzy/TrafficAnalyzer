# CLAUDE.md — Claude 长期协作规则

> 本文件是 Claude 作为 TrafficAnalyzer 长期核心工程师的协作规范。
> 所有开发工作必须先阅读本文件。

## 数据架构优先级（ADR-019）

目标架构固定为 PostgreSQL connection database=`road9` + TimescaleDB；UAV 内部 Topic、`msg_type`、WebSocket channel 和本项目自建表使用 `uav_` 前缀；InfluxDB、Telegraf、Grafana 为迁移后退役链路。本文中仍出现的旧 Topic、InfluxDB/Grafana 或 Telegraf 描述只表示当前遗留实现，不得用于新增功能；若与 `DECISIONS.md` ADR-019、`ARCHITECTURE.md`、`API_CONTRACTS.md`、`DATABASE_SCHEMA.md` 冲突，以后者为准。

## 项目概要

TrafficAnalyzer 是智慧交通大项目下的无人机交通 AI 子系统，使用 YOLO11 检测车辆、ByteTrack 跟踪轨迹并计算态势/冲突。当前代码仍有 Kafka→Telegraf/InfluxDB→Grafana 遗留链路；目标数据链路为 `uav_*` Kafka → PostgreSQL database=`road9`/TimescaleDB → Platform API/WebSocket。

## 开发规则

### 1. 先读后写
- 修改任何文件前，必须先 Read 该文件及其直接依赖
- 修改管道节点前，必须先理解 FrameElement 的字段生命周期
- 修改配置前，必须先确认所有使用该配置项的节点

### 2. 管道节点规范
- 每个节点必须是一个类，包含 `__init__(self, config)` 和 `process(self, frame_element)` 方法
- `process()` 方法开头必须检查 `isinstance(frame_element, VideoEndBreakElement)`，如果是则直接返回
- `process()` 方法必须返回 frame_element（或 None，仅对于终端节点）
- 节点不得持有帧级别的状态，所有状态必须存储在 FrameElement 上
- 使用 `@profile_time` 装饰器标记 `process()` 方法

### 3. 数据模型规范
- FrameElement 的新字段必须在 `__init__` 中声明，初始值为 None
- 使用 Python 3.10+ 联合类型语法：`np.ndarray | None`
- TrackElement 的字段修改必须同步更新 TrackerInfoUpdateNode 和 CalcStatisticsNode
- 禁止在 FrameElement 上动态添加未声明的属性（当前 KafkaProducerNode 的 `send_to_kafka` 是历史遗留问题）

### 4. 配置规范
- 所有配置项必须定义在 `configs/app_config.yaml` 中
- 需要跨容器变化的值使用 `${oc.env:VAR_NAME}` 环境变量注入
- 新增配置项必须同时更新 `app_config copy.yaml`（俄语备份）
- 道路数量不得硬编码（当前是技术债，见 DECISIONS.md）

### 5. 进程模型规范
- 唯一的管道入口是 `main_optimized.py`（3 进程并行 + 健康检查），不得新增入口文件
- 队列的 `maxsize` 是关键调优参数：当前使用 50
- 所有子进程必须设置 `daemon=True`
- VideoEndBreakElement 是唯一的流结束信号，不得使用 Queue 关闭或其他机制

### 6. 平台服务规范（单体架构）
- `platform/` 已从微服务重构为**单体架构**（2026-05-29）
- 所有 API 端点位于 `platform/app/api/v1/`，由单一 FastAPI 应用提供服务
- **禁止**重新引入微服务拆分（gateway、独立 service 等）
- **禁止**使用 python-jose（ARM64 兼容性问题），必须使用 PyJWT
- 新增 API 端点必须添加 JWT 认证中间件保护（公开端点除外）
- Kafka 消费者和 WebSocket 管理器在应用 lifespan 中初始化和启动
- 目标历史查询使用 PostgreSQL/TimescaleDB；InfluxQL 只允许在迁移兼容适配器中读取旧数据，不得扩展为新查询契约
- 前端 `traffic-fly-console/nginx.conf` 必须代理到 `platform:8000`（不是 gateway）

### 7. 摄像头微服务规范（视频分析管道）
- 视频分析管道（`main*.py`）仍使用独立容器模式
- 新增摄像头必须：
  1. 在 `docker-compose.yaml` 添加 `traffic_analyzer_camera_{n}` 服务
  2. 使用统一 Topic builder 发布 `uav_statistics_{camera_id}` 等目标消息
  3. 配置 Platform 消费、`road9` 写入和 API/WebSocket 展示，不新增 Telegraf/Grafana 配置
  4. Nginx 配置无需修改时继续使用正则动态路由

### 7. 第三方代码规范
- `byte_tracker/` 目录是从开源项目移植的代码，保持其原始结构
- 修改 ByteTrack 参数只通过 `configs/app_config.yaml` 的 `tracking_node` 部分
- 不得修改 `byte_tracker/utils/kalman_filter.py` 和 `byte_tracker/utils/matching.py`，除非有明确的算法改进需求

## 架构原则

### 必须遵守
- **节点式管道**：新功能必须作为管道节点实现，不得在 main*.py 中添加内联逻辑
- **FrameElement 单一数据流**：节点间通信只通过 FrameElement 字段，不得使用全局变量或外部存储
- **配置驱动**：所有可变参数必须通过 Hydra 配置，不得硬编码
- **进程隔离**：GPU 推理、CPU 计算、IO 操作应分离到不同进程

### 设计模式
- **生成器模式**：VideoReader 使用 `yield` 逐帧产出，这是管道起点的标准模式
- **惰性初始化**：VideoSaverNode 在首帧时才创建 VideoWriter（因为需要知道分辨率）
- **哨兵模式**：VideoEndBreakElement 作为流结束信号，通过 isinstance 检查传递

## 禁止事项

1. **禁止在节点 process() 方法中抛出异常来终止管道** — 必须使用 VideoEndBreakElement
2. **禁止在 FrameElement 上存储大对象**（如完整的帧历史）— 内存会在多进程队列中爆炸
3. **禁止修改 BaseTrack._count 全局计数器** — 它是跨进程不安全的，但在单进程内可以工作
4. **禁止在 ShowNode 中添加业务逻辑** — 它只负责渲染
5. **禁止在 Dockerfile 中使用 `latest` 标签的 GPU 基础镜像** — 当前使用 `python:3.10.13` 是有意的
6. **禁止在 kafka_producer_node 配置中硬编码 bootstrap_servers** — 本地开发和 Docker 环境使用不同的地址
7. **禁止新增或扩展 Grafana 仪表盘** — Grafana 已进入退役范围；遗留文件只允许迁移、归档和安全清理
8. **禁止在 platform/ 中使用 python-jose** — ARM64 上会触发 SIGILL（exit 132），必须使用 PyJWT
9. **禁止将 platform/ 重新拆分为微服务** — 已经过单体架构验证，微服务增加了不必要的复杂度
10. **禁止在 platform/app/main.py 的 lifespan 中阻塞启动** — PostgreSQL/TimescaleDB、Kafka 等依赖必须按批准策略就绪或显式降级，不得静默吞掉持久化失败

## 模块边界

```
elements/     ← 只被 nodes/ 和 main*.py 引用
nodes/        ← 只引用 elements/、utils_local/、byte_tracker/
byte_tracker/ ← 自包含模块；当前由 GroundTrajectoryTrackerNode 引用，旧组合节点仅供 legacy 回滚
utils_local/  ← 被 nodes/ 和 main*.py 引用
configs/      ← 只被 Hydra 框架和 VideoReader 读取
services/     ← 只被 Docker Compose 使用，Python 代码不直接引用
main*.py      ← 顶层入口，引用所有模块

platform/app/ ← 单体 Web 平台，独立模块
  ├── api/v1/     ← REST 端点，只被 main.py 路由注册
  ├── core/       ← 配置和数据库，被 api/ 和 services/ 引用
  ├── kafka/      ← Kafka 消费者和 WebSocket，只被 main.py lifespan 管理
  ├── services/   ← 业务逻辑，被 api/ 引用
  ├── models/     ← SQLAlchemy 模型
  └── utils/      ← InfluxDB 查询工具
```

## 类型规范

- 使用 Python 3.10+ 联合类型：`int | None`，不用 `Optional[int]`
- numpy 数组标注为 `np.ndarray`（不标注 dtype）
- 配置字典标注为 `dict`（不使用 TypedDict，因为 Hydra 的 OmegaConf 类型不兼容）
- 返回值标注必须一致：节点的 `process()` 返回 `FrameElement`

## API 规范

### 视频分析管道 Kafka 遗留消息格式（仅迁移适配器兼容）

以下无前缀/固定道路字段是当前遗留格式，不再是“不可更改”的目标契约。目标生产者必须遵循 `API_CONTRACTS.md` 的 `uav_*` 信封、动态粒度和时间语义；迁移期适配器可读取旧格式，但须有退役日期。
```json
{
  "camera_id": "id_{camera_id}",
  "cars": <int>,
  "road_1": <float | null>,
  "road_2": <float | null>,
  "road_3": <float | null>,
  "road_4": <float | null>,
  "road_5": <float | null>
}
```

### 视频分析管道 Flask 端点
- `GET /` — 返回 index.html 模板
- `GET /video` — MJPEG 流（multipart/x-mixed-replace）

### 视频分析管道 Nginx 路由
- `GET /camera_{n}` → 代理到 `traffic_analyzer_camera_{n}:8100/video`

### 平台 Web 服务 API（platform/app/api/v1/）

**认证端点（无需 JWT）：**
- `POST /api/v1/auth/register` — 用户注册（username, email, password, role）
- `POST /api/v1/auth/login` — 用户登录（返回 JWT token）

**受保护端点（需 Bearer token）：**
- `GET /api/v1/auth/me` — 当前用户信息
- `GET /api/v1/intersections` — 路口列表
- `GET /api/v1/drones` — 无人机列表
- `POST /api/v1/drones` — 创建无人机
- `GET /api/v1/trajectories` — 车辆轨迹
- `GET /api/v1/alerts` — 告警列表
- `GET /api/v1/system/health` — 系统健康状态
- `GET /api/v1/video/streams` — 视频流列表

**WebSocket 端点：**
- `WS /ws/{channel}` — 实时数据推送（需 subscribe 消息）

**健康检查（无需认证）：**
- `GET /health` — 存活检查
- `GET /ready` — 就绪检查（含依赖状态）

## 数据访问规范

- 目标连接 database 固定为 `road9`，但 schema、账号和权限必须显式配置，不得假定同名 schema。
- 时序指标、遥测、轨迹点和冲突事实写 TimescaleDB Hypertable；事务对象写普通 `uav_*` PostgreSQL 表。
- `uav_message_inbox` 以 `(source_system,message_id)` 提供长期消费幂等，并与事实写入同一事务；Kafka offset 只能在事务成功后提交。
- 旧 InfluxDB 只读用于迁移；旧 `time` 不得统一映射为 `occurred_at`，须保留原始时间、语义和质量并隔离 epoch 异常。
- 新增/修改表、Topic、保留、压缩和迁移规则必须同步 `DATABASE_SCHEMA.md`，不得通过运行时 `create_all()` 隐式变更生产 schema。

## 重构规范

### 已完成的重构
- **平台单体化（2026-05-29）**：将 `platform/` 从 4 个微服务（gateway、operations、vision、flight）合并为单一 FastAPI 应用
  - 所有 API 端点保留原始路径和响应格式
  - 前端 `traffic-fly-console/nginx.conf` 已更新为代理到 `platform:8000`
  - JWT 库从 python-jose 迁移到 PyJWT（ARM64 兼容性）
  - 本地启动和 Docker Compose 两种工作流均已验证

### 允许的重构
- 提取重复的进程启动逻辑到公共函数
- ~~将 ShowNode 的渲染逻辑拆分为子方法~~ ✅ 已完成（2026-06-09，使用 supervision 库重构为 10 个子方法）
- ~~从轨迹数据自动推断车道中心线~~ ✅ 已完成（2026-06-09，AutoLaneInferenceNode 替代人工标注）
- ~~YOLO 分割模型车道检测~~ ✅ 已完成（2026-06-10，LaneDetectionNode，三级优先级链：manual > model > auto）
- 为 CalcStatisticsNode 和 KafkaProducerNode 中的硬编码道路数量引入配置化
- **清理 platform/ 下的遗留微服务目录**（gateway/、services/、shared/、frontend/）— 已确认不再使用

### 需要讨论的重构
- 合并 4 个 main*.py 入口为统一的入口 + 运行模式配置
- 将 VideoEndBreakElement 哨兵模式替换为管道事件系统
- 将 byte_tracker/ 替换为 ultralytics 内置的跟踪器

### 禁止的重构
- 不得将 FrameElement 改为 dataclass（会破坏多进程序列化）
- 不得将 Hydra 替换为其他配置框架（整个项目深度依赖）
- 不得升级或扩建 InfluxDB/Grafana 链路；按 ADR-019 迁移至 `road9`/TimescaleDB 并完成对账后退役

## 测试规范

当前项目没有测试框架。如果添加测试：
- 使用 pytest
- 优先为 `utils_local/utils.py` 和 `byte_tracker/` 编写单元测试
- 管道节点测试需要 mock FrameElement
- 不得为 main*.py 编写集成测试（需要 GPU 和完整微服务栈）

## 代码风格

- 注释和变量名使用中英混合（项目历史原因，保持一致性）
- 日志使用 Python logging 模块，不使用 print（除了 main*.py 中的启动信息）
- 错误处理使用 assert + 描述信息，不使用 try/except（除了队列操作）

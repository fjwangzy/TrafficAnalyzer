# DATABASE_SCHEMA.md — TrafficAnalyzer 数据库结构

> 基于 commit `e69acee` 的真实代码分析。

## InfluxDB 1.8

### 连接信息
| 参数 | 值 |
|------|------|
| 版本 | InfluxDB 1.8 |
| 端口 | 8086（容器内）/ 8087（宿主机映射） |
| 数据库 | `influx` |
| 保留策略 | 自动创建，30 天保留 |
| 认证 | 环境变量 `INFLUXDB_ADMIN_USER` / `INFLUXDB_ADMIN_PASSWORD` |

平台启动时会通过 `platform/app/utils/influx_query.py::InfluxQuery` 检查目标数据库；
若 `influx` 不存在会自动创建并切换到该库。根 `docker-compose.yaml` 同时配置
`INFLUX_DB=influx`（应用读取）和 `INFLUXDB_DB=influx`（InfluxDB 1.8 首次初始化读取），
确保新卷和已有旧卷都能自愈。

### Measurement: `camera_{N}`（Telegraf/Grafana 兼容链路）

每个摄像头一个 measurement，由 Telegraf 的 `name_override` 配置控制。

#### 字段（Fields）

| 字段名 | 数据类型 | 说明 | 来源 |
|--------|----------|------|------|
| `cars` | float | 当前帧滑动窗口平均车辆数 | CalcStatisticsNode → KafkaProducerNode |
| `road_1` ~ `road_N` | float | 动态道路活跃度（辆/分钟）；兼容字段，平台主契约优先使用 `roads` 数组 | CalcStatisticsNode |
| `camera_id` | string | 摄像头标识（格式 `id_{N}`） | KafkaProducerNode |

#### 标签（Tags）
| 标签名 | 说明 |
|--------|------|
| `host` | Telegraf 自动添加的主机名 |

#### 时间戳
- 由 Telegraf 的 `interval = "2s"` 控制写入频率
- 实际数据频率由 KafkaProducerNode 的 `how_often_sec`（默认 1 秒）控制

### Measurement: `intersection_stats`（Platform 复盘链路）

平台 Kafka consumer 收到 `statistics_*` 后通过 `platform/app/utils/influx_query.py::write_stats()` 写入，用于平台历史统计查询。

#### 标签（Tags）

| 标签名 | 说明 |
|--------|------|
| `intersection_id` | 路口标识，如 `INT_camera_1` |
| `camera_id` | 摄像头标识，如 `id_1` |

#### 字段（Fields）

| 字段名 | 数据类型 | 说明 |
|--------|----------|------|
| `cars` | float | 当前帧车辆数/滑动平均车辆数 |
| `fps` | float | 检测管道处理帧率 |
| `congestion_index` | float | 多因子拥堵指数 |
| `active_tracks` | int | 当前活跃轨迹数 |
| `total_vehicles` | int | 累计车辆数 |
| `road_1` ~ `road_8` | float | 动态道路活跃度，按消息中 roads 或兼容字段写入 |
| `dir_straight_count` / `dir_left_turn_count` / `dir_right_turn_count` / `dir_u_turn_count` | int | 各方向车辆数 |
| `dir_*_avg_speed` | float | 各方向平均速度 |
| `avg_speed_kmh` | float | 整体平均速度 |
| `queue_count` | int | 当前排队车辆数 |

### Measurement: `track_events`

平台 Kafka consumer 收到 `track_complete_*` 后通过 `write_track_event()` 写入，用于轨迹历史查询、转向统计和 BEV 复盘。

#### 标签（Tags）

| 标签名 | 说明 |
|--------|------|
| `intersection_id` | 路口标识 |
| `turn_behavior` | `straight` / `left_turn` / `right_turn` / `u_turn` / `unknown` |
| `vehicle_class` | `motor` / `non_motor` / `unknown` |

#### 字段（Fields）

| 字段名 | 数据类型 | 说明 |
|--------|----------|------|
| `track_id` | int | 跟踪 ID |
| `duration_sec` | float | 轨迹持续时间 |
| `avg_speed_kmh` | float | 平均速度 |
| `max_speed_kmh` | float | 最大速度 |
| `trajectory_world_m` | string(JSON) | 世界坐标轨迹点列 |
| `trajectory_px` | string(JSON) | 像素坐标轨迹点列 |
| `entry_point_m` | string(JSON) | 入口世界坐标 |
| `exit_point_m` | string(JSON) | 出口世界坐标 |
| `world_anchor_lat_lon` | string(JSON) | 世界坐标 GPS 锚点 |
| `start_road` | int | 起始道路 ID（有道路标注时） |
| `exit_road` | int | 离开道路 ID（有道路标注时） |

### Measurement: `conflict_events`

平台 Kafka consumer 收到 `conflicts_*` 后通过 `write_conflict_event()` 写入，用于冲突事件历史复盘。

#### 标签（Tags）

| 标签名 | 说明 |
|--------|------|
| `intersection_id` | 路口标识 |
| `severity` | `warning` / `critical` / `info` |
| `prediction_type` | `path_intersection` / `same_time_cpa` 等候选来源 |
| `conflict_scene` | `suspected_right_turn_mv_nmv` / `suspected_unprotected_left_turn` 等业务场景 |

#### 字段（Fields）

| 字段名 | 数据类型 | 说明 |
|--------|----------|------|
| `motor_id` | int | 机动车轨迹 ID |
| `non_motor_id` | int | 非机动车轨迹 ID |
| `ttc_sec` | float | 预测碰撞时间 |
| `distance_m` | float | 预测冲突时刻双方距离 |
| `pet_sec` | float | 双方到达冲突点时间差 |
| `arrival_time_delta_sec` | float | 到达时间差（与 `pet_sec` 同源，便于前端/报表读取） |
| `motor_arrival_ttc_sec` | float | 机动车到达冲突点预测时间 |
| `non_motor_arrival_ttc_sec` | float | 非机动车到达冲突点预测时间 |
| `conflict_angle_deg` | float | 双方速度向量夹角 |
| `risk_score` | int | 0-100 风险分 |
| `motor_speed_kmh` | float | 机动车速度 |
| `evidence` | string(JSON) | near-miss 证据数组，如 `hard_ttc_or_pet`、`hard_pet`、`hard_deceleration` |
| `motor_position_m` | string(JSON) | 机动车预测冲突点世界坐标 |
| `non_motor_position_m` | string(JSON) | 非机动车预测冲突点世界坐标 |
| `world_anchor_lat_lon` | string(JSON) | 世界坐标 GPS 锚点 |

### 数据写入路径

```
KafkaProducerNode.send(topic="statistics_{N}", value={...})
  ↓ JSON 序列化
Kafka topic: statistics_{N}
  ↓ Telegraf kafka_consumer input
Telegraf (data_format = "json", name_override = "camera_{N}")
  ↓ line protocol
InfluxDB measurement: camera_{N}

Platform KafkaConsumer 订阅 ((statistics|track_complete|conflicts|telemetry)_.*|system_metrics)
  ↓ statistics_*       → write_stats()
  ↓ track_complete_*   → write_track_event()
  ↓ conflicts_*        → write_conflict_event()
InfluxDB measurements: intersection_stats / track_events / conflict_events
```

### Telegraf 配置（关键部分）
```toml
[[outputs.influxdb]]
  urls = ["http://influxdb:8086"]
  database = "influx"

[[inputs.kafka_consumer]]
  brokers = ["kafka:29092"]
  topics = ["statistics_1"]
  data_format = "json"
  name_override = "camera_1"
  json_string_fields = ["camera_id",]

[[inputs.kafka_consumer]]
  brokers = ["kafka:29092"]
  topics = ["statistics_2"]
  data_format = "json"
  name_override = "camera_2"
  json_string_fields = ["camera_id",]
```

**为什么 `json_string_fields` 只包含 `camera_id`**：默认情况下 Telegraf 将 JSON 中的字符串字段忽略。`camera_id` 是唯一需要保留的字符串字段（作为 field 而非 tag 存储）。

### 查询模式（Grafana/Platform InfluxQL）

#### 车辆数时序图
```sql
SELECT mean("cars")
FROM "camera_1"
WHERE $timeFilter
GROUP BY time($interval)
```
- 使用 `mean()` 聚合以适应 Grafana 的时间分辨率
- `$timeFilter` 和 `$interval` 是 Grafana 模板变量

#### 当前道路拥堵（最新值）
```sql
SELECT *
FROM "camera_1"
ORDER BY time DESC
LIMIT 1
```
实际仪表盘可按路口配置选择 `road_1` ~ `road_N` 字段。

#### 道路拥堵趋势
```sql
SELECT *
FROM "camera_1"
ORDER BY time DESC
```

#### 平台历史统计
```sql
SELECT mean("cars") AS "cars",
       mean("avg_speed_kmh") AS "avg_speed_kmh",
       mean("active_tracks") AS "active_tracks"
FROM "intersection_stats"
WHERE "intersection_id" = 'INT_camera_1'
  AND time > now() - 1h
GROUP BY time(1m)
ORDER BY time ASC
```

#### 历史轨迹复盘
```sql
SELECT *
FROM "track_events"
WHERE "intersection_id" = 'INT_camera_1'
  AND time > now() - 1h
ORDER BY time DESC
LIMIT 500
```

#### 历史冲突复盘
```sql
SELECT *
FROM "conflict_events"
WHERE "intersection_id" = 'INT_camera_1'
  AND time > now() - 1h
ORDER BY time DESC
LIMIT 200
```
平台 API：`GET /api/v1/trajectories/{intersection_id}/conflicts?period=1h&limit=200`，返回字段与 `conflict_events` 一致，并将 `evidence`、`motor_position_m`、`non_motor_position_m`、`world_anchor_lat_lon` 从 JSON 字符串还原为数组。

### 新增摄像头的数据库操作

1. **无需手动创建 database/measurement** — Platform 启动时会确保 `influx` database 存在；InfluxDB 1.8 在首次写入时自动创建 measurement
2. **需要在 Telegraf 中添加 `[[inputs.kafka_consumer]]` 块** — 指定新 topic 和 name_override
3. **需要重启 Telegraf 容器** — `docker compose restart telegraf`

## PostgreSQL（平台业务库）

平台业务库由 `platform/app/core/database.py::init_db()` 通过 SQLAlchemy
`Base.metadata.create_all()` 初始化。PostgreSQL 不可用时平台会降级启动，但认证和告警历史
等依赖数据库的能力会受限。

### Table: `users`

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | int PK | 用户 ID |
| `username` | string | 登录名 |
| `email` | string | 邮箱 |
| `hashed_password` | string | bcrypt 密码哈希 |
| `role` | string | `admin` / `operator` / `viewer` |
| `is_active` | bool | 是否启用 |
| `created_at` | timestamp | 创建时间 |
| `updated_at` | timestamp | 更新时间 |

### Table: `alerts`

平台 AlertEngine 创建和确认告警时会同步写入 PostgreSQL；启动时会加载历史告警到内存缓存，
因此 `/api/v1/alerts`、Dashboard 未处理告警数和告警详情在服务重启后仍可用于事件处置复盘。
数据库不可用时平台降级为内存告警，不阻塞实时 WebSocket 推送。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string PK | 告警 ID |
| `intersection_id` | string | 路口 ID |
| `alert_type` | string | 告警类型，如 `conflict`、`congestion`、`queue_overflow` |
| `severity` | string | `P1` / `P2` / `P3` |
| `title` | string | 告警标题 |
| `description` | text/null | 告警描述 |
| `status` | string | `open` / `acknowledged` |
| `timestamp` | string | 触发时间（ISO 格式） |
| `track_ids` | JSON | 关联轨迹 ID 列表 |
| `snapshot_url` | string/null | 告警截图 URL |
| `video_clip_url` | string/null | 视频片段 URL |
| `vlm_summary` | text/null | VLM 分析摘要 |
| `acknowledged_by` | string/null | 确认人 |
| `acknowledged_at` | string/null | 确认时间（ISO 格式） |
| `push_logs` | JSON | 推送记录 |
| `updated_at` | timestamp/null | 最近持久化更新时间 |

## Grafana SQLite（内部数据库）

### 文件位置
- `services/grafana/grafana.db` — Grafana 运行时 SQLite 数据库
- `services/grafana/provisioning/dashboards/` — Grafana 仪表盘 provisioning
- `services/grafana/provisioning/datasources/datasource.yaml` — Grafana 数据源 provisioning

### 说明
- 此文件由 Grafana 自动管理，不应手动修改
- 包含用户、会话、告警等运行时数据
- 仪表盘定义通过 provisioning 目录管理，不存储在此数据库中
- 已在 `.gitignore` 中排除

### Provisioned datasources

| 名称 | UID | 类型 | 容器内地址 | 用途 |
|------|-----|------|------------|------|
| `InfluxDB` | `cdycrblq6bf9ce` | `influxdb` | `http://influxdb:8086` | 兼容 Grafana 旧统计看板，查询 `influx` 数据库中的 `camera_{N}` measurement |
| `PostgreSQL` | `f848db3d-2635-4913-be1c-ae2d0db7c90a` | `grafana-postgresql-datasource` | `postgres:5432` | 查询平台业务库 `traffic_platform` |

`camera-1.json` 与 `camera-2.json` 固定引用上述 datasource UID。变更 datasource UID 前必须同步更新 dashboard JSON，否则 Grafana 面板会显示数据源缺失。

Grafana 容器通过根 `docker-compose.yaml` 注入 `INFLUXDB_ADMIN_USER` / `INFLUXDB_ADMIN_PASSWORD`，供 datasource provisioning 在容器启动时展开；未提供 `.env` 时 Grafana 登录默认值为 `admin` / `admin123`，InfluxDB datasource 用户名和密码保持为空，适配本地无认证 InfluxDB 1.8。

## Kafka 数据模型

### Topic 结构
| Topic | 生产者 | 消费者 | 保留期 |
|-------|--------|--------|--------|
| `statistics_{camera_id}` | 检测管道 KafkaProducerNode | Telegraf、Platform KafkaConsumer | 24 小时 |
| `track_complete_{camera_id}` | 检测管道 KafkaProducerNode | Platform KafkaConsumer | 24 小时 |
| `conflicts_{camera_id}` | 检测管道 KafkaProducerNode | Platform KafkaConsumer | 24 小时 |
| `telemetry_{camera_id}` | 检测管道 KafkaProducerNode（消息体含 `drone_id`）/平台适配器 | Platform KafkaConsumer | 24 小时 |
| `system_metrics` | 系统指标生产者/平台适配器 | Platform KafkaConsumer | 24 小时 |

Platform 订阅正则：

```text
((statistics|track_complete|conflicts|telemetry)_.*|system_metrics)
```

### 消息格式
- 序列化：JSON（`json.dumps().encode("utf-8")`）
- 无 key（所有消息发送到同一 partition）
- 无 schema registry（无 schema 验证）

### Kafka 配置
| 参数 | 值 |
|------|------|
| 内部监听器 | `kafka:29092`（PLAINTEXT） |
| 外部监听器 | `localhost:9092`（SASL_PLAINTEXT） |
| 认证 | JAAS PlainLoginModule |
| 消息保留 | 24 小时 |
| Zookeeper | `zookeeper:2181` |

### ⚠️ 数据安全
- Kafka 内部通信无加密（PLAINTEXT）
- 外部监听器使用 SASL_PLAINTEXT（有认证但无 TLS 加密）
- 适合内网部署，不适合公网暴露

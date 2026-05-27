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

### Measurement: `camera_{N}`

每个摄像头一个 measurement，由 Telegraf 的 `name_override` 配置控制。

#### 字段（Fields）

| 字段名 | 数据类型 | 说明 | 来源 |
|--------|----------|------|------|
| `cars` | float | 当前帧滑动窗口平均车辆数 | CalcStatisticsNode → KafkaProducerNode |
| `road_1` | float | 道路 1 的车辆活跃度（辆/分钟） | CalcStatisticsNode |
| `road_2` | float | 道路 2 的车辆活跃度（辆/分钟） | CalcStatisticsNode |
| `road_3` | float | 道路 3 的车辆活跃度（辆/分钟） | CalcStatisticsNode |
| `road_4` | float | 道路 4 的车辆活跃度（辆/分钟） | CalcStatisticsNode |
| `road_5` | float | 道路 5 的车辆活跃度（辆/分钟） | CalcStatisticsNode |
| `camera_id` | string | 摄像头标识（格式 `id_{N}`） | KafkaProducerNode |

#### 标签（Tags）
| 标签名 | 说明 |
|--------|------|
| `host` | Telegraf 自动添加的主机名 |

#### 时间戳
- 由 Telegraf 的 `interval = "2s"` 控制写入频率
- 实际数据频率由 KafkaProducerNode 的 `how_often_sec`（默认 1 秒）控制

### 数据写入路径

```
KafkaProducerNode.send(topic="statistics_{N}", value={...})
  ↓ JSON 序列化
Kafka topic: statistics_{N}
  ↓ Telegraf kafka_consumer input
Telegraf (data_format = "json", name_override = "camera_{N}")
  ↓ line protocol
InfluxDB measurement: camera_{N}
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

### 查询模式（Grafana InfluxQL）

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
SELECT road_1, road_2, road_3, road_4, road_5
FROM "camera_1"
ORDER BY time DESC
LIMIT 1
```

#### 道路拥堵趋势
```sql
SELECT road_1, road_2, road_3, road_4, road_5
FROM "camera_1"
ORDER BY time DESC
```

### 新增摄像头的数据库操作

1. **无需手动创建 measurement** — InfluxDB 1.8 在首次写入时自动创建
2. **需要在 Telegraf 中添加 `[[inputs.kafka_consumer]]` 块** — 指定新 topic 和 name_override
3. **需要重启 Telegraf 容器** — `docker compose restart telegraf`

## Grafana SQLite（内部数据库）

### 文件位置
- `services/grafana/grafana.db` — Grafana 运行时 SQLite 数据库

### 说明
- 此文件由 Grafana 自动管理，不应手动修改
- 包含用户、会话、告警等运行时数据
- 仪表盘定义通过 provisioning 目录管理，不存储在此数据库中
- 已在 `.gitignore` 中排除

## Kafka 数据模型

### Topic 结构
| Topic | 生产者 | 消费者 | 保留期 |
|-------|--------|--------|--------|
| `statistics_1` | camera_1 容器 | Telegraf | 24 小时 |
| `statistics_2` | camera_2 容器 | Telegraf | 24 小时 |

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

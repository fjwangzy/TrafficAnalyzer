# API_CONTRACTS.md — TrafficAnalyzer API 契约

> 基于 commit `e69acee` 的真实代码分析。

## 1. Kafka 消息契约

### Topic 命名
- 格式：`statistics_{camera_id}`
- 示例：`statistics_1`、`statistics_2`

### 消息格式（JSON）
```json
{
  "camera_id": "id_1",
  "cars": 12,
  "road_1": 4.2,
  "road_2": 3.8,
  "road_3": null,
  "road_4": 2.1,
  "road_5": 1.5
}
```

### 字段说明
| 字段 | 类型 | 说明 |
|------|------|------|
| `camera_id` | string | 格式 `id_{N}`，N 为摄像头编号 |
| `cars` | int | 当前帧滑动窗口平均车辆数 |
| `road_1` ~ `road_5` | float \| null | 每条道路的车辆活跃度（辆/分钟），缓冲区未充满时为 null |

### 发送频率
- 由 `kafka_producer_node.how_often_sec` 控制（默认 1 秒）
- 第一帧始终发送

### 生产者
- 文件：`nodes/KafkaProducerNode.py`
- 序列化：`json.dumps(x).encode("utf-8")`
- 同步发送：`.get(timeout=1)`（阻塞等待 broker 确认）

### 消费者
- Telegraf `[[inputs.kafka_consumer]]`
- 配置：`services/telegraf/telegraf.conf`

### ⚠️ 契约约束
- **不可更改字段名**：Grafana 仪表盘的 InfluxQL 查询直接引用 `road_1`~`road_5`
- **不可更改 road 数量**：硬编码 5 条道路，增减需要同时修改 CalcStatisticsNode、KafkaProducerNode、Telegraf、Grafana 仪表盘
- **不可更改 topic 命名规则**：Telegraf 配置中按 topic 名匹配

## 2. Flask 视频流 API

### 端点

#### `GET /`
- 返回：HTML 页面（`utils_local/templates/index.html`）
- 内容：包含 `<img src="/video"/>` 的简单页面

#### `GET /video`
- 返回：`multipart/x-mixed-replace; boundary=frame` MJPEG 流
- 每帧格式：JPEG 编码的 numpy 数组
- 帧尺寸：由 `video_server_node.output_size` 控制（默认 `[800, 470]`）
- 绑定地址：`0.0.0.0:8100`

### 技术细节
- 使用 Flask 的 `Response` 生成器实现流式推送
- 帧通过 `cv2.imencode('.jpg', frame)` 编码
- 服务器在守护线程中运行（`Thread(daemon=True)`）
- 帧更新通过 `self._frame` 实例变量，无锁保护（可能出现撕裂）

## 3. Nginx 反向代理路由

### 路由规则
```nginx
location ~ ^/camera_(\d+)$ {
    resolver 127.0.0.11 [::1];
    set $camera_id $1;
    proxy_pass http://traffic_analyzer_camera_$camera_id:8100/video;
}
```

### 访问方式
| URL | 代理到 |
|-----|--------|
| `http://localhost:8009/camera_1` | `traffic_analyzer_camera_1:8100/video` |
| `http://localhost:8009/camera_2` | `traffic_analyzer_camera_2:8100/video` |
| `http://localhost:8009/camera_N` | `traffic_analyzer_camera_N:8100/video` |

### 约束
- 容器名必须遵循 `traffic_analyzer_camera_{N}` 格式
- Nginx 使用 Docker 内部 DNS（`127.0.0.11`）解析容器名
- 只代理 `/video` 端点，不代理 `/`

## 4. InfluxDB 数据模型

### 数据库
- 名称：`influx`
- 版本：InfluxDB 1.8
- 保留策略：30 天自动删除

### Measurement
- 命名：`camera_{N}`（由 Telegraf `name_override` 控制）
- 每个摄像头一个 measurement

### 字段
| 字段 | 类型 | 说明 |
|------|------|------|
| `cars` | float | 车辆总数（滑动窗口平均） |
| `road_1` ~ `road_5` | float | 道路活跃度（辆/分钟） |
| `camera_id` | string | 摄像头标识（`id_N`） |

### 标签
- 无自定义标签（Telegraf 默认添加 `host` 标签）

### 查询示例（Grafana InfluxQL）
```sql
-- 车辆数时序图
SELECT mean("cars") FROM "camera_1" WHERE $timeFilter GROUP BY time($interval)

-- 当前道路拥堵
SELECT road_1, road_2, road_3, road_4, road_5 FROM "camera_1" ORDER BY time DESC LIMIT 1

-- 道路拥堵趋势
SELECT road_1, road_2, road_3, road_4, road_5 FROM "camera_1" ORDER BY time DESC
```

## 5. 管道节点接口

### 标准接口
```python
class SomeNode:
    def __init__(self, config: dict) -> None:
        """从 Hydra 配置字典初始化节点"""
        ...

    def process(self, frame_element: FrameElement) -> FrameElement:
        """处理一帧，返回增强的 FrameElement"""
        if isinstance(frame_element, VideoEndBreakElement):
            return frame_element
        ...
        return frame_element
```

### 特殊接口

#### VideoReader（生成器模式）
```python
def process(self) -> Generator[FrameElement, None, None]:
    """逐帧产出 FrameElement，流结束时产出 VideoEndBreakElement"""
```

#### VideoSaverNode（终端节点）
```python
def process(self, frame_element: FrameElement) -> None:
    """写入帧到文件，收到 VideoEndBreakElement 时释放资源"""
```

#### FlaskServerVideoNode.VideoServer（终端节点）
```python
def process(self, frame_element: FrameElement) -> None:
    """更新帧缓冲区，Flask 线程持续推送"""
```

## 6. Grafana API（管理脚本使用）

### 获取仪表盘
```
GET http://localhost:3111/api/dashboards/uid/{uid}
Authorization: Basic {base64(admin:admin)}
```

### 更新仪表盘
```
POST http://localhost:3111/api/dashboards/db
Content-Type: application/json
{
  "dashboard": {...},
  "message": "update reason",
  "overwrite": true
}
```

### 已知仪表盘 UID
| 摄像头 | UID |
|--------|-----|
| Camera 1 | `edycr94pt2mm8b` |
| Camera 2 | `adycu34xs035sb` |

### ⚠️ 安全风险
- `export_dashboards.py` 和 `fetch_dashboard.py` 中硬编码了 `admin:admin` 凭据
- 这些脚本仅用于开发环境，生产环境不应使用

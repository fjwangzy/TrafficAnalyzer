# Traffic Platform Gateway

API 网关服务，负责请求路由、身份验证和流量控制。

## 功能

- **JWT 身份验证**：验证所有请求的 Bearer Token
- **请求路由**：根据 URL 路径将请求转发到对应的微服务
- **健康检查**：监控网关和下游服务状态

## 路由规则

| 路径前缀 | 目标服务 | 说明 |
|---------|---------|------|
| `/api/v1/intersections` | operations:8001 | 路口管理 |
| `/api/v1/alerts` | operations:8001 | 告警管理 |
| `/api/v1/webhooks` | operations:8001 | Webhook 配置 |
| `/api/v1/reports` | operations:8001 | 报告生成 |
| `/api/v1/auth` | operations:8001 | 认证授权 |
| `/api/v1/video` | vision:8002 | 视频流管理 |
| `/api/v1/trajectories` | vision:8002 | 轨迹分析 |
| `/api/v1/detection` | vision:8002 | 检测任务 |
| `/api/v1/tracks` | vision:8002 | 跟踪数据 |
| `/api/v1/drones` | flight:8003 | 无人机管理 |
| `/api/v1/missions` | flight:8003 | 任务规划 |
| `/api/v1/telemetry` | flight:8003 | 遥测数据 |
| `/api/v1/calibration` | annotation:8004 | 标定管理 |
| `/api/v1/labels` | annotation:8004 | 标注数据 |

## 环境变量

| 变量名 | 默认值 | 说明 |
|-------|--------|------|
| `OPERATIONS_URL` | `http://localhost:8001` | 运营服务地址 |
| `VISION_URL` | `http://localhost:8002` | 视觉分析服务地址 |
| `FLIGHT_URL` | `http://localhost:8003` | 飞控服务地址 |
| `ANNOTATION_URL` | `http://localhost:8004` | 标注服务地址 |

## 本地开发

```bash
# 安装依赖
cd platform/gateway
pip install -e .

# 启动服务
uvicorn app.main:app --reload --port 8000

# 或使用 Docker
docker build -t traffic-gateway .
docker run -p 8000:8000 traffic-gateway
```

## API 端点

### 健康检查

```bash
# 网关健康状态
GET /health

# 所有服务就绪状态
GET /ready
```

### 认证

所有 `/api/v1/*` 请求（除 `/api/v1/auth/login` 和 `/api/v1/auth/register` 外）都需要在 Header 中提供有效的 JWT Token：

```
Authorization: Bearer <token>
```

网关会将用户信息注入到转发请求的 Header 中：

- `X-User-ID`：用户 ID
- `X-User-Name`：用户名
- `X-User-Role`：用户角色

## 架构

```
Client → Gateway (8000) → Operations Service (8001)
                        → Vision Service (8002)
                        → Flight Service (8003)
                        → Annotation Service (8004)
```

网关使用 `httpx.AsyncClient` 进行异步请求转发，支持流式响应和超时控制。

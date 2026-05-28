# Platform Docker Configuration

Docker Compose 配置文件，用于启动整个 Traffic Platform 微服务架构。

## 服务列表

### 基础设施服务

| 服务 | 端口 | 说明 |
|------|------|------|
| `postgres` | 5432 | PostgreSQL 16 数据库 |
| `influxdb` | 8086 | InfluxDB 1.8 时序数据库 |
| `kafka` | 9092 | Apache Kafka 消息队列 |

### 平台服务

| 服务 | 端口 | 说明 |
|------|------|------|
| `gateway` | 8000 | API 网关（路由、认证） |
| `operations` | 8001 | 运营服务（用户、认证） |
| `vision` | 8002 | 视觉分析服务（占位） |
| `flight` | 8003 | 飞控服务（占位） |
| `annotation` | 8004 | 标注服务（占位） |

## 启动服务

```bash
# 进入 docker 目录
cd platform/docker

# 启动所有服务
docker-compose -f docker-compose.platform.yml up -d

# 查看日志
docker-compose -f docker-compose.platform.yml logs -f

# 停止服务
docker-compose -f docker-compose.platform.yml down

# 停止并删除数据卷（谨慎使用）
docker-compose -f docker-compose.platform.yml down -v
```

## 验证服务

```bash
# 检查所有容器状态
docker-compose -f docker-compose.platform.yml ps

# 测试 API 网关
curl http://localhost:8000/health

# 测试运营服务
curl http://localhost:8001/health

# 测试用户注册
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","email":"admin@example.com","password":"password123","role":"admin"}'

# 测试用户登录
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"password123"}'
```

## 数据卷

- `postgres_data` - PostgreSQL 数据持久化
- `influxdb_data` - InfluxDB 数据持久化
- `kafka_data` - Kafka 数据持久化

## 网络

所有服务都在 `traffic-net` 桥接网络中，可以互相通信。

## 环境变量

### Gateway

- `OPERATIONS_URL` - 运营服务地址
- `VISION_URL` - 视觉服务地址
- `FLIGHT_URL` - 飞控服务地址
- `ANNOTATION_URL` - 标注服务地址

### Operations

- `OPS_DATABASE_URL` - PostgreSQL 连接 URL
- `OPS_SERVICE_NAME` - 服务名称
- `OPS_SERVICE_PORT` - 服务端口
- `OPS_DEBUG` - 调试模式

## 开发模式

本地开发时，可以只启动基础设施服务，然后在本地运行微服务：

```bash
# 只启动基础设施
docker-compose -f docker-compose.platform.yml up -d postgres influxdb kafka

# 在本地运行运营服务
cd platform/services/operations
export OPS_DATABASE_URL="postgresql+asyncpg://traffic:traffic@localhost:5432/traffic_platform"
uvicorn app.main:app --reload --port 8001
```

## 故障排查

### 数据库连接失败

```bash
# 检查 PostgreSQL 是否就绪
docker-compose -f docker-compose.platform.yml exec postgres pg_isready -U traffic

# 查看数据库日志
docker-compose -f docker-compose.platform.yml logs postgres
```

### Kafka 连接失败

```bash
# 检查 Kafka 状态
docker-compose -f docker-compose.platform.yml exec kafka kafka-topics --bootstrap-server localhost:9092 --list

# 查看 Kafka 日志
docker-compose -f docker-compose.platform.yml logs kafka
```

### 服务健康检查失败

```bash
# 查看所有服务健康状态
docker-compose -f docker-compose.platform.yml ps

# 重启特定服务
docker-compose -f docker-compose.platform.yml restart <service_name>

# 重建服务
docker-compose -f docker-compose.platform.yml up -d --build <service_name>
```

# Operations Service

运营服务，负责用户管理、认证和业务操作。

## 功能

- 用户注册和登录
- JWT 令牌认证
- 用户角色管理（admin/operator/viewer）
- PostgreSQL 数据库存储

## 技术栈

- FastAPI
- SQLAlchemy (async)
- PostgreSQL
- Alembic (数据库迁移)
- passlib + bcrypt (密码加密)

## 本地开发

```bash
# 安装依赖
cd platform/services/operations
pip install -e .

# 配置环境变量
cp .env.example .env
# 编辑 .env 设置数据库连接

# 启动服务
uvicorn app.main:app --reload --port 8001

# 或使用 Docker
docker build -t traffic-operations .
docker run -p 8001:8001 --env-file .env traffic-operations
```

## API 端点

### 认证

- `POST /api/v1/auth/register` - 注册新用户
- `POST /api/v1/auth/login` - 登录获取令牌
- `GET /api/v1/auth/me` - 获取当前用户信息

### 健康检查

- `GET /` - 服务根端点
- `GET /health` - 健康检查

## 数据库

服务使用 PostgreSQL 存储用户数据。表结构：

```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'viewer',
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

## 环境变量

| 变量名 | 默认值 | 说明 |
|-------|--------|------|
| `OPS_DATABASE_URL` | `postgresql+asyncpg://traffic:traffic@localhost:5432/traffic_platform` | 数据库连接 URL |
| `OPS_SERVICE_NAME` | `operations` | 服务名称 |
| `OPS_SERVICE_PORT` | `8001` | 服务端口 |
| `OPS_DEBUG` | `false` | 调试模式 |
| `OPS_CORS_ORIGINS` | `["http://localhost:3000", "http://localhost:8080"]` | CORS 允许的源 |

## 依赖

- `traffic-platform-shared` - 共享库（JWT、配置等）
- `fastapi` - Web 框架
- `sqlalchemy[asyncio]` - ORM
- `asyncpg` - PostgreSQL 异步驱动
- `passlib[bcrypt]` - 密码加密

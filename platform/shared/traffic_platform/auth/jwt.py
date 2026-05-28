"""JWT utilities"""
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from pydantic import BaseModel
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from ..config import get_settings


class TokenPayload(BaseModel):
    """JWT Token 载荷"""
    sub: str  # user_id
    username: str
    role: str  # admin/operator/viewer
    exp: datetime


# Security scheme
security = HTTPBearer()


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    创建 JWT access token

    Args:
        data: Token 载荷数据，必须包含 sub, username, role
        expires_delta: 过期时间增量，默认使用配置值

    Returns:
        JWT token 字符串
    """
    settings = get_settings()
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.jwt.access_token_expire_minutes
        )

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.jwt.secret_key,
        algorithm=settings.jwt.algorithm,
    )
    return encoded_jwt


def verify_token(token: str) -> TokenPayload:
    """
    验证并解码 JWT token

    Args:
        token: JWT token 字符串

    Returns:
        TokenPayload 对象

    Raises:
        HTTPException: Token 无效或已过期
    """
    settings = get_settings()
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            token,
            settings.jwt.secret_key,
            algorithms=[settings.jwt.algorithm],
        )
        user_id: str = payload.get("sub")
        username: str = payload.get("username")
        role: str = payload.get("role")
        exp: int = payload.get("exp")

        if user_id is None or username is None or role is None:
            raise credentials_exception

        return TokenPayload(
            sub=user_id,
            username=username,
            role=role,
            exp=datetime.fromtimestamp(exp),
        )
    except JWTError:
        raise credentials_exception


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> TokenPayload:
    """
    FastAPI 依赖：从 Authorization header 提取并验证当前用户

    Usage:
        @app.get("/protected")
        async def protected_route(user: TokenPayload = Depends(get_current_user)):
            return {"user": user.username}
    """
    return verify_token(credentials.credentials)


def require_role(*roles: str):
    """
    FastAPI 依赖：要求用户具有指定角色

    Usage:
        @app.get("/admin-only")
        async def admin_route(user: TokenPayload = Depends(require_role("admin"))):
            return {"message": "Admin access granted"}
    """
    async def role_checker(
        user: TokenPayload = Depends(get_current_user),
    ) -> TokenPayload:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required roles: {', '.join(roles)}",
            )
        return user

    return role_checker

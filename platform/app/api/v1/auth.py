"""Authentication API endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.schemas.auth import Token, UserCreate, UserLogin, UserResponse
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(user_data: UserCreate, request: Request, db: AsyncSession = Depends(get_db)):
    """Register a new user."""
    user = getattr(request.state, "user", None) or {}
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Administrator role required")
    user = await auth_service.create_user(db, user_data)
    return user


@router.post("/login", response_model=Token)
async def login(credentials: UserLogin, response: Response, db: AsyncSession = Depends(get_db)):
    """Login and get access token."""
    user = await auth_service.authenticate_user(db, credentials.username, credentials.password)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Create access token
    access_token = auth_service.create_access_token(
        data={"sub": str(user.id), "username": user.username, "role": user.role}
    )
    response.set_cookie(
        key=auth_service.settings.media_cookie_name,
        value=access_token,
        max_age=auth_service.settings.jwt_access_token_expire_minutes * 60,
        httponly=True,
        secure=auth_service.settings.media_cookie_secure,
        samesite=auth_service.settings.media_cookie_samesite,
        path=auth_service.settings.media_cookie_path,
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user,
    }


@router.get("/me", response_model=UserResponse)
async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get the active database user identified by authenticated scope state."""
    claims = getattr(request.state, "user", None) or {}
    try:
        user_id = int(claims.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid authenticated identity")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Authenticated user is unavailable")
    return user


@router.post("/logout")
async def logout(response: Response):
    """Idempotently clear the browser media session."""
    response.delete_cookie(
        key=auth_service.settings.media_cookie_name,
        path=auth_service.settings.media_cookie_path,
        secure=auth_service.settings.media_cookie_secure,
        httponly=True,
        samesite=auth_service.settings.media_cookie_samesite,
    )
    return {"status": "logged_out"}


@router.get("/media-session", response_model=UserResponse)
async def media_session(request: Request, db: AsyncSession = Depends(get_db)):
    """Validate the HttpOnly media cookie and return its active user."""
    return await get_current_user(request, db)

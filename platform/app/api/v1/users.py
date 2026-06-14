"""Read-only user API endpoints."""
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User


router = APIRouter(prefix="/users", tags=["users"])


def serialize_user(user: Any) -> dict:
    """Convert a User model to a safe API payload."""
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "created_at": user.created_at,
    }


@router.get("")
async def list_users(db: AsyncSession = Depends(get_db)):
    """List platform users without password hashes."""
    result = await db.execute(select(User).order_by(User.id.asc()))
    return [serialize_user(user) for user in result.scalars().all()]

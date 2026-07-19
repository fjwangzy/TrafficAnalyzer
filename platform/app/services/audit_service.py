"""Durable audit writer for sensitive Platform operations."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.survey import AuditLog


class AuditService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._sessions = session_factory

    async def record(
        self,
        *,
        actor: dict[str, Any],
        action: str,
        target_type: str,
        target_id: str,
        after_value: dict[str, Any] | None = None,
        reason: str | None = None,
    ) -> None:
        try:
            actor_id = int(actor.get("sub"))
        except (TypeError, ValueError):
            actor_id = None
        async with self._sessions() as session:
            async with session.begin():
                session.add(
                    AuditLog(
                        actor_id=actor_id,
                        action=action,
                        target_type=target_type,
                        target_id=target_id[:80],
                        after_value=after_value,
                        reason=reason,
                        request_id=uuid.uuid4().hex,
                    )
                )

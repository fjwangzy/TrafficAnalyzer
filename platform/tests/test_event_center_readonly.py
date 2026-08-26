from unittest.mock import AsyncMock

import pytest

from app.services.event_center import EventCenter


class _ScalarResult:
    def scalars(self):
        return self

    def all(self):
        return []


class _Session:
    statements = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def execute(self, query):
        self.statements.append(str(query))
        return _ScalarResult()


@pytest.mark.asyncio
async def test_event_center_does_not_materialize_quality_events_on_list_by_default():
    _Session.statements.clear()
    center = EventCenter(lambda: _Session())
    center.materialize_quality_events = AsyncMock()

    assert await center.list_events(limit=150) == []
    center.materialize_quality_events.assert_not_awaited()


@pytest.mark.asyncio
async def test_conflict_filters_are_applied_before_database_limit():
    _Session.statements.clear()
    center = EventCenter(lambda: _Session())

    assert await center.list_events(
        event_type="conflict",
        inter_id="INT-current",
        source_profile_id="SRC-current",
        mission_id="MSN-current",
        limit=150,
    ) == []

    conflict_sql = next(
        sql
        for sql in _Session.statements
        if "FROM uav_conflict_events" in sql and "uav_conflict_reviews" not in sql
    )
    assert "WHERE uav_conflict_events.inter_id" in conflict_sql
    assert "uav_conflict_events.source_profile_id" in conflict_sql
    assert "uav_conflict_events.mission_id" in conflict_sql
    assert not any("FROM uav_ai_events" in sql for sql in _Session.statements)

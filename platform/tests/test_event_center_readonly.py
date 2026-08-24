from unittest.mock import AsyncMock

import pytest

from app.services.event_center import EventCenter


class _ScalarResult:
    def scalars(self):
        return self

    def all(self):
        return []


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def execute(self, _query):
        return _ScalarResult()


@pytest.mark.asyncio
async def test_event_center_does_not_materialize_quality_events_on_list_by_default():
    center = EventCenter(lambda: _Session())
    center.materialize_quality_events = AsyncMock()

    assert await center.list_events(limit=150) == []
    center.materialize_quality_events.assert_not_awaited()

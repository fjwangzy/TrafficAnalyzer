from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.v1.events import EventReviewRequest, review_event


@pytest.mark.asyncio
async def test_realtime_message_alias_reviews_resolved_persistent_conflict_id():
    center = SimpleNamespace(get_event=AsyncMock(return_value={
        "id": "conflict-persistent-1",
        "inter_id": "INT-1",
        "source_kind": "conflict",
    }))
    metric_store = SimpleNamespace(review_conflict=AsyncMock(return_value={
        "id": "conflict-persistent-1",
        "review_status": "confirmed",
    }))
    request = SimpleNamespace(
        state=SimpleNamespace(user={"sub": "7", "role": "admin"}),
        app=SimpleNamespace(state=SimpleNamespace(
            event_center=center,
            metric_store=metric_store,
        )),
    )

    result = await review_event(
        "realtime-message-1",
        EventReviewRequest(
            review_status="confirmed",
            expected_revision=1,
            reason="实时监控技术复核",
        ),
        request,
    )

    assert result["id"] == "conflict-persistent-1"
    metric_store.review_conflict.assert_awaited_once_with(
        "INT-1",
        "conflict-persistent-1",
        "confirmed",
        1,
        7,
        "实时监控技术复核",
    )

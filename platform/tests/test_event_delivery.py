import pytest

from app.services.event_delivery import (
    DeliveryEnvelope,
    DeliveryResult,
    DisabledMainPlatformAdapter,
    EventDelivery,
)


class RecordingAdapter:
    def __init__(self):
        self.envelopes = []

    async def deliver(self, envelope):
        self.envelopes.append(envelope)
        return DeliveryResult(status="delivered", platform_event_id="external-1")


def envelope():
    return DeliveryEnvelope(
        source_system="uav_traffic_analyzer_ai",
        source_event_id="evt-1",
        idempotency_key="uav_traffic_analyzer_ai:evt-1",
        schema_version="uav_ai_event/v1",
        payload_hash="a" * 64,
        payload={"event_type": "conflict"},
    )


@pytest.mark.asyncio
async def test_event_delivery_keeps_the_canonical_envelope_intact():
    adapter = RecordingAdapter()
    result = await EventDelivery(adapter).deliver(envelope())

    assert adapter.envelopes == [envelope()]
    assert result.status == "delivered"
    assert result.platform_event_id == "external-1"


@pytest.mark.asyncio
async def test_main_platform_adapter_never_simulates_success_before_contract_approval():
    result = await EventDelivery(DisabledMainPlatformAdapter()).deliver(envelope())

    assert result.status == "blocked"
    assert result.platform_event_id is None
    assert result.receipt is None
    assert result.error_code == "main_platform_contract_unverified"

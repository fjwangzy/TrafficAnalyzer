"""Canonical event-delivery interface with a deliberately disabled external adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DeliveryEnvelope:
    source_system: str
    source_event_id: str
    idempotency_key: str
    schema_version: str
    payload_hash: str
    payload: dict


@dataclass(frozen=True)
class DeliveryResult:
    status: str
    platform_event_id: str | None = None
    receipt: dict | None = None
    error_code: str | None = None


class DeliveryAdapter(Protocol):
    async def deliver(self, envelope: DeliveryEnvelope) -> DeliveryResult: ...


class EventDelivery:
    """Keep idempotency stable while hiding transport and receipt semantics."""

    def __init__(self, adapter: DeliveryAdapter):
        self._adapter = adapter

    async def deliver(self, envelope: DeliveryEnvelope) -> DeliveryResult:
        return await self._adapter.deliver(envelope)


class DisabledMainPlatformAdapter:
    """Production-safe default until the external contract is formally frozen."""

    async def deliver(self, envelope: DeliveryEnvelope) -> DeliveryResult:
        return DeliveryResult(status="blocked", error_code="main_platform_contract_unverified")


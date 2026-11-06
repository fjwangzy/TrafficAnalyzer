"""Recovery must preserve rejected facts and never turn a terminal rejection into ACK."""

from types import SimpleNamespace
import json
import pytest
from app.services.trajectory_recovery import TrajectoryRecoveryService
from app.services.replay_v2_metric_store import _hash
from utils_local.message_identity import seal_payload


class Session:
    def __init__(self, receipt):
        self.receipt = receipt

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def get(self, *args):
        return self.receipt


class Producer:
    def __init__(self):
        self.sent = []

    async def send_and_wait(self, *args, **kwargs):
        self.sent.append((args, kwargs))


def setup(tmp_path, status):
    payload = seal_payload(
        {
            "transport_version": "uav-fixed/v2",
            "storage_profile": "replay_v2",
            "deployment_id": "test",
            "msg_type": "uav_track_complete",
            "message_id": "m1",
            "data": {"mission_id": "M1"},
        }
    )
    path = tmp_path / "P1/awaiting-receipt/m1.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"id": "m1", "topic": "uav_track_complete", "payload": payload}))
    service = TrajectoryRecoveryService.__new__(TrajectoryRecoveryService)
    service.root = tmp_path
    service.producer = Producer()
    service.sessions = lambda: Session(
        SimpleNamespace(message_hash=_hash(payload), deployment_id="test", status=status)
    )
    return service, path


@pytest.mark.asyncio
async def test_quarantined_receipt_preserves_payload_instead_of_deleting_as_committed(tmp_path):
    service, path = setup(tmp_path, "quarantined")
    raw = path.read_bytes()
    await service.reconcile(path)
    assert (tmp_path / "P1/quarantine/m1.json").read_bytes() == raw
    assert not service.producer.sent


@pytest.mark.asyncio
async def test_unknown_receipt_state_never_deletes_the_only_durable_fact(tmp_path):
    service, path = setup(tmp_path, "processing")
    await service.reconcile(path)
    assert path.exists()
    assert not service.producer.sent


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "published"])
async def test_committed_database_receipt_allows_retiring_spool(tmp_path, status):
    service, path = setup(tmp_path, status)
    await service.reconcile(path)
    assert not path.exists()


@pytest.mark.asyncio
async def test_recovery_does_not_compete_with_a_live_delivery_owner(tmp_path):
    from utils_local.spool_lock import spool_lock

    service, path = setup(tmp_path, "published")
    with spool_lock(tmp_path / "P1", path.name) as held:
        assert held
        await service.reconcile(path)
        assert path.exists()
    await service.reconcile(path)
    assert not path.exists()

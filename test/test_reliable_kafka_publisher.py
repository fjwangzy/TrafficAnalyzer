import time

import pytest

import nodes.ReliableKafkaPublisher as reliable_module
from nodes.ReliableKafkaPublisher import ReliableKafkaPublisher, kafka_compression_type


class _Future:
    def __init__(self, error=None):
        self.error = error

    def get(self, timeout=None):
        if self.error:
            raise self.error
        return {"timeout": timeout}


class _Producer:
    def __init__(self, fail=False):
        self.fail = fail
        self.sent = []

    def send(self, topic, value):
        if self.fail:
            return _Future(RuntimeError("kafka unavailable"))
        self.sent.append((topic, value))
        return _Future()

    def flush(self, timeout=None):
        return None


def _wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_replay_v2_compression_fails_before_start_when_zstd_is_missing(monkeypatch):
    monkeypatch.setattr(reliable_module, "has_zstd", lambda: False)

    with pytest.raises(RuntimeError, match="zstandard"):
        kafka_compression_type("replay_v2")

    assert kafka_compression_type("live") is None


def test_durable_message_survives_publisher_restart(tmp_path):
    spool = tmp_path / "pipeline-spool"
    failed = ReliableKafkaPublisher(
        _Producer(fail=True), spool, retry_interval_sec=0.01, delivery_timeout_sec=0.01
    )
    failed.publish("uav_track_complete_10", {"message_id": "track-1"}, durable=True)
    first = failed.close(timeout_sec=0.02)
    assert first["durable_pending"] == 1
    assert first["dropped_samples"] == 0

    producer = _Producer()
    recovered = ReliableKafkaPublisher(producer, spool, retry_interval_sec=0.01)
    assert _wait_until(lambda: recovered.snapshot()["durable_pending"] == 0)
    final = recovered.close()

    assert producer.sent == [("uav_track_complete_10", {"message_id": "track-1"})]
    assert final["actual_samples"] == 1
    assert final["coverage_ratio"] == 1.0


def test_best_effort_delivery_reports_measured_coverage(tmp_path):
    producer = _Producer()
    publisher = ReliableKafkaPublisher(producer, tmp_path / "stats-spool")
    publisher.publish("uav_statistics_10", {"message_id": "stats-1"})
    assert _wait_until(lambda: publisher.snapshot()["actual_samples"] == 1)
    snapshot = publisher.close()

    assert snapshot["expected_samples"] == 1
    assert snapshot["actual_samples"] == 1
    assert snapshot["dropped_samples"] == 0
    assert snapshot["coverage_ratio"] == 1.0

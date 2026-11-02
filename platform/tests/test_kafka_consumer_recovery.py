from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from aiokafka import TopicPartition
from aiokafka.structs import OffsetAndMetadata

from app.kafka.consumer import KafkaConsumerService


class _Consumer:
    def __init__(self, service, records, ends):
        self.service = service
        self.records = iter(records)
        self.ends = ends
        self.positions = {}
        self.commit = AsyncMock()
        self.stop = AsyncMock()
        self.end_offsets = AsyncMock(side_effect=lambda partitions: {partition: ends[partition] for partition in partitions})

    def assignment(self):
        return set(self.ends)

    def seek(self, partition, offset):
        self.positions[partition] = offset

    def __aiter__(self):
        return self

    async def __anext__(self):
        for record in self.records:
            if isinstance(record, Exception):
                raise record
            partition = TopicPartition(record.topic, record.partition)
            if record.offset >= self.positions.get(partition, 0):
                return record
        self.service._running = False
        raise StopAsyncIteration


def _service():
    return KafkaConsumerService("localhost:9092", "test", "uav_statistics_.*", Mock())


def _record(topic, offset, value):
    return SimpleNamespace(topic=topic, partition=0, offset=offset, value=value)


@pytest.mark.asyncio
async def test_failed_record_resumes_latest_without_blocking_other_sources(caplog):
    service = _service()
    failed = TopicPartition("uav_statistics_1", 0)
    healthy = TopicPartition("uav_statistics_2", 0)
    consumer = _Consumer(service, [
        _record(failed.topic, 0, "bad"),
        _record(failed.topic, 1, "backlog"),
        _record(healthy.topic, 0, "healthy"),
        _record(failed.topic, 10, "new"),
    ], {failed: 10, healthy: 1})
    service._consumer = consumer
    service._running = True
    service._process_message = AsyncMock(side_effect=[RuntimeError("database failed"), None, None])

    await service._consume_loop()

    assert [call.args[0] for call in service._process_message.await_args_list] == ["bad", "healthy", "new"]
    assert consumer.positions == {failed: 10}
    assert consumer.commit.await_args_list[0].args[0][failed].offset == 10
    assert consumer.commit.await_args_list[-1].args[0] == {failed: OffsetAndMetadata(11, "")}
    assert "resume_offset=10" in caplog.text


@pytest.mark.asyncio
async def test_decode_failure_resumes_assigned_partitions_at_latest():
    service = _service()
    partition = TopicPartition("uav_statistics_1", 0)
    consumer = _Consumer(service, [ValueError("invalid JSON"), _record(partition.topic, 10, "new")], {partition: 10})
    service._consumer = consumer
    service._running = True
    service._process_message = AsyncMock()

    await service._consume_loop()

    service._process_message.assert_awaited_once_with("new", partition.topic, 0, 10)
    assert consumer.positions == {partition: 10}


@pytest.mark.asyncio
async def test_commit_failure_does_not_replay_processed_record_forever():
    service = _service()
    partition = TopicPartition("uav_statistics_1", 0)
    consumer = _Consumer(service, [
        _record(partition.topic, 0, "processed"),
        _record(partition.topic, 1, "backlog"),
        _record(partition.topic, 10, "new"),
    ], {partition: 10})
    consumer.commit.side_effect = [RuntimeError("commit failed"), None, None]
    service._consumer = consumer
    service._running = True
    service._process_message = AsyncMock()

    await service._consume_loop()

    assert [call.args[0] for call in service._process_message.await_args_list] == ["processed", "new"]
    assert consumer.positions == {partition: 10}


@pytest.mark.asyncio
async def test_reconnected_consumer_ignores_old_committed_backlog():
    service = _service()
    partition = TopicPartition("uav_statistics_1", 0)
    consumer = _Consumer(service, [_record(partition.topic, 0, "old"), _record(partition.topic, 10, "new")], {partition: 10})
    service._consumer = consumer
    service._running = True
    service._resume_after_reconnect = True
    service._process_message = AsyncMock()

    await service._consume_loop()

    service._process_message.assert_awaited_once_with("new", partition.topic, 0, 10)
    assert not service._resume_after_reconnect


@pytest.mark.asyncio
async def test_unavailable_broker_uses_bounded_reconnect_instead_of_spinning():
    service = _service()
    partition = TopicPartition("uav_statistics_1", 0)
    consumer = _Consumer(service, [OSError("broker failed")] * 10, {partition: 10})
    consumer.end_offsets.side_effect = OSError("broker failed")
    service._consumer = consumer
    service._running = True
    service._reconnect_loop = AsyncMock()

    with patch("app.kafka.consumer.asyncio.sleep", new_callable=AsyncMock):
        await service._consume_loop()
        await service._task

    consumer.stop.assert_awaited_once()
    service._reconnect_loop.assert_awaited_once()
    assert service._consumer is None

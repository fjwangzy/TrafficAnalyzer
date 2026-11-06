from types import SimpleNamespace
import pytest
from utils_local.replay_topics import FIXED_TOPICS


def test_missing_topics_are_rejected_without_requesting_their_metadata():
    from utils_local.kafka_topic_preflight import inspect_topics

    class Admin:
        def list_topics(self):
            return ["uav_statistics"]

        def describe_topics(self, names):
            raise AssertionError("must not request metadata for missing topics")

    with pytest.raises(ValueError, match="MISSING_TOPICS"):
        inspect_topics(Admin(), partitions=3, replication_factor=1)


def test_topic_partition_and_replication_requirements_are_read_only():
    from utils_local.kafka_topic_preflight import inspect_topics

    class Admin:
        def list_topics(self):
            return list(FIXED_TOPICS.values())

        def describe_topics(self, names):
            return [
                {
                    "topic": n,
                    "error_code": 0,
                    "partitions": [{"partition": i, "replicas": [1]} for i in range(3)],
                }
                for n in names
            ]

    assert len(inspect_topics(Admin(), partitions=3, replication_factor=1)) == 9
    with pytest.raises(ValueError, match="TOPIC_CAPACITY"):
        inspect_topics(Admin(), partitions=4, replication_factor=1)

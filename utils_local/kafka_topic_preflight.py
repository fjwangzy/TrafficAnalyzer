"""Read-only fixed-topic checks. Only the explicit initializer creates Topics."""

import os
from kafka.admin import KafkaAdminClient
from utils_local.kafka_security import kafka_security_options
from utils_local.replay_topics import FIXED_TOPICS


def inspect_topics(admin, *, partitions=3, replication_factor=1):
    if partitions < 1 or replication_factor < 1:
        raise ValueError("invalid Topic capacity requirements")
    names = sorted(set(FIXED_TOPICS.values()))
    missing = set(names) - set(admin.list_topics())
    if missing:
        raise ValueError(
            "MISSING_TOPICS: "
            + ",".join(sorted(missing))
            + "; run explicit init_fixed_kafka_topics.py"
        )
    rows = admin.describe_topics(names)
    described = {row["topic"]: row for row in rows}
    for name in names:
        row = described.get(name, {})
        parts = row.get("partitions", [])
        if (
            row.get("error_code")
            or len(parts) < partitions
            or any(
                len(p.get("replicas", [])) < replication_factor
                or p.get("error_code", 0)
                for p in parts
            )
        ):
            raise ValueError("TOPIC_CAPACITY_OR_AUTH: " + name)
    return rows


def check_fixed_topics(
    bootstrap, security=None, *, partitions=None, replication_factor=None
):
    admin = KafkaAdminClient(
        bootstrap_servers=bootstrap,
        request_timeout_ms=10000,
        **(security if security is not None else kafka_security_options()),
    )
    try:
        return inspect_topics(
            admin,
            partitions=int(
                partitions
                if partitions is not None
                else os.environ.get("KAFKA_TOPIC_PARTITIONS", "3")
            ),
            replication_factor=int(
                replication_factor
                if replication_factor is not None
                else os.environ.get("KAFKA_TOPIC_REPLICATION_FACTOR", "1")
            ),
        )
    finally:
        admin.close()

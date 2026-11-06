#!/usr/bin/env python3
"""Explicit fixed-topic creation; no retained Topic or ACL is changed/deleted."""

import argparse
from pathlib import Path
import sys

for candidate in Path(__file__).resolve().parents:
    if (candidate / "utils_local").is_dir():
        sys.path.insert(0, str(candidate))
        break
from kafka.admin import KafkaAdminClient, NewTopic
from utils_local.kafka_security import kafka_security_options
from utils_local.kafka_topic_preflight import inspect_topics
from utils_local.replay_topics import FIXED_TOPICS


def main():
    import os

    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap", default=os.environ.get("KAFKA_BOOTSTRAP"))
    parser.add_argument("--partitions", type=int, default=3)
    parser.add_argument("--replication-factor", type=int, required=True)
    args = parser.parse_args()
    if not args.bootstrap or args.partitions < 1 or args.replication_factor < 1:
        parser.error(
            "bootstrap and positive partition/replication settings are required"
        )
    admin = KafkaAdminClient(
        bootstrap_servers=args.bootstrap, **kafka_security_options()
    )
    try:
        existing = set(admin.list_topics())
        missing = [
            NewTopic(name, args.partitions, args.replication_factor)
            for name in FIXED_TOPICS.values()
            if name not in existing
        ]
        if missing:
            admin.create_topics(missing)
        inspect_topics(
            admin,
            partitions=args.partitions,
            replication_factor=args.replication_factor,
        )
        print("FIXED_TOPICS_READY count=9; existing Topics, data and ACLs retained")
    finally:
        admin.close()


if __name__ == "__main__":
    main()

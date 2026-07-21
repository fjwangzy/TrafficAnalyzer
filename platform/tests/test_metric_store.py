import base64
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

from app.kafka.consumer import KafkaConsumerService
from app.models.survey import EvidenceItem, EvidencePackage
from app.services.alert_engine import AlertEngine
from app.services.metric_store import (
    InMemoryMetricStoreAdapter,
    MessageEnvelope,
    MetricContractError,
    PostgresMetricStoreAdapter,
    _period_start,
)


class _RecordingWS:
    def __init__(self):
        self.messages = []

    async def broadcast(self, channel, message):
        self.messages.append((channel, message))


class _FailOnceWS(_RecordingWS):
    def __init__(self):
        super().__init__()
        self.failed = False

    async def broadcast(self, channel, message):
        if not self.failed:
            self.failed = True
            raise RuntimeError("temporary websocket failure")
        await super().broadcast(channel, message)


class _RecordingSession:
    def __init__(self):
        self.rows = []

    def add(self, row):
        self.rows.append(row)


class MetricStoreContractTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.adapter = PostgresMetricStoreAdapter(None)

    def test_canonical_contract_requires_matching_v1_schema(self):
        now = datetime.now(UTC).isoformat()
        payload = {
            "message_id": "msg-1",
            "msg_type": "uav_stats",
            "schema_version": "uav_stats/v2",
            "occurred_at": now,
            "produced_at": now,
            "source_system": "uav_traffic_analyzer_ai",
            "data": {},
        }
        with self.assertRaises(MetricContractError):
            self.adapter._normalize(MessageEnvelope(payload, "uav_statistics_1", 0, 1))

    def test_unprefixed_legacy_message_type_is_rejected(self):
        with self.assertRaisesRegex(MetricContractError, "unsupported canonical msg_type"):
            self.adapter._normalize(MessageEnvelope(
                {"msg_type": "track_complete", "timestamp_last": 12.5, "track_id": 7},
                "uav_track_complete_1",
                0,
                3,
            ))

    def test_unprefixed_or_mismatched_topic_is_rejected(self):
        payload = self._stats_payload("topic-contract-1", 1)
        with self.assertRaisesRegex(MetricContractError, "unsupported canonical topic"):
            self.adapter._normalize(MessageEnvelope(payload, "statistics_1", 0, 1))
        with self.assertRaisesRegex(MetricContractError, "unsupported canonical topic"):
            self.adapter._normalize(MessageEnvelope(payload, "uav_conflicts_1", 0, 2))

    def test_all_period_includes_offline_replay_business_time(self):
        self.assertEqual(_period_start("all"), datetime.min.replace(tzinfo=UTC))

    def test_snapshot_evidence_links_package_for_foreign_key_ordering(self):
        payload = self._stats_payload("stats-evidence-1", 3)
        payload["data"].update({
            "event_snapshot_jpeg": base64.b64encode(b"jpeg").decode(),
            "event_snapshot_width": 960,
            "event_snapshot_height": 540,
        })
        envelope = MessageEnvelope(payload, "uav_statistics_1", 0, 4)
        normalized = self.adapter._normalize(envelope)
        session = _RecordingSession()
        stored = SimpleNamespace(
            storage_key="objects/aa/key",
            sha256="a" * 64,
            size_bytes=4,
        )
        with patch(
            "app.services.metric_store.ContentAddressedStore.ingest_bytes",
            return_value=stored,
        ):
            self.adapter._add_stats(session, envelope, normalized)

        evidence = next(row for row in session.rows if isinstance(row, EvidenceItem))
        self.assertIsNotNone(evidence.package)
        self.assertEqual(evidence.package_id, evidence.package.id)
        self.assertIn(evidence, evidence.package.items)

    def test_conflict_evidence_bundle_persists_three_synchronized_images(self):
        now = datetime.now(UTC).isoformat()
        kinds = [
            "conflict_original_frame",
            "conflict_detector_frame",
            "conflict_trajectory_reconstruction",
        ]
        payload = {
            "message_id": "conflict-evidence-1",
            "msg_type": "uav_conflict",
            "schema_version": "uav_conflict/v1",
            "occurred_at": now,
            "produced_at": now,
            "source_system": "uav_traffic_analyzer_ai",
            "intersection_id": "INT_camera_1",
            "data": {
                "motor_id": 101,
                "non_motor_id": 202,
                "evidence_images": [
                    {
                        "kind": kind,
                        "jpeg_base64": base64.b64encode(f"jpeg-{index}".encode()).decode(),
                        "width": 960,
                        "height": 540,
                    }
                    for index, kind in enumerate(kinds)
                ],
            },
        }
        envelope = MessageEnvelope(payload, "uav_conflicts_1", 0, 7)
        normalized = self.adapter._normalize(envelope)
        session = _RecordingSession()
        stored = [
            SimpleNamespace(
                storage_key=f"objects/{index}/key",
                sha256=str(index) * 64,
                size_bytes=6,
            )
            for index in range(3)
        ]

        with patch(
            "app.services.metric_store.ContentAddressedStore.ingest_bytes",
            side_effect=stored,
        ):
            self.adapter._add_conflict(session, envelope, normalized)

        package = next(row for row in session.rows if isinstance(row, EvidencePackage))
        evidence = [row for row in session.rows if isinstance(row, EvidenceItem)]
        self.assertEqual([item.kind for item in evidence], kinds)
        self.assertEqual(len(package.items), 3)
        self.assertIsNone(evidence[0].derived_from_id)
        self.assertEqual(evidence[1].derived_from_id, evidence[0].id)
        self.assertEqual(evidence[2].derived_from_id, evidence[0].id)
        self.assertEqual(
            [ref["kind"] for ref in normalized["data"]["evidence_refs"]],
            kinds,
        )
        self.assertNotIn("evidence_images", normalized["data"])

    def test_historical_traffic_snapshot_retains_tcc_diagnostics_and_lineage(self):
        diagnostics = {"enabled": True, "status": "no_prediction_candidates"}
        row = SimpleNamespace(
            observed_at=datetime.now(UTC),
            intersection_id="INT-1",
            inter_id="INT-1",
            grain_type="intersection",
            grain_key="INT-1",
            cars=12,
            vehicle_count=12,
            flow_veh_per_min=None,
            avg_speed_kmh=18.0,
            congestion_index=2.1,
            queue_length_m=0.0,
            headway_sec=None,
            quality_status="unverified",
            time_quality="ingest_only",
            source_profile_id="SRC-1",
            pipeline_id="pipe-1",
            payload={"data": {"tcc_diagnostics": diagnostics}},
        )

        result = self.adapter._traffic_dict(row)

        self.assertEqual(result["tcc_diagnostics"], diagnostics)
        self.assertEqual(result["source_profile_id"], "SRC-1")
        self.assertEqual(result["pipeline_id"], "pipe-1")

    @staticmethod
    def _stats_payload(message_id: str, cars: int) -> dict:
        now = datetime.now(UTC).isoformat()
        return {
            "message_id": message_id,
            "msg_type": "uav_stats",
            "schema_version": "uav_stats/v1",
            "occurred_at": now,
            "produced_at": now,
            "source_system": "uav_traffic_analyzer_ai",
            "intersection_id": "INT_camera_1",
            "data": {"cars": cars, "intersection_id": "INT_camera_1"},
        }

    async def test_consumer_does_not_rebroadcast_duplicate_message(self):
        ws = _RecordingWS()
        store = InMemoryMetricStoreAdapter()
        service = KafkaConsumerService(
            bootstrap_servers="localhost:9092",
            group_id="test",
            topics_pattern="uav_statistics_.*",
            ws_manager=ws,
            metric_store=store,
        )
        payload = self._stats_payload("stable-1", 2)

        await service._process_message(payload, "uav_statistics_1", 0, 10)
        await service._process_message(payload, "uav_statistics_1", 0, 11)

        self.assertEqual(len(ws.messages), 1)
        self.assertEqual(ws.messages[0][0], "uav_intersection:INT_camera_1")
        self.assertEqual(ws.messages[0][1]["type"], "uav_stats")

    async def test_consumer_replays_pending_dispatch_after_side_effect_failure(self):
        ws = _RecordingWS()
        store = InMemoryMetricStoreAdapter()
        service = KafkaConsumerService(
            bootstrap_servers="localhost:9092",
            group_id="test",
            topics_pattern="uav_statistics_.*",
            ws_manager=ws,
            metric_store=store,
        )
        payload = self._stats_payload("dispatch-retry-1", 2)
        original = service._handle_stats
        attempts = 0

        async def fail_once(data, intersection_id):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("temporary side effect failure")
            await original(data, intersection_id)

        service._handle_stats = fail_once
        with self.assertRaisesRegex(RuntimeError, "temporary"):
            await service._process_message(payload, "uav_statistics_1", 0, 10)
        key = ("uav_traffic_analyzer_ai", "dispatch-retry-1")
        self.assertEqual(store.dispatch_attempts[key], 1)
        self.assertIn("temporary side effect failure", store.dispatch_errors[key])
        self.assertIsNotNone(store.last_dispatch_attempt_at[key])
        await service._process_message(payload, "uav_statistics_1", 0, 10)
        await service._process_message(payload, "uav_statistics_1", 0, 10)

        self.assertEqual(attempts, 2)
        self.assertEqual(len(ws.messages), 1)
        self.assertEqual(store.dispatch_attempts[key], 2)
        self.assertNotIn(key, store.dispatch_errors)

    async def test_conflict_retry_is_not_swallowed_by_visibility_cache(self):
        ws = _FailOnceWS()
        store = InMemoryMetricStoreAdapter()
        alert_engine = AlertEngine(ws)
        service = KafkaConsumerService(
            bootstrap_servers="localhost:9092",
            group_id="test",
            topics_pattern="uav_conflicts_.*",
            ws_manager=ws,
            alert_engine=alert_engine,
            metric_store=store,
        )
        now = datetime.now(UTC).isoformat()
        payload = {
            "message_id": "conflict-retry-1",
            "msg_type": "uav_conflict",
            "schema_version": "uav_conflict/v1",
            "occurred_at": now,
            "produced_at": now,
            "source_system": "uav_traffic_analyzer_ai",
            "intersection_id": "INT_camera_1",
            "data": {
                "motor_id": 96,
                "non_motor_id": 88,
                "severity": "critical",
                "ttc_sec": 1.2,
                "distance_m": 0.8,
            },
        }

        with self.assertRaisesRegex(RuntimeError, "temporary websocket"):
            await service._process_message(payload, "uav_conflicts_1", 0, 10)
        await service._process_message(payload, "uav_conflicts_1", 0, 10)

        self.assertEqual(len(alert_engine.alerts), 1)

    async def test_consumer_quarantines_permanent_contract_error_without_broadcast(self):
        ws = _RecordingWS()
        store = InMemoryMetricStoreAdapter()
        service = KafkaConsumerService(
            bootstrap_servers="localhost:9092",
            group_id="test",
            topics_pattern="uav_statistics_.*",
            ws_manager=ws,
            metric_store=store,
        )
        invalid = {
            "message_id": "poison-1",
            "msg_type": "uav_stats",
            "schema_version": "uav_stats/v2",
            "source_system": "uav_traffic_analyzer_ai",
            "data": {},
        }

        await service._process_message(invalid, "uav_statistics_1", 2, 99)

        self.assertEqual(ws.messages, [])
        self.assertEqual(len(store.dead_letters), 1)
        dead_letter = store.dead_letters[("uav_statistics_1", 2, 99)]
        self.assertEqual(dead_letter["reason_code"], "MetricContractError")

    async def test_identity_conflict_is_quarantined(self):
        ws = _RecordingWS()
        store = InMemoryMetricStoreAdapter()
        service = KafkaConsumerService(
            bootstrap_servers="localhost:9092",
            group_id="test",
            topics_pattern="uav_statistics_.*",
            ws_manager=ws,
            metric_store=store,
        )
        first = self._stats_payload("stable-2", 2)
        conflicting = {**first, "data": {**first["data"], "cars": 9}}

        await service._process_message(first, "uav_statistics_1", 0, 10)
        await service._process_message(conflicting, "uav_statistics_1", 0, 11)

        self.assertEqual(len(ws.messages), 1)
        self.assertEqual(len(store.dead_letters), 1)
        self.assertEqual(
            store.dead_letters[("uav_statistics_1", 0, 11)]["reason_code"],
            "MessageIdentityConflict",
        )


if __name__ == "__main__":
    unittest.main()

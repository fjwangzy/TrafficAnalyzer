import unittest

from app.kafka.consumer import KafkaConsumerService


class _RecordingWS:
    def __init__(self):
        self.messages = []

    async def broadcast(self, channel, message):
        self.messages.append((channel, message))


class _FailingLaneAnnotationStore:
    def observe_stats(self, intersection_id, data):
        raise OSError("[Errno 30] Read-only file system: '/calibration'")


class KafkaConsumerStatsTest(unittest.IsolatedAsyncioTestCase):
    async def test_stats_broadcast_continues_when_lane_annotation_store_fails(self):
        ws = _RecordingWS()
        service = KafkaConsumerService(
            bootstrap_servers="localhost:9092",
            group_id="test",
            topics_pattern="statistics_.*",
            ws_manager=ws,
            lane_annotation_store=_FailingLaneAnnotationStore(),
        )

        await service._handle_stats(
            {
                "msg_type": "stats",
                "lane_stats": {"1": {"count": 2}},
                "active_trajectories": [{"track_id": 7, "trajectory_world_m": [[0, 0]]}],
            },
            "INT_camera_1",
        )

        self.assertEqual(len(ws.messages), 1)
        channel, message = ws.messages[0]
        self.assertEqual(channel, "intersection:INT_camera_1")
        self.assertEqual(message["type"], "stats")
        self.assertEqual(message["data"]["active_trajectories"][0]["track_id"], 7)
        self.assertEqual(message["data"]["lanes"][0]["vehicle_count"], 2)

"""Offline benchmark: real multiprocessing queue plus real producer, no Kafka network."""

import multiprocessing as mp
import time
import tempfile
import json
from types import SimpleNamespace
from native_trajectory_pickle_fixture import make
from services.MissionTrajectoryArchive import MissionTrajectoryArchive
import test_kafka_active_trajectories as m


def consume(queue, pipe):
    f = queue.get()
    pipe.send(
        (
            len(f.active_tracks),
            sum(len(t.trajectory_points) for t in f.active_tracks.values()),
            f.active_tracks[10].trajectory_points[-1],
        )
    )
    pipe.close()


for numpy in (True, False):
    f = make(numpy)
    samples = []
    with tempfile.TemporaryDirectory() as directory:
        n = m.KafkaActiveTrajectoriesTest()._producer_without_kafka()
        n.storage_profile = "replay_v2"
        n.trajectory_archive = MissionTrajectoryArchive(directory)
        n.mission_id = "profile"
        n.source_profile_id = "SRC-profile"
        n.drone_id = "uav"
        n.mission_topic = "uav_replay_v2_mission_profile"
        n.run_id = "test"
        n.how_often_sec = 0
        n.publisher = SimpleNamespace(
            snapshot=lambda: {}, publish=lambda *a, **kw: None
        )
        for _ in range(3):
            context = mp.get_context("fork")
            queue = context.Queue(maxsize=2)
            receiver, sender = context.Pipe(False)
            child = context.Process(target=consume, args=(queue, sender))
            child.start()
            sender.close()
            start = time.perf_counter()
            queue.put(f)
            begin = time.perf_counter()
            n.process(f)
            foreground = (time.perf_counter() - begin) * 1000
            assert receiver.poll(30)
            out = receiver.recv()
            child.join(5)
            assert child.exitcode == 0
            samples.append(
                {
                    "foreground_ms": foreground,
                    "roundtrip_ms": (time.perf_counter() - start) * 1000,
                }
            )
            assert out == (250, 125000, (511.0, 501.0)), out
            queue.close()
            queue.join_thread()
            receiver.close()
    print(
        json.dumps(
            {
                "numpy_bbox": numpy,
                "samples": samples,
                "all_points_and_values_preserved": True,
            }
        ),
        flush=True,
    )

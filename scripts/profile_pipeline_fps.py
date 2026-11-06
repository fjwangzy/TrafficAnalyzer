#!/usr/bin/env python3
"""Profile the production node sequence frame-by-frame on real material.

The production entrypoint (`main_optimized.py`) splits the same node calls across
processes.  This script keeps the calls in one process so every stage can be
timed per frame with `perf_counter`/`process_time`, and optionally profiled with
`cProfile`.  It never publishes to Kafka and never touches the database.

Examples:

    VIDEO_SRC=... TOPIC_NAME=uav_statistics_1 CAMERA_ID=1 \
    .venv-mps/bin/python scripts/profile_pipeline_fps.py \
        --frames 90 --telemetry-srt test_videos/inter_xqh/telemetry.srt \
        --out output/fps-profile-20261105

    # Function-level attribution for the tracker stages only.
    ... --frames 40 --cprofile --out output/fps-profile-20261105/cprofile

``--egress`` measures the four-process handoff with an in-process ACK writer.  Runs
longer than the 128-point online history tail can trip the archive's monotonic
history guard ("authoritative point history regressed"); use ``--debug-egress`` to
print the offending track state, and keep egress runs short or segmented.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def build_config(args) -> dict:
    from hydra import compose, initialize_config_dir
    from omegaconf import OmegaConf

    # Paths live in the environment: Hydra's override grammar rejects the dots and
    # CJK characters of the real 4K fixtures.
    os.environ["VIDEO_SRC"] = str(Path(args.video).resolve())
    os.environ["FRAME_STRIDE"] = str(args.stride)
    if args.weight:
        os.environ["DETECTION_WEIGHT_PATH"] = args.weight
    overrides = [
        f"detection_node.imgsz={args.imgsz}",
        f"detection_node.device={args.device}",
    ]
    with initialize_config_dir(
        config_dir=str((PROJECT_ROOT / "configs").resolve()), version_base=None
    ):
        cfg = compose(config_name="app_config", overrides=overrides)
    config = OmegaConf.to_container(cfg, resolve=True)
    config["pipeline"]["send_info_kafka"] = False
    config["pipeline"]["save_video"] = False
    config["pipeline"]["show_in_web"] = False
    config["video_reader"]["skip_secs"] = args.skip_secs
    if args.telemetry_srt:
        config["telemetry"].update(
            {
                "enabled": True,
                "source": "srt",
                "file_path": str(Path(args.telemetry_srt).resolve()),
                "sync_tolerance_sec": 0.1,
                "time_offset_sec": 0.0,
            }
        )
    if args.telemetry_file:
        config["telemetry"].update(
            {
                "enabled": True,
                "source": "file",
                "file_path": str(Path(args.telemetry_file).resolve()),
                "sync_tolerance_sec": args.sync_tolerance,
                "time_offset_sec": args.time_offset,
            }
        )
    return config


class Timer:
    def __init__(self) -> None:
        self.rows: dict[str, list[tuple[float, float]]] = defaultdict(list)

    def run(self, name, function, *call_args, **call_kwargs):
        wall = time.perf_counter()
        cpu = time.process_time()
        try:
            return function(*call_args, **call_kwargs)
        finally:
            self.rows[name].append(
                ((time.perf_counter() - wall) * 1000.0, (time.process_time() - cpu) * 1000.0)
            )

    def summary(self, frames: int) -> dict:
        out = {}
        for name, samples in self.rows.items():
            wall = sorted(sample[0] for sample in samples)
            cpu = sorted(sample[1] for sample in samples)
            out[name] = {
                "calls": len(wall),
                "calls_per_frame": round(len(wall) / max(frames, 1), 3),
                "wall_median_ms": round(statistics.median(wall), 2),
                "wall_p90_ms": round(wall[int(0.9 * (len(wall) - 1))], 2),
                "wall_max_ms": round(wall[-1], 2),
                "wall_total_ms": round(sum(wall), 1),
                "cpu_median_ms": round(statistics.median(cpu), 2),
                "cpu_total_ms": round(sum(cpu), 1),
            }
        return out


class FakeWriter(threading.Thread):
    """Ack every egress packet without the journal, so ACK latency is excluded."""

    def __init__(self, queue, acks) -> None:
        super().__init__(daemon=True, name="fake-egress-writer")
        self.queue = queue
        self.acks = acks
        self.packets = 0
        self._stopped = threading.Event()

    def run(self) -> None:
        from queue import Empty

        while not self._stopped.is_set():
            try:
                packet = self.queue.get(timeout=0.1)
            except Empty:
                continue
            self.packets += 1
            self.acks.put(packet[1])

    def stop(self) -> None:
        self._stopped.set()
        self.join(timeout=2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True)
    parser.add_argument("--frames", type=int, default=90)
    parser.add_argument("--warmup", type=int, default=5, help="timed frames are dropped from the first N")
    parser.add_argument("--stride", type=int, default=3)
    parser.add_argument("--skip-secs", type=float, default=0.0)
    parser.add_argument("--imgsz", type=int, default=960)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--weight", default="")
    parser.add_argument("--telemetry-srt", default="")
    parser.add_argument("--telemetry-file", default="", help="DJI Cloud OSD JSON/TXT replay")
    parser.add_argument("--time-offset", type=float, default=0.0)
    parser.add_argument("--sync-tolerance", type=float, default=2.5)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--render", action="store_true", help="also time ShowNode on a frame copy (P3 cost)")
    parser.add_argument("--egress", action="store_true", help="sender-only IPC with fake ACK; excludes real journal, receiver and Kafka")
    parser.add_argument("--cprofile", action="store_true")
    parser.add_argument("--debug-egress", action="store_true", help="abort on misaligned track arrays")
    detection_trace = parser.add_mutually_exclusive_group()
    detection_trace.add_argument("--record-detections", type=Path)
    detection_trace.add_argument("--replay-detections", type=Path)
    args = parser.parse_args()

    os.environ.setdefault("ROAD_FEATURES_ENABLED", "false")
    os.environ.setdefault("TRACKING_PROFILE", "hover_cruise_v1")
    config = build_config(args)

    from nodes.VideoReader import VideoReader
    from nodes.DetectionNode import DetectionNode
    from nodes.HomographyCalibrationNode import HomographyCalibrationNode
    from nodes.MotionCompensationNode import MotionCompensationNode
    from nodes.ImageMotionEstimationNode import ImageMotionEstimationNode
    from nodes.FlightGeoReferenceNode import FlightGeoReferenceNode
    from nodes.GroundTrajectoryTrackerNode import GroundTrajectoryTrackerNode
    from nodes.PostTrackingWorldProjectionNode import PostTrackingWorldProjectionNode
    from nodes.TrackerInfoUpdateNode import TrackerInfoUpdateNode
    from nodes.SpeedEstimationNode import SpeedEstimationNode
    from nodes.DirectionFlowNode import DirectionFlowNode
    from nodes.TrajectoryNode import TrajectoryNode
    from nodes.LaneChangeDetectionNode import LaneChangeDetectionNode
    from nodes.EnforcementDetectionNode import EnforcementDetectionNode
    from nodes.RoadMapMatchingNode import RoadMapMatchingNode
    from nodes.ConflictDetectionNode import ConflictDetectionNode
    from nodes.CalcStatisticsNode import CalcStatisticsNode
    from nodes.ShowNode import ShowNode
    from services.PipelineEgress import EgressClient, SnapshotScheduler, freeze_egress_views

    road_features = os.environ.get("ROAD_FEATURES_ENABLED", "true").lower() != "false"

    reader = VideoReader(config["video_reader"], config.get("telemetry"))
    from utils_local.detection_trace import DetectionTrace
    trace = DetectionTrace(args.replay_detections or args.record_detections,
                           replay=bool(args.replay_detections),
                           identity={"video": str(Path(args.video).resolve()), "stride": args.stride,
                                     "skip_secs": args.skip_secs}) if (args.replay_detections or args.record_detections) else None
    detection = None if args.replay_detections else DetectionNode(config)
    homography = HomographyCalibrationNode(config)
    motion_compensation = MotionCompensationNode(config)
    image_motion = ImageMotionEstimationNode(config)
    geo_reference = FlightGeoReferenceNode(config)
    tracker = GroundTrajectoryTrackerNode(config)
    world_projection = PostTrackingWorldProjectionNode(config)
    tracker_info = TrackerInfoUpdateNode(config)
    speed = SpeedEstimationNode(config)
    direction = DirectionFlowNode(config)
    trajectory = TrajectoryNode(config)
    lane_change = LaneChangeDetectionNode(config)
    enforcement = EnforcementDetectionNode(config)
    map_matching = RoadMapMatchingNode(config)
    conflict = ConflictDetectionNode(config)
    statistics_node = CalcStatisticsNode(config)
    show = ShowNode(config) if args.render else None
    scheduler = SnapshotScheduler(config) if args.egress else None

    egress_client = writer = None
    if args.egress:
        from multiprocessing import Queue

        queue, acks = Queue(maxsize=32), Queue()
        writer = FakeWriter(queue, acks)
        writer.start()
        if args.debug_egress:

            class DebugEgressClient(EgressClient):
                def point_rows(self, track_id, arrays, base=0):
                    try:
                        return super().point_rows(track_id, arrays, base)
                    except ValueError as exc:
                        print(
                            "POINT_ROWS_FAILURE",
                            "track=", track_id,
                            "base=", base,
                            "lengths=", {k: len(v) for k, v in arrays.items()},
                            "start=", self.offsets.get(str(track_id)),
                            "reason=", exc,
                        )
                        raise

        egress_client = (DebugEgressClient if args.debug_egress else EgressClient)(
            "tracker",
            queue,
            acks,
            timeout=10.0,
            alive=lambda: True,
            optimized_views=bool(config["pipeline"].get("transport_views_optimized", True)),
            bounded_history=True,
            history_tail_points=int(config["pipeline"].get("online_history_tail_points", 128)),
        )

    timer = Timer()
    load = []
    wall_total = time.perf_counter()
    processed = 0
    profiler = None
    if args.cprofile:
        import cProfile

        profiler = cProfile.Profile()

    try:
        frames = reader.process()
        while processed < args.frames + args.warmup:
            element = next(frames, None)
            if element is None or type(element).__name__ == "VideoEndBreakElement":
                break
            frame_wall = time.perf_counter()
            if args.replay_detections:
                trace.apply(element)
            else:
                element = timer.run("detect", detection.process, element)
                if trace is not None and type(element).__name__ != "VideoEndBreakElement":
                    trace.record(element)
            if type(element).__name__ == "VideoEndBreakElement":
                break
            timed = processed >= args.warmup

            def step(name, function, *call_args):
                if not timed:
                    return function(*call_args)
                return timer.run(name, function, *call_args)

            if profiler is not None and timed:
                profiler.enable()
            element = step("tracker.image_motion", image_motion.process, element)
            element = step("tracker.association", tracker.process, element)
            element = step("tracker.homography", homography.process, element)
            element = step("tracker.motion_compensation", motion_compensation.process, element)
            element = step("tracker.geo_reference", geo_reference.process, element)
            element = step("tracker.world_projection", world_projection.process, element)
            element = step("tracker.info", tracker_info.process, element)
            element = step("tracker.speed", speed.process, element)
            element = step("tracker.direction", direction.process, element)
            element = step("tracker.trajectory", trajectory.process, element)
            element = step("tracker.lane_change", lane_change.process, element)
            element = step("tracker.map_matching", map_matching.process, element)
            element = step("tracker.enforcement", enforcement.process, element)
            element = step("tracker.conflict", conflict.process, element)
            element = step("tracker.statistics", statistics_node.process, element)
            if profiler is not None and timed:
                profiler.disable()

            if scheduler is not None:
                step("tracker.snapshot_scheduler", scheduler.apply, element)
            if egress_client is not None:
                if args.debug_egress:
                    from services.PipelineEgress import POINT_FIELDS, TRACK_FIELDS

                    for row in getattr(element, "completed_tracks", None) or []:
                        lengths = {
                            field: len(row.get(field) or ()) for field in POINT_FIELDS
                        }
                        if len(set(lengths.values())) > 1:
                            print(
                                "MISALIGNED_COMPLETED",
                                row.get("track_id"),
                                "start=",
                                row.get("trajectory_history_start", 0),
                                lengths,
                            )
                            raise SystemExit(4)
                    for track in (getattr(element, "active_tracks", None) or {}).values():
                        lengths = {
                            source: len(getattr(track, source, ()) or ())
                            for source in TRACK_FIELDS
                        }
                        if len(set(lengths.values())) > 1:
                            print(
                                "MISALIGNED",
                                getattr(track, "id", None),
                                "start=",
                                getattr(track, "trajectory_history_start", 0),
                                lengths,
                            )
                            raise SystemExit(3)
                step("tracker.egress_delta", egress_client.frame, element)
            else:
                step("tracker.freeze_views", freeze_egress_views, element)

            if show is not None and timed:
                render_frame = element.frame.copy()
                element.frame = render_frame
                timer.run("show.render", show.process, element)
                element.frame = None

            if timed:
                diagnostics = getattr(element, "tracking_diagnostics", None) or {}
                load.append(
                    {
                        "frame_num": int(getattr(element, "frame_num", -1)),
                        "detections": len(getattr(element, "detected_xyxy", None) or []),
                        "active_tracks": len(getattr(element, "active_tracks", None) or {}),
                        "tracker_state_ids": len(
                            diagnostics.get("association_state_ids") or []
                        ),
                        "wall_ms": round((time.perf_counter() - frame_wall) * 1000.0, 1),
                        "total_points": sum(
                            len(getattr(track, "trajectory_points", None) or ())
                            for track in (getattr(element, "active_tracks", None) or {}).values()
                        ),
                        "stage_ms": {
                            name: round(samples[-1][0], 2)
                            for name, samples in timer.rows.items()
                        },
                    }
                )
            processed += 1
    finally:
        if trace is not None:
            trace.close()
        wall_elapsed = time.perf_counter() - wall_total
        if writer is not None:
            writer.stop()

    args.out.mkdir(parents=True, exist_ok=True)
    result = {
        "video": args.video,
        "stride": args.stride,
        "imgsz": args.imgsz,
        "measurement_scope": "single-process nodes; fake ACK excludes real P4 journal, receiver and Kafka",
        "detection_trace_sha256": trace.digest.hexdigest() if trace is not None else None,
        "device": config["detection_node"].get("device"),
        "weight": config["detection_node"].get("weight_pth"),
        "road_features": road_features,
        "frames_read": processed,
        "frames_timed": len(load),
        "wall_sec": round(wall_elapsed, 2),
        "stages": timer.summary(len(load)),
        "load": load,
    }
    (args.out / "stages.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))

    if profiler is not None:
        import pstats

        profiler.dump_stats(str(args.out / "tracker.prof"))
        with (args.out / "cprofile.txt").open("w") as handle:
            pstats.Stats(profiler, stream=handle).sort_stats("tottime").print_stats(45)

    rows = list(result["stages"].items())
    print(f"timed frames={len(load)} wall={wall_elapsed:.1f}s")
    print(f"{'stage':34} {'med_ms':>8} {'p90_ms':>8} {'cpu_med':>8} {'total_ms':>9}")
    for name, data in rows:
        print(
            f"{name:34} {data['wall_median_ms']:>8.1f} {data['wall_p90_ms']:>8.1f} "
            f"{data['cpu_median_ms']:>8.1f} {data['wall_total_ms']:>9.1f}"
        )
    if load:
        print(
            "avg detections=%.1f tracks=%.1f  sum(stage median)=%.1fms"
            % (
                statistics.mean(row["detections"] for row in load),
                statistics.mean(row["active_tracks"] for row in load),
                sum(
                    data["wall_median_ms"]
                    for name, data in rows
                    if data["calls_per_frame"] >= 0.9
                ),
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

import importlib.util
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from utils_local.detection_trace import DetectionTrace
from utils_local.runtime_logging import StageMonitor

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_frame_budget_is_not_sum_of_medians():
    compare = module("compare_fps_profile")
    run = {
        "frames": [
            {"stage_ms": {"tracker.info": a, "tracker.speed": b}}
            for a, b in [(100, 1), (1, 100), (1, 1)]
        ]
    }
    assert compare.p2_sum(run) == 101
    with pytest.raises(ValueError):
        compare.p2_sum({"frames": []})


def test_audit_summary_contains_all_calls_and_bounded_percentiles(monkeypatch, caplog):
    monkeypatch.setenv("PIPELINE_PERF_AUDIT", "1")
    with caplog.at_level(logging.INFO):
        monitor = StageMonitor()
        try:
            for _ in range(4):
                with monitor.stage("audit.test"):
                    pass
        finally:
            monitor.close()
    summary = [
        json.loads(row.message.split("PERF_SUMMARY ", 1)[1])
        for row in caplog.records
        if "PERF_SUMMARY " in row.message
    ]
    assert summary[0]["count"] == 4
    assert summary[0]["percentile_samples"] == 4
    assert summary[0]["total_ms"] >= summary[0]["p99_ms"] >= summary[0]["p50_ms"] >= 0


def test_detection_capture_replays_exact_frames_and_rejects_mismatch(tmp_path):
    video = tmp_path / "video"
    video.write_bytes(b"test-video")
    identity = {"video": str(video), "stride": 3}
    path = tmp_path / "detections.jsonl"
    recorder = DetectionTrace(path, replay=False, identity=identity)
    source = SimpleNamespace(
        frame_num=3, timestamp=0.1, detected_xyxy=[[1, 2, 3, 4]], detected_cls_ids=[3]
    )
    recorder.record(source)
    recorder.close()
    reader = DetectionTrace(path, replay=True, identity=identity)
    target = SimpleNamespace(frame_num=3, timestamp=0.1)
    reader.apply(target)
    reader.close()
    assert target.detected_xyxy == source.detected_xyxy
    assert recorder.digest.hexdigest() == reader.digest.hexdigest()
    with pytest.raises(ValueError, match="mismatch"):
        DetectionTrace(path, replay=True, identity={**identity, "stride": 5})


def test_percentile_buffer_is_bounded_but_totals_cover_every_call(monkeypatch):
    monkeypatch.setenv("PIPELINE_PERF_AUDIT", "1")
    monitor = StageMonitor()
    try:
        for i in range(10000):
            monitor.observe("audit.bound", float(i))
        metric = monitor._metrics["audit.bound"]
        assert len(metric["samples"]) == 4096
        assert metric["count"] == 10000
        assert metric["total_ms"] == sum(range(10000))
    finally:
        monitor.close()


def test_resource_sampler_without_optional_dependencies(monkeypatch):
    runner = module("run_fps_audit")
    monkeypatch.setattr(runner, "psutil", None)
    monkeypatch.setattr(
        runner.subprocess,
        "check_output",
        lambda *a, **k: "10 1 2.0 100\n11 10 80.0 200\n12 11 5.0 300\n99 1 9.0 900\n",
    )
    rows = runner.sample_processes(10, {})
    assert {row["pid"] for row in rows} == {10, 11, 12}
    assert rows[1]["rss"] == 200 * 1024
    assert all(row["io"] is None for row in rows)

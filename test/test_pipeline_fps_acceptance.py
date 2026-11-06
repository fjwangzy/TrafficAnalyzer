import importlib.util
import json
from pathlib import Path


spec = importlib.util.spec_from_file_location("fps_accept", Path(__file__).resolve().parents[1]/"scripts/accept_pipeline_fps.py")
fps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fps)


def diagnosis(tmp_path, rate=3, depth=0, seconds=330):
    from datetime import datetime, timedelta, timezone
    start = datetime(2026, 11, 4, tzinfo=timezone.utc)
    lines = []
    for offset in range(0, seconds+1, 30):
        timestamp = (start+timedelta(seconds=offset)).isoformat().replace("+00:00", "Z")
        lines.append(f"{timestamp} EGRESS_STATUS frames={{'tracker': {int(offset*rate)}, 'show': {int(offset*rate)}}} queue_depth={depth} committed={int(offset*rate)}")
    path = tmp_path/"diagnosis.json"
    path.write_text(json.dumps({"logs": {"pipe-current.log": "\n".join(lines)}}))
    return path


def test_three_fps_completed_frames_pass(tmp_path):
    assert fps.inspect_diagnosis(diagnosis(tmp_path))["status"] == "passed"


def test_slow_or_backpressured_run_fails(tmp_path):
    assert fps.inspect_diagnosis(diagnosis(tmp_path, rate=.7))["status"] == "failed"
    assert fps.inspect_diagnosis(diagnosis(tmp_path, depth=32))["status"] == "failed"


def test_short_capture_does_not_claim_acceptance(tmp_path):
    assert fps.inspect_diagnosis(diagnosis(tmp_path, seconds=180))["status"] == "not_evaluated"


def test_full_log_retains_actual_pipeline_identity(tmp_path):
    source = diagnosis(tmp_path)
    lines = json.loads(source.read_text())["logs"]["pipe-current.log"]
    raw = tmp_path/"copied-log.txt"
    raw.write_text(lines.replace(" EGRESS_STATUS", " pipeline=pipe-original EGRESS_STATUS"))
    result = fps.inspect_diagnosis(raw)
    assert result["status"] == "passed"
    assert result["pipeline"] == "pipe-original"


def test_arrival_watermarks_cannot_claim_business_commit(tmp_path):
    path = diagnosis(tmp_path)
    value = json.loads(path.read_text())
    import re
    value['logs']['pipe-current.log'] = re.sub(r" committed=\d+", "", value['logs']['pipe-current.log'])
    path.write_text(json.dumps(value))
    assert fps.inspect_diagnosis(path)['status'] == 'not_evaluated'


def test_slow_commit_cannot_be_hidden_by_fast_tracker_and_show(tmp_path):
    path = diagnosis(tmp_path)
    value = json.loads(path.read_text())
    import re
    value['logs']['pipe-current.log'] = re.sub(
        r'committed=(\d+)', lambda m: 'committed='+str(int(m[1])//3),
        value['logs']['pipe-current.log'])
    path.write_text(json.dumps(value))
    result = fps.inspect_diagnosis(path)
    assert result['status'] == 'failed'
    assert result['completed_fps'] == 1
    assert result['arrival_fps']['tracker'] == 3

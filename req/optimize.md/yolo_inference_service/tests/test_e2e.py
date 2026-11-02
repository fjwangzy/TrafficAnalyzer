#!/usr/bin/env python3
"""端到端验证：订更新面断言双通道 + 每流 seq 严格 +1（须服务与上游已运行）。

用法（model_deployment 根目录）：
  python3 device_run_new/service_ultimate/yolo_inference_service/tests/test_e2e.py
"""
import sys, os
sys.path.insert(0, os.getcwd())

import time
from device_run_new.service_ultimate.core_module.py_module.yolo_client import (
    YoloInferenceClient,
)

CTRL = "ipc:///tmp/drn-yolo-inference.sock"


def main() -> int:
    client = YoloInferenceClient(CTRL)
    health = client.health()
    update_ep = health.get("update_endpoint") or "ipc:///tmp/drn-yolo-inference-updates.sock"
    print(f"health: streams={health.get('known_streams')} update={update_ep}")
    sub = client.subscribe_updates(update_endpoint=update_ep)

    per_stream: dict[str, int] = {}
    events = dual_ok = track_ok = bad_gap = 0
    t0 = time.time()
    while time.time() - t0 < 10.0:
        evt = sub.receive(timeout=2.0)
        if evt is None:
            continue
        r = evt.result
        events += 1
        prev = per_stream.get(r.stream_id)
        if prev is not None and r.seq != prev + 1:
            bad_gap += 1
            print(f"GAP {r.stream_id}: {prev} -> {r.seq}")
        per_stream[r.stream_id] = r.seq
        if r.detections and r.untracked_detections:
            dual_ok += 1
        # 契约：track_id >= 1 才写键；短拷/未确认条目可无该键（合法），
        # 但一旦出现必须 >= 1。
        if all(d.get("track_id", 1) >= 1 for d in r.detections):
            track_ok += 1
    sub.close()

    print(f"events={events} streams={len(per_stream)} bad_gap={bad_gap} "
          f"dual_channel_frames={dual_ok} track_ok_frames={track_ok}")
    ok = (events >= 10 and len(per_stream) >= 1 and bad_gap == 0
          and dual_ok > 0 and track_ok == events)  # track_ok==events 见上：全帧合法
    print("e2e:", "PASS" if ok else "FAIL")
    client.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

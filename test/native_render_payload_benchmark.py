"""Verify ordinary render payload size is independent of full trajectory length."""

import gc
import json
import pickle
import time
from native_trajectory_pickle_fixture import make
from services.PipelineEgress import freeze_frame

for count in (500, 5000):
    frame = make(False, 250, count)
    start = time.perf_counter()
    raw = pickle.dumps(frame, protocol=pickle.HIGHEST_PROTOCOL)
    old_ms = (time.perf_counter() - start) * 1000
    frozen = freeze_frame(frame)
    start = time.perf_counter()
    encoded = pickle.dumps(frozen, protocol=pickle.HIGHEST_PROTOCOL)
    new_ms = (time.perf_counter() - start) * 1000
    restored = pickle.loads(encoded)
    assert len(encoded) <= len(raw) * 0.1
    for key, track in frame.active_tracks.items():
        view = restored.active_tracks[key]
        assert (
            len(view.trajectory_points) <= 30 and view.trajectory_point_count == count
        )
        assert list(view.trajectory_points) == track.trajectory_points[-30:]
        assert (
            list(view.ground_contact_points_px) == track.ground_contact_points_px[-30:]
        )
    print(
        json.dumps(
            {
                "tracks": 250,
                "points_per_track": count,
                "full_frame_bytes": len(raw),
                "render_frame_bytes": len(encoded),
                "reduction_ratio": 1 - len(encoded) / len(raw),
                "full_pickle_ms": old_ms,
                "render_pickle_ms": new_ms,
                "original_tails_and_ids_preserved": True,
            }
        ),
        flush=True,
    )
    del frame, raw, frozen, encoded, restored
    gc.collect()

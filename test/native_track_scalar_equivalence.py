"""Run against either package to compare full tracking records across scalar conversion."""
import json
import sys
import numpy as np
from test_ground_trajectory_tracker import BaseTrack, _TrackingPipeline, _config, _frame, TrackerInfoUpdateNode


def encode(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(type(value).__name__)


BaseTrack._count = 0
tracker = _TrackingPipeline(_config())
accumulator = TrackerInfoUpdateNode(_config())
snapshots = []
for index in range(20):
    frame = _frame(index * .1, [20 + index, 20, 40 + index, 40])
    frame.pixel_to_world_enu = np.eye(3)
    frame.homography_matrix = np.eye(3)
    frame.drone_displacement_m = np.zeros(2)
    frame = accumulator.process(tracker.process(frame))
    snapshots.append({'ids': frame.id_list, 'boxes': frame.tracked_xyxy,
                      'tracks': {str(key): vars(value).copy() for key, value in frame.buffer_tracks.items()}})
    # Freeze each frame so later in-place track history enrichment cannot change it.
    snapshots[-1] = json.loads(json.dumps(snapshots[-1], default=encode))
termination = tracker.flush('natural_eof')
completed = accumulator.flush(timestamp=1.9, reason=termination['termination_reason'],
                              terminated_track_ids=termination['terminated_track_ids'])
snapshots.append({'completed_tracks': completed.completed_tracks})
with open(sys.argv[1], 'w') as stream:
    json.dump(snapshots, stream, default=encode, sort_keys=True, separators=(',', ':'))
print('PASS frozen 20-frame full tracking records and EOF records:', sys.argv[1])

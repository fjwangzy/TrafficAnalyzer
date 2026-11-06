"""Synthetic full-history payload used by native IPC regression measurements."""

import numpy as np
from elements.FrameElement import FrameElement
from elements.TrackElement import TrackElement


def make(native, tracks_count=250, point_count=500):
    f = FrameElement("fixture", None, 60.0, 600, {})
    tracks = {}
    for i in range(tracks_count):
        t = TrackElement(i, 0.0)
        for j in range(point_count):
            x = np.int64(i + j) if native else int(i + j)
            y = np.int64(j) if native else int(j)
            # Matches bbox arithmetic in TrackerInfoUpdateNode.
            cx = (x + x + 4) / 2.0
            cy = (y + y + 4) / 2.0
            t.trajectory_points.append((cx, cy))
            t.ground_contact_points_px.append((cx, float(y + 4)))
            t.trajectory_enu_m.append((float(cx), float(cy)))
            t.trajectory_gcj02.append(
                (117.0 + float(cx) * 1e-6, 36.0 + float(cy) * 1e-6)
            )
            t.trajectory_timestamps_sec.append(j * 0.1)
            t.trajectory_frame_nums.append(j * 3 + 1)
            t.point_quality_lineage.append(
                {
                    "tracking_quality": "verified",
                    "geo_quality": "verified",
                    "road_quality": "unavailable",
                    "source_frame_num": j * 3 + 1,
                }
            )
        t.trajectory_output_eligible = True
        tracks[i] = t
    f.buffer_tracks = tracks
    f.active_tracks = tracks
    f.mature_tracks = tracks
    return f

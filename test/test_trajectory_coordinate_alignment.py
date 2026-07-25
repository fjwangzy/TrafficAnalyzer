import numpy as np

from elements.FrameElement import FrameElement
from nodes.TrajectoryNode import TrajectoryNode


def test_completed_trajectory_downsampling_preserves_all_coordinate_lineage():
    count = 101
    values = [[float(index), float(index + 1)] for index in range(count)]
    completed = {
        "track_id": 7,
        "trajectory_px": [point.copy() for point in values],
        "trajectory_bbox_center_px": [point.copy() for point in values],
        "ground_contact_points_px": [point.copy() for point in values],
        "trajectory_enu_m": [point.copy() for point in values],
        "trajectory_gcj02": [point.copy() for point in values],
        "trajectory_timestamps_sec": [index * 0.1 for index in range(count)],
        "trajectory_frame_nums": list(range(count)),
        "point_quality_lineage": [{"frame_num": index} for index in range(count)],
    }
    frame = FrameElement(
        source="test",
        frame=np.zeros((10, 10, 3), dtype=np.uint8),
        timestamp=10.0,
        frame_num=100,
        roads_info={},
    )
    frame.completed_tracks = [completed]
    node = TrajectoryNode({"trajectory": {"enabled": True}})

    result = node.process(frame)

    output = result.completed_tracks[0]
    expected_length = len(output["trajectory_px"])
    assert expected_length <= 51
    for key in (
        "trajectory_bbox_center_px",
        "ground_contact_points_px",
        "trajectory_enu_m",
        "trajectory_gcj02",
        "trajectory_timestamps_sec",
        "trajectory_frame_nums",
        "point_quality_lineage",
    ):
        assert len(output[key]) == expected_length

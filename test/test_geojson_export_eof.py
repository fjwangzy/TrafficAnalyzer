from elements.FrameElement import FrameElement
from nodes.GeoJsonExportNode import GeoJsonExportNode


def test_geojson_export_accepts_canonical_completed_track_without_frame(tmp_path):
    node = GeoJsonExportNode(
        {
            "geojson_export": {
                "enabled": True,
                "output_dir": str(tmp_path),
                "simplify_tolerance_m": 0,
            }
        }
    )
    flush_frame = FrameElement(
        source="fixture.mp4",
        frame=None,
        timestamp=12.0,
        frame_num=360,
        roads_info={},
    )
    flush_frame.completed_tracks = [
        {
            "track_id": 7,
            "trajectory_px": [[100.0, 200.0], [110.0, 210.0]],
            "trajectory_gcj02": [
                [117.093, 36.6628],
                [117.0931, 36.6629],
            ],
            "anchor_gcj02": [117.093, 36.6628],
        }
    ]

    assert node.process(flush_frame) is flush_frame
    assert node._collected_tracks[0]["geometry"]["coordinates"] == [
        [117.093, 36.6628],
        [117.0931, 36.6629],
    ]

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


def test_four_worker_spatial_export_does_not_hold_all_completed_features_in_memory(tmp_path):
    import json
    from services.SpatialFeatureSpool import SpatialFeatureSpool
    node=GeoJsonExportNode({'pipeline':{'egress_enabled':True},'geojson_export':{'output_dir':str(tmp_path)}})
    assert isinstance(node._collected_tracks,SpatialFeatureSpool)
    feature={'type':'Feature','geometry':{'type':'LineString','coordinates':[[117,36],[117.1,36.1]]},'properties':{'track_id':1}}
    for i in range(1000):node._collected_tracks.append({**feature,'properties':{'track_id':i}})
    path=node._export_geojson('test')
    data=json.loads(open(path).read())
    assert data['metadata']['track_count']==1000 and len(data['features'])==1000
    assert data['features'][0]['properties']['track_id']==0
    assert data['features'][-1]['properties']['track_id']==999
    node._collected_tracks.close()

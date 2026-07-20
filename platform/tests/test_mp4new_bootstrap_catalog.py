from pathlib import Path

from scripts.bootstrap_mp4new_sources import LOCAL_REPLAY_CATALOG, MP4NEW_CATALOG

ROOT = Path(__file__).resolve().parents[2]


def test_mp4new_catalog_has_three_intersections_and_eight_readable_pairs():
    sources = [source for item in MP4NEW_CATALOG for source in item["sources"]]
    assert len(MP4NEW_CATALOG) == 3
    assert len(sources) == 8
    assert len({item["inter_id"] for item in MP4NEW_CATALOG}) == 3
    assert len({source["profile_id"] for source in sources}) == 8
    for source in sources:
        assert (ROOT / source["video"]).is_file()
        assert (ROOT / source["telemetry"]).is_file()
        assert source["time_offset_sec"] > 0


def test_mp4new_catalog_preserves_known_offsets_and_degradation():
    sources = {source["profile_id"]: source for item in MP4NEW_CATALOG for source in item["sources"]}
    assert sources["SRC-MP4NEW-HY-0624-PM"]["time_offset_sec"] == 233.463
    assert sources["SRC-MP4NEW-HY-0625-AM"]["time_offset_sec"] == 178.129
    assert sources["SRC-MP4NEW-LS-0624-PM"]["time_offset_sec"] == 179.115
    assert sources["SRC-MP4NEW-LS-0625-AM"]["time_offset_sec"] == 132.032
    assert sources["SRC-MP4NEW-CH-0625-AM"]["time_offset_sec"] == 247.096
    assert sources["SRC-MP4NEW2-HY-0715-PM"]["time_offset_sec"] == 169.004
    assert sources["SRC-MP4NEW2-LS-0715-PM"]["time_offset_sec"] == 691.247
    assert sources["SRC-MP4NEW2-CH-0715-PM"]["time_offset_sec"] == 334.868
    assert sources["SRC-MP4NEW-LS-0624-PM"]["known_degradation"] == "telemetry_gap_34s"


def test_local_replay_catalog_has_four_intersections_and_nine_pairs():
    sources = [source for item in LOCAL_REPLAY_CATALOG for source in item["sources"]]
    assert len(LOCAL_REPLAY_CATALOG) == 4
    assert len(sources) == 9
    assert len({item["drone_id"] for item in LOCAL_REPLAY_CATALOG}) == 4
    inter_xqh = next(source for source in sources if source["profile_id"] == "SRC-INTER-XQH-0403-PM")
    assert inter_xqh["telemetry_type"] == "srt"
    assert inter_xqh["time_offset_sec"] == 0
    for source in sources:
        assert (ROOT / source["video"]).is_file()
        assert (ROOT / source["telemetry"]).is_file()


def test_local_replay_catalog_has_traceable_test_coordinates_for_map_acceptance():
    for item in LOCAL_REPLAY_CATALOG:
        coordinate = item["test_coordinate"]
        assert 36.6 < coordinate["lat"] < 36.8
        assert 117.0 < coordinate["lon"] < 117.2
        assert "telemetry_median" in coordinate["source"]


def test_all_local_replay_sources_start_without_lane_annotation_parameters():
    assert all(not item.get("roads_json") for item in LOCAL_REPLAY_CATALOG)

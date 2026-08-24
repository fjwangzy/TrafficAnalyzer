from pathlib import Path

from scripts.bootstrap_mp4new_sources import (
    ALL_LOCAL_REPLAY_CATALOG,
    LOCAL_REPLAY_CATALOG,
    MP4NEW_CATALOG,
    MP4728_CATALOG,
    MP4820_CATALOG,
)

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


def test_mp4728_catalog_registers_jingshi_profiles_with_distinct_telemetry():
    assert len(MP4728_CATALOG) == 1
    item = MP4728_CATALOG[0]
    assert item["inter_id"] == "INT_MP4728_JINGSHI_CORRIDOR"
    sources = {source["profile_id"]: source for source in item["sources"]}
    assert set(sources) == {
        "SRC-MP4728-JS-0728-3MS",
        "SRC-MP4728-JS-0728-5MS",
        "SRC-MP4728-JS-0728-7MS",
        "SRC-MP4729-JS-0729-3MS",
    }
    assert all(source["telemetry_enabled"] is True for source in sources.values())
    assert sources["SRC-MP4728-JS-0728-3MS"]["time_offset_sec"] == 72.778
    assert sources["SRC-MP4728-JS-0728-5MS"]["time_offset_sec"] == 72.438
    assert sources["SRC-MP4728-JS-0728-7MS"]["time_offset_sec"] == 74.373
    assert sources["SRC-MP4729-JS-0729-3MS"]["time_offset_sec"] == 73.779
    telemetry_hashes = {
        source["source_manifest"]["telemetry_sha256"] for source in sources.values()
    }
    assert len(telemetry_hashes) == 4
    for source in sources.values():
        assert source["acceptance_mode"] == "roadless_trajectory"
        assert (ROOT / source["video"]).is_file()
        assert (ROOT / source["telemetry"]).is_file()


def test_all_local_catalog_adds_mp4728_without_expanding_map_dependent_catalog():
    sources = [source for item in ALL_LOCAL_REPLAY_CATALOG for source in item["sources"]]
    assert len(LOCAL_REPLAY_CATALOG) == 4
    assert len(ALL_LOCAL_REPLAY_CATALOG) == 6
    assert len(sources) == 15


def test_mp4820_catalog_isolated_and_requires_laser_verified_geo_tcc_validation():
    assert len(MP4820_CATALOG) == 1
    item = MP4820_CATALOG[0]
    assert item["inter_id"] == "INT_MP4820_JINGSHI_EAST_CORRIDOR"
    sources = {source["profile_id"]: source for source in item["sources"]}
    assert set(sources) == {"SRC-MP4820-JS-0813-EW", "SRC-MP4820-JS-0813-WE"}
    assert sources["SRC-MP4820-JS-0813-EW"]["time_offset_sec"] == 58.451
    assert sources["SRC-MP4820-JS-0813-WE"]["time_offset_sec"] == 216.149
    for source in sources.values():
        assert source["acceptance_mode"] == "geo_tcc_validation"
        assert source["telemetry_agl_policy"] == "laser_target"
        assert source["min_tcc_eligible_coverage"] == 0.90
        assert (ROOT / source["video"]).is_file()
        assert (ROOT / source["telemetry"]).is_file()


def test_all_local_replay_catalog_has_traceable_test_coordinates_for_acceptance():
    for item in ALL_LOCAL_REPLAY_CATALOG:
        coordinate = item["test_coordinate"]
        assert 36.6 < coordinate["lat"] < 36.8
        assert 117.0 < coordinate["lon"] < 117.2
        assert "telemetry_median" in coordinate["source"]


def test_all_local_replay_sources_start_without_lane_annotation_parameters():
    assert all(not item.get("roads_json") for item in ALL_LOCAL_REPLAY_CATALOG)

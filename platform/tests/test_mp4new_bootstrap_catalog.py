from pathlib import Path

from scripts.bootstrap_mp4new_sources import MP4NEW_CATALOG


ROOT = Path(__file__).resolve().parents[2]


def test_mp4new_catalog_has_three_intersections_and_five_readable_pairs():
    sources = [source for item in MP4NEW_CATALOG for source in item["sources"]]
    assert len(MP4NEW_CATALOG) == 3
    assert len(sources) == 5
    assert len({item["inter_id"] for item in MP4NEW_CATALOG}) == 3
    assert len({source["profile_id"] for source in sources}) == 5
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
    assert sources["SRC-MP4NEW-LS-0624-PM"]["known_degradation"] == "telemetry_gap_34s"

from __future__ import annotations

import pytest

from scripts.inventory_trajectory_replay import (
    INTER_XQH_SOURCE_PROFILES,
    MP4NEW_SOURCE_PROFILES,
    catalog_source_profiles,
    resolve_source_profiles,
)


def test_catalog_source_profiles_preserves_catalog_order():
    assert catalog_source_profiles(
        (
            {"sources": ({"profile_id": "SRC-A"}, {"profile_id": "SRC-B"})},
            {"sources": ({"profile_id": "SRC-C"},)},
        )
    ) == ("SRC-A", "SRC-B", "SRC-C")


def test_resolve_source_profiles_defaults_to_eight_mp4new_sources():
    assert resolve_source_profiles(None) == MP4NEW_SOURCE_PROFILES
    assert len(MP4NEW_SOURCE_PROFILES) == 8


def test_resolve_source_profiles_can_include_inter_xqh_once():
    selected = resolve_source_profiles(
        [MP4NEW_SOURCE_PROFILES[0], MP4NEW_SOURCE_PROFILES[0]],
        include_inter_xqh=True,
    )
    assert selected == (MP4NEW_SOURCE_PROFILES[0], *INTER_XQH_SOURCE_PROFILES)


def test_resolve_source_profiles_rejects_unknown_scope():
    with pytest.raises(ValueError, match="unknown replay SourceProfile"):
        resolve_source_profiles(["SRC-NOT-ALLOWLISTED"])

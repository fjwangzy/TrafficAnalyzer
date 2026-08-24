from pathlib import Path

from scripts.build_mp4820_tcc_review import _copy_event_evidence, _stakeholder_html


def test_copy_event_evidence_is_idempotent_for_read_only_managed_files(tmp_path):
    evidence_root = tmp_path / "managed"
    source = evidence_root / "objects" / "ab" / "digest"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"immutable evidence")
    source.chmod(0o444)
    output_dir = tmp_path / "review" / "evidence"
    entry = {
        "review_id": "event-1",
        "event": {"evidence_files": [{"storage_key": "objects/ab/digest"}]},
    }

    assert _copy_event_evidence(entry, evidence_root, output_dir) == ["event-1/digest"]
    assert _copy_event_evidence(entry, evidence_root, output_dir) == ["event-1/digest"]
    assert (output_dir / "event-1" / "digest").read_bytes() == b"immutable evidence"


def test_stakeholder_html_keeps_unreviewed_truth_pending_and_escapes_event_values():
    rendered = _stakeholder_html(
        [{
            "profile_id": "SRC-MP4820-JS-0813-EW",
            "telemetry_sync_coverage_ratio": 1.0,
            "laser_agl_coverage_ratio": 1.0,
            "camera_lens_coverage_ratio": 1.0,
            "laser_agl_residual_p95_m": 0.1,
        }],
        [{
            "profile_id": "SRC-MP4820-JS-0813-EW",
            "natural_eof": True,
            "road9_reconciliation": {"matched": True},
            "tcc_eligibility": {"coverage_ratio": 0.9},
            "tcc_event_count": 1,
            "passed": True,
        }],
        {
            "formal_events": 1,
            "confirmed": 0,
            "false_positive": 0,
            "uncertain": 0,
            "pending_review": 1,
            "formal_precision": "not_evaluated",
        },
        [{
            "kind": "formal_event",
            "review_id": "event-1",
            "profile_id": "SRC-MP4820-JS-0813-EW",
            "timestamp_sec": 1.0,
            "review_status": "pending_review",
            "event": {"severity": "<critical>"},
        }],
        Path("output/reports/mp4820-tcc-truth-20260820"),
    )

    assert "待全部人工复核" in rendered
    assert "&lt;critical&gt;" in rendered
    assert "召回率：<code>not_evaluated</code>" in rendered

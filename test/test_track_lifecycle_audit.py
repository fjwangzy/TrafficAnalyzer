from scripts.audit_track_lifecycle import build_report


def test_audit_marks_duplicate_or_reasonless_pipelines_unfit_for_formal_stats():
    report = build_report(
        [
            {
                "pipeline_id": "pipeline-duplicate",
                "track_id": "7",
                "completion_count": 2,
                "missing_reason_count": 0,
                "source_message_ids": ["m1", "m2"],
            },
            {
                "pipeline_id": "pipeline-reasonless",
                "track_id": "8",
                "completion_count": 1,
                "missing_reason_count": 1,
                "source_message_ids": ["m3"],
            },
        ]
    )

    assert report["read_only"] is True
    assert report["summary"] == {
        "issue_pairs": 2,
        "duplicate_completion_pairs": 1,
        "missing_termination_reason_pairs": 1,
        "affected_pipelines": 2,
    }
    assert report["affected_pipeline_ids"] == [
        "pipeline-duplicate",
        "pipeline-reasonless",
    ]
    assert all(
        issue["formal_statistics_status"] == "invalid"
        for issue in report["issues"]
    )

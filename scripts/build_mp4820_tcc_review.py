#!/usr/bin/env python3
"""Build auditable mp4820 TCC review inputs and stakeholder-report data.

This tool never assigns a human outcome.  It prepares every emitted strict TCC
event and the required negative samples for visual review, then derives a
report payload whose conclusion remains ``pending_review`` until a reviewer
records a decision in ``review-decisions.json``.
"""

from __future__ import annotations

import argparse
from html import escape
import json
import math
import shutil
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2


ROOT = Path(__file__).resolve().parents[1]
PLATFORM_DIR = ROOT / "platform"
for item in (ROOT, PLATFORM_DIR):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from scripts.bootstrap_mp4new_sources import MP4820_CATALOG  # noqa: E402
from services.TelemetryFileReader import TelemetryFileReader  # noqa: E402


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, round((len(values) - 1) * 0.95))]


def source_catalog() -> dict[str, dict]:
    item = MP4820_CATALOG[0]
    return {
        source["profile_id"]: {**item, **source}
        for source in item["sources"]
    }


def video_probe(path: Path) -> dict:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"cannot open video: {path}")
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    finally:
        capture.release()
    return {
        "fps": fps,
        "frame_count": frames,
        "duration_sec": frames / fps if fps > 0 else None,
        "resolution": [width, height],
    }


def source_quality(source: dict) -> dict:
    """Measure every source frame's nearest-telemetry and strict AGL readiness."""
    video = ROOT / source["video"]
    telemetry = ROOT / source["telemetry"]
    probe = video_probe(video)
    reader = TelemetryFileReader(
        str(telemetry),
        sync_tolerance_sec=float(source["sync_tolerance_sec"]),
        time_offset_sec=float(source["time_offset_sec"]),
        agl_policy=source["telemetry_agl_policy"],
    )
    samples = int(probe["frame_count"])
    matched = 0
    agl_verified = 0
    lens_verified = 0
    residuals: list[float] = []
    reasons: Counter[str] = Counter()
    for frame_no in range(samples):
        record = reader.get_nearest(frame_no / probe["fps"])
        if record is None:
            reasons["telemetry_sync_gap"] += 1
            continue
        matched += 1
        if record.get("altitude_agl_source") == "laser_target_altitude":
            agl_verified += 1
        else:
            reasons[str(record.get("altitude_agl_source") or "agl_unavailable")] += 1
        if record.get("camera_lens_verified") is True:
            lens_verified += 1
        else:
            reasons["camera_lens_unverified"] += 1
        residual = record.get("altitude_agl_residual_m")
        if isinstance(residual, (int, float)) and math.isfinite(residual):
            residuals.append(float(residual))
    return {
        "profile_id": source["profile_id"],
        "video": source["video"],
        "telemetry": source["telemetry"],
        "time_offset_sec": source["time_offset_sec"],
        "sync_tolerance_sec": source["sync_tolerance_sec"],
        "acceptance_mode": source["acceptance_mode"],
        "min_tcc_eligible_coverage": source["min_tcc_eligible_coverage"],
        "source_manifest": source["source_manifest"],
        "video_probe": probe,
        "frame_samples": samples,
        "telemetry_sync_coverage_ratio": round(matched / samples, 6) if samples else 0.0,
        "laser_agl_coverage_ratio": round(agl_verified / samples, 6) if samples else 0.0,
        "camera_lens_coverage_ratio": round(lens_verified / samples, 6) if samples else 0.0,
        "laser_agl_residual_p95_m": _p95(residuals),
        "input_quality_reason_counts": dict(sorted(reasons.items())),
    }


def _source_time(message: dict) -> float | None:
    raw = message.get("source_time_raw") or {}
    value = raw.get("frame_timestamp_sec") if isinstance(raw, dict) else None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _event_review_entry(profile_id: str, event: dict, index: int) -> dict:
    data = event.get("data") or {}
    return {
        "review_id": f"{profile_id}-event-{index:03d}",
        "kind": "formal_event",
        "profile_id": profile_id,
        "timestamp_sec": _source_time(event),
        "review_status": "pending_review",
        "event": {
            key: data.get(key)
            for key in (
                "motor_id", "non_motor_id", "prediction_type", "distance_m", "ttc_sec",
                "pet_sec", "arrival_time_delta_sec", "severity", "conflict_scene",
                "conflict_angle_deg", "risk_score", "evidence", "min_same_time_distance_m",
                "evidence_status", "evidence_files",
            )
        },
    }


def _negative_review_entries(profile_id: str, stats: list[dict]) -> list[dict]:
    eligible = [item for item in stats if (item.get("data") or {}).get("tcc_analytics_eligible")]
    candidates = []
    for item in eligible:
        diagnostic = (item.get("data") or {}).get("tcc_diagnostics") or {}
        if int(diagnostic.get("business_events_emitted") or 0) > 0:
            continue
        candidate_pairs = int(diagnostic.get("candidate_pairs") or 0)
        predictions = int(diagnostic.get("prediction_candidates") or 0)
        evidence_passed = int(diagnostic.get("evidence_passed") or 0)
        if candidate_pairs <= 0:
            continue
        score = predictions * 10000 + evidence_passed * 1000 + candidate_pairs
        candidates.append((score, _source_time(item), diagnostic))
    candidates.sort(key=lambda item: (-item[0], item[1] if item[1] is not None else float("inf")))
    selected: list[dict] = []
    for score, timestamp, diagnostic in candidates:
        if timestamp is None or any(abs(timestamp - row["timestamp_sec"]) < 5 for row in selected):
            continue
        selected.append({
            "review_id": f"{profile_id}-negative-risk-{len(selected) + 1:03d}",
            "kind": "high_risk_negative",
            "profile_id": profile_id,
            "timestamp_sec": timestamp,
            "risk_rank_score": score,
            "review_status": "pending_review",
            "tcc_diagnostics": diagnostic,
        })
        if len(selected) == 20:
            break
    if eligible:
        for bucket in range(10):
            item = eligible[min(len(eligible) - 1, int((bucket + 0.5) * len(eligible) / 10))]
            timestamp = _source_time(item)
            if timestamp is None or any(abs(timestamp - row["timestamp_sec"]) < 5 for row in selected):
                continue
            selected.append({
                "review_id": f"{profile_id}-negative-uniform-{bucket + 1:02d}",
                "kind": "uniform_eligible_negative",
                "profile_id": profile_id,
                "timestamp_sec": timestamp,
                "review_status": "pending_review",
                "tcc_diagnostics": (item.get("data") or {}).get("tcc_diagnostics") or {},
            })
    return selected


def _copy_event_evidence(entry: dict, evidence_root: Path, output_dir: Path) -> list[str]:
    copied = []
    for evidence in (entry.get("event") or {}).get("evidence_files") or []:
        key = evidence.get("storage_key") if isinstance(evidence, dict) else None
        if not isinstance(key, str) or Path(key).is_absolute() or ".." in Path(key).parts:
            continue
        source = evidence_root / key
        if not source.is_file():
            continue
        target = output_dir / entry["review_id"] / Path(key).name
        target.parent.mkdir(parents=True, exist_ok=True)
        # Managed evidence is intentionally read-only.  ``copy2`` preserves that
        # mode, so copying directly to an existing target makes a second review
        # build fail with EACCES.  Replace through a sibling file to keep bundle
        # generation idempotent without weakening the evidence permissions.
        staging = target.with_name(f".{target.name}.staging")
        staging.unlink(missing_ok=True)
        shutil.copy2(source, staging)
        staging.replace(target)
        copied.append(str(target.relative_to(output_dir)))
    return copied


def _extract_clip(source: dict, entry: dict, output_dir: Path) -> str | None:
    timestamp = entry.get("timestamp_sec")
    if not isinstance(timestamp, (int, float)):
        return None
    clip_dir = output_dir / "clips"
    clip_dir.mkdir(parents=True, exist_ok=True)
    clip = clip_dir / f"{entry['review_id']}.mp4"
    command = [
        "ffmpeg", "-y", "-ss", f"{max(float(timestamp) - 5.0, 0.0):.3f}",
        "-i", str(ROOT / source["video"]), "-t", "10", "-an", "-c:v", "libx264",
        "-preset", "veryfast", "-crf", "20", str(clip),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode:
        entry["clip_error"] = completed.stderr[-500:]
        return None
    return str(clip.relative_to(output_dir))


def _review_summary(entries: list[dict]) -> dict:
    counts = Counter(str(entry.get("review_status") or "pending_review") for entry in entries if entry["kind"] == "formal_event")
    confirmed = counts["confirmed"]
    false_positive = counts["false_positive"]
    return {
        "formal_events": sum(counts.values()),
        "confirmed": confirmed,
        "false_positive": false_positive,
        "uncertain": counts["uncertain"],
        "pending_review": counts["pending_review"],
        "formal_precision": round(confirmed / (confirmed + false_positive), 4)
        if confirmed + false_positive else "not_evaluated",
        "formal_recall": "not_evaluated",
    }


def _artifact_payload(quality: list[dict], results: list[dict], review: dict, entries: list[dict]) -> dict:
    source_rows = [
        {
            "profile_id": row["profile_id"],
            "sync_pct": round(100 * row["telemetry_sync_coverage_ratio"], 2),
            "laser_agl_pct": round(100 * row["laser_agl_coverage_ratio"], 2),
            "lens_pct": round(100 * row["camera_lens_coverage_ratio"], 2),
            "laser_residual_p95_m": row["laser_agl_residual_p95_m"],
        }
        for row in quality
    ]
    funnel_rows = []
    for result in results:
        funnel = result.get("tcc_diagnostics") or {}
        funnel_rows.extend([
            {"profile_id": result["profile_id"], "stage": "候选帧", "count": funnel.get("frames_with_candidate_pairs", 0)},
            {"profile_id": result["profile_id"], "stage": "预测帧", "count": funnel.get("frames_with_predictions", 0)},
            {"profile_id": result["profile_id"], "stage": "正式事件", "count": result.get("tcc_event_count", 0)},
        ])
    event_rows = [
        {
            "review_id": entry["review_id"], "profile_id": entry["profile_id"],
            "timestamp_sec": entry.get("timestamp_sec"), "status": entry.get("review_status"),
            "severity": (entry.get("event") or {}).get("severity"),
            "ttc_sec": (entry.get("event") or {}).get("ttc_sec"),
            "pet_sec": (entry.get("event") or {}).get("pet_sec"),
            "scene": (entry.get("event") or {}).get("conflict_scene"),
        }
        for entry in entries if entry["kind"] == "formal_event"
    ] or [{"review_id": "none", "profile_id": "-", "timestamp_sec": None, "status": "no_formal_event", "severity": None, "ttc_sec": None, "pet_sec": None, "scene": None}]
    summary = [{
        "source_count": len(quality), "formal_events": review["formal_events"],
        "pending_review": review["pending_review"], "formal_precision": review["formal_precision"],
    }]
    return {
        "surface": "report",
        "manifest": {
            "version": 1,
            "title": "mp4820 经十路东段 TCC 真实性验证",
            "description": "两段 2026-08-13 无人机巡航素材；正式事件须逐条视觉复核，召回率未评估。",
            "sources": [
                {"id": "mp4820-inputs", "label": "mp4820 视频与 DJI 遥测源清单", "path": "test_videos/mp4820"},
                {"id": "run-results", "label": "原生 MPS 回放结果", "path": "output/native-mps/mp4820-tcc"},
                {"id": "review-manifest", "label": "事件与负样本复核清单", "path": "review-manifest.json"},
            ],
            "blocks": [
                {"id": "answer", "type": "markdown", "body": "## 当前结论\n本报告仅展示可审计的回放与复核状态。未完成全部人工复核前，TCC 真实性结论为 **pending_review**；无外部穷举真值，召回率不评估。", "sourceId": "run-results"},
                {"id": "metrics", "type": "metric-strip", "cardIds": ["coverage-card", "event-card", "review-card"]},
                {"id": "quality-title", "type": "markdown", "body": "## 输入与投影质量\n同步、激光 AGL、广角镜头验证均按来源分别统计。镜头或激光语义不可信的帧不得进入正式 TCC。", "sourceId": "mp4820-inputs"},
                {"id": "funnel-title", "type": "markdown", "body": "## TCC 漏斗\n候选和预测反映算法确实执行；只有严格 path-intersection 且完整证据的事件进入正式复核。", "sourceId": "run-results"},
                {"id": "funnel-chart", "type": "chart", "chartId": "funnel-chart"},
                {"id": "events-title", "type": "markdown", "body": "## 正式事件复核表\n`confirmed`、`false_positive`、`uncertain` 由人工视频复核填写；不得从轨迹观感推导真值指标。", "sourceId": "review-manifest"},
                {"id": "events-table", "type": "table", "tableId": "events-table"},
                {"id": "limits", "type": "markdown", "body": "## 解释边界\n本次不创建人工轨迹标注包，不声明 IDF1、HOTA、ID switch、位置 RMSE、速度 MAE 或正式召回率。Lane/Link 在本来源中保持不可用。", "sourceId": "review-manifest"},
            ],
            "cards": [
                {"id": "coverage-card", "dataset": "summary", "metrics": [{"label": "独立来源", "field": "source_count", "format": "integer"}], "sourceId": "run-results"},
                {"id": "event-card", "dataset": "summary", "metrics": [{"label": "正式 TCC 事件", "field": "formal_events", "format": "integer"}], "sourceId": "run-results"},
                {"id": "review-card", "dataset": "summary", "metrics": [{"label": "待人工复核", "field": "pending_review", "format": "integer"}], "sourceId": "review-manifest"},
            ],
            "charts": [
                {"id": "funnel-chart", "type": "bar", "title": "TCC 漏斗分方向统计", "subtitle": "帧/事件计数；正式事件不等同于人工确认。", "dataset": "funnel", "encodings": {"x": {"field": "stage"}, "y": {"field": "count"}, "color": {"field": "profile_id"}}, "sourceId": "run-results"},
            ],
            "tables": [
                {"id": "events-table", "dataset": "events", "columns": [{"field": "review_id", "label": "复核ID"}, {"field": "profile_id", "label": "来源"}, {"field": "timestamp_sec", "label": "视频秒"}, {"field": "severity", "label": "等级"}, {"field": "ttc_sec", "label": "TTC"}, {"field": "pet_sec", "label": "PET"}, {"field": "scene", "label": "场景"}, {"field": "status", "label": "复核结论"}], "defaultSort": {"field": "timestamp_sec", "direction": "asc"}, "sourceId": "review-manifest"},
            ],
        },
        "snapshot": {"version": 1, "generatedAt": datetime.now(UTC).isoformat(), "datasets": {"summary": summary, "source-quality": source_rows, "funnel": funnel_rows or [{"profile_id": "-", "stage": "未运行", "count": 0}], "events": event_rows}},
        "sources": [
            {"id": "mp4820-inputs", "label": "mp4820 视频与 DJI 遥测源清单", "path": "test_videos/mp4820", "description": "目录哈希、时长和帧级同步由 source manifest 与 preflight 固化。"},
            {"id": "run-results", "label": "原生 MPS 回放结果", "path": "output/native-mps/mp4820-tcc", "description": "Kafka 捕获、road9 对账、TCC 漏斗与严格事件。", "query": {"sql": "SELECT source_profile_id, COUNT(*) AS stats_samples, COUNT(*) FILTER (WHERE COALESCE((payload->>'tcc_analytics_eligible')::boolean, false)) AS tcc_eligible_samples FROM uav_traffic_metrics WHERE inter_id = 'INT_MP4820_JINGSHI_EAST_CORRIDOR' AND source_profile_id IN ('SRC-MP4820-JS-0813-EW', 'SRC-MP4820-JS-0813-WE') GROUP BY source_profile_id", "description": "Reconcile per-source stats and TCC eligibility persisted from the native MPS replay.", "tables_used": ["uav_traffic_metrics"], "filters": ["inter_id = INT_MP4820_JINGSHI_EAST_CORRIDOR", "two mp4820 source profiles only"], "metric_definitions": ["Stats samples are distinct persisted uav_stats envelopes for the replay pipeline.", "TCC eligible samples require payload.tcc_analytics_eligible=true."]}},
            {"id": "review-manifest", "label": "事件与负样本复核清单", "path": "review-manifest.json", "description": "每个正式事件及确定性负样本的视觉复核状态。", "query": {"sql": "SELECT id, source_profile_id, occurred_at, payload FROM uav_conflict_events WHERE inter_id = 'INT_MP4820_JINGSHI_EAST_CORRIDOR' AND source_profile_id IN ('SRC-MP4820-JS-0813-EW', 'SRC-MP4820-JS-0813-WE') ORDER BY occurred_at", "description": "Load strict conflict facts before joining the local reviewer decision manifest.", "tables_used": ["uav_conflict_events"], "filters": ["inter_id = INT_MP4820_JINGSHI_EAST_CORRIDOR", "two mp4820 source profiles only"], "metric_definitions": ["Formal events are strict path_intersection events with distance_m approximately zero and complete evidence.", "Review status is a local human decision keyed by review_id and is not an algorithmic truth label."]}},
        ],
    }


def _technical_markdown(quality: list[dict], results: list[dict], review: dict) -> str:
    lines = [
        "# mp4820 经十路东段 TCC 真实性验证", "",
        "## 当前结论", "",
        f"- 复核状态：`{'pending_review' if review['pending_review'] else 'reviewed'}`。",
        f"- 正式事件：{review['formal_events']}；已确认：{review['confirmed']}；误报：{review['false_positive']}；不确定：{review['uncertain']}。",
        f"- 正式事件精确率：`{review['formal_precision']}`；召回率：`not_evaluated`。", "",
        "## 输入质量", "",
    ]
    for row in quality:
        lines.append(
            f"- `{row['profile_id']}`：同步 {row['telemetry_sync_coverage_ratio']:.2%}；"
            f"激光 AGL {row['laser_agl_coverage_ratio']:.2%}；广角镜头 {row['camera_lens_coverage_ratio']:.2%}；"
            f"激光残差 P95={row['laser_agl_residual_p95_m']}m。"
        )
    lines.extend(["", "## 回放与边界", ""])
    for result in results:
        tcc = result.get("tcc_eligibility") or {}
        lines.append(
            f"- `{result['profile_id']}`：EOF={result.get('natural_eof')}；road9 对账="
            f"{(result.get('road9_reconciliation') or {}).get('matched')}；TCC 覆盖="
            f"{tcc.get('coverage_ratio')}；严格事件={result.get('tcc_event_count')}；通过={result.get('passed')}。"
        )
    lines.extend([
        "", "## 不声明项", "",
        "- 无外部穷举真值，不声明 IDF1、HOTA、ID switch、位置 RMSE、速度 MAE 或正式召回率。",
        "- 本来源无 lane_verified 地图；Lane/Link/正式转向归属保持 unavailable。",
    ])
    return "\n".join(lines) + "\n"


def _display(value: Any) -> str:
    """Render an untrusted fact as plain text in the standalone stakeholder report."""
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _html_table(columns: list[tuple[str, str]], rows: list[dict[str, Any]]) -> str:
    header = "".join(f"<th>{escape(label)}</th>" for _, label in columns)
    body = "".join(
        "<tr>" + "".join(
            f"<td>{escape(_display(row.get(field)))}</td>" for field, _ in columns
        ) + "</tr>"
        for row in rows
    ) or f"<tr><td colspan=\"{len(columns)}\">无记录</td></tr>"
    return f"<table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>"


def _stakeholder_html(quality: list[dict], results: list[dict], review: dict, entries: list[dict], bundle_dir: Path) -> str:
    """Build a portable, read-only HTML view without inventing review outcomes."""
    source_rows = [
        {
            "profile_id": row["profile_id"],
            "sync": f"{row['telemetry_sync_coverage_ratio']:.2%}",
            "laser_agl": f"{row['laser_agl_coverage_ratio']:.2%}",
            "vision_lens": f"{row['camera_lens_coverage_ratio']:.2%}",
            "residual_p95": row["laser_agl_residual_p95_m"],
        }
        for row in quality
    ]
    run_rows = [
        {
            "profile_id": result.get("profile_id"),
            "natural_eof": result.get("natural_eof"),
            "road9_reconciled": (result.get("road9_reconciliation") or {}).get("matched"),
            "eligible_coverage": (result.get("tcc_eligibility") or {}).get("coverage_ratio"),
            "strict_events": result.get("tcc_event_count"),
            "engineering_passed": result.get("passed"),
        }
        for result in results
    ]
    event_rows = [
        {
            "review_id": entry["review_id"],
            "profile_id": entry["profile_id"],
            "timestamp_sec": entry.get("timestamp_sec"),
            "severity": (entry.get("event") or {}).get("severity"),
            "ttc_sec": (entry.get("event") or {}).get("ttc_sec"),
            "pet_sec": (entry.get("event") or {}).get("pet_sec"),
            "status": entry.get("review_status"),
        }
        for entry in entries if entry["kind"] == "formal_event"
    ]
    conclusion = "已完成" if not review["pending_review"] else "待全部人工复核"
    bundle_link = escape(bundle_dir.name)
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>mp4820 经十路东段 TCC 真实性验证</title><style>
body{{font:15px/1.55 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#172033;max-width:1180px;margin:32px auto;padding:0 20px;background:#f7f9fc}}
h1{{margin-bottom:4px}} section{{background:#fff;border:1px solid #dce3ef;border-radius:10px;padding:18px 20px;margin:16px 0}} .state{{font-weight:700;color:#9b3b00}} table{{width:100%;border-collapse:collapse;margin-top:10px}} th,td{{text-align:left;padding:8px;border-bottom:1px solid #e6ebf2;vertical-align:top}}th{{background:#f2f5f9}}code{{background:#f2f5f9;padding:2px 4px;border-radius:3px}}</style></head>
<body><h1>mp4820 经十路东段 TCC 真实性验证</h1><p>生成时间：{escape(datetime.now(UTC).isoformat())}。范围仅限本批两段 2026-08-13 无人机巡航素材。</p>
<section><h2>当前结论：<span class="state">{conclusion}</span></h2><p>正式事件 {review['formal_events']}；confirmed {review['confirmed']}；false_positive {review['false_positive']}；uncertain {review['uncertain']}；待复核 {review['pending_review']}。正式精确率：<code>{escape(_display(review['formal_precision']))}</code>；召回率：<code>not_evaluated</code>。</p><p>无外部穷举真值，因此 IDF1、HOTA、ID switch、位置 RMSE、速度 MAE 均为 <code>not_evaluated</code>。本批无 lane_verified 地图，不声明 Lane/Link 或正式转向事实。</p></section>
<section><h2>输入与投影质量</h2>{_html_table([('profile_id','来源'),('sync','遥测同步'),('laser_agl','激光 AGL'),('vision_lens','广角镜头'),('residual_p95','AGL 残差 P95 (m)')], source_rows)}</section>
<section><h2>原生 MPS 回放与对账</h2>{_html_table([('profile_id','来源'),('natural_eof','自然 EOF'),('road9_reconciled','road9 对账'),('eligible_coverage','TCC eligible 覆盖'),('strict_events','严格事件'),('engineering_passed','工程通过')], run_rows)}</section>
<section><h2>正式事件人工复核</h2>{_html_table([('review_id','复核 ID'),('profile_id','来源'),('timestamp_sec','视频秒'),('severity','等级'),('ttc_sec','TTC'),('pet_sec','PET'),('status','结论')], event_rows)}<p>完整证据、前后 5 秒原片段和负样本清单见同级 <a href="{bundle_link}/README.md">复核包</a>。</p></section>
</body></html>\n"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, help="native MPS output directory containing two source folders")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--extract-clips", action="store_true")
    parser.add_argument("--evidence-root", type=Path, default=ROOT / ".runtime" / "survey")
    parser.add_argument("--technical-report", type=Path)
    parser.add_argument("--html-report", type=Path, help="standalone stakeholder HTML report")
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    catalog = source_catalog()
    quality = [source_quality(source) for source in catalog.values()]
    results = []
    entries: list[dict] = []
    if args.run_dir:
        run_dir = args.run_dir.resolve()
        for profile_id, source in catalog.items():
            source_dir = run_dir / profile_id
            result = _read_json(source_dir / "result.json", None)
            if result is None:
                raise RuntimeError(f"missing result.json for {profile_id}: {source_dir}")
            results.append(result)
            events = _read_json(source_dir / "tcc-events.json", [])
            stats = _read_json(source_dir / "stats.json", [])
            entries.extend(_event_review_entry(profile_id, event, index + 1) for index, event in enumerate(events))
            entries.extend(_negative_review_entries(profile_id, stats))
    decision_path = output_dir / "review-decisions.json"
    decisions = {item.get("review_id"): item for item in _read_json(decision_path, []) if isinstance(item, dict)}
    for entry in entries:
        decision = decisions.get(entry["review_id"], {})
        if decision.get("review_status") in {"confirmed", "false_positive", "uncertain"}:
            entry["review_status"] = decision["review_status"]
            entry["review_note"] = decision.get("review_note")
        if entry["kind"] == "formal_event":
            entry["evidence_copies"] = _copy_event_evidence(entry, args.evidence_root, output_dir / "evidence")
        if args.extract_clips:
            clip = _extract_clip(catalog[entry["profile_id"]], entry, output_dir)
            if clip:
                entry["clip"] = clip
    review = _review_summary(entries)
    _write_json(output_dir / "source-quality.json", quality)
    _write_json(output_dir / "review-manifest.json", entries)
    _write_json(output_dir / "artifact.json", _artifact_payload(quality, results, review, entries))
    (output_dir / "README.md").write_text(
        "# mp4820 TCC review bundle\n\n"
        "`review-manifest.json` lists every formal event and deterministic negative samples. "
        "Copy reviewed statuses into `review-decisions.json`, then rebuild this bundle.\n",
        encoding="utf-8",
    )
    if args.technical_report:
        args.technical_report.write_text(_technical_markdown(quality, results, review), encoding="utf-8")
    if args.html_report:
        args.html_report.parent.mkdir(parents=True, exist_ok=True)
        args.html_report.write_text(
            _stakeholder_html(quality, results, review, entries, output_dir), encoding="utf-8"
        )
    print(json.dumps({"output_dir": str(output_dir), "sources": len(quality), "formal_events": review["formal_events"], "pending_review": review["pending_review"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

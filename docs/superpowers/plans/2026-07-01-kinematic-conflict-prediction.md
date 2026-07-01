# Kinematic Conflict Prediction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace proximity-triggered motor/non-motor conflicts with 0-5 second future trajectory collision prediction.

**Architecture:** Keep the existing pipeline node and Kafka event contract. Change `ConflictDetectionNode` into a pure kinematic predictor that samples future world-coordinate positions, emits only predicted collisions, and preserves pair deduplication.

**Tech Stack:** Python, NumPy, Hydra YAML config, existing script-based regression tests.

---

### Task 1: Update Tests For New Business Semantics

**Files:**
- Modify: `test_refactor_unit.py`
- Modify: `test_pipeline_no_yolo.py`
- Modify: `test_pipeline_inter_xqh.py`

- [ ] Replace proximity-trigger expectations with "near but diverging does not report".
- [ ] Add 0-3s critical predicted collision test.
- [ ] Add 3-5s warning predicted collision test.
- [ ] Keep non-motor/motor class filtering tests.
- [ ] Update inline conflict config dictionaries to use `prediction_horizon_sec`, `critical_horizon_sec`, `sample_interval_sec`, `collision_radius_m`, `arrival_time_tolerance_sec`, and `relative_speed_min_ms`.

### Task 2: Implement Future Trajectory Prediction

**Files:**
- Modify: `nodes/ConflictDetectionNode.py`

- [ ] Remove `proximity_threshold_m` as a trigger.
- [ ] Replace `ttc_threshold_sec` with `prediction_horizon_sec`.
- [ ] Add `_predict_collision(...)` returning the earliest predicted collision metadata.
- [ ] Classify severity from `ttc_sec`: `critical` for `<= critical_horizon_sec`, otherwise `warning`.
- [ ] Use predicted future distance for `distance_m`.
- [ ] Preserve world-position output and pair dedupe behavior.

### Task 3: Update Config And Docs

**Files:**
- Modify: `configs/app_config.yaml`
- Modify: `configs/app_config copy.yaml`
- Modify: `docs/BUSINESS_LOGIC.md`
- Modify: `docs/API_CONTRACTS.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/PROJECT_STRUCTURE.md`
- Modify: `docs/TASKS.md`
- Modify: `docs/2026-05-31-uav-traffic-perception-system-design.md`

- [ ] Replace proximity/TTC dual-factor wording with future trajectory collision wording.
- [ ] Document the new default configuration and deprecated old trigger fields.
- [ ] Preserve compatibility notes for `conflicts_{n}` message fields.

### Task 4: Verify

**Commands:**
- `python test_refactor_unit.py`
- `python test_pipeline_no_yolo.py`

**Expected:**
- Unit regression script reports all checks passing.
- No-YOLO pipeline test completes with all checks passing.

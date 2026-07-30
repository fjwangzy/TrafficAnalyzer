# 无人机巡航跟踪与路口悬停融合 Runbook

> 状态：2026-07-28 `local_engineering_passed / source_inputs_complete / road_context_degraded /
> geo_not_evaluated / production_accuracy_not_claimed`。
> 本文用于本机运行、质量诊断、xqh 工程复验和回滚；不替代生产精度签字。

## 1. 适用范围与硬边界

同一 Mission 支持：

```text
进场巡航 → 模式/质量过渡 → 路口悬停正拍 → 模式/质量过渡 → 离场巡航
```

- `hover_cruise_v1` 是新 FlightPlan 默认 profile；既有计划由 `20260723_0019` 保持为 `hover_only_legacy`。
- 悬停关键帧是创建、拟合和发布 `lane_verified` 地图的唯一来源；巡航帧不得修改地图。
- Mission 固定一个 SourceProfile、可选 verified SourceGeoRegistration 和可选 Runtime Road Map Bundle。
- 公共坐标为 GCJ-02，ENU 只用于米制计算。
- `degraded/unverified` 成熟像素轨迹必须进入轨迹事件和通用车辆计数；缺失能力按 geo/road/TCC
  独立降级，不得用零值伪装。
- Apple Silicon 开发态必须使用原生 arm64 Platform + Metal/MPS；Docker Compose 是生产发布拓扑。

## 2. ByteTrack 节点位置

```text
进程 1：VideoReader + telemetry → DetectionNode（YOLO only）
进程 2：ImageMotionEstimationNode（背景视觉warp）
       → GroundTrajectoryTrackerNode（纯图像 ByteTrack）
       → Homography/MotionCompensation → FlightGeoReferenceNode
       → PostTrackingWorldProjectionNode（稳定track_id/可空世界坐标）
       → TrackerInfoUpdate/Speed/Direction/Map/Lane/TCC/Statistics/Kafka
进程 3：Show/MJPEG/VideoSaver
```

`GroundTrajectoryTrackerNode` 保留 ByteTrack 高低置信两轮关联，只使用背景视觉 warp、补偿后 IoU、类别软约束、置信度和真实源时间。它禁止读取 H、ENU、遥测和地图质量。`PostTrackingWorldProjectionNode` 在 ID 确定后唯一执行接地点去畸变及独立 SourceGeoRegistration 的 ENU/GCJ-02 投影；`TrackerInfoUpdateNode` 只消费其结果。路网只由后置 `RoadMapMatchingNode` 填充 Lane ID、Link ID 与匹配质量，不能创建、覆盖或关闭世界坐标。旧组合节点和当前 H 历史重投影速度回退只服务 `hover_only_legacy`。

## 3. 运行前检查

1. 确认工作树，避免覆盖未提交修改：

   ```bash
   git status --short --branch --untracked-files=all
   git submodule status --recursive
   ```

2. 确认模型和 xqh 素材存在：

   ```bash
   test -f weights/yolo11s-visdrone.pt
   test -f 'test_videos/inter_xqh/DJI_20260403142902_0001_V小清河北路与水屯路路口.mp4'
   test -f test_videos/inter_xqh/telemetry.srt
   ```

3. 确认本机数据库迁移头：

   ```bash
   cd platform
   python -m alembic current
   # 期望：20260728_0020 (head)
   ```

4. 世界坐标运行只需确认 SourceProfile 的 verified SourceGeoRegistration、配准位姿、相机哈希和地理配准覆盖；`lane_verified` map 不是前置条件。没有地理配准时仍输出成熟像素轨迹，ENU/GCJ-02 与速度诚实为空。

## 4. 本机启动

```bash
scripts/mac_local_platform.sh up
cd console2 && npm run dev
```

本地无 Kafka 的检测调试：

```bash
python main_optimized.py pipeline.send_info_kafka=False tracking_profile=hover_cruise_v1
```

实时 RTSP 使用有界最新帧策略；离线 MP4 使用反压且不丢源帧。两者都必须保留真实源时间和 EOF。

## 5. xqh 后半程工程验收

从仓库根目录执行：

```bash
.venv-mps/bin/python scripts/accept_xqh_hover_departure.py \
  --start-offset-sec 840 \
  --departure-offset-sec 902 \
  --stride 4 \
  --output docs/generated/xqh-hover-departure-acceptance.json \
  --screenshots-dir docs/test-screenshots \
  --progress-every 200
```

验收器使用真实 4K MP4、逐帧 SRT、生产 VisDrone 模型和原生 MPS，同时运行不影响业务结果的 legacy shadow。当前基线：

| 项目 | 基线 |
|---|---:|
| 处理帧 / 检测覆盖 | 1142 / 100% |
| 源采样频率 | 7.4925Hz |
| YOLO 稳态 p95 | 175.51ms |
| 完整单进程帧 p95 | 270.401ms |
| 正式帧视觉有效率 | 100% |
| 降级业务泄漏 | 0 |
| 原始/合法检测与非法框 | 107603 / 107603 / 0 |
| active/completed/candidate 点对齐失败 | 0 / 0 / 0 |
| 候选末点/bbox接地点残差 P95 / max | 1.146 / 1.4px |
| 自然 EOF | 通过 |
| 生产ShowNode候选尾迹门禁 | 通过 |

正式研判窗口为 855.088–900.867 秒；901 秒后必须关闭。901.134 秒直接进入 `unsupported_pose` 是安全质量断点，不要求人为制造 `transition` 标签。离场阶段显示候选框、紧凑 `#ID class C` 标签和最多30点的琥珀虚线尾迹，右上角统一说明 `CANDIDATE / NO STATS-TCC`；正式轨迹、统计与 TCC 必须为0。

结果文件：

- `docs/generated/xqh-hover-departure-acceptance.json`
- `docs/test-screenshots/xqh-hover-departure-hover_verified.jpg`
- `docs/test-screenshots/xqh-hover-departure-hover_exit_quality_break.jpg`
- `docs/test-screenshots/xqh-hover-departure-departure_cruise.jpg`
- `docs/test-screenshots/xqh-hover-departure-departure_degraded.jpg`
- `docs/test-screenshots/xqh-hover-departure-*-show-node.jpg`
- `docs/test_report_inter_xqh.md`

## 6. 质量诊断顺序

Monitoring 出现能力降级时，按以下顺序分别检查：

1. `flight_phase`：是否为 `hover_verified` 或合格 `cruise_nadir`。
2. `telemetry_quality`：时间同步、GPS、AGL、姿态和派生/报告速度是否一致。
3. `visual_warp_quality`：背景点数、RANSAC inlier、重投影误差和遥测/视觉差异。
4. `trajectory_output_eligible`：只检查检测、图像关联成熟度、时间间隔和终止原因。
5. `geo_analytics_eligible`：检查独立 SourceGeoRegistration、姿态与当前点世界投影；失败只让
   对应 ENU/GCJ-02、速度和方向降级。
6. `road_analytics_eligible`：检查可选地图、版本/anchor 兼容与 Lane/Link 匹配；失败只关闭
   Lane ID、Link ID 与匹配质量。
7. `tcc_analytics_eligible`：检查可信世界坐标、时间、跟踪质量与 TCC 证据，不读取 road gate。
8. `formal_analytics_eligible`：仅为完整道路能力的旧消费者兼容字段，不控制轨迹缓冲、完成事件、
   世界坐标、速度、方向、通用统计或 TCC。

禁止通过放宽距离、IoU 或 TCC 阈值掩盖遥测、地图或视觉质量问题。

常见安全结果：

| 现象 | 处置 |
|---|---|
| 遥测/H缺失 | 稳定 `track_id` 和像素轨迹继续；当前 ENU/GCJ-02 写 `null`，速度为空 |
| 源时间倒退或处理帧间隔 >0.5 秒 | 重置图像 association，`source_time_reversal/source_time_gap` |
| 模式切换且图像关联连续 | 保留 `association_id` 与稳定 `track_id`；逐层更新能力状态 |
| 位姿/地理质量中断 | 像素轨迹不中断；世界点可同索引降级为 `null` 后恢复 |
| 地图缺失、版本不兼容或离开地图覆盖 | 只关闭 Lane ID、Link ID 与匹配质量；轨迹和世界坐标不受影响 |
| active 与 completed ENU 不一致 | 立即阻断；检查是否错误地用当前 H 重投影历史像素 |
| 有图像历史但 ENU 少于3点 | 仍输出像素 active/completed；速度为空，禁止启用当前 H 历史回退 |
| 有世界点但 Lane/Link 为空 | 检查 RoadMapMatching；不得回退为从地图创建世界坐标 |

### 6.1 输出视频中只有框、没有尾迹

先区分显示回归与 ID 关联回归：

1. 若框和 ID 连续，但尾迹缺失，运行 `test/test_show_node_class_colors.py`；成熟像素轨迹应显示类别色实线，无道路资格时标 `P`，真正未成熟候选才显示相机补偿后的短琥珀虚线和 `#ID class C`。该测试直接比较生产 `ShowNode` 开/关尾迹的像素差，不能只在4K原图上目测。
2. 若图像 `association_id` 本身频繁重置，先检查源时间缺口、背景视觉warp质量、IoU和检测漏帧；
   地图覆盖、H、地理配准或模式质量不得结束 `track_id` 或重置图像 ID。不要用放宽阈值掩盖问题。
3. 候选可以在 `buffer_tracks` 中保留图像生命周期，但必须保持 `trajectory_output_eligible=false`；成熟像素轨迹使用 `track_id_by_association`，不得因 `road_analytics_eligible=false` 降回候选。验证时同时运行 `test/test_ground_trajectory_tracker.py`、`test/test_calc_statistics_capability.py` 和 `test/test_kafka_active_trajectories.py`，分别确认 road/TCC 零越界。
4. 若尾迹形成跨画面长线，先检查 `detection_diagnostics.invalid_geometry_count`；非0表示检测边界问题，禁止仅靠渲染截断。再核对 `trajectory_px/trajectory_enu_m/trajectory_timestamps_sec/trajectory_frame_nums` 同索引，以及 `trajectory_display_px` 是否只由背景 `camera_motion_warp` 递推。ShowNode 读取当前 H 即为架构违规。
5. 正式轨迹不应依赖 `sv.TraceAnnotator` 内部历史。`trajectory_px` 是源帧接地点，`trajectory_bbox_center_px` 是旧中心点，`trajectory_display_px` 是图像显示事实，`trajectory_enu_m` 是 ID 后业务事实；四者不能互相覆盖。
6. 低速/静止目标的细小往返线只允许在 ShowNode 绘制副本中简化；不得平滑或删改 canonical 像素、ENU、时间和帧号事实。

快速回归：

```bash
.venv-mps/bin/python -m pytest \
  test/test_show_node_class_colors.py \
  test/test_ground_trajectory_tracker.py \
  test/test_kafka_active_trajectories.py \
  test/test_detection_geometry.py \
  test/test_trajectory_coordinate_alignment.py \
  test/test_main_optimized_eof.py \
  test/test_xqh_acceptance_rendering.py -q
```

完整 xqh 验收必须检查 `zero_invalid_detection_geometry=true`、三类点对齐、`quality_break_preserves_image_identity=true`、`zero_road_capability_leak=true`、`zero_tcc_capability_leak=true`、`trajectory_output_trail_rendered=true` 和落地点残差门禁，并审阅 `docs/test-screenshots/xqh-trajectory-display-accepted-20260728/comparison-before-after.jpg` 及最终 `*-show-node.jpg`；只看验收器自绘框图不足以覆盖生产输出视频的尾迹回归。

## 7. 数据库迁移与 xqh lineage

只允许前向迁移，不回滚数据库结构：

```bash
cd platform
python -m alembic upgrade head
python -m alembic current
```

xqh 配准 lineage 检查默认 dry-run：

```bash
python scripts/backfill_cruise_registration_lineage.py \
  --map-version-id CMV-b83a25740598430bb996f75d \
  --source-profile-id SRC-INTER-XQH-0403-PM \
  --capture-frame-id FRM-4221C85DCB81
```

当前重复执行应返回 `changed=false / would_change=false`。只有首次补齐且人工核对目标 ID、关键帧、32 条 verified lane 和覆盖范围后才能追加 `--apply`。脚本不修改 homography、车道几何或发布状态；既有非空 lineage 不同会拒绝覆盖。

## 8. 回归命令

```bash
python -m pytest test -q
python -m pytest platform/tests -q
cd console2 && npm test -- --run && npm run build
cd ..
python test/test_refactor_unit.py
python test/test_pipeline_inter_xqh.py
git ls-files --modified --others --exclude-standard -- '*.py' | xargs python -m ruff check
python scripts/audit_adr019_retirement.py --scope local --strict
git diff --check
```

2026-07-28 当前基线：Python 全量 397 passed/5 skipped/10 subtests；Console2 18 files/148 tests
并完成 production build；xqh 56/0/0；mp4728 三源自然 EOF 共 7,881 条完成轨迹且 Kafka/road9
精确一致。ADR-019 strict 有 9 项通过，仍由既有外部 `local_runtime_evidence` 门禁返回非零。
项目不建设人工标注、预标注或标注工作包，IDF1/HOTA 等依赖人工真值的指标不评估、不宣称。

## 9. 回滚

将 FlightPlan 或 Pipeline 的 `tracking_profile` 切回：

```text
hover_only_legacy
```

回滚效果：

- 恢复既有悬停检测/跟踪能力。
- 自动关闭巡航正式研判。
- 不降级 `20260728_0020`，不删除 SourceGeoRegistration、`uav_flight_segments` 或轨迹质量事实，
  不恢复旧 Topic，也不得恢复“地理/路网质量结束轨迹”的旧生命周期。
- 不删除新节点；待生产门禁通过并稳定观察后，才单独评审删除 legacy 路径。

## 10. 工程放行与精度声明边界

当前项目只执行无需人工标注的自动化工程验收，不建设人工标注、预标注、复核工作台或标注工作包。放行必须满足：

- 成熟 `degraded/unverified` 像素轨迹必须进入 active/completed 事件和通用车辆计数；候选只表示
  未成熟关联。缺路网时 Lane/Link 匹配泄漏保持 0，缺可信世界证据时速度/TCC 泄漏保持 0。
- 图像、ENU、GCJ-02、时间、帧号和质量 lineage 对齐失败为 0，active/completed 使用同一点列事实。
- 原生 MPS profile 的端到端 p95 ≤1 秒、有效检测频率 ≥6Hz；离线回放自然 EOF、队列反压和可恢复证据通过。
- 悬停正拍固定基线、xqh 尾部离场分层降级和 mp4728 三源自然 EOF 对账通过；ADR-019 strict
  的既有外部门禁必须如实单列，不得用本地功能回归替代。

xqh 不是精度真值集。没有外部已批准真值时，IDF1、HOTA、正式 ID switch、位置 RMSE、速度 MAE和车道准确率一律标为 `not_evaluated`，不得用观测ID数量、寿命、IoU或肉眼尾迹替代。现有只读评测器仅在未来外部项目主动提供完整真值时可选使用；本项目不生成、预标注、分派或审核该类数据。

当前工程结论为 `local_engineering_passed / source_inputs_complete / road_context_degraded /
geo_not_evaluated / production_accuracy_not_claimed`。该结论允许交付已验证的检测、成熟像素轨迹、
分层能力降级和悬停能力，但不等于宣称世界坐标、速度或 12m/s 巡航精度。

## 11. 权威文档

- 架构：`docs/ARCHITECTURE.md`
- 业务门禁：`docs/BUSINESS_LOGIC.md`
- Kafka/API：`docs/API_CONTRACTS.md`
- road9：`docs/DATABASE_SCHEMA.md`
- ADR：`docs/DECISIONS.md`
- 当前任务和未关闭项：`docs/TASKS.md`
- xqh 证据：`docs/test_report_inter_xqh.md`

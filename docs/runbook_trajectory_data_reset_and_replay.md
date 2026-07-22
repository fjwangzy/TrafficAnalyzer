# GCJ-02 渠化地图重建与轨迹回归 Runbook

> 日期：2026-07-21  
> 状态：历史清理和第一阶段完成；技术演示按用户要求收敛为 2 条轨迹抽样  
> 坐标/底图：GCJ-02 + 高德地图

## 1. 固定边界

保留 `uav_users/uav_drones/uav_video_sources/uav_telemetry_sources/uav_flight_plans`、Alembic
版本和原始 MP4/SRT/遥测/影像文件。YCX database=`ycx`, schema=`road9` 永远只读，不在重建
脚本中出现为目标库。其 WKT 字段由只读查询中的 PostGIS `ST_GeomFromText(...,4326)` 解析；
`inter_id/link_id/lane_id` 一律按不透明 geomhash 字符串处理。

清除范围由 `platform/scripts/rebuild_gcj02_data.py` 的固定 `CLEAR_TABLES` 和 Kafka allowlist 控制。
禁止 `DROP DATABASE`、无边界 `CASCADE`、通配表发现、Kafka 内部 Topic 删除或从旧消息恢复。

## 2. 已执行的清理

清理前 Platform、Mission 和 Pipeline 已停止，活动任务为零。执行命令必须显式提供环境开关和
确认串；默认命令始终为 dry-run：

```bash
PYTHONPATH=platform:. python platform/scripts/rebuild_gcj02_data.py \
  --output /private/tmp/TrafficAnalyzer-gcj02-rebuild-manifest.json --include-kafka

ALLOW_GCJ02_REBUILD=1 PYTHONPATH=platform:. \
python platform/scripts/rebuild_gcj02_data.py \
  --execute --confirm REBUILD_GCJ02_BUSINESS_DATA --include-kafka \
  --output /private/tmp/TrafficAnalyzer-gcj02-rebuild-manifest.json
```

2026-07-21 执行结果：清理时 Alembic head 为 `20260721_0016`，随后以前向迁移升级至
`20260721_0017`；保留 3 个用户、5 台无人机、10 个视频源、
10 个遥测源和 1 个飞行计划；飞行计划重置为 `draft / UNBOUND-GCJ02`；20 个原始文件全部存在
并记录 SHA-256；所有清理表为零，只有一条重建起点审计；62 个 `uav_*` Topic 的 end offset
全部为 0，受管 Consumer Group 不存在。

数据库历史业务行和旧 Kafka 消息已删除，不能由本系统直接恢复；只能依赖外部备份或保留原始
素材重新生成。执行证据为 `/private/tmp/TrafficAnalyzer-gcj02-rebuild-manifest.json` 和
`docs/test_report_gcj02_rebuild_local.json`。

## 3. 第一阶段：渠化车道标注

1. 启动原生 Platform 和 Console2，进入 `/admin/calibration`。
2. 输入 `inter_id`。本地已有版本时只读本地；本地无数据时才从 YCX 导入该路口。
3. 首路口固定为 `011wwe0z19700001 / 小清河北路与水屯路路口`，导入基线为 8 Link / 32 lane candidate。
4. 从保留原始素材生成/选择真实正拍关键帧，完成畸变校正和正射化。
5. 使用控制点计算 pixel→ENU 单应矩阵，服务端统一生成 GCJ-02；浏览器不得二次转换。
6. 先拟合 Link，再编辑车道面、边界、停止线、导流区、待转区和转向关系。
7. 通过 Link P95≤3m、车道中位≤0.75m/P95≤1.5m、拓扑/自交/重叠/方向/停止线/人工复核门禁。
8. 发布不可变 `lane_verified`。YCX candidate 数量不一致时使用本地稳定车道键，`source_lane_id` 可空。

对每个启用 SourceProfile 绑定的路口重复上述步骤。在全部路口达到 `lane_verified` 前，不得执行
第二阶段正式重跑。第一阶段可使用测试轨迹辅助检查，但不得生成正式研判事实。

2026-07-21/22 技术演示批次已发布 4 个不可变版本：小清河北路与水屯路
`CMV-1d3dedffa32145dca68c148d`（8 Link/32 Lane）、海右路
`CMV-5442ffb9608c483bbc11c92e`（8/30）、礼士路
`CMV-3d95098d2a7d4705992c93a8`（7/19）、崇华路
`CMV-e00cef599ed44e35add1aa67`（8/23）。9 个视频源均有独立 verified 配准；Link P95、车道
中位/P95、拓扑、自交、重叠、方向和停止线技术门禁全部通过。该结果允许演示重跑，但生产
发布仍需道路标线数据负责人完成人工签署。
结构化证据见 `docs/test_report_gcj02_stage1_20260721.json`，完整九图清单见
`.runtime/calibration/stage1-manifest.json`。

## 4. 第二阶段：逐源重跑

```bash
.venv-mps/bin/python -c "import platform, torch; print(platform.machine(), torch.backends.mps.is_built(), torch.backends.mps.is_available())"
scripts/mac_local_platform.sh up

.venv-mps/bin/python scripts/run_native_mps_replays.py \
  --output-dir output/native-mps/gcj02-map-projection-v3-20260722 \
  --sample-fps 3 --imgsz 640
```

重跑工具先获取精确 `lane_verified` Runtime Road Map Bundle；缺失即失败，不使用道路 JSON 或
自动车道候选。全部源按顺序执行，避免 MPS 竞争。每源先保存独立运行结果；全部 EOF 后执行
`platform/scripts/finalize_demo_replay_batches.py`，把输入 SHA-256、Mission、地图/转换/模型版本
固化并关联事实。单源失败仅通过固定白名单脚本 `rollback_replay_source_batch.py` 回滚该批次，
修复后从原始素材重新运行。

正式重跑前运行 `backfill_runtime_registration_motion_reference.py` 的 dry-run 与固定确认执行，
保证每个 verified 配准含配准时 GCJ-02 位置。`gcj02-demo-20260721` 与
`gcj02-map-projection-v2-20260722` 都是已回滚的无效工程批次，不得使用 `--resume` 复用其
结果；新批次必须使用独立输出目录和新的 Pipeline ID。

技术演示缩小范围时，使用重复 `--source` 仅固化已自然 EOF 的来源；未传 `--source` 仍要求
目录中 9 个结果全部通过。验收工具同样支持显式来源和最小样本数，例如：

```bash
PYTHONPATH=platform:. .venv-mps/bin/python \
  platform/scripts/verify_gcj02_demo_replays.py \
  --output-dir output/native-mps/gcj02-map-projection-v3-20260722 \
  --source SRC-INTER-XQH-0403-PM --sample-per-source 2 --minimum-samples 2
```

若中途停止来源，先停止 Platform 消费者并执行 `rollback_replay_source_batch.py`，恢复消费者后
再次 dry-run，直到 Kafka 尾部不能重新生成事实。已发布地图但 Dashboard 仍显示候选坐标时，
先 dry-run 再固定确认执行 `backfill_lane_verified_road_context.py`；脚本只按地图 `source_checksum`
更新 4 个已登记快照，不修改地图、轨迹、YCX 或原始素材。

## 5. 验收与停止条件

- 每源自然 EOF，Kafka、数据库和前端轨迹数对账一致；
- 至少 100 条人工复核轨迹，车道匹配准确率 ≥95%；
- 高德地图上的 `trajectory_gcj02` 与渠化车道无系统偏移；
- 速度、距离、TTC、PET、面积只使用 ENU，展示只使用 GCJ-02；
- 新记录不含旧坐标字段，Console2 活动代码不含 OSM/OpenLayers 或坐标 fallback；
- Platform、Console2、真实视频管道和 ADR-019 严格审计通过。

任一地图未 `lane_verified`、MPS 不可用、进程 CPU fallback、输入哈希变化、消息对账不一致或
轨迹抽检不达标时立即停止。技术演示重跑不等同于生产人工验收；至少 100 条人工车道复核及
≥95% 准确率仍是生产签署门禁，自动空间一致性检查只能作为辅助证据。

## 6. 2026-07-22 收尾基线与下一阶段入口

本轮状态固定为 `local_demo_complete / production_signoff_blocked`：

- 第一阶段：4 个路口、31 Link、104 个本地稳定车道和 9 个 SourceProfile verified 配准已发布；
- 第二阶段：5 个来源自然 EOF，形成 5 个 completed Mission 和 13,042 条新轨迹；
- 用户指定的视频回归范围：小清河北路 2 条轨迹样本，不继续等待其余来源全量运行；
- 运行状态：原生 Platform 可按 `scripts/mac_local_platform.sh up` 恢复，收尾时不得存在活动 Pipeline；
- 权威证据：`docs/test_report_gcj02_two_stage_demo_20260722.md` 及其引用的结构化 JSON；
- 无效批次：`gcj02-demo-20260721` 与 `gcj02-map-projection-v2-20260722` 已回滚，不得恢复或续跑；
- 凭证边界：`docs/road_pg.md` 不进入代码、构建、报告或交接文档，提交前必须继续排除。

下一阶段不得重新打开旧坐标或 OSM/OpenLayers 兼容。推进生产签署时按顺序执行：道路标线负责人
复核 4 个发布版本；随机抽取不少于 100 条轨迹并证明车道匹配准确率 ≥95%；确认是否补跑其余
来源；最后完成生产密钥、域名白名单、TLS/SASL、容量、HA、备份恢复和 RPO/RTO 门禁。

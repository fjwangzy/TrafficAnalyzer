# XQH TCC 输出链路修复与验证（2026-08-09）

## 1. 验收结论

小清河路口 `011wwe0z19700001`、来源 `SRC-INTER-XQH-0403-PM` 已恢复正式
`path_intersection` TCC 事件的检测器画面、Replay V2 持久化、REST 回放和 Monitoring 展示。
最终真实运行在源视频 `T+15.816s` 产生一条 `warning` 事件：机动车轨迹 `88`、非机动车
轨迹 `725`，`TTC=2.25s`、`PET=0.18s`、`distance_m=0.0`，证据为
`hard_pet + hard_deceleration`。

本机只保留一套最新可用运行态：Platform `8000`、Console2 `5173`，运行档为
`APP_RUNTIME_PROFILE=replay_v2`。不再把 `8000/8200` 双端口隔离作为本次方案或验收条件。

## 2. 回归链和根因

本次不是 TCC 数学判定单点失效，而是输出链路上四个契约漂移叠加：

1. 图像跟踪重构后，当前帧保存 `association_id -> internal track_id` 映射，但
   `ShowNode` 仍用事件中的 association ID 直接查内部轨迹缓存。事件和证据文件已经产生，
   检测器输出帧却找不到端点，因而不画红色连接线、冲突点和 TTC 徽章。
2. Replay V2 生产者没有写 canonical `data.offset_ms`，存储层又把缺失值静默当成 `0`；
   所有历史冲突看起来都发生在 `T+0`。
3. Replay V2 冲突表只保存 TTC/PET 等预测值，没有保存 `motor_id`、`non_motor_id`、
   `distance_m` 和 `conflict_scene`。Monitoring 的正式业务过滤要求
   `prediction_type=path_intersection && distance_m≈0`，所以持久化事件被过滤。
4. Monitoring 对所有来源固定查询最近 `24h`。XQH 本地 MP4/SRT 使用 2026-04-03 的业务时间，
   2026-08-09 复盘时自然查不到。与此同时 Replay V2 Alembic 目录缺少 `env.py`，旧库停在旧
   head 时不暴露问题，新迁移出现后才会使从零/向前迁移失败。

对应历史变更定位：`e748c22` 引入 association/internal ID 分离后没有同步 Show 冲突绘制；
`b28f9ac` 引入 Replay V2 存储契约后，生产者没有提供严格 offset。

## 3. 完整解决方案

### 3.1 检测器画面身份边界

- `ConflictDetectionNode` 和事件继续使用稳定 association ID，不改业务事件身份。
- `ShowNode` 在绘制时使用当前帧 `track_id_by_association` 映射到内部缓存 ID。
- 只为旧的同 ID 数据保留精确 fallback；不猜测、不重编号事件。
- 冲突端点、红色连接线、预测冲突点和 TTC 徽章继续来自实际 `frame_result`，证据模块不重绘。

### 3.2 Replay 时间契约

- Replay V2 producer 以 Mission 的源时间起点计算非负整数 `offset_ms`，写入每个 canonical
  envelope。
- Store 对缺失、非数值、非有限或负 offset fail closed，不再默认 `0`。
- 冲突查询先按 Mission 创建时间倒序、再按源 offset 倒序，确保最新一次回放优先。

### 3.3 冲突事实契约和迁移

- Replay V2 冲突事实新增可空列：`motor_track_id`、`non_motor_track_id`、`distance_m`、
  `conflict_scene`。
- Store 写入并原样返回这四项，使 REST 和实时消息使用同一业务过滤口径。
- Alembic 新 head 为 `20260809_rv2_0004`，并补齐可执行的异步 `env.py`。
- 不回填旧行：旧行缺身份/距离且 offset 为 0 是历史不完整事实，禁止推断或伪造。

### 3.4 Monitoring 查询策略

- `mode=local` 的 SourceProfile 使用 `period=all`，用于离线素材按业务时间复盘。
- 其他实时来源仍用 `period=24h`，避免无界读取。
- 页面仍固定请求 `prediction_type=path_intersection`，并保留 `distance_m≈0` 的严格过滤。

## 4. 测试方法和门禁

| 层级 | 方法 | 验收点 | 本次结果 |
|---|---|---|---|
| 单元：画面 | 构造 association ID 与内部 ID 不同的轨迹 | 冲突连线/标记实际落到两条轨迹 | 通过 |
| 单元：生产者 | 以非零源时间运行 Replay envelope | `offset_ms` 为相对 Mission 起点，非法时间拒绝 | 通过 |
| 单元：Store | 缺失/非法/负 offset 及完整冲突字段 round-trip | 不再产生静默 T+0；身份、距离、场景可读 | 通过 |
| Schema | Alembic head、`env.py`、新增列 | 空库和旧 head 均可向前迁移 | 通过 |
| PostgreSQL 集成 | 在 road9 执行迁移和事实写读 | 新 head 生效、查询契约一致 | 7 passed |
| XQH 静态基线 | `test/test_pipeline_inter_xqh.py` | 视频/SRT/标定/节点链不回归 | 55 PASS / 0 FAIL / 1 WARN |
| XQH 实跑 | 原生 MPS 启动 XQH pipeline | 产生正式 TCC，offset 非零，图片有检测器叠加 | 通过 |
| REST | 按 source/pipeline/path_intersection 查询 | 返回完整身份、距离、TTC/PET、证据 | 通过 |
| Console | 本地源历史查询 + production build | 请求 `period=all` 且严格展示正式事件 | 聚焦测试、build 通过 |
| 浏览器 | 打开真实 Monitoring 深链 | 实时画面和事件卡可见 | 通过 |

建议后续每次变更至少执行：

```bash
python -m pytest \
  test/test_show_node_class_colors.py \
  test/test_kafka_active_trajectories.py -q

python -m pytest \
  platform/tests/test_replay_v2_schema.py \
  platform/tests/test_replay_v2_metric_store_contract.py -q

RUN_PG_INTEGRATION=1 python -m pytest \
  platform/tests/test_replay_v2_schema.py \
  platform/tests/test_replay_v2_metric_store_contract.py \
  platform/tests/test_replay_v2_postgres_integration.py -q

PYTORCH_ENABLE_MPS_FALLBACK=1 .venv-mps/bin/python test/test_pipeline_inter_xqh.py

cd console2
npm test -- --maxWorkers=1 --no-file-parallelism src/LiveModules.test.jsx
npm run build
```

完整 UI 文件当前仍有两个与 TCC period 修复无关、可独立复现的既有失败：未绑定道路上下文的
演示检测按钮门禁，以及 Mission 业务失败提示。TCC 本地历史查询聚焦用例通过，production build
通过；在这两个既有用例修复前，不宣称 Console2 全量测试全绿。

## 5. XQH 最终真实证据

- Mission：`MSN-AE785FD3C417`
- Pipeline：`pipe-d6e82e41`
- 路口：`011wwe0z19700001`
- SourceProfile：`SRC-INTER-XQH-0403-PM`
- 事件源时间：`offset_ms=15816`
- 事件：`warning / path_intersection / general_crossing`
- 轨迹：`motor_id=88 / non_motor_id=725`
- 指标：`TTC=2.25s / PET=0.18s / distance_m=0.0`
- 证据：`hard_pet / hard_deceleration`
- 质量：`quality_status=estimated / time_quality=verified`
- 检测器证据图：
  `test_videos/videos_out/conflict_20260809_220023_warning_ttc2.2s_m88_nm725.jpg`
- Monitoring 深链：
  `/monitoring?intersection_id=011wwe0z19700001&source_profile_id=SRC-INTER-XQH-0403-PM`

人工停止任务用于快速验收，所以该 Mission 的结束诊断为 `incomplete/cancelled`，不是完整 EOF
封存；这不改变事件事实和 TCC 链路验证结论。当前验收属于真实素材上的工程功能验证，没有外部
轨迹真值，因此 IDF1/HOTA、正式 ID switch、位置 RMSE 和速度 MAE 仍为 `not_evaluated`。

## 6. 单版本运行方法

```bash
APP_RUNTIME_PROFILE=replay_v2 \
PLATFORM_INSTANCE=replay_v2 \
PLATFORM_PORT=8000 \
scripts/mac_local_platform.sh up

cd console2 && npm run dev
```

验收前后检查：

```bash
curl -fsS http://127.0.0.1:8000/ready
lsof -nP -iTCP:8000 -sTCP:LISTEN
lsof -nP -iTCP:5173 -sTCP:LISTEN
```

只维护上述最新运行态；不启动或保留 `8200`。

## 7. 2026-08-10 AI 事件中心补充修复

### 7.1 现象与根因

Monitoring 已能读取 Replay V2 的正式冲突事实，但 AI 事件中心的统一查询只覆盖
`uav_ai_events` 与普通 `uav_conflict_events`，遗漏 `uav_replay_v2_conflict_events`。同时，
Monitoring 的“全部事件”链接只跳转 `/events`，没有保留路口、SourceProfile、Mission 与事件 ID。
因此最终 XQH 事件虽然存在于事实表和 Monitoring 中，事件中心仍查询不到；列表里 TTC/PET 相同的
`d7969fe...` 属于其他 Source/Mission，不能作为 XQH 验收证据。

### 7.2 解决方案与边界

- Event Center 服务将 Replay V2 冲突事实投影为统一事件读模型，支持
  `intersection_id/source_profile_id/mission_id/event_type` 服务端过滤与按 ID 详情查询；不复制事实，
  也不新增伪造的普通事件记录。
- 统一读模型明确返回 `source_kind=replay_v2_conflict`、真实事实表名、双方轨迹、TTC/PET、距离、
  场景、证据、Mission、Pipeline、SourceProfile 与路口。
- Replay V2 冲突当前没有对应的复核写模型，事件中心只读展示并隐藏复核按钮；API 对错误复核请求
  返回 422，避免写入另一套事件存储。
- Monitoring 的“全部事件”深链保留事件类型、路口、SourceProfile、Mission 与真实事件 ID；事件中心
  使用固定长度的查询依赖并由服务端过滤，直接打开深链时也能加载目标详情。

### 7.3 XQH 验证结果

修复前连续两次调用以下精确过滤查询均返回 `count=0`；修复后连续两次均返回 `count=1`：

```text
/api/v1/events?event_type=conflict&inter_id=011wwe0z19700001
  &source_profile_id=SRC-INTER-XQH-0403-PM
  &mission_id=MSN-AE785FD3C417&limit=150
```

事件中心最终事实：

- Event ID：`d1bfae25da343b0d5e32c61ffe85a09f5892180d`
- Mission / Pipeline：`MSN-AE785FD3C417` / `pipe-d6e82e41`
- SourceProfile / 路口：`SRC-INTER-XQH-0403-PM` / `011wwe0z19700001`
- 轨迹：机动车 `88`、非机动车 `725`
- 指标：`TTC=2.25s`、`PET=0.18s`、`distance_m=0.0`
- 事实表：`uav_replay_v2_conflict_events`
- AI 事件中心深链：
  `/events?event_id=d1bfae25da343b0d5e32c61ffe85a09f5892180d&event_type=conflict&intersection_id=011wwe0z19700001&source_profile_id=SRC-INTER-XQH-0403-PM&mission_id=MSN-AE785FD3C417`

自动化结果：Platform 全量 `303 passed / 6 skipped / 10 subtests passed`；事件中心 Replay V2
聚焦测试与只读复核测试 `3 passed`；Console Router 全文件 `63 passed`，Monitoring 深链聚焦测试
通过，production build 通过。真实浏览器页面已验证列表仅返回这一条 XQH 事件，详情中的 Mission、
Pipeline、SourceProfile、事实表、双方轨迹、TTC/PET 与只读标记一致，浏览器无 error/warning 日志。

## 8. 2026-08-10 Replay V2 事件图片补充修复

### 8.1 根因

`TccEvidencePublisherNode` 已在 ShowNode 完成真实画面叠加后，把原始帧和检测器输出帧保存为
内容寻址对象，并随冲突 envelope 发送 `evidence_files`。普通 MetricStore 会校验文件 SHA-256、
大小、类型和受控 storage key，再登记 `EvidencePackage/EvidenceItem`；Replay V2 MetricStore 此前只
保存 `evidence` 风险规则标签，完全忽略 `evidence_files`。因此事件中心返回
`evidence_refs=[]`，前端按契约没有图片可展示，并非前端图片组件故障。

### 8.2 修复与历史事件补登记

- Replay V2 冲突入库现在对受控内容寻址对象执行 hash/size/media-type/storage-key 校验，并在同一
  事务登记 `owner_type=replay_v2_conflict` 的 EvidencePackage 和 EvidenceItem；本地绝对路径不会
  进入事件 API。
- Event Center 按 Replay V2 event ID 批量读取 EvidenceItem，返回可鉴权的
  `/api/v1/survey-evidence/{id}/content` 引用和 SHA-256；详情页复用既有 Blob 下载、缩略图和全屏查看。
- 历史 XQH Kafka offset `50` 已因保留策略淘汰，但对应检测器内容寻址对象仍存在。使用
  `platform/scripts/register_replay_v2_conflict_evidence.py` 对 Event、Inbox lineage、JPEG 可读性、
  3840×2160 尺寸和 SHA-256 完成 dry-run 后，仅为目标事件补登记证据引用；未修改事件指标、轨迹、
  Mission 或原始文件。

历史事件最终证据：

- Event：`d1bfae25da343b0d5e32c61ffe85a09f5892180d`
- Evidence：`043185b552f3d058500b79e53ba7dfc27657baf5`
- Kind：`conflict_detector_frame`
- SHA-256：`a1a58957492a461039abb18935e726d9d0f628c965bc1f24837500391a36aecc`
- JPEG：`3840×2160 / 2,748,877 bytes`

### 8.3 验证

- 原确定性红灯连续两次返回 `evidence_refs=[] / NO_IMAGE_EVIDENCE`；修复后连续两次均返回一个
  `conflict_detector_frame`，受控内容接口返回 `image/jpeg`，下载大小和 SHA-256 完全一致。
- Replay V2 evidence + Event Center 聚焦测试 `6 passed`；相关 MetricStore 回归 `23 passed`；
  TCC Evidence Publisher、Show 和 Kafka 回归 `41 passed`。
- Platform 全量 `304 passed / 6 skipped / 10 subtests passed`；Console Router 全文件 `63 passed`；
  production build 通过。
- 本机只重启 `replay_v2` 的 Platform `8000`，数据库、Kafka、TimescaleDB、PipelineManager 均健康；
  `8200` 未监听。

## 9. 2026-08-10 事件列表选中项关联图片修复

### 9.1 频发告警

事件 `EVT-8da17afcda8e2f0cdc1db1bebb982ef6` 是 2026-08-09 21:55:20（UTC+8）触发的
“冲突事件频发（4次/分钟）”。原告警 payload 没有直接保存子事件 ID；Event Center 现在从告警
业务时间之前 60 秒的 Replay V2 inbox `received_at + fact_refs` 恢复同一 XQH 路口的 4 个子冲突，
并把各自受管检测器帧投影到聚合详情：

| 子冲突 | 检测器帧 SHA-256 前缀 |
|---|---|
| `86b348ad01260bb2888657f062a708c2bc4440e0` | `ab471fc69bf5` |
| `af7281f93440e6fa98a639ae640c34dbe65f0400` | `2304e7dadd7f` |
| `665eef16c21ffc61f03d3ff9c5fc1722514fc0b2` | `bcc573b71095` |
| `0eb63df8adc7bdc9ea147feffbf289deb4041221` | `674f94cb7eb1` |

四张图均为原有 3840×2160 检测器 JPEG，dry-run 核对 Event、Inbox lineage、Mission、文件可读性、
尺寸、大小和 SHA-256 后登记；没有修改冲突事实。接口同时返回有序 `related_event_ids`，每个证据
引用携带 `related_event_id`，不靠文件名猜测关联。

### 9.2 测绘成果与不可恢复历史事件

- `EVT-CA8624DA3384` 的 4 项证据改为 1 张 `survey_report_annotated_image` 图片预览，以及 PDF、
  JSON、GeoJSON 三个附件按钮；报告文件不再被错误送入图片组件。
- `365a8b24...`、`78534ef7...`、`39d9564b...` 三条 2026-08-04 早期 Replay V2 冲突只保存了
  `offset_ms=0` 和 TTC/PET，没有事件帧、双方轨迹和可靠源时间，原 Kafka offset 也已过保留期。
  这些详情明确显示 `historical_managed_evidence_unavailable / 历史关联图不可恢复`；禁止把新任务或
  相近 TTC 的图片挂到这些旧事实上。

## 10. 2026-08-10 典型 TTC 1.6s 历史事件恢复

目标文件 `conflict_20260715_164100_critical_ttc1.6s_m6342_nm5713.jpg` 的文件名时间是旧进程
落盘墙钟，不是视频业务时间。4K 像素反查确定它来自 XQH 原视频约 `33.37303s`、源帧约 `1000`。

验证分三层：

1. 当前 `hover_cruise_v1` Mission `MSN-EF5A3F3A77F8` 跑到源时间 `41.3413s`，仅在
   `15.8158s` 产出 `88/725, TTC=2.25s`，目标帧不触发。
2. 当前 `hover_only_legacy` Mission `MSN-BA3CF1A27746` 跑到 `42.743s`，未产出 TCC；说明差异
   不只是跟踪器开关，还包括历史冲突规则。
3. 使用 2026-07-14 提交 `41fb6e6`、同一 0–42s 原片、同一 SRT、旧 XQH 路区、
   `frame_stride=5` 和当时配置离线重跑，重新产出 `critical / TTC=1.6s`。复现轨迹 ID 为
   `6239/5620`，旧图为 `6342/5713`；ID 跨运行不稳定，但两张 3840×2160 画面平均绝对像素差
   `1.3843`，`99.437%` 像素差不超过 5，确认是同一源帧和同一冲突几何。

恢复事实：

- Event：`19ecefebf106dc541be6bff8c5918295e121cafa`
- Mission：`MSN-HIST-XQH-20260403-F1000`（sealed historical replay）
- Pipeline：`historical-detector-41fb6e6`
- 业务时间：`2026-04-03T06:29:35.373Z`（源视频起点 + 33.373s）
- 轨迹 / 指标：旧运行 `6342/5713`、`critical`、`TTC=1.6s`
- Evidence：`0969a479fa73451623b85887ccadefa978ea6d36`
- Evidence SHA-256：`082d0de8e6685233b4df1c2fe0fdea492e0a7dbadacb83e8e2d788da1ae7d54e`
- 口径：`historical_detector_output / historical_reconstructed / reconstructed`

AI 事件中心以“历史检测口径复现”单独标识，并明确“当前生产口径在同一源帧未触发”；该事件只用于
历史复盘，不宣称当前算法检出，也不进入当前生产效果统计。

## 11. 2026-08-10 当前检测器正式恢复与实时验收

深入复盘确认当前 `hover_cruise_v1` 在目标源时间的所有正式门禁均已通过，唯一旧拒绝条件是当前
ENU 运动夹角 `160.8° > 150°`。该差异来自跟踪/世界投影重构后的运动几何，不是一次近期配置
误改。阈值扫描显示简单扩到 `170°` 会额外放入视觉不明确的近对向事件，因此最终不是直接放宽：

- 标准 `30°~150°` 路径交点规则保持不变；
- `150°~170°` 只接受 `TTC<=3s`、`PET<=1s`、避险行为和明确左转弧线同时成立的路径交点；
- 近对向直行以 `high_angle_scene_ambiguous` 拒绝；同刻 CPA 继续关闭；
- Event Center 展示预测类型、冲突场景和中文证据，原始帧与检测器帧保持两项内容寻址证据。

输出链另发现两项独立缺陷并修复：Replay V2 生产者缺少 `zstandard`，消费者又被不完整临时
`cramjam` 目录遮蔽；现统一由当前 MPS 环境提供双端依赖，并在启动前失败关闭。检测器此前只在 EOF/
停止时发布 Mission，导致运行中冲突已入库却被事件中心内连接隐藏；现首帧先发布 `status=running`
Mission 事实，再允许 Stats/Conflict 到达。

最终真实验收：Mission `MSN-DD60921B64E2`、Pipeline `pipe-9e362f56` 在仍为 `running` 时，
`T+33.333s` 输出事件 `ddb7ca9ec5419a8088bb55c6912f8f6c90a4ac0a`：`critical`、
`path_intersection`、`TTC=2.16s`、`PET=0.03s`、轨迹 `1802/1770`、场景
`suspected_unprotected_left_turn`、证据 `hard_pet + hard_deceleration + high_angle_crossing`。
Event detail 同时返回两张 3840×2160 JPEG，内容接口均为 200；真实浏览器已确认两图和“TCC 判定依据”
可见。命中后人工停止，Platform 保持单一 8000 实例、`pipelines_active=0`。

## 12. 2026-08-10 原事件 TCC 聚焦画面重建

针对事件 `ddb7ca9ec5419a8088bb55c6912f8f6c90a4ac0a`，检测器帧改为聚焦叙事：非冲突目标不再
绘制框、标签或轨迹，且冲突帧关闭 FPS、道路、车道、方向和统计叠加；只保留轨迹 `1802/1770`
双方框、历史轨迹、分别收敛到预测冲突点的虚线预测轨迹、红黄爆点和 `TTC 2.2s` 徽章。预测线
继承各自对象检测框和实线历史轨迹的颜色，并用分段虚线表达未来延长；TTC 徽章在爆点周围动态选位，避开双方框、标签、历史
轨迹和预测轨迹。旧两端点连线和钻石端点已移除。

为避免用相近帧覆盖历史事实，原生 MPS 使用同一 `SRC-INTER-XQH-0403-PM`、stride 3 重放，重新命中
`T+33.333s / critical / TTC=2.16s / PET=0.03s / 1802×1770`；新旧原始帧 SHA-256 均为
`dae77839fd12c8e1ded384697f16789bf230cc5a7154626fdda1321ef35cf3e9`。因此只换版原事件的派生
`conflict_detector_frame`：EvidenceItem ID 仍为 `d8cf0df89425607c7a45314ff81eb37a86d6ddcc`，新 SHA-256 为
`a64b7a20150896b9b628433ca825834e02354dce144507bb79133d36d4c1d107`，EvidencePackage 升为
version 4 并重算 manifest；事件 ID、Mission、业务字段和原图均未修改。

临时重放产生的 2 条重复冲突及其数据库证据引用已移除，内容寻址对象未物理删除。聚焦渲染、精确
Show 输出证据和后置发布组合测试为 `31 passed`；换版后原事件 API 返回 200、detector 内容下载哈希
与登记值一致，临时 Mission 冲突查询为 0，Platform `8000` ready 且 `pipelines_active=0`。

> 审计更正：旧阶段中位数之和仅为预算估算，旧 EGRESS_STATUS 输入水位不代表业务提交。正式验收须使用新增 committed 水位并独立核对数据库回执，见 FPS_REGRESSION_AUDIT_20261105.md。

# 2026-11-05 FPS 优化方案、计划与验证方法

本文是可执行方案，不是已完成的修复。基线证据见 [FPS_ROOT_CAUSE_20261105.md](FPS_ROOT_CAUSE_20261105.md)：现场当前跑的是 **2026.11.04.2**，两条限速链分别是 P2 串行业务链（约 637ms/帧）和 P4 egress 接收（拥堵场景 >1.18s/帧，队列 32/32 长期满）。本轮不修改模型、分辨率、stride、阈值或质量门禁，不新增 DDL，不改变 canonical 消息与 v2 摘要契约。

## 1. 目标与判定口径

| 项目 | 口径 |
| --- | --- |
| 页面 FPS | `SnapshotScheduler.apply`→`frame.pipeline_fps`→`stats.fps`，即 **P2 完成帧率**（2 秒滑窗），不是 YOLO 推理帧率 |
| 硬目标 | 生产同源素材 **≥3.0 FPS 连续 5 分钟**，且后半段 ≥ 前半段 90%（无衰减）——沿用 `scripts/accept_pipeline_fps.py` 判据 |
| 延伸目标 | ≥5.0 FPS（P2 与 P4 都要 ≤200ms/帧） |
| 伴随条件（必须同时成立） | ① egress 队列满采样占比 <10%；② `journal_bytes` 线性增长、无 ECHO/补发；③ 业务事实逐字段一致；④ 无 ERROR/WORKER_FAILED；⑤ RSS 无持续增长 |
| 非目标 | 用降检测数、关业务节点、调阈值、加 stride 换来的数字提升，不计为修复（可作为单独的业务取舍另行决策） |

**预算换算**：`FPS = 1000 / P2_ms`，P4 也必须满足 `1000 / P4_ms ≥ 目标 FPS`，两者取小。要 3 FPS：P2 ≤333ms、P4 ≤333ms；要 5 FPS：两者都 ≤200ms。

## 1.1 实施状态（2026-11-05）

本轮已落地五项，实测与回归证据见 [FPS_OPTIMIZATION_VALIDATION_20261105.md](FPS_OPTIMIZATION_VALIDATION_20261105.md)：

| 工作包 | 状态 | 实测 |
| --- | --- | --- |
| WP1 P4 接收批量化 + 分项计时 | ✅ | `.2`→`.3`+本轮：接收端合计降幅 94–98%，每帧 SQL SELECT 3,402→0，tail hash 一致 |
| WP2 接收端尾迹冻结 + wire 增量 `frame_delta` | ✅ | `restore` 4.4–6.1ms；facts 包 276→109KB/帧 |
| WP4a 图像轨迹批量 warp | ✅ | 9.42→2.81ms（3.35×） |
| WP4b 世界投影/GCJ 增量 | ✅ | 25.8→3.9ms（6.64×） |
| WP5 冲突网格预筛 | ✅ | 72.5→29.1ms（2.49×，22,500 对）；小场景按阈值回退逐对 |
| WP2 wire 增量协议（`frame_delta`） | ✅ | facts 包 −60%、每帧总字节 −52%（实测 journal） |
| WP3 轨迹数治理 / WP6 渲染 / WP7 NMS | ⏳ | 未开始 |

单进程节点 A/B（同负载、背靠背；排除真实 journal/Kafka）：P2 串行预算 104.9→78.2ms（−25.5%），其中三个被改阶段合计 −17.2ms；现场 5 分钟 A/B 仍未执行，3 FPS 目标仍为待验证。

## 2. 现状预算与目标分配

现场 `pipe-399dd5fe`（.2、直播拥堵、300 检测/300→519 轨迹）P2 纯计算约 637ms；`pipe-8f75642b`（.1、回放、138–158 检测）P2 串行 637ms。两者同量级，说明 P2 成本主要由“轨迹数×每轨迹工作量”决定。

| 阶段 | 直播现状 ms<br>300 检测/519 轨迹 | 回放现状 ms<br>158 检测/280 轨迹 | 目标 ms | 手段（工作包） |
| --- | ---: | ---: | ---: | --- |
| association | 323.4 | 167.0 | 120 / 70 | WP4 缓存 tlbr + 批量 warp + 去逐轨迹 numpy |
| info | 105.5 | 57.7 | 40 / 25 | WP4 环形缓冲 + WP5 增量类别投票 |
| image_motion | 75.0 | 74.6 | 60 | WP4 一次灰度化、复用角点（不降分辨率） |
| egress 交接（真实工作） | ~100 | ~100（`.2` 拆分后） | 30 | WP2 facts 增量快照 |
| world_projection | 14.6 | 33.3 | 8 / 15 | WP4 GCJ-02 只算新点 |
| conflict | 0.7 | 68.9 | 不变 / 25 | WP5 空间网格预筛（直播该时段被低速门禁提前过滤） |
| speed | 1.0 | 36.0 | 不变 / 12 | WP5 窗口增量 |
| lane_change + 其余 9 节点 | ~18 | ~14 | 14 | WP4 复用已算好的历史 |
| **P2 合计** | **≈637** | **≈637** | **274 / 249** | 约 **3.6–4.0 FPS** |

两个基线刚好都是 637ms 但构成不同：直播被 association/info 主导，回放因 conflict/speed 生效而更分散；目标列按各自构成给出，落到同一条预算线。

P4 目标：当前 472KB/帧、10.2 包/帧、>1.18s/帧 → 先由 WP1 批量化降到约 250–350ms，再由 WP2 把载荷降到 <60KB/帧、2–3 包/帧，目标 ≤200ms/帧。

## 3. 优化原则（针对上一轮失效的原因）

1. **只认端到端**：任何单项收益必须体现在 P2 预算或 P4 帧时间上，单函数微基准不作为结论。
2. **先减工作量，再谈并行**：P2 是一条串行链，减少每帧 Python 运算量优先于加进程；加进程留到 WP9 评估。
3. **一项一开关**：每项改动带独立配置开关（默认新路径），可单点回退；三进程/四进程、Mac/MPS 默认值不变。
4. **同负载才比较**：A/B 必须同素材、同检测数/轨迹数、同版本其余部分，否则用 `compare_fps_profile.py` 直接判不可比。
5. **每次改动都带语义门禁**：业务事实逐字段对照 + 显示逐像素对照，不允许“更快但字段变了”。

## 4. 工作包

### WP0 现场版本与基线（0.5 人日，阻塞其他项）

- **内容**：确认现场 `app/services/PipelineEgress.py` 是否含 `egress.append_points`/`egress.restore_tails`（没有即 .2）；导出 ≥5 分钟诊断；记录 `nproc`、governor、`pgrep -af main_optimized.py | wc -l`。
- **产出**：一份 `.2` 基线 JSON（`accept_pipeline_fps.py` 输出）+ 主机事实清单。
- **完成定义**：能明确回答“现场跑的是哪个包、当时 P2/P4 各多少 ms、队列多满”。
- **命令**：
  ```sh
  grep -c "egress.append_points\|egress.restore_tails" <现场>/app/services/PipelineEgress.py
  cat /sys/devices/system/cpu/cpu0/cpufreq/{scaling_governor,scaling_cur_freq,cpuinfo_max_freq}
  python scripts/accept_pipeline_fps.py diagnosis.json --minimum-fps 3 --minimum-duration 300
  ```

### WP1 P4 接收批量化落地（1–2 人日）

- **现状**：`.2` 的 `DeltaTracks.append` 逐点逐字段 `INSERT`（约 2,100 条/帧）；`.3` 已有 `append_batch` + `DiskArray.TAIL_POINTS=128`。
- **方案**：部署 `.3` 接收端（`.3` 已带 `egress.restore_tails`/`egress.append_points` 计时）；再给 `commit_frame` 补 `egress.geojson`、`egress.facts_json`、`egress.kafka_produce` 三个分项计时，补齐目前无法归因的 P4 时间。
- **预期**：P4 帧时间 1.18s → 0.25–0.35s；直播场景 0.70 → 1.4–1.6 FPS（回到 P2 上限）。
- **风险**：批量化改变写入时序 → 必须保留 `.2` 回退包，并做归档逐条对账。
- **完成定义**：同一路视频 `.2` vs `.3` 5 分钟 A/B，队列满占比 <10%，归档行数与点序一致。

### WP2 facts 增量快照（3–5 人日，收益最大）

- **现状**：每帧把全部轨迹的元数据+尾点重新 pickle/JSON，472KB/帧、10 包/帧；`.3` 只是把“冻结”拆开，没有减少“发什么”。
- **方案**：
  1. P2 侧维护 `track_facts_version`，每帧只发 `changed` 轨迹（新增、属性变化、关闭）与新增点；未变化轨迹只发心跳位图。
  2. P4 侧 `restore_fact_tails` 改为按增量 apply，不再整表重建；显示视图单独限流（见 WP6）。
  3. 协议加 `facts_delta_v1` 版本位，接收端对旧包保持兼容读取。
- **预期**：472KB → <60KB、10 包 → 2–3 包；P2 交接 100 → 30ms；P4 降至 ≤200ms。
- **风险**：契约变更影响 Replay v2 与归档重放 → 需迁移/兼容策略与逐字段 diff；旧消费者不得恢复。
- **完成定义**：固定素材 300 帧，归档事实与 `.2` 逐字段一致；A/B 中 P2/P4 同时下降。

### WP3 轨迹数治理（2–3 人日）

- **现状**：直播拥堵场景检测恒定 300，轨迹从 300 涨到 519；0.7 FPS 时 `max_lost_sec=2.0s` 只等于约 2 帧，lost track 来不及回收，形成“低 FPS→轨迹堆积→更慢”的正反馈。
- **方案**：① lost track 回收同时受“源时间 2s”和“处理帧数上限”约束；② 对连续 N 帧不可见且从未成熟的 candidate 直接丢弃；③ 复核 `max_det`（疑似 ultralytics 默认 300）是否应显式配置——**此项涉及业务召回，需业务确认，不在本方案默认修改**。
- **预期**：轨迹数收敛到接近可见目标数（约 −30%），P2 各逐轨迹阶段同比 −20–30%。
- **风险**：过早回收会拆轨迹、影响速度/冲突统计 → 需用固定素材做 ID/事件对照。
- **完成定义**：拥堵素材 300 帧内轨迹数不再单调增长；业务事件数不变。

### WP4 P2 环形缓冲 + 批量几何（5–7 人日，P2 主战场）

- **现状**：每帧每轨迹重建 4 份视图、5,231 次 `list.copy`、1,486/1,194 次 `tlwh`/`tlbr`、142 次单轨迹 warp、285 个 shapely `Point`。
- **方案**：
  1. `TrackElement` 的点历史改定长 numpy 环形缓冲（`(N,K,4)` + 时间/帧号），append O(1)，视图用切片，不再逐点 `copy`。
  2. 每帧一次性缓存 `tlbr` 为 `(N,4)` 数组；warp 合并为一次 `(N·K,3) @ M.T`。
  3. ENU→GCJ-02 只对新点计算，尾部缓存；显示/候选视图共享只读数组。
  4. `plain()`/`freeze_*` 直接读环形缓冲，避免中间 dict。
- **预期**：association 323→120、info 105→40、world 15→8、lane_change 8→4；P2 −250ms 左右。
- **风险**：环形缓冲与增量发送/EOF 密封/`trajectory_history_start` 的边界多 → 必须先补 WP0 里的回归（含 `authoritative point history regressed` 场景）。
- **完成定义**：`compare_fps_profile.py` 判 passed（负载可比、回归 ≤5%）；业务事实与显示逐像素一致。

### WP5 冲突网格与速度增量（3–5 人日）

- **现状**：conflict O(轨迹²) Python 循环（回放窗口 58,509 对/68.9ms）；speed 逐轨迹扫窗口 36ms。
- **方案**：① 用固定网格（边长按车道宽）预筛候选对，角度/速度/可见性门禁顺序与阈值完全不变；② speed 用滑动窗口增量求和，不用每帧重扫；③ 用 shadow 诊断对比“被剪掉的对原本是否也过不了门禁”。
- **预期**：conflict 69→25、speed 36→12。
- **风险**：漏配对 → 高角度/高冲突场景必须逐事件对照。
- **完成定义**：固定素材冲突事件集合（含时间戳、参与者、TTC/PET）完全一致，误漏为 0。

### WP6 显示与 MJPEG（2–3 人日）

- **现状**：`show.render` 168.9ms（回放）/282.3ms（直播 519 轨迹），P3 独立进程但 P2 降下来后它会成为新上限。
- **方案**：① 1280 宽画布渲染后放大输出（绘制成本 ∝ 像素，画质需验收）；② 轨迹尾迹批量绘制；③ 显示刷新率与业务帧率解耦（显示可 5 FPS，业务仍逐帧）——**显示刷新率是产品口径，需确认**。
- **预期**：render ≤80ms，MJPEG ≤15ms。
- **完成定义**：8 组逐像素场景对照通过；肉眼看不出降质（以 1280 放大前后截图对照）。

### WP7 检测后处理（2–3 人日，P1 侧）

- **现状**：直播场景检测阶段 156.7ms，其中 `ascend.cpu_nms` 85.6ms（55%），检测数恒定 300。
- **方案**：① NMS 批量化/向量化（一次 IoU 矩阵替代逐类循环）；② 评估 NPU 侧 NMS 或 `max_det` 显式配置；③ 保证检测结果逐框一致（类别/分数/IoU 阈值不变）。
- **预期**：156.7 → 90ms，P1 上限 6.4 → 11 FPS，5 FPS 目标时不再卡 P1。
- **完成定义**：同帧检测框集合与分数逐元素一致。

### WP8 主机与部署（0.5–1 人日，只读优先）

- **内容**：governor/频率、并发管道数、cpuset/NUMA、`top -H` 线程分布；单核基准与 Mac 对照。仅在确认低频/争用后建议变更，并记录变更前后同素材 A/B。
- **判据**：单核基准明显低于硬件标称（2.6GHz）或存在多管道争用时才动作。

### WP9 长稳与发布（2 人日）

- 2 小时整管道长稳（内存、队列、journal、RSS、Kafka 延迟），完整包构建、清单、回退验证。

## 5. 排期（按 1 人并行能力估算，可按人力并行压缩）

| 波次 | 内容 | 出口门禁 | 预计 |
| --- | --- | --- | --- |
| M0（第 1 天） | WP0 + 现场 `.2` 基线 + WP1 部署 `.3` | 5 分钟 A/B：队列满 <10%，FPS 达 P2 上限（≥1.4） | 0.5–1 天 |
| M1（第 1 周） | WP2 facts 增量 + WP3 轨迹治理 | 单机 300 帧 P2 ≤ 400ms；现场 ≥2.5 FPS 且事实一致 | 5–6 天 |
| M2（第 2 周） | WP4 环形缓冲 + WP5 冲突/速度 | 单机 P2 ≤ 300ms；现场 ≥3.0 FPS 连续 5 分钟 | 7–10 天 |
| M3（第 3 周） | WP6 渲染 + WP7 NMS + WP8 | 现场 ≥4.0 FPS；P3/P1 不再是上限 | 4–6 天 |
| M4（验收） | WP9 长稳 + 完整包 + A/B 报告 | ≥3.0 FPS × 5 分钟（延伸 ≥5）、2 小时长稳、回退演练 | 2–3 天 |

合计约 **22–30 人日**。M0/M1 不依赖 WP4，可先拿到 2.5 FPS 级别的确定性收益。

## 6. 验证方法（五层，逐层放行）

### L0 静态与单元回归（每次提交）

```sh
python -m pytest platform/tests -q
python -m pytest test/test_kafka_active_trajectories.py test/test_utils_local.py \
  test/test_byte_tracker_core.py test/test_four_process_transport_optimization.py \
  test/test_position_gate_batch.py -q
python test/test_pipeline_inter_xqh.py          # 基线 55 PASS / 0 FAIL / 1 WARN（方向统计缺项）
cd console2 && npm test && npm run build
ruff check scripts && git diff --check
```

新回归必须包括：环形缓冲边界、增量 facts 与旧包兼容、网格预筛等价性、`authoritative point history regressed`（见根因文档 8.1）。

### L1 组件基准（每次结构性改动）

```sh
.venv-mps/bin/python scripts/benchmark_pipeline_transport.py \
  --baseline <旧版 PipelineEgress.py> --iterations 100 --output <dir>
.venv-mps/bin/python scripts/benchmark_association_gate.py --iterations 100 --output <dir>/gate.json
```

判据：字节数必须下降且可解释；函数级结果逐元素一致（费用矩阵、检测框、事件集合）。

### L2 单机逐帧剖析（每个工作包完成时）

```sh
VIDEO_SRC="test_videos/inter_xqh/DJI_20260403142902_0001_V小清河北路与水屯路路口.mp4" \
TOPIC_NAME=uav_statistics_1 CAMERA_ID=1 DETECTION_WEIGHT_PATH=weights/uav_best.pt \
.venv-mps/bin/python scripts/profile_pipeline_fps.py --video "$VIDEO_SRC" \
  --frames 300 --warmup 5 --telemetry-srt test_videos/inter_xqh/telemetry.srt \
  --out output/fps-profile-20261105/<wp>-after

.venv-mps/bin/python scripts/compare_fps_profile.py \
  output/fps-profile-20261105/<baseline>/stages.json \
  output/fps-profile-20261105/<wp>-after/stages.json \
  --target-ms 333 --json output/fps-profile-20261105/<wp>-ab.json
```

判据（脚本自动给出）：负载可比（轨迹/检测漂移 ≤15%）、P2 预算回归 ≤5%、达到 `--target-ms`。不可比时脚本直接判 `not_evaluated`，不得拿来宣称收益。

### L3 四进程真实拓扑（每个里程碑）

- 本机 native 四进程：自然 EOF、手动停止、强杀 egress、双 EOF、持久 ACK 保留、SHM 清理。
- 隔离 Kafka→PG→Console：空库、显式 `init-db`、双 head 门禁、鉴权 API/WS/媒体、归档行数与点序对账。
- 判据：无 `WORKER_FAILED`、无 `EGRESS_UNCONFIRMED_RETAINED`、`spool` 无残留、数据库行数与摘要一致。

### L4 现场 5 分钟同源 A/B（发布门禁）

同一路视频、同一时段负载（轨迹/检测数漂移 ≤15%）、同一其余配置，新旧包各跑 ≥5 分钟：

```sh
python scripts/accept_pipeline_fps.py diagnosis-after.json --minimum-fps 3 --minimum-duration 300
```

必须同时提交的证据：

| 证据 | 来源 | 判据 |
| --- | --- | --- |
| 完成帧率 | `EGRESS_STATUS` 的 `frames` 水位 | ≥3.0 FPS 且后半段 ≥90% 前半段 |
| 队列健康 | `queue_depth` 采样 | 满队列占比 <10% |
| P2 分项 | `STAGE_END stage=tracker.*` | 各阶段合计与目标表误差 ≤15% |
| P4 分项 | `egress.*`（WP1 新增） | 帧时间 ≤333ms（5 FPS 时 ≤200ms） |
| 每帧载荷 | `journal_bytes` 差分 / 帧数 | 下降且与 WP2 目标一致 |
| 业务事实 | 归档/DB/消息 | cars、轨迹数、速度、道路、冲突逐字段一致 |
| 主机 | `top -H`、governor、管道数 | 与 WP0 基线一致（无新增争用） |

**反刷分门禁**：A/B 两轮的检测数、轨迹数、分辨率、stride、模型、阈值必须相同；业务消息条数（`uav_statistics`、`uav_track_complete`、冲突 Topic）必须一致；任一不一致即判 A/B 无效。

## 7. 风险与回退

| 风险 | 缓解 |
| --- | --- |
| 增量 facts 破坏回放/归档兼容 | 版本位 + 旧包只读兼容 + 逐字段 diff；数据版本产生后不回退旧消费者 |
| 环形缓冲破坏增量发送/EOF 密封 | 先补 `authoritative point history regressed` 回归；保留逐点路径开关 |
| 轨迹回收过早导致拆轨迹 | 固定素材 ID/事件对照；只对“从未成熟”的 candidate 生效 |
| 渲染降分辨率影响取证 | 只降显示画布，不动证据帧（TCC/执法仍用原图） |
| 主机 governor 变更影响其他服务 | 只读检查优先；变更需运维窗口 + 变更前后同素材 A/B |
| 新包不可用 | 保留 `.2` 完整包与 `.3` 回退验证；`traffic rollback` 流程不变 |

## 8. 交付物与文档同步

- 代码：WP1–WP7 各项带开关的补丁；新增 `scripts/compare_fps_profile.py`（已提供）。
- 文档：本方案、`FPS_ROOT_CAUSE_20261105.md`（证据）、`ARCHITECTURE.md`（若进程内数据流变化）、`API_CONTRACTS.md`（若 facts 增量涉及消息契约）、`TASKS.md`（逐项勾选）、发布报告与 `DELIVERY-*.json`。
- 每次现场 A/B 归档：`diagnosis-*.json`、`accept` 输出、`STAGE_*` 原始行、`journal_bytes` 差分、`top -H` 快照。

## 9. 里程碑验收数字

| 里程碑 | 单机 P2（300 帧） | 现场 FPS（5 分钟） | 队列满占比 | 其他 |
| --- | ---: | ---: | ---: | --- |
| M0 | 不要求 | ≥1.4（回到 P2 上限） | <10% | 归档行数一致 |
| M1 | ≤400ms | ≥2.5 | <10% | facts 逐字段一致 |
| M2 | ≤300ms | **≥3.0** | <10% | 冲突事件集合一致 |
| M3 | ≤250ms | ≥4.0 | <10% | 渲染像素对照通过 |
| M4 | ≤250ms | ≥3.0 × 5 分钟、延伸 ≥5.0 | <10% | 2 小时长稳、回退演练 |

## 10. 需要业务/运维先拍板的四件事

1. 显示刷新率是否允许低于业务帧率（WP6，影响体感但不影响业务事实）。
2. `max_det`（疑似默认 300）是否显式提高——影响密集场景召回，但会增加 P1/P2/P4 负担。
3. lost/candidate 轨迹的回收口径（按源时间还是按处理帧），影响 ID 连续性与统计。
4. governor/CPU 亲和变更是否允许在生产窗口执行（WP8）。

以上四项未定之前，WP0/WP1/WP2/WP4/WP5 可以照常推进，不依赖这些决策。

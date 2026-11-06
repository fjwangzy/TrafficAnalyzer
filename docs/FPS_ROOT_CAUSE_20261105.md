> 2026-11-05 审计更正：本文历史现场“完成帧率”由 tracker/show 输入水位推导，只能作为归档接收进度；未证明业务提交或数据库入库。阶段中位数之和只作预算估算。“部署 .3 即解除现场瓶颈”仍待验证；最新复测与限制见 [FPS_REGRESSION_AUDIT_20261105.md](FPS_REGRESSION_AUDIT_20261105.md)。

# 2026-11-05 “检测器输出 FPS 只有 2”根因排查与方案分析

本轮只做诊断与本机受控测量：未改业务算法、模型、分辨率/stride、阈值或质量门禁，未发布新包，未在 UOS/Ascend 实机复验。现场数字取自仓库既有证据（`output/fps-diagnosis-20261104/metrics.json`，构建 2026.11.04.1，`pipe-8f75642b`）；本机数字为今日实测（Mac/MPS、真实 4K 视频 + SRT 遥测、Kafka 关闭）。本文所有推断都标注了“实测/推算”。

## 1. 三条确定结论

1. 页面“检测器输出 · YOLO11 → 位姿感知 ByteTrack”旁的 FPS **不是 YOLO 推理帧率**，而是 P2（tracker/在线分析）进程的输出帧率：`services/PipelineEgress.py` 的 `SnapshotScheduler.apply` 用 2 秒滑窗写 `frame.pipeline_fps`，`nodes/KafkaProducerNode.py:1086` 优先读它作为 `stats.fps`，`console2/src/App.jsx:918` 直接显示。现场 Ascend OM 推理 8.1ms、检测阶段整体 85.4ms，**推理不是瓶颈**。
2. **FPS ≈ 1000 /（P2 串行阶段之和）**，但 2026-11-04 18:30 的直播诊断出现了第二种限速：**P4（egress/归档/Kafka）成为瓶颈，P2 在交接处等 ACK**。该次 `queue_depth` 长期 32/32（队列满）、`tracker.egress_delta` 中位 2023.7ms（其中真正的冻结+序列化只有约 100ms）、P1 `queue.detect.put` 3199.6ms，完成帧率 **0.70–0.74 FPS** 并随轨迹数（300→519）缓慢下降。同一份诊断里更早的回放窗口（243→280 轨迹）仍是 P2 计算受限：串行 637ms、实测 1.38–1.49 FPS、队列 0–9。**所以现场不是“一个瓶颈”，而是两个：轨迹少时卡 P2 串行链，轨迹多/负载重时卡 P4 吞吐。**
3. P2 受限时，624ms 里没有单一热点，而是六个中等阶段摊开（交接 189、关联 144、冲突 83、图像运动 63、状态 61、速度 38）。因此**只修最大的一项（交接 189ms）也只有 1.6→2.3 FPS，修任一 40–80ms 的阶段只值 0.2–0.3 FPS**；要达到 3 FPS 必须降到 ≤333ms，5 FPS 必须 ≤200ms，只有把“逐轨迹/逐点 Python 重建”改成批量或增量才可能。

## 2. 三份实测基线（不可混用）

| 基线 | 拓扑/版本 | 负载 | P2 串行合计 | 页面/完成帧率 |
| --- | --- | --- | ---: | ---: |
| A 现场 UOS/310P3 | 四进程，.1，路网关 | 297 轨迹 / 197 检测 | 624ms（中位和） | **1.506 FPS**（272 帧/180.6s） |
| B 本机 11-03 | 三进程，.1（优化前源码），路网开 | 299 轨迹 / 150 检测 | 344ms（中位和） | 约 **2.5 FPS**（末段 12 个 5s 采样中位） |
| C 本机 11-05（今日） | 四进程，当前源码，路网关 | 147–252 轨迹 / 100–148 检测 | 121ms（中位和） | **7.67 FPS**（213→1593 帧/180s，窗口 7.0–8.2） |

C 相对 B 快了约 2.8 倍，但**不能全部归功于优化**：C 还关了路网（B 有 `tracker.map_matching` 44ms 与车道节点）、负载低 30–40%、且 B 是三进程（P2 还要做 `kafka_archive` 30.9ms 与 `render_snapshot` 23.7ms）。要拆分归因，必须在同一机器上对同一版本做开关对照（`PIPELINE_TRANSPORT_VIEWS_OPTIMIZED` / `BATCH_POSITION_GATE`），本轮没做。**同理，A 与 C 的 5.1 倍不能直接当作“现场机器慢 5 倍”**——这是本轮排查中最容易得出错误结论的地方。

同一操作归一化后再比（关联的距离矩阵按 轨迹×检测 对数折算）：

| 观测 | 现场 A | 本机 B | 本机 C |
| --- | ---: | ---: | ---: |
| 关联每候选对 | 2.46µs（58,509 对） | 2.09µs（44,850 对） | 约 1.0–1.5µs（推算，负载逐帧在 147–252 轨迹/100–148 检测间波动） |
| decode | 28.3ms | 30.0ms | 14.4ms |
| 检测阶段 | 85.4ms | 103.7ms | 66.5ms |

结论：**单次操作层面现场只比本机 B 慢 1.2 倍左右**（与 Kunpeng 920@2.6GHz 对 M 系单核的差距一致），而 decode/检测甚至更快。现场 FPS 低主要来自“版本差异 + 负载更高 + 每帧工作总量本来就大”，不是现场机器异常慢，也不是某个函数在现场退化。但 `info/speed/conflict` 三项现场是本机 B 的 2.7–3.0 倍，超出单核算力差，最可能的原因是**现场是巡航素材、成熟且可判定的轨迹更多**（本机 B 是悬停素材，速度接近 0、冲突对大量被速度门禁提前过滤）。这一点必须用同素材对照确认，本文不下结论。

### 2.1 现场最新诊断（用户附件 `/Volumes/HIKSEMI/drone/diagnosis.json`）

该附件含三条流水线。按日志里的阶段名可以判定各自跑的代码：

| 流水线 | 时间（UTC） | 指纹 | 代码版本 |
| --- | --- | --- | --- |
| `pipe-8f75642b` | 03:58–04:02 | 无 `egress.freeze_previews`（.2 起才有）、无 `append_points`/`restore_tails`（.3 才有） | **.1** |
| `pipe-399dd5fe` | 10:30–10:33 | 有 `freeze_previews`、无 `append_points`/`restore_tails` | **.2** |
| 导出头 `version` | — | — | `2026.11.04.2` |

**结论：这份诊断里没有 .3 的运行样本。** 判据是 `.3` 独有的 `egress.append_points`（`dist/traffic-analyzer-native-2026.11.04.3/app/services/PipelineEgress.py:1057`）与 `egress.restore_tails`（同文件 974）在两条日志里都不存在，而 `.2` 起才有的 `egress.freeze_previews`（`.2` 同文件 228）在 `pipe-399dd5fe` 里存在。现场核对只需一条命令：

```sh
grep -c "egress.append_points\|egress.restore_tails" <现场>/app/services/PipelineEgress.py
```

`0` 就是 .2 及更早；`.3` 应为 2 处以上。

两次运行的负载与瓶颈完全不同：

| 指标 | `pipe-8f75642b`（.1，回放/稀疏） | `pipe-399dd5fe`（.2，直播/拥堵） |
| --- | ---: | ---: |
| 完成帧率 | 1.38–1.49 FPS | **0.70–0.74 FPS**（逐窗下降） |
| 轨迹数 / 检测数 | 243–280 / 138–158 | **300→519 / 300（检测数恒定在 300，疑似 ultralytics 默认 `max_det=300` 上限）** |
| egress 队列深度 | 0–9 | **20→32（长期满）** |
| `tracker.egress_delta` | 186.3ms | **2023.7ms（其中冻结+序列化约 100ms）** |
| `queue.detect.put` | 520.2ms | **3199.6ms** |
| `tracker.association` | 167.0ms | 323.4ms（486×300≈14.6 万对，2.2µs/对） |
| `tracker.info` / `image_motion` | 57.7 / 74.6ms | 105.5 / 75.0ms |
| `tracker.conflict` / `speed` | 68.9 / 36.0ms | 0.7 / 1.0ms（拥堵低速被门禁提前过滤，非关闭） |
| `show.render`（P3） | 168.9ms | 282.3ms |
| 检测阶段（含 NMS） | 75.6ms（NMS 30.6） | 156.7ms（**NMS 85.6，占 55%**） |
| 每帧归档字节 / 包数 | 约 255KB / 8.2 包 | 约 472KB / 10.2 包 |

`pipe-399dd5fe` 的 P2 纯计算（把 2023.7ms 的等待剔除）约 640ms，与上一节的 624ms 同量级；也就是说 **P2 本身没有退化，是 P4 接不住 472KB/帧 × 10 包/帧**，把 P2 压在 ACK 前面。这一条正好解释了“改了 P2 却看不到 FPS 变化”。

### 2.2 P4 为什么在 .2 接不住

`.2` 的接收端是逐点写入：`PipelineEgress.DeltaTracks.append` 对每个点、每个字段各调一次 `DiskArray.extend`（`dist/traffic-analyzer-native-2026.11.04.2/app/services/PipelineEgress.py:649-666`，`TrajectorySpoolIndex.py:41-47` 每字段一条 SQLite `INSERT`）。每帧约 300 个新增轨迹点 × 7 个点字段 ≈ **2,100 条 INSERT/帧**，再加每帧 `commit_frame` 里的 `restore_fact_tails` 全量重建尾巴、facts 快照 pickle、以及 500 条轨迹的 stats JSON。`.3` 改的正是这里：`append_batch` + `DiskArray.TAIL_POINTS=128` 尾部缓存 + `prepare/accept` 一次编码（`.3` 同文件 22-63 行），并给 `restore_tails`/`append_points` 加了分项计时。

因此当前建议的第一步不是继续改业务算法，而是 **确认并真正部署 .3，再在同一路视频上做 .2→.3 的五分钟 A/B**。按 `.3` 组件基准（追加/接收路径约 79%–83% 降幅），P4 若从“接不住”变成“接得住”，`pipe-399dd5fe` 这类直播场景应回到 P2 计算上限（约 0.64s/帧 ≈ 1.5 FPS），之后再谈用第 7 节的批量改造把它推到 3 FPS 以上。

## 3. 剩下的 624ms 到底花在哪

按 .1 实测中位值（`output/fps-diagnosis-20261104/metrics.json`）：

| 阶段 | ms | 占比 | 内容 |
| --- | ---: | ---: | --- |
| `tracker.egress_delta` | 188.8 | 30% | 两次 `freeze_frame` 全量冻结 + pickle（.1 路径） |
| `tracker.association` | 143.9 | 23% | ByteTrack 预测/距离/门控/指派 + 逐轨迹图像历史重建 |
| `tracker.conflict` | 82.6 | 13% | O(轨迹²) 候选对 Python 循环（58,509 对） |
| `tracker.image_motion` | 62.9 | 10% | 灰度 + 角点 + LK 光流（原生） |
| `tracker.info` | 60.6 | 10% | 逐轨迹状态/类别投票/历史维护 |
| `tracker.speed` | 38.4 | 6% | 逐轨迹历史窗口测速 |
| `tracker.world_projection` | 32.6 | 5% | 逐轨迹逐点 ENU/GCJ-02 重建 |
| 其余 9 个节点合计 | 13.9 | 2% | 方向/轨迹/换道/路网/执法/统计等 |

.1 的交接路径已在 .3 候选中重写：`dist/traffic-analyzer-native-2026.11.04.1/app/services/PipelineEgress.py:386-390` 是 `freeze_frame(frame)` + `freeze_frame(frame,0)` 两次全量冻结；`.3` 同文件 194/515 行改为 `freeze_egress_views` 一次冻结、显示/归档分离，并带 `egress.freeze_metadata/freeze_tracks/freeze_previews` 分项计时。

**推算**（把 C 的每单位成本套到 A 的负载）：关联 58.5k×1.1µs≈64ms、交接≈20ms，其余阶段按同负载线性放大 → P2 约 375ms ≈ **2.7 FPS**。这就是“两个主要优化全部落地、但没有再做新优化”的上限，和文档里“1.7–2.0 目标已过、3 FPS 仍未验收”的记录吻合。若现场仍看到 2 FPS，第一件事是确认跑的是不是 .3、以及是否真的落到了当前源码（下一节）。

## 4. 为什么前几轮优化“做了很久但没效果”

1. **优化的是占比小的子路径。** 交接 42→11.5ms、门控 5.4→2.0ms 是本机微基准；相对 624ms 是 5–8%，端到端不到 0.2 FPS。文档本身也写了“不等于整个关联耗时已下降”。
2. **在没有瓶颈的机器上量收益，没在现场闭环。** 收益全在 Mac/MPS 或 ARM64 用户态工具镜像取得；现场 5 分钟同源 A/B 与 `scripts/accept_pipeline_fps.py --minimum-fps 3 --minimum-duration 300` 从未在现场跑通，所以“有效”无法证伪也无法证实。
3. **现场跑的仍是旧路径。** 诊断用的 .1 里没有 `freeze_egress_views`，最大单项（189ms）根本没被修；如果现场现在还是 .1，那么“优化很久”对现场数字的贡献接近 0。
4. **没有处理占据 60% 的六阶段结构成本。** 关联/冲突/状态/速度/世界投影都是“每条轨迹每帧重建全部视图”，与算法参数无关，只和轨迹数×历史长度有关；不做批量/增量，任何参数调整都在噪声内。
5. **瓶颈已经换人，优化的还是旧的。** 直播拥堵场景（300 检测/519 轨迹）现在是 P4 接不住 472KB×10 包/帧，P2 在 ACK 上等 2 秒；这时候再去优化 P2 的关联或门控，对 FPS 基本没有影响。P4 的批量接收（`append_batch`+128 点缓存）恰好只在 .3 里，而现场日志显示跑的是 .2（见 2.1），所以“优化很久没效果”有一半原因是**优化没有在跑**。

## 5. 结构成本：每帧十万次小操作

cProfile（40 帧，仅 tracker 阶段；cProfile 本身约 2.7 倍放大，用来看比例和次数而不是绝对时间）与真实四进程运行时的 macOS `sample`（tracker 进程 8 秒）：

| 观测 | 每帧 | 说明 |
| --- | ---: | --- |
| Python 函数调用 | 108,490 | 4,339,600/40 帧 |
| `STrack.tlwh` 属性 | 1,486 | 每次 `mean[:4].copy()`，产生 numpy 临时对象 |
| `STrack.tlbr` 属性 | 1,194 | 内部再调 `tlwh`，再复制一次 |
| `round()` | 5,704 | 逐框/逐点取整，可整批 |
| `list.copy()` | 5,231 | 逐轨迹把 30 点尾迹整体复制，重建全部视图 |
| `apply_camera_warp` | 245 | 每条轨迹一次 3×3 矩阵乘，可合并为一次 matmul |
| `_warp_display_points` | 142 | 每条轨迹单独造齐次矩阵 |
| shapely `Point` | 285 | 逐点构造几何对象 |
| `gc_collect_main` | 约占采样 7–9% | 逐帧创建大量 dict/list/Track 的回收成本 |
| 灰度 + LK 光流 | 约占采样 14% | 原生部分，不是主要头 |

根因模式一句话：**每帧只有 1 个新点，却把每条轨迹的全部派生视图重算一遍。** 具体在三处：

- `GroundTrajectoryTrackerNode._build_image_trajectories`：逐轨迹 warp + 新建含 4 键 dict + 30 点列表复制；
- `PostTrackingWorldProjectionNode._enrich_trajectories`：逐轨迹 30 点 `point.copy()`、`dict(point)` 血缘复制，并对全部 30 点重算 ENU→GCJ-02（约 7,200 次三角/帧）；
- `EgressClient.frame`：把上述结构整体 pickle（.1 还要冻两次）。

## 6. 现场先做的 10 分钟只读体检（改代码前）

1. `pgrep -af main_optimized.py | wc -l`：四条 worker 是**一条**流水线。若同时在跑多路视频，单条 FPS 是被摊薄的，容量口径要先定。
2. `top -H -p <tracker_pid>`：确认是 1 个线程 ~100%（预期），而不是多 worker 互抢或被 cgroup 限到 1 核。
3. `cat /sys/devices/system/cpu/cpu0/cpufreq/{scaling_governor,scaling_cur_freq,cpuinfo_max_freq}`。若 governor 是 `powersave/ondemand` 或长期低频，单线程突发负载会被压低；处理方式见 `docs/KUNPENG920_CPU_TUNING_RUNBOOK_20261020.md`（该文档已有 96 核/4 NUMA/2.6GHz 的现场事实）。
4. 确认现场版本：`app/services/PipelineEgress.py` 里是否存在 `freeze_egress_views`。没有就是 .1，先谈部署而不是继续优化。
5. 导出新的 `diagnosis.json`，跑一次 `python scripts/accept_pipeline_fps.py <file> --minimum-fps 3 --minimum-duration 300`，同时记录 `EGRESS_STATUS` 的 `frames` 水位与轨迹/检测数，才能和本机 C 基线对齐。

## 7. 方案（按收益/成本排序，均不改业务口径）

| 优先级 | 改动 | 现场收益估算 | 边界/风险 |
| --- | --- | ---: | --- |
| P0 | **确认并部署 .3**（`append_batch` + 128 点尾部缓存），先在直播拥堵场景做 .2→.3 的 5 分钟同源 A/B | 解除 P4 队列饱和（0.70 → 约 1.5 FPS） | 接收端行为变化，需保留 `.2` 回退包与归档逐条对账 |
| P0 | **facts 快照增量**：每帧只发新增点与变更元数据，不再发 500 条轨迹的全量快照（当前 472KB/帧） | 交接与 P4 再降 50% 以上 | 需同步改接收端 `restore_fact_tails` 与回放兼容；必须逐字段对照 |
| P0 | 轨迹历史改**定长 numpy 环形缓冲**（`(N,K,4)` 存 x/y/t/frame 与 ENU），append O(1)，视图用切片返回 | 状态/速度/世界投影 132 → 40ms，同时消灭 5,231 次/帧 list 复制 | 需覆盖 `trajectory_history_start`、增量发送、EOF 密封 |
| P1 | **批量几何**：每帧一次缓存 `tlbr`（N×4 数组）；warp 合并为一次 matmul；ENU→GCJ-02 只算新增点并缓存尾部 | 关联 144 → 60–70ms | 浮点结果需逐元素对照（仓库已有门控逐元素对照范式） |
| P1 | **冲突候选空间网格预筛**：门禁、角度、速度阈值完全不变，只减少进入判定的对数 | 冲突 83 → 20–30ms | 必须证明被剪掉的对原本也过不了门禁，并保留 shadow 对比 |
| P2 | **显示渲染降分辨率**：1280 绘制后放大给 MJPEG，或批量绘制；不要 4K 逐目标绘制 | 渲染 188 → 60–80ms | P3 独立进程，只有 P2 降下来它才会成为新上限 |
| P2 | **P2 内部分工**：把冲突/序列化这类可并行阶段放到第二个常驻进程按帧序合并 | 边际 20–30% | 引入 IPC 与顺序约束，确定性不如前四项 |
| — | `frame_stride` 3→5/6 只减少“每秒处理的源帧”，不降低单帧成本，是“实时跟得上 vs 处理更多帧”的业务取舍，不作为性能修复宣称 | — | 需业务确认，本文不默认修改 |

前四项合计（相对 .1 的 624ms）：624 − 169（交接）− 80（关联）− 92（状态/速度/世界投影）− 55（冲突）≈ **228ms ≈ 4.4 FPS**；再叠加渲染优化后 P3 也不再卡住。反之只做交接一项 ≈ 2.7 FPS。

## 8. 如何验证（可复跑）

本机（改动前后各一次，同素材同参数）：

```sh
VIDEO_SRC="test_videos/inter_xqh/DJI_20260403142902_0001_V小清河北路与水屯路路口.mp4" \
TOPIC_NAME=uav_statistics_1 CAMERA_ID=1 DETECTION_WEIGHT_PATH=weights/uav_best.pt \
.venv-mps/bin/python scripts/profile_pipeline_fps.py \
  --video "$VIDEO_SRC" --frames 300 --warmup 5 \
  --telemetry-srt test_videos/inter_xqh/telemetry.srt \
  --render --egress --out output/fps-profile-20261105/<tag>
```

该脚本按 `main_optimized.py` 的节点顺序逐帧计时（可用 `--cprofile` 出函数级归因），输出 `stages.json`（含逐帧 `stage_ms`、检测/轨迹数）与 `cprofile.txt`。本轮的原始结果在 `output/fps-profile-20261105/`。

`--egress` 只用于量交接成本：>128 帧会触发归档端单调性守卫（见第 8.1 节），长跑请分段或去掉该开关。
现场：完整四进程跑 ≥5 分钟，导出诊断后用既有门禁判分，并同时核对业务事实（轨迹数/速度/冲突/道路标签）逐字段一致、显示逐像素一致、EOF 与持久 ACK 不变、归档点序不变。`test/test_pipeline_inter_xqh.py` 当前 55 PASS / 0 FAIL / 1 WARN（方向统计缺项），不能当性能通过。

## 8.1 附带发现：归档端在特定条件下会硬失败（需单独确认）

用 `--egress --debug-egress` 跑真实素材时，150 帧内必现：

```
POINT_ROWS_FAILURE track=3 base=0 lengths={每个点数组都=51} start=101
ValueError: authoritative point history regressed   (services/PipelineEgress.py:437)
```

即同一 `track_id` 已经持久发送到第 101 点，随后被以 51 点、`trajectory_history_start=0` 重新提交，
归档端按设计拒绝继续（`point_rows` 的单调性守卫），tracker worker 直接失败。**是“轨迹丢失后重新激活、
历史被重建但 `trajectory_history_start` 未同步”，还是 `bounded_history` 的 128 点淘汰与
`completed_tracks` 行进错位，本轮没有定论**；今天同一份代码的四进程真实运行跑了 1,593 帧未复现，
所以不能据此宣称生产必现。但它和 FPS 目标直接相关：128 点淘汰是按“处理帧”算的，FPS 越高越容易触发，
因此**在提升 FPS 之前应先给这条边界补一个回归测试**（可用上面的命令复现），否则提速可能以崩溃为代价。

## 9. 本轮边界

- 未在 UOS/310P3 实机复现，未做 governor/频率/并发管道核查；第 6 节仍是待验证项。
- 未修改任何业务节点，第 7 节未实施，因此**不宣称问题已修复**；第 8.1 节的失败也未修复。
- A/B/C 三份基线是不同版本与不同负载，只能做归一化比较；本文已把“现场慢 5 倍”这个错误结论显式排除。
- 今日 C 基线 7.67 FPS 说明“当前源码必然只有 2 FPS”不成立；现场 2 FPS 需要用当前构建 + 当前素材重新测量后才能定性是版本、负载还是主机因素。

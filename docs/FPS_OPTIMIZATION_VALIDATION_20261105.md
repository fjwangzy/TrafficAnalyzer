> 2026-11-05 审计更正：§3 为单进程节点计时；假 ACK 排除了真实 P4、journal 刷盘与 Kafka。表中 P2 为旧脚本的各阶段中位数之和，不能称为实测端到端 FPS。新对照使用逐帧 P2 总耗时；旧现场 EGRESS_STATUS 只有输入水位，也不能作为业务提交或入库完成证明。详见 [FPS_REGRESSION_AUDIT_20261105.md](FPS_REGRESSION_AUDIT_20261105.md)。

# 2026-11-05 FPS 优化实施与验证（WP1/WP2/WP4a/WP4b/WP5）

本页记录本轮实际落地的改动与验证证据。方案见 [FPS_OPTIMIZATION_PLAN_20261105.md](FPS_OPTIMIZATION_PLAN_20261105.md)，根因证据见 [FPS_ROOT_CAUSE_20261105.md](FPS_ROOT_CAUSE_20261105.md)。未在 UOS/Ascend310P3 实机复验，现场 5 分钟 A/B 仍是发布门禁；本轮不宣称生产 3 FPS 已达成。

## 1. 落地清单

| 工作包 | 文件 | 开关（默认） | 做法 | 等价性策略 |
| --- | --- | --- | --- | --- |
| WP1 P4 可观测性 | `services/PipelineEgress.py` | 无 | 新增 `egress.commit_frame`、`egress.geojson`、`egress.producer` 分项计时；`egress.enqueue` 增记 `kind` | 纯日志 |
| WP2 接收端尾迹冻结 | `services/TrajectorySpoolIndex.py`、`services/PipelineEgress.py` | 无（行为等价） | 盘上尾部缓存改为**入库时冻结一次**（`plain` 后的 tuple），每帧切片只做浅拷贝，不再 `deepcopy`+`plain` 两遍；`restore_fact_tails` 对已冻结 tuple 跳过 `plain` | 新增 `test_cached_tail_matches_plain_contract`，逐字段等于 `plain()` 旧契约 |
| WP4a 图像轨迹批量 warp | `nodes/GroundTrajectoryTrackerNode.py` | `TRACKER_BATCH_WARP=1` | 每帧把所有轨迹的显示尾迹拼成 `(M,3)` 一次 matmul，按偏移拆回；矩阵每帧只校验一次；去掉逐点 `.copy()`；逐点 `round` 向量化并对 1-ulp 歧义值回退内建 `round` | 140 帧 A/B（无 warp/2×3/NaN/奇异/中途换 warp/丢失重激活）四组列表逐元素相等 |
| WP4b 世界投影增量 | `nodes/PostTrackingWorldProjectionNode.py` | `WORLD_PROJECTION_INCREMENTAL=1` | 按 association 缓存 GCJ 尾部，只转换新点；锚点变化/None 使缓存失效并整尾重算；ENU/lineage 只在出口浅拷贝 | 170 帧真实 tracker 场景，两分支输出与改动前逐字节 JSON 相同 |
| WP5 冲突网格预筛 | `nodes/ConflictDetectionNode.py` | `CONFLICT_GRID_PREFILTER=1`、`CONFLICT_GRID_MIN_PAIRS=20000` | ENU 均匀网格 3×3 邻格枚举近邻对；被跳过的远距对按旧逐对语义批量补记诊断；逐对门禁抽成唯一 `_evaluate_pair()` 两路径共用 | 120 随机场景×2 帧 + 300 场景差分逐字段一致；见 §5 的唯一已知偏差 |

状态更正：WP2 wire 增量 `frame_delta` 已实现，见 §2.3；WP3 轨迹数治理、WP6 渲染、WP7 NMS 未完成。

## 2. 组件级实测

### 2.1 接收端（WP1+WP2，`scripts/benchmark_egress_receiver.py`）

三份实现跑同一批合成包（`.1`/`.2`/当前源码），脚本断言三份的 `tail_sha256` 相同：

| 场景 | `.2` append+restore | 仅 WP1（.3 批量化） | WP1+WP2（本轮） | `.2`→本轮 合计降幅 |
| --- | ---: | ---: | ---: | ---: |
| 280 轨迹×160 点 | 34.7 + 264.7ms | 17.6 + 39.6ms | 17.6 + **4.4ms** | 80.9% → **94.2%** |
| 486 轨迹×160 点 | 64.9 + 459.1ms | 34.9 + 69.1ms | 35.4 + **5.8ms** | 80.2% → **94.7%** |
| 486 轨迹×5000 点 | 1.8 + 351.6ms | 2.6 + 71.7ms | 2.6 + **6.1ms** | 79.0% → **98.0%** |

- 每帧 SQL SELECT：`.2` 为 1,960 / 3,402 / 3,402，本轮全部为 **0**。
- `tail_sha256` 三版本一致，脚本 `passed=true`（门禁 ≥70%，实得 94–98%）。
- 结论：`.2` 的 `restore` 是明显的回归（`.1` 为 16–30ms，`.2` 涨到 265–459ms），`.3` 修回了大部分，本轮把剩下的 `deepcopy+plain` 双遍也去掉，降到 4–6ms。

### 2.2 节点级（同进程交替测量，median）

| 阶段 | 旧 | 新 | 加速 | 规模 |
| --- | ---: | ---: | ---: | --- |
| 图像轨迹（WP4a） | 9.42ms | 2.81ms | **3.35×** | 300 轨迹×30 点，9 次交替中位 |
| 世界投影/GCJ-02（WP4b） | 25.8ms | 3.9ms | **6.64×** | 300 轨迹×30 ENU 点，7 次中位；场景内转换次数 9,606→813 |
| 冲突候选（WP5） | 72.5ms | 29.1ms | **2.49×** | 300 轨迹 / 22,500 对，7 次中位（重复 2.5–2.9×） |

### 2.3 WP2 wire 增量：`frame_delta`

**设计与开关**：`EgressClient.frame` 不再每帧 pickle 全部轨迹元数据，而是发 `frame_delta`：

| 部分 | 内容 | 频率 |
| --- | --- | --- |
| `meta` | 帧级字段（去掉 `render_snapshot`，它是发给图像属主的显示视图，egress 侧从不读取） | 每帧 |
| `present` / `mature` | 在场轨迹键与成熟子集 | 每帧 |
| `dynamic` | 逐帧变化字段（点计数、时间戳、速度、朝向、bbox、ENU 位置、速度矢量等） | 每帧 |
| `static` | 其余轨迹元数据（类别/模型/道路/匹配/质量等） | **仅新增或值变化时** |

接收端 `apply_facts_delta()` 用静态块缓存重建与全量快照完全相同的 `RenderTrackSnapshot`；`PIPELINE_FACTS_DELTA=0` 回退整包 `frame`，`PacketJournal` 同时接受两种 kind。

**字段划分来自实测**（真实走廊 39 帧 × ~613 轨迹的逐字段变化率）：`avg_speed_kmh` 52%、`current_observation_timestamp_sec` 34%、`timestamp_last`/`current_bbox_xyxy`/`current_position_enu_m`/`trajectory_point_count` 29%、`speed_kmh`/`heading_angle` 28%、`velocity_ms` 24%；其余（类别/模型/道路/匹配/质量/`max_speed_kmh`）≤3%。第一版把速度/朝向留在静态块，导致约 25% 轨迹每帧重发整块静态元数据；按上表调整后静态块降到约 1KB/帧。

**等价性**：新增 `test/test_egress_facts_delta.py`（5 项：逐帧逐字段重建一致、静态块仅在变化时重发、离场轨迹剪枝与未知轨迹报错、字段划分覆盖完整、稳态体积下降）；`test/test_four_process_transport_optimization.py` 的 3 项归档契约测试改为先重建 delta 再与旧契约逐字段比较（唯一差异是 `render_snapshot` 为 `None`，已显式断言）。

**实测体积**（真实 4K 走廊、live + 关路网 + 四进程，同一台机、同一路源，用 `scripts/measure_egress_payload.py` 直接读 journal）：

| 指标 | 全量快照管道 | `frame_delta` 管道 | 变化 |
| --- | ---: | ---: | ---: |
| facts 包中位 | 276,127 B | **109,404 B** | **−60%** |
| facts 包 p90 | 442,072 B | **191,750 B** | −57% |
| 每帧总字节（含 points/close/discard/render） | 321,078 B | **155,390 B** | **−52%** |
| 轨迹数 | 587 | 656（更高） | 增量侧负载更重仍更省 |

两点仍需注意：`frame_meta` 里的 `association_trajectories`（约 20KB/帧）P4 并未读取，但为保持既有归档事实契约暂未删除；`discard` 包约 9 个/帧、每个都触发一次 journal fsync，批量合并是下一项低风险收益。

## 3. 单进程节点 A/B（同一素材、同一负载、背靠背）

命令（OFF/ON 各一次，300 帧，ROAD_FEATURES_ENABLED=false）：

```sh
# OFF
TRACKER_BATCH_WARP=0 WORLD_PROJECTION_INCREMENTAL=false CONFLICT_GRID_PREFILTER=false \
.venv-mps/bin/python scripts/profile_pipeline_fps.py --video ... --frames 300 --warmup 5 \
  --telemetry-srt test_videos/inter_xqh/telemetry.srt --out output/fps-opt-20261105/harness-switch-off
# ON：同命令，去掉三个开关
.venv-mps/bin/python scripts/compare_fps_profile.py \
  output/fps-opt-20261105/harness-switch-off/stages.json \
  output/fps-opt-20261105/harness-switch-on/stages.json \
  --target-ms 333 --json output/fps-opt-20261105/ab-switch.json
```

| 指标 | OFF | ON | 变化 |
| --- | ---: | ---: | ---: |
| P2 串行预算（tracker 阶段和） | 104.9ms | 78.2ms | **−25.5%** |
| 对应上限 | 9.53 FPS | 12.79 FPS | — |
| 负载（轨迹/检测） | 234 / 161 | 234 / 161 | 可比 |
| association | 28.8 | 19.9 | −30.9% |
| world_projection | 6.7 | 2.7 | −59.7% |
| conflict | 15.7 | 11.2 | −28.7% |
| 未改动阶段（image_motion/info/speed/freeze） | — | — | 合计约 −9ms，属环境漂移 |

判分：`verdict=passed`（负载可比、无 >5% 回归、达到目标预算）。**可归因收益是三个被改阶段合计 −17.2ms/帧**；其余 −9ms 来自机器负载波动，不记在本轮改动上。微基准（同进程交替）才是各阶段加速比的权威数字。

## 4. 四进程真实拓扑

`main_optimized.py` 四进程、真实 4K+SRT、Kafka 关闭、220 秒：

| 指标 | 改动前（同日较早） | 本轮 | 说明 |
| --- | ---: | ---: | --- |
| `egress.restore_tails` | 77.8ms | **11.5ms** | 与组件基准方向一致；本次样本 7 个 |
| `egress.commit_frame` | 未测量 | 14.2ms | 本轮新增加的分项 |
| `egress.geojson` | 未测量 | 0.3ms | 新增分项 |
| 采样到的 `frame` 包 | — | 188KB（n=2） | 说明 wire 增量仍有空间（§7） |
| 采样到的 `points_batch` | — | 25KB（n=5） | 同上 |
| 完成帧率 | 7.67 FPS | 5.11 FPS | **不可比**：本次运行期间宿主机 load≈6.0（并行 VM/渲染进程），所有未改动阶段同样慢 1.5× |

因此四进程这一轮只作为**健康检查**：无 `WORKER_FAILED`、无 `EGRESS_UNCONFIRMED_RETAINED`、归档持续前进、帧率平稳（5.32/5.09/4.99/5.00/5.04/5.11，无衰减）。绝对 FPS 的对比必须放到现场 5 分钟同源 A/B。

## 5. 已知边界与未证明项

1. **WP5 唯一的诊断偏差**：画面框嵌套但 ENU 距离 > `max_pair_distance_m`（遮挡/超车导致接触点相距远）时，逐对路径计 `nested_cross_class_detection`，网格路径计 `distance_filtered`。两条路径都不会为该对生成事件，业务事实不变；需要逐字节诊断一致时设 `CONFLICT_GRID_PREFILTER=0`。已用 `test_far_pair_with_overlapping_bboxes_moves_one_diagnostic_counter_only` 固化该边界。
2. **小场景阈值**：候选对 < `CONFLICT_GRID_MIN_PAIRS`(默认 20000) 时不建网格（本机悬停素材约 1.3 万对，网格只会增加开销）。生产 486 轨迹×300 检测约 14.6 万对，走网格。
3. **WP4a 取整**：向量化 `round` 对 1-ulp 歧义值回退内建 `round`，622k 对抗样本与 140 帧真实序列逐元素一致；没有形式化证明覆盖所有 double。
4. **WP4b 共享不可变元素**：出口列表浅拷贝，元素（tuple/dict）与内部历史共享；现有消费方只读（grep 验证），若未来有就地修改会污染后续帧。
5. **既有潜在缺陷（非本轮引入）**：`enable_same_time_cpa=true` 且发出 `same_time_cpa` 事件时，`prediction` 缺少 `min_same_time_distance_m`，在 `ConflictDetectionNode` 取证阶段会 KeyError；生产默认 false，本轮未改。
6. **既有的归档单调性守卫问题**（见根因文档 8.1）仍未修复，本轮未触碰；提速后淘汰/重激活更频繁，需在 WP3/WP4 前补回归。
7. 未在 UOS/Ascend310P3 上运行；未做 2 小时长稳；现场 P95/P99 未测。

## 6. 回归证据

| 检查 | 结果 |
| --- | --- |
| `pytest platform/tests -q` | 439 passed, 11 skipped, 10 subtests |
| `pytest test/` 文档核心子集（kafka/active_trajectories、utils、bytetracker、main EOF、telemetry、frame stride） | 52 passed |
| `test/test_road9_compose_runtime.py` | 6 passed |
| conflict 网格 + TCC 诊断 | 151 passed |
| tracker 批量 warp + 图像跟踪 | 34 passed |
| 投影增量 + 世界投影 | 18 passed |
| egress 尾迹 + 管道/四进程/三进程传输 | 44 passed |
| `python test/test_pipeline_inter_xqh.py` | **55 PASS / 0 FAIL / 1 WARN**（与改动前基线相同，告警为既有的 direction_stats 空） |
| `ruff check`（本轮所有改动文件） | All checks passed |
| `git diff --check` | clean |

## 6.1 页面真实测试暴露的两个平台缺陷（已修，非本优化引入）

切到 `APP_RUNTIME_PROFILE=live` 后控制台完全没有指标，定位到两处既有缺陷，任一都会让 live 剖析下的数据链路完全断掉：

| 缺陷 | 现象 | 修复 |
| --- | --- | --- |
| `run_platform.py` 用 `setdefault` 把消费正则固定成旧的按相机模式 `(uav_(statistics|track_complete|conflicts|telemetry)_.*|uav_system_metrics)` | 检测器已改为固定 Topic `uav_statistics`，平台却只订阅 `uav_statistics_<camera>`，live 模式一条消息都不消费（消费组 `uav-platform-local` 无提交位点） | 改用 `utils_local.replay_topics.CANONICAL_CONSUMER_PATTERN` |
| `_add_ingest_receipt` 只定义在 `MetricStorePort` Protocol 上，`PostgresMetricStoreAdapter` / `ReplayV2MetricStoreAdapter` 都没继承也没实现 | 每条消息 `persist()` 抛 `AttributeError`，消费者按“失败即跳最新”降级，数据库 0 行、WS 无推送 | 抽成模块级 `record_ingest_receipt()`，两个适配器都实现；新增 `platform/tests/test_metric_store_ingest_receipt.py` |

修复后实测：单条巡航管道 30 秒写入 `uav_track_complete` 430 条、`uav_telemetry` 32 条、`uav_statistics` 5 条；`GET /api/v1/intersections/INT_MP4728_JINGSHI_CORRIDOR/stats` 返回 `fps=4.9, cars=225, inference_ms=268.8, effective_imgsz=1280`。平台回归 442 passed / 11 skipped。

## 6.2 页面实测暴露的 P4 写入墙（未修，WP3 范围）

在页面连续跑经十路 3m/s 走廊约 10 分钟后（910 帧、**991 条轨迹**、检测仅 261–298），出现：

| 现象 | 数值 |
| --- | ---: |
| `egress.append_points` 单次停顿 | 5.3s → 16.3s |
| `queue.track.get` / `queue.detect.put` 停顿 | 5.0–5.6s |
| egress 队列满导致的 `send()` 超时 | 10s 后抛 `TimeoutError: egress queue remained full`，tracker 退出、整管道 exit(1) |
| 掉帧后 `fps` | 5.13 → 1.09 |

根因是 `DeltaTracks.append_batch` 仍按**每轨迹每字段一条 SQLite INSERT**：600+ 轨迹 ≈ 每帧 4,200 条写入，机器一有负载就滚成秒级停顿；轨迹无上限堆积（206→991，约 +1 条/帧）持续放大它。旧全量管道同样撞过这个墙（`ack_wait pending=32`、5s），只是没跨过 10s 超时。**与 wire 增量无关**：delta 只减字节，不减点写入量。

修复方向（下一步，按序）：① 跨轨迹按字段批量 INSERT（消掉秒级停顿与崩溃点）；② WP3 轨迹回收（把轨迹稳定在 200–300）；③ 评估 `egress_timeout_sec` 与队列深度作为兜底。

## 6.3 当前环境状态（交接）

| 项 | 状态 |
| --- | --- |
| 平台 | 运行中（launchd），`APP_RUNTIME_PROFILE=live`、`ROAD_FEATURES_ENABLED=false`、`PIPELINE_EGRESS_ENABLED=true` |
| Web | Vite dev 运行中：http://localhost:5173（代理 /api、/ws 到 8000） |
| 检测管道 | **无运行中**（最后一条 `pipe-86e98b4e` 按上面 6.2 的 P4 墙退出 code=1） |
| Kafka/TimescaleDB | 运行中（9092 / 5432），固定 Topic 已创建 |
| 启停命令 | `APP_RUNTIME_PROFILE=live ROAD_FEATURES_ENABLED=false PIPELINE_EGRESS_ENABLED=true scripts/mac_local_platform.sh up|stop|restart`；前端 `cd console2 && npm run dev` |
| 复跑基准 | `scripts/profile_pipeline_fps.py` + `scripts/compare_fps_profile.py`（单机 A/B）；`scripts/measure_egress_payload.py`（wire 体积）；`scripts/accept_pipeline_fps.py`（现场 5 分钟） |

## 7. 下一步

1. **现场**：部署 `.3` 基线 + 本轮补丁，跑 5 分钟同源 A/B（`scripts/accept_pipeline_fps.py`），同时提交 `egress.commit_frame`/`restore_tails` 分项、队列深度与 `journal_bytes`。这是唯一能判定 3 FPS 的证据。
2. **WP2 第二阶段（wire 增量）**：本轮采样显示 `frame` 包仍有 188KB（约 300 轨迹），P4 每帧要为全量 facts 做 pickle/JSON；下一步按方案做 `facts_delta_v1`（只发变化轨迹 + 心跳位图），预期每帧载荷降一个量级。
3. **WP3 轨迹数治理**：现场拥堵场景轨迹从 300 涨到 519，先补归档单调性回归再动回收口径。
4. **WP6/WP7**：P2 降到 ~250ms 后渲染（现场 168–282ms）会成为新上限；检测侧 NMS 已占 55%（85.6ms/300 检测）。

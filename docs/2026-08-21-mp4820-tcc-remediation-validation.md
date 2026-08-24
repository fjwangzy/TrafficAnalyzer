# MP4820 TCC 误报修复实施与验收报告（2026-08-21）

## 1. 范围与结论口径

本报告落实 `docs/2026-08-20-mp4820-tcc-false-positive-remediation-plan.md`，范围限定为：

- `SRC-MP4820-JS-0813-EW`
- `SRC-MP4820-JS-0813-WE`
- 用户指定的三个历史事件：`7ebd0196...`、`198c8ff6...`、`d9ddc314...`
- 后续追加复核的同轨迹对事件：`22cf739c...`、`f29dd04d...`
- 同一素材修复过程中暴露的出画参与者、车辆内部跨类别伪检和低夹角同向通行事件

本次结论只证明本地工程链路和本批真实素材，不声明生产精度、召回率、IDF1/HOTA、位置 RMSE 或速度 MAE。

## 2. 历史事件复核

| 事件 | 源时间 | 历史计算 | 画面/轨迹否定事实 | 修复归属 |
|---|---:|---|---|---|
| `7ebd0196...` | 23.2899s | TTC 0.38s、夹角 80.4° | 事件双方为 2328/3059，但事件图没有形成双方可同时辨认的完整证据，画面还混入 5193 的 112km/h 异常速度事实 | 稳健速度、当前帧双方观测、完整可见性、事件精确双方 |
| `198c8ff6...` | 24.6913s | TTC 0.47s、PET 0.41s、夹角 107.1° | 事件双方为 5282/5336，图中只明确显示 5282，且同帧叠加其他轨迹对和多个爆点，不能据此证明该配对近失碰撞 | 当前帧双方观测、完整可见性、事件精确双方、审计字段 |
| `d9ddc314...` | 25.2252s | TTC 0.26s、PET 0.02s、夹角 95.5° | 388 与 5887 位于同向车流，画面速度达到 75/59km/h，历史轨迹外推与画面平行通行不一致 | 遥测插值、稳健速度/方向、普通交叉最小夹角与方向置信度 |
| `22cf739c...` | 24.1241s | TTC 0.51s、PET 0.13s、夹角 125.2° | 与 `f29dd04d...` 为旧管道同一轨迹对 3752/3059；逐帧显示为同向近平行车辆，无共同冲突区，且旧轨迹类别 lineage 不一致 | 精确人工驳回、事件标题真实性、当前生产口径重跑 |
| `f29dd04d...` | 26.3930s | TTC 0.40s、PET 0.01s、夹角 119.1° | 与上一条相同：同一旧管道、同一轨迹对、相同近平行形态，不构成可复核机非冲突 | 精确人工驳回、事件标题真实性、当前生产口径重跑 |

历史事件不删除、不静默改写。`22cf739c...` 与 `f29dd04d...` 已通过公开复核 API 精确写入 `rejected / revision=2` 和同一逐帧复核原因；其他事件不受影响。验收以同一 SourceProfile 的新 Pipeline 是否重新输出正式事件为准。

## 3. 已实施修复

1. 文件遥测在同步容忍和最大分段间隔内做标量线性插值、角度最短弧插值，保留左右记录与插值 lineage；禁止跨缺口外推。
2. 视觉位姿残差超过门槛时关闭当帧世界/TCC 能力；AGL 缺失严格 fail closed。
3. 速度使用可信 ENU 分段的稳健中位数，超过 45m/s 的异常段不参与速度、方向和避险证据。
4. TCC 方向使用稳健多段方向；普通交叉要求双方方向置信度至少 0.6、夹角至少 60°。
5. 活动轨迹使用最近 30 帧业务类别滚动投票；当前类别须与投票一致且置信度至少 0.8。
6. 双方必须在事件当前采样帧被关联，bbox 距边界至少 8px；lost-buffer 和出画目标不得继续外推正式事件。
7. 跨类别 bbox 高度嵌套时按同一物体重复检测拒绝，避免车辆内部 `pedestrian/motor` 伪检成为第二参与者。
8. 新事件增加同刻最小距离、双方速度、方向/类别置信度、投影快照、运动段、边界净距和算法版本；详情接口区分精确 `related_tracks` 与 `context_tracks`。
9. 事件冷却统一以正式业务 `track_id` 配对作为键，避免图像关联 ID 与正式 ID 混用导致冷却状态逐帧被清除；2 秒冷却窗内同级不重复，等级升级可立即发布，窗外再次预测仍按现行合同发布。
10. Event Center 不再把算法输出硬编码为“真实机非冲突”：待复核、已确认、已驳回分别显示“待复核冲突候选”“已确认机非冲突”“已驳回冲突候选”；Replay V2 只读事实也保持“冲突候选”语义。
11. 原生 MPS runner 使用手工分区和显式 next offset 捕获 Kafka；`Invalid file descriptor` 或 broker 短暂重启时重建 consumer 并从最后已消费 offset 继续，避免健康检测任务被验收采集器中止。

上述改动位于现有节点 seam，不替换 YOLO、ByteTrack、Kafka Topic、road9 表或 Platform 主体。

## 4. 自动回归

| 门禁 | 结果 |
|---|---|
| TCC/跟踪/回放 runner 定向回归 | 115 passed；含三个实际误报形态重建、正式 ID 冷却、Kafka 手工分区消费及 road9 延迟对账用例 |
| 遥测/投影/速度/事件详情定向回归 | 通过 |
| Platform 全量测试 | 316 passed / 6 skipped / 10 subtests passed |
| Kafka/ByteTrack 核心回归 | 30 passed |
| Console2 production build | 通过 |
| Console2 全量测试 | 231 passed / 4 failed；失败属于工作区既有非 TCC 前端契约变更，未纳入本修复 |
| XQH 真实视频基线 | 55 PASS / 0 FAIL / 1 WARN；唯一警告为前 100 帧方向统计仍为空 |
| TCC 评审包幂等回归 | 2 passed；只读 managed evidence 可重复重建 |
| `git diff --check` | 通过 |

## 5. 真实回放验收

最终固定代码输出目录：

```text
output/native-mps/mp4820-tcc-remediation-20260821-final8
```

运行参数：原生 macOS arm64/MPS、`hover_cruise_v1`、`frame_stride=3`、自适应 imgsz、严格 `geo_tcc_validation`。

| SourceProfile | 自然 EOF | Kafka/road9 对账 | TCC eligible 覆盖 | 新正式 TCC | 视觉复核 |
|---|---|---|---:|---:|---|
| `SRC-MP4820-JS-0813-EW` | 是，返回码 0 | 6,362 个唯一完成轨迹与 road9 排空后精确一致；旧 runner 快照为 6,363/6,162 | 1,533/1,929，79.47%，未达 90% 门槛 | 7 | 三个用户事件时刻均无正式事件；7 个新事件逐帧均为双方可辨认的实际交叉/转向互动 |
| `SRC-MP4820-JS-0813-WE` | 是，返回码 0 | road9 恢复后按唯一 `source_message_id` 精确一致：1,347 stats / 7,536 tracks / 13 conflicts / 3,063 telemetry | 717/1,347，53.23%，未达 90% 门槛 | 13 | 13 个事件的原图、检测图和前后 10 秒片段全部确认为实际交叉/转向互动 |

EW 的 7 个新事件源时间为 `224.6244s`、`257.1569s`、`338.7384s`、`349.0487s`、`404.5041s`、`424.8244s`、`426.6262s`。视觉复核确认参与者均在当前帧内，轨迹对应实际交叉或转向穿越，未再出现历史的单参与者、出画外推、同车跨类重检或同向车流伪交叉形态。

WE 的 13 个新事件源时间为 `4.8048s`、`5.5055s`、`38.8388s`、`227.9277s`、`234.3341s`、`246.9467s`、`251.1509s`、`252.7525s`、`254.5543s`、`255.9557s`、`256.0558s`、`257.7575s`、`341.1408s`。其中：

- `4.8048s → 5.5055s` 和 `255.9557s → 256.0558s` 分别为同一参与对由 warning 升为 critical，符合升级立即发布合同；
- `246.9467s → 251.1509s` 为同一参与对持续风险，间隔 4.204 秒，超过 2 秒冷却窗，符合当前重复发布合同；
- `252.7525s–257.7575s` 边界簇经片段确认，参与者在事件前已持续可见，车辆转向与非机动车直行路径真实相交，不是刚入画外推；
- `341.1408s` 为支路驶出汽车与主路非机动车约 60.6° 交叉，TTC 1.23 秒、PET 0.03 秒与画面一致。

评审包位于 `output/native-mps/mp4820-tcc-remediation-20260821-final8/review`，`review-decisions.json` 和重建后的 `review-manifest.json` 均为 `confirmed=20 / false_positive=0 / uncertain=0 / pending_review=0`。这是本批两源已输出事件的逐条视觉确认率，不等同于生产总体 precision；负样本没有外部穷举真值，因此 recall 仍不评估。

WE 运行末段 Docker 虚拟盘再次写满，road9 checkpoint 进入 recovery，导致 runner 原始 `result.json` 的最终对账和 Pipeline 注销失败。恢复过程遵循精确边界：Kafka 已预先完整复制到 `/private/tmp/mp4820-native-kafka-20260821/data` 并由原生 broker 继续服务；随后移除已停用的 `traffic_analyzer-kafka-1` 及其约 12.9GB `traffic_kafka_data` 卷，不删除 road9、轨迹、冲突或证据。road9 恢复 healthy 后消费者追平，独立证据 `post-recovery-reconciliation.json` 记录 1,347/7,536/13/3,063 全部精确一致；陈旧 Pipeline 已停止，临时原生 broker 已受控关闭。原 `result.json` 保留故障现场，不被改写。

Console2 5173 服务可正常启动，真实事件页进入本地登录门禁；未代填凭证。最终视觉判定直接使用同一事件 payload 指向的 managed 原图、检测图和评审片段完成，不依赖页面截图替代证据。

工程验收结果：两源均自然 EOF、返回码 0，Kafka/road9 在恢复后精确对账；历史三个事件时刻均未再次输出正式 TCC；20 个其他新事件均已逐条核对双方原图、检测图、轨迹和 payload。严格 Source 验收仍不通过，因为 EW/WE 的 TCC eligible 覆盖率分别只有 79.47%/53.23%，低于 90% 门槛；不降低门槛换取通过。

## 6. 最终结论

```text
historical_false_positive_recurrence_not_observed
emitted_event_visual_review_confirmed_20_of_20
road9_reconciliation_matched_after_recovery
strict_source_acceptance_failed_tcc_eligible_coverage
production_accuracy_not_claimed
formal_recall_not_evaluated
```

## 7. 追加误报复核与独立重跑（2026-08-21 至 2026-08-22）

用户追加指出 `22cf739c...` 与 `f29dd04d...` 为同类近平行误报。两条旧事实已精确驳回为 `rejected / revision=2`，Event Center 页面契约同步改为候选/确认/驳回三态，未删除历史事实。

独立证据目录为 `output/native-mps/mp4820-tcc-rerun-20260821-real-events-v6`。EW 新管道 `pipe-49aa9d8e` 自然 EOF、返回码 0，Kafka 为 `3153/6362/7/4257`；Platform 尾部排空后 road9 四类精确一致。WE 新管道 `pipe-a3687752` 自然 EOF、返回码 0，`3217/7536/13/3836` 在 runner 内精确一致。两源 `invalid_tcc_events=[]`，新管道均未输出涉及旧轨迹 `3752/3059` 的事件。TCC eligible 覆盖率为 75.61% / 51.73%，仍低于 90% 严格门槛，验收保持失败，不下调阈值。

长运行首次尝试暴露 Docker 虚拟盘 100% 导致 road9 recovery 与 Kafka broker 重启；未删除任何 road9、轨迹、冲突或证据卷，虚拟盘无损扩容至 128GB。runner 增加显式 next-offset 的 Kafka consumer 重建，覆盖 `Invalid file descriptor` 与短暂 broker 重启；本次最终双源重跑恢复次数均为 0。

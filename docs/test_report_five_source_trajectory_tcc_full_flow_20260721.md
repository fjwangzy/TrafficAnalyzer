# 五视频源轨迹检测、回放与 TCC 事件全流程验收报告

> 执行日期：2026-07-21（Asia/Shanghai）  
> 结论：**本机功能验收通过**；不等同于生产精度、性能、容量或道路上下文验收。

## 1. 验收范围

本次覆盖 `mp4new` 的五个 canonical SourceProfile：

1. `SRC-MP4NEW-HY-0624-PM`
2. `SRC-MP4NEW-HY-0625-AM`
3. `SRC-MP4NEW-LS-0624-PM`
4. `SRC-MP4NEW-LS-0625-AM`
5. `SRC-MP4NEW-CH-0625-AM`

验收链路为：原始 MP4 + DJI Cloud JSON 遥测 → `main_optimized.py` → canonical Kafka
`uav_*` → Platform → `road9`/TimescaleDB → Console2 BEV 历史回放；另通过真实 Mission
验证严格 TCC 事件、三图证据、事件中心和停止回收。

## 2. 执行环境与口径

- 主机：Apple Silicon `arm64`
- Python：3.11.15
- PyTorch：2.2.2，MPS built/available 均为 `true`
- 批量参数：`frame_stride=60`、`imgsz=640`
- 运行产物：`output/native-mps/five-source-fullflow-20260721-stride60/summary.json`
- canonical 数据库：PostgreSQL database=`road9` + TimescaleDB
- canonical Topic、`msg_type`、WebSocket channel：只使用 `uav_` 前缀

`frame_stride=60` 用于覆盖完整视频时间轴的功能验收，不是逐帧召回率、误报率或生产性能证明。
严格 TCC 正样本另使用 Platform Mission 默认 `frame_stride=5` 验证，未通过放宽业务阈值造数。

## 3. 五源检测与持久化结果

| SourceProfile | Pipeline | Stats | 完成轨迹 | TCC 诊断样本 | 严格 TCC | 返回码 | 结果 |
|---|---|---:|---:|---:|---:|---:|---|
| `SRC-MP4NEW-HY-0624-PM` | `pipe-f0641ee2` | 533 | 2,019 | 533 | 0 | 0 | PASS |
| `SRC-MP4NEW-HY-0625-AM` | `pipe-6d145fb0` | 375 | 1,485 | 375 | 0 | 0 | PASS |
| `SRC-MP4NEW-LS-0624-PM` | `pipe-508ce9e8` | 408 | 970 | 408 | 0 | 0 | PASS |
| `SRC-MP4NEW-LS-0625-AM` | `pipe-7380f11d` | 386 | 662 | 386 | 0 | 0 | PASS |
| `SRC-MP4NEW-CH-0625-AM` | `pipe-f891df54` | 394 | 2,237 | 394 | 0 | 0 | PASS |
| **合计** | 5 | **2,096** | **7,373** | **2,096** | **0** | — | **5/5 PASS** |

Road9 只读对账按 `source_profile_id + pipeline_id + grain_type=intersection` 统计，五源分别为
533/375/408/386/394 条，与 Kafka 直采 Stats 完全一致；`uav_track_events` 分别为
2,019/1,485/970/662/2,237 条，也与批量产物完全一致。批量运行中的 0 个严格 TCC 是真实结果；
每个 Stats 都包含 TCC 漏斗诊断，因此不是“节点未运行”。礼士路 6.24 已知约 34 秒遥测空洞继续按
degraded/missing calibration 如实呈现，不插值伪造。

MPS 推理中位数为 192.8–286.1ms，P95 为 501.1–964.7ms；海右路 6.24 出现 7,094.9ms
最大长尾。本轮只把它记录为本机技术观察，不据此声明生产 SLO。

## 4. TCC 正样本、证据与事件记录

通过真实 Mission API 创建并运行：

- Mission：`MSN-0A894D610BBD`
- Pipeline：`pipe-e7d55e0a`
- SourceProfile：`SRC-MP4NEW-CH-0625-AM`
- RoadContext：`ROAD-MP4NEW-CH-UNVERIFIED-V1`

最终产生 7 个事件，全部满足：

- `prediction_type=path_intersection`
- `distance_m=0`
- 每个事件恰好一个 `hash_verified` EvidencePackage
- 每包固定包含 `conflict_original_frame`、`conflict_detector_frame`、
  `conflict_trajectory_reconstruction`

Road9 对账为 7 个严格事件、7 个证据包、21 个证据项。最新事件
`b5100f7dcb623c3efb81298833128468f5303141` 的三张 JPEG 分别为 140,633、149,252、
120,588 bytes，内容 SHA-256 与 API 引用逐项一致。事件中心真实页面展示三张独立缩略图；原始画面
全屏预览、显式关闭按钮和关闭后的隐藏状态均通过浏览器验收。

验收结束通过 Mission Stop API 停止任务。最终 Mission 为 `cancelled/manual_stop`，Pipeline 为
`desired=stopped / observed=stopped`；Platform `/ready` 返回 database、Kafka、TimescaleDB、
PipelineManager 全部 healthy，`pipelines_active=0`，无运行中 Pipeline。

## 5. Console2 历史回放

验收中发现 `/monitoring` 原先只投放当前 WebSocket 会话的 active/completed 轨迹；离线源虽然
Road9 已有轨迹，BEV 仍显示 `0 TRACKS`。本轮按 TDD 修复：监测页按当前
`source_profile_id` 调用轨迹 API，使用 `period=24h&limit=500&spatial_ready=true&min_world_points=2`，
离线时投放历史轨迹并明确标记“BEV 历史轨迹回放”。

真实浏览器逐源结果：五个 SourceProfile 均显示 `BEV 历史轨迹回放 · 500 TRACKS`；崇华路最新
TCC 卡片可选中为 `event-card critical selected`，回放主视图保持 500 条世界坐标轨迹。500 是页面
保护上限，不代表数据库总轨迹数；总量以 Road9 对账为准。

## 6. 回归结果

| 验证 | 结果 |
|---|---|
| `python -m pytest platform/tests -q` | 148 passed / 5 skipped / 10 subtests passed |
| 检测器聚焦 pytest | 14 passed |
| MPS runner 聚焦 pytest | 13 passed |
| `python test_refactor_unit.py` | 52 PASS / 0 FAIL |
| `python test_pipeline_inter_xqh.py` | 56 PASS / 0 FAIL / 0 WARN |
| Console2 全量测试 | 15 files / 90 passed |
| `npm run build` | PASS，5,467 modules transformed |
| ADR-019 strict audit | PASS |
| canonical Compose config | PASS |
| `git diff --check` | PASS |

Console2 首轮与两个 Python 套件并行时有 2 个 lazy-route 加载超时；单独串行重跑为 90/90，
且真实容器页面通过，因此记录为资源竞争噪声，不作为功能失败。检测器长时多进程退出仍会在 macOS
日志中出现 `multiprocessing.resource_tracker` 共享内存告警；五源返回码、消息计数和进程回收均正常，
但该告警应继续作为技术债跟踪。

## 7. 结论与边界

五源轨迹检测、canonical Kafka/road9 持久化、Console2 历史 BEV 回放、真实 TCC 事件、三图证据、
事件中心展示和任务停止回收均已闭环，本机功能验收通过。

未关闭的外部门禁保持不变：道路上下文仍为 unverified；`frame_stride=60` 不证明模型精度；生产 GPU、
镜像 pin/签名、秘密管理、TLS/SASL、HA、容量、保留策略和 RPO/RTO 仍需独立验收。

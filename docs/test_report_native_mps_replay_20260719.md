# Apple Silicon 原生 MPS 八源轨迹/TCC 回放报告

> 日期：2026-07-19  
> 范围：`test_videos/mp4new` 5 源、`test_videos/mp4new2` 3 源；本机根 Compose Kafka/road9/Platform。  
> 边界：本轮证明原生 MPS、全时间轴回放、canonical 消息与持久化闭环，不证明逐帧检测召回率、TCC 事件召回率、生产容量或道路标定精度。

## 根因与实施结果

原 1800ms 以上推理由 Platform Linux 容器内 CPU 执行：容器 PyTorch 不含 MPS，Mac 当前 Conda Python 又是 x86_64/Rosetta。4K 视频、YOLO `imgsz=960` 与仅 4 vCPU 叠加后，实测常见 1.8–2.0s，竞争时可到 7–10s；后处理不是主因。

本次交付：

- `scripts/bootstrap_native_mps.sh`：使用原生 arm64 `uv` 建立可重复执行的 `.venv-mps`，安装检测器与 Platform 本地包，并强制校验 arm64、MPS built/available；
- `platform/scripts/bootstrap_mp4new_sources.py`：在既有海右路、礼士路、崇华路下新增 3 个 `mp4new2` SourceProfile，总目录为 4 路口、9 源（含 `inter_xqh`），本轮选择其中 8 个 mp4new/mp4new2 源；
- `scripts/run_native_mps_replays.py`：宿主机 MPS 串行回放、外部 Pipeline 登记、JWT 自动刷新、陈旧登记清理、断点续跑、Kafka 直采完整轨迹/TCC 与性能汇总；
- 批处理关闭无消费者画面渲染、冲突视频保存和重复悬停 JPEG，但保留真实 TCC 证据快照；交互式 Mission 默认行为不变。

环境验证：

```json
{
  "machine": "arm64",
  "python": "3.11.15",
  "torch": "2.2.2",
  "mps_built": true,
  "mps_available": true
}
```

复现命令：

```bash
scripts/bootstrap_native_mps.sh
docker compose -p traffic_analyzer exec -T platform \
  python /project/platform/scripts/bootstrap_mp4new_sources.py --check
.venv-mps/bin/python scripts/run_native_mps_replays.py \
  --output-dir output/native-mps/full-20260719-mps640 \
  --frame-stride 60 --imgsz 640 --resume
```

## 八源结果

首源在优化过程已用 stride 30 完整跑通，后 7 源使用 stride 60；两者都覆盖完整视频时间轴。该采样只用于链路和真实事实验收，不作为检测/TCC 召回率证明。

| SourceProfile | stride | 轨迹 | TCC | inference median / P95 / max (ms) | 结果 |
| --- | ---: | ---: | ---: | --- | --- |
| `SRC-MP4NEW-HY-0624-PM` | 30 | 2,500 | 0 | 214.2 / 723.0 / 3,172.6 | PASS |
| `SRC-MP4NEW-HY-0625-AM` | 60 | 1,485 | 0 | 307.9 / 680.5 / 4,708.9 | PASS |
| `SRC-MP4NEW2-HY-0715-PM` | 60 | 1,077 | 0 | 287.7 / 545.4 / 5,427.6 | PASS |
| `SRC-MP4NEW-LS-0624-PM` | 60 | 970 | 0 | 289.8 / 811.9 / 3,538.7 | PASS（保留 telemetry_gap_34s） |
| `SRC-MP4NEW-LS-0625-AM` | 60 | 662 | 0 | 253.9 / 584.1 / 3,553.5 | PASS |
| `SRC-MP4NEW2-LS-0715-PM` | 60 | 458 | 0 | 184.9 / 361.0 / 3,163.8 | PASS |
| `SRC-MP4NEW-CH-0625-AM` | 60 | 2,237 | 0 | 323.4 / 736.5 / 2,774.2 | PASS |
| `SRC-MP4NEW2-CH-0715-PM` | 60 | 1,490 | 0 | 216.9 / 445.1 / 3,513.9 | PASS |

汇总为 `8/8 PASS`、10,879 条完成轨迹、0 条 TCC。所有视频进程返回码为 0；每个来源均有统计和完成轨迹。TCC 门禁只接受 `prediction_type=path_intersection && distance_m≈0`；0 是本批素材的真实结果，没有调整阈值制造事件。

常态推理中位为 184.9–323.4ms、P95 为 361.0–811.9ms，相比原容器 CPU 常见 1800ms 已显著下降。MacBook Air 无风扇长时间负载仍出现 2.77–5.43s 的 max 长尾，因此结论是“常态 CPU 回退问题已修复，长尾尚未完全消除”，不能报告为全时段实时。

## Kafka、road9 与重启复验

Kafka 直采和 road9 按同一批 `pipeline_id` 对账：

| SourceProfile | road9 轨迹 | road9 冲突 |
| --- | ---: | ---: |
| `SRC-MP4NEW-HY-0624-PM` | 2,500 | 0 |
| `SRC-MP4NEW-HY-0625-AM` | 1,485 | 0 |
| `SRC-MP4NEW2-HY-0715-PM` | 1,077 | 0 |
| `SRC-MP4NEW-LS-0624-PM` | 970 | 0 |
| `SRC-MP4NEW-LS-0625-AM` | 662 | 0 |
| `SRC-MP4NEW2-LS-0715-PM` | 458 | 0 |
| `SRC-MP4NEW-CH-0625-AM` | 2,237 | 0 |
| `SRC-MP4NEW2-CH-0715-PM` | 1,490 | 0 |

重启 Platform 后健康检查恢复为 healthy；再次查询 road9 为 `10879|8`（轨迹数|来源数）。目录检查为 `intersections=4 / sources=9 / changed=0 / passed=true`。

完整机器证据位于 `output/native-mps/full-20260719-mps640/summary.json` 及各 SourceProfile 子目录的 `tracks.json`、`tcc-events.json`、`stats.json`、`result.json`、`pipeline.log`。该目录属于本机运行产物，不纳入 Git。

## 剩余风险

- MPS 长尾 max 仍超过 1800ms，后续应在冷机/热机、供电模式和不同 `imgsz` 下做独立 soak，并评估半精度或模型规格；
- 本轮 stride 30/60 和 `imgsz=640` 是全目录链路验收参数，不可替代默认 `imgsz=960` 的小目标精度回归；
- 8 源没有自然产生 TCC 正样本，只证明零事件事实和严格事件契约；事件召回仍需经审核的真实正样本集；
- RoadContext 仍为 unverified，世界坐标和事件距离不得作为生产执法或权威道路精度结论。

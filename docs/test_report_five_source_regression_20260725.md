# 五路口视频整体回归报告（2026-07-25）

> 执行日期：2026-07-25（Asia/Shanghai）  
> 结论：`local_engineering_acceptance_passed / production_accuracy_not_claimed`。目标五段视频的完整原生 MPS 回放、Kafka/road9 对账、TCC 证据、控制面与 Console2 浏览器验证通过；无独立真值的精度指标保持 `not_evaluated`。

## 1. 范围与数据边界

本轮按不清理历史数据、追加隔离 `run_id/pipeline_id` 的方式覆盖：

1. `SRC-MP4NEW-HY-0624-PM`
2. `SRC-MP4NEW-HY-0625-AM`
3. `SRC-MP4NEW-LS-0624-PM`
4. `SRC-MP4NEW-LS-0625-AM`
5. `SRC-MP4NEW-CH-0625-AM`

执行链路为 MP4 + DJI Cloud JSON → 原生 macOS arm64/MPS `main_optimized.py` → canonical
Kafka `uav_*` → Platform → PostgreSQL database=`road9`/TimescaleDB → REST/WebSocket/MJPEG →
Console2。没有删除既有轨迹、inbox、证据、Topic 或 offset。

五个经典 `mp4new` SourceProfile 均已绑定 `lane_verified` Runtime Road Map Bundle，但缺少
`hover_cruise_v1` 所需的 `registration_pose/camera_calibration/map_coverage_enu_m` 谱系。默认巡航
首轮因此将 469/469 个统计帧阻断为候选、正式轨迹为 0，这是安全门禁的正确行为。完整既有业务
回归随后显式使用 `hover_only_legacy`；不得将本报告解释为巡航 ID 精度或生产准确率验收。

## 2. 原生 MPS 自然 EOF 结果

- 设备：Apple Silicon `arm64`，Python 3.11.15，PyTorch 2.2.2，MPS built/available=`true`
- 模型：`weights/yolo11s-visdrone.pt`，SHA-256
  `9679a16c7c2ba34caf2e33b8a8fa0f98ce9c458e58ceeba01c99068c10c4a3f3`
- 参数：`frame_stride=10`、`imgsz=640`、串行五源、自然 EOF
- 机器报告：[`summary.json`](../output/native-mps/five-source-regression-eof-fixed-20260725T130100Z/summary.json)，SHA-256
  `90435154cddb80315521906d4d9e3ac6647869e6e8e8f0e9df1af860489aac99`

| SourceProfile | Pipeline | Stats | 完成轨迹 | 严格 TCC | 推理中位/P95 | 返回码 | 结果 |
|---|---|---:|---:|---:|---:|---:|---|
| `SRC-MP4NEW-HY-0624-PM` | `pipe-efce32ee` | 543 | 3,157 | 3 | 48.4 / 140.2ms | 0 | PASS |
| `SRC-MP4NEW-CH-0625-AM` | `pipe-3eb14ddb` | 509 | 4,005 | 10 | 57.9 / 278.6ms | 0 | PASS |
| `SRC-MP4NEW-HY-0625-AM` | `pipe-923b0464` | 388 | 2,304 | 1 | 48.2 / 132.4ms | 0 | PASS |
| `SRC-MP4NEW-LS-0625-AM` | `pipe-d25dd5c1` | 382 | 1,295 | 8 | 46.2 / 161.4ms | 0 | PASS |
| `SRC-MP4NEW-LS-0624-PM` | `pipe-b644c8c7` | 401 | 1,477 | 4 | 47.1 / 135.4ms | 0 | PASS |
| **合计** | 5 | **2,223** | **12,238** | **26** | — | — | **5/5 PASS** |

五源均有 TCC 漏斗诊断样本，`invalid_tcc_events=[]`。因此某些帧没有预测或业务事件是检测器真实
筛选结果，不是节点未运行。推理延迟只覆盖 `YOLO.predict`，不代表端到端或生产 SLO。

## 3. Kafka、road9 与业务事实对账

按 `source_profile_id + pipeline_id` 只读对账，Kafka 直采与 road9 精确一致：

| SourceProfile | Stats | Track events | Conflict events | Track points | 车道匹配轨迹 |
|---|---:|---:|---:|---:|---:|
| `SRC-MP4NEW-HY-0624-PM` | 543 | 3,157 | 3 | 154,034 | 1,852 |
| `SRC-MP4NEW-CH-0625-AM` | 509 | 4,005 | 10 | 182,817 | 2,154 |
| `SRC-MP4NEW-HY-0625-AM` | 388 | 2,304 | 1 | 111,251 | 1,305 |
| `SRC-MP4NEW-LS-0625-AM` | 382 | 1,295 | 8 | 52,750 | 707 |
| `SRC-MP4NEW-LS-0624-PM` | 401 | 1,477 | 4 | 70,206 | 885 |
| **合计** | **2,223** | **12,238** | **26** | **571,058** | **6,903** |

- 12,238/12,238 完成轨迹均有至少两个 ENU 点，且 ENU/GCJ-02 序列等长；地图版本、锚点、
  平均/最大速度均存在，退役契约键计数为 0。
- 26/26 冲突均为 `prediction_type=path_intersection` 且 `abs(distance_m)<=0.05`。
- 26/26 冲突均为 `evidence_status=complete`，每个 `evidence_refs` 恰含
  `conflict_original_frame`、`conflict_detector_frame`、`conflict_trajectory_reconstruction` 三类。
- 礼士路 0624 遥测按 offset 179.115s、容差 2.5s 复验：视频 807s 仍可匹配，810/820/837s
  均返回 `None`，确认空洞不使用旧值回退或伪插值；该来源的素材质量仍保持 degraded。

## 4. 控制面与真实浏览器

修复验证脚本的认证契约后，`platform/scripts/validate_mp4new_runtime.py --timeout 180` 对注册目录
全部 9 个来源执行并 9/9 通过，覆盖目标五源及四个补充来源：

- Mission/Pipeline 进入 running；首个重复启动返回 `409/drone_mission_active`；
- MJPEG 均返回真实 JPEG（15,027 bytes）；
- canonical WebSocket 均收到 `uav_stats` 与 `uav_telemetry`；
- 每个 Mission 均 `cancelled/manual_stop`，结束后活动 Mission 为 0。

真实 Chromium 登录 Console2 后，目标海右路源显示历史 BEV `500 TRACKS` 和 6 条近期机非冲突
事件；从页面启动演示检测后显示“实时分析中”、真实“检测器输出视频流”，同时按巡航谱系缺失事实
显示“TCC 已关闭：正式质量门禁未通过”。浏览器 Console 为 0 error。截图：
[`five-source-live-monitoring-20260725.png`](test-screenshots/five-source-live-monitoring-20260725.png)，
SHA-256 `47602955f01a7694113b8c991d981b443b49a031491cb45e39f423d6ba3ec86a`。

## 5. 本轮发现并关闭的问题

1. MPS runner 原先不能显式选择 tracking profile；已增加 `--tracking-profile`，报告与注册请求均记录
   实际 profile，避免把 legacy 回归误标为 cruise。
2. `GeoJsonExportNode` 在 EOF flush 帧 `frame=None` 时读取 `frame.shape` 崩溃；现优先使用完成轨迹的
   canonical `trajectory_gcj02`，仅在存在真实图像时才走旧像素/H fallback，并加入 EOF 回归。
3. 运行态验证器仍把 JWT 放入 WebSocket URL；当前安全契约明确禁止 query token。现改为复用登录
   设置的 HttpOnly 媒体 Cookie，并加入不泄漏令牌到 URL 的回归测试。
4. 两个 ADR-019 本机拓扑测试仍断言旧 Docker 应用容器；已同步到当前“原生 Platform + Docker
   road9/Kafka”开发合同，并使用当前 Alembic head。

上述修复均遵循最小失败复现 → 根因证据 → 聚焦回归 → 真实运行复验的诊断流程。

## 6. 最终自动化门禁

| 验证 | 最终结果 |
|---|---|
| 根 `pytest test -q` | 143 passed |
| Platform `pytest platform/tests -q` | 213 passed / 5 skipped / 1 dependency deprecation warning / 10 subtests passed |
| Console2 `npm test -- --run` | 18 files / 147 tests passed |
| Console2 `npm run build` | PASS，5,290 modules transformed |
| `test/test_refactor_unit.py` | 52 PASS / 0 FAIL |
| `test/test_pipeline_inter_xqh.py` | 56 PASS / 0 FAIL / 0 WARN |
| ADR-019 local strict audit | 10/10 PASS |
| 修改范围 ruff / compileall | PASS |
| `git diff --check` | PASS；仅既有 `FrameElement.py` CRLF 转换提示 |
| Platform 最终状态 | ready，database/Kafka/TimescaleDB/PipelineManager healthy，`pipelines_active=0` |

## 7. 最终边界

本轮关闭五源检测、legacy 跟踪、世界坐标序列、车道匹配、速度字段、严格 TCC、三图证据、
Kafka/road9、Mission、WebSocket、MJPEG、Console2 历史与实时可见性、EOF 和进程回收的本机工程门禁。

没有外部批准的轨迹/位置/速度真值，因此 IDF1、HOTA、正式 ID switch、位置 RMSE、速度 MAE 为
`not_evaluated`。经典五源缺少巡航注册谱系，`hover_cruise_v1` 的候选隔离已验证，但正式巡航准确率
未验收。生产镜像 pin/签名、秘密管理、TLS/SASL、HA、容量、保留策略和 RPO/RTO 继续属于外部门禁。

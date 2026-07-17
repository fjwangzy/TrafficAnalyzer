# mp4new 多路口实时检测测试报告

> 测试日期：2026-07-15  
> 测试范围：`test_videos/mp4new` 五组 MP4+DJI Cloud JSON、road9 持久化、Mission/Pipeline 启停、Kafka/WebSocket、MJPEG 代理和 console2 多路口控制页。
> 结论：检测与控制 **5/5 PASS**；遥测连续性 **4/5 PASS + 1 DEGRADED**。礼士路 0624 的约 34 秒空洞作为素材质量问题保留，不插值、不伪造。道路/车道尚未标定，本报告不验收道路归属、车道流量或权威 GIS 坐标。

> **历史拓扑说明（2026-07-16）**：下文 `docker-compose.road9.yaml` 与隔离端口是 2026-07-15 的历史联调证据，已退出当前运行时。当前唯一正式本机拓扑是根 `docker-compose.yaml`；五组来源在该拓扑上的自然 EOF、关键帧、测绘、标注与重启验收见[六组本机全流程报告](test_report_local_replay_full_flow.md)。

## 1. 测试环境与方法

- 使用仓库当前 `weights/yolo11s-visdrone.pt` 权重和 `main_optimized.py` 三进程检测管道。
- 目标栈使用 `docker-compose.road9.yaml`，常驻端口为 road9 `6544`、Kafka `19093`、Platform `18005`、console2 `4177`；正常回放 `FRAME_STRIDE=10`。
- 真实联调启用 Kafka，五组 Mission 均使用 `telemetry.source=file`、固定偏移和 `sync_tolerance_sec=2.5`。
- 五个遥测 `.txt` 均按 DJI Cloud API `drone-osd` JSON 导出解析，不按 DJI 字幕 SRT 解析。
- 未提供人工道路多边形，因此仅验证视频解码、目标检测、跟踪、遥测注入和 MJPEG 输出，不验证车道级统计。
- 每组均通过 Mission API 启动，等待 `/api/v1/video/camera/{camera_id}` 返回真实 JPEG，并订阅规范 `uav_intersection:{id}`、`uav_telemetry:{drone_id}` WebSocket；测试后通过 API 停止并确认无活动 Mission。
- 另以当前检测配置（`imgsz=960`、`confidence=0.05`）在 CPU 上对每组开头 10 个 stride-10 帧做量化采样，统计检测数、活跃跟踪数和 YOLO 推理延迟；该采样用于可重复的横向比较，不等同于完整三进程管道吞吐率。

## 2. 素材与遥测验证

验收阈值：偏移后的首帧、中段、末段最近遥测记录误差不超过 2.5 秒。

| 路口 | 时段 | 视频时长 | 遥测时长 | 最大匹配误差 | MJPEG 画面 FPS | 结果 |
|---|---|---:|---:|---:|---:|---|
| 解放东路-海右路 | 0624 晚高峰 | 1073.339s | 1457.238s | 1.576s | 3.7 | PASS |
| 解放东路-礼士路 | 0624 晚高峰 | 837.203s | 1187.860s | 30.427s | 3.8 | **DEGRADED（已知空洞）** |
| 新泺大街-崇华路 | 0625 早高峰 | 807.974s | 1231.744s | 1.343s | 2.8 | PASS |
| 解放东路-海右路 | 0625 早高峰 | 750.984s | 1085.811s | 1.804s | 3.7 | PASS |
| 解放东路-礼士路 | 0625 早高峰 | 811.878s | 1121.711s | 0.323s | 4.8 | PASS |

### 降级分析

解放东路-礼士路 0624 晚高峰遥测在相对时间 985.891s 至 1019.945s 之间存在 34.054s 空洞。视频末端目标时间为 1016.318s；空洞前记录与目标时间相差 30.427s，即使取空洞后的绝对最近记录仍相差 3.627s，均超过 2.5 秒阈值。最终实现的 `TelemetryFileReader.get_nearest()` 在该区间返回 `None`，明确表达“无有效遥测”，不会回退为旧记录。

该问题作为素材质量事实保留；运行时不伪造、不插值。该来源持久化为 `validation_status=degraded`、`validation_error_code=telemetry_gap_34s`，不影响检测、跟踪、MJPEG 和控制目标判定。

## 3. 帧级核心指标

每组采样视频帧号为 0、10、20……90，共 10 帧，覆盖源视频开头约 3 秒。检测数与跟踪数格式均为“中位数（最小值–最大值）”。

| 路口 | 时段 | 检测数/帧 | 活跃跟踪数/帧 | 跟踪为正帧 | 唯一跟踪 ID | 推理延迟 P50 / P95 |
|---|---|---:|---:|---:|---:|---:|
| 解放东路-海右路 | 0624 晚高峰 | 181.0（170–188） | 136.5（131–160） | 10/10 | 168 | 675.2 / 944.5ms |
| 解放东路-礼士路 | 0624 晚高峰 | 170.0（161–175） | 120.5（116–156） | 10/10 | 163 | 668.4 / 728.9ms |
| 新泺大街-崇华路 | 0625 早高峰 | 300.0（300–300） | 213.0（169–300） | 10/10 | 344 | 672.9 / 733.2ms |
| 解放东路-海右路 | 0625 早高峰 | 176.0（169–189） | 132.0（124–169） | 10/10 | 172 | 686.1 / 762.1ms |
| 解放东路-礼士路 | 0625 早高峰 | 65.0（58–69） | 41.0（37–66） | 10/10 | 71 | 694.7 / 795.5ms |

核心结果：50/50 采样帧均有检测且活跃跟踪数大于 0；各源活跃跟踪中位数为 41.0–213.0，CPU 推理延迟 P50 为 668.4–694.7ms，真实 MJPEG 画面显示 FPS 为 2.8–4.8。崇华路检测数连续达到 Ultralytics 默认 `max_det=300` 上限，因此 300 应理解为下限/饱和值，不能据此宣称画面中恰好只有 300 个目标。

## 4. 系统联调结果

固定接入对象：3 个逻辑路口、3 架无人机、5 个回放源、3 个 `quality_status=unverified` RoadContext。初始化脚本首次写入 16 个固定对象，第二次执行 `changed=0`，`--check` 返回 3 路口/5 来源完整；未写入车道、道路多边形或权威坐标。

| 来源 | 偏移 | Mission/Pipeline | MJPEG | WebSocket | 停止/复用 | 结果 |
|---|---:|---|---|---|---|---|
| `SRC-MP4NEW-HY-0624-PM` | 233.463s | running / 子进程存活 | JPEG 15027 B | stats + telemetry | cancelled/manual_stop | PASS |
| `SRC-MP4NEW-HY-0625-AM` | 178.129s | running / 子进程存活 | JPEG 15027 B | stats + telemetry | cancelled/manual_stop | PASS |
| `SRC-MP4NEW-LS-0624-PM` | 179.115s | running / 子进程存活 | JPEG 15027 B | stats + telemetry；连续性降级 | cancelled/manual_stop | PASS + DEGRADED |
| `SRC-MP4NEW-LS-0625-AM` | 132.032s | running / 子进程存活 | JPEG 15027 B | stats + telemetry | cancelled/manual_stop | PASS |
| `SRC-MP4NEW-CH-0625-AM` | 247.096s | running / 子进程存活 | JPEG 15027 B | stats + telemetry | cancelled/manual_stop | PASS |

补充控制面证据：

- 同一无人机运行中重复启动返回 `409`，错误码 `drone_mission_active`；停止后同一来源可再次启动。
- 海右路 0624 与礼士路 0625 通过并发验证器同时启动：两个 Mission 均独立进入 `running`，分别取得真实 MJPEG、`uav_stats` 与 `uav_telemetry`，随后均为 `cancelled/manual_stop`，结束后活动 Mission 为 0。
- 五组均创建并消费 `uav_statistics_*`、`uav_telemetry_*`，实际检测还产生 `uav_track_complete_*`；消息中的 `drone_id` 使用固定 `UAV-MP4NEW-*`，不再回退为 `drone_{camera_id}`。
- 海右路 0625 在 `FRAME_STRIDE=2000` 的 EOF 专项中于 32.787 秒进入 `completed/source_eof`；专项结束后目标栈已恢复 `FRAME_STRIDE=10`。
- console2 实拍时崇华路预览 DOM 原始尺寸为 1280×720，页面同屏展示三个已登记路口、五个来源选择、一个运行中真实预览和两个待命卡片。

## 5. 自动化与回归结果

| 检查项 | 结果 |
|---|---|
| `python -m pytest platform/tests -q` | PASS：83 passed，5 skipped，11 subtests passed |
| 隔离 `road9_i2_test`：`test_mission_postgres_integration.py` | PASS：2 passed；实际覆盖同无人机并发保护、人工停止、自然 EOF、Pipeline 异常与运行时丢失；测试库已删除 |
| `python -m pytest test_telemetry_file_reader.py test_video_reader_frame_stride.py test_road9_compose_runtime.py test_kafka_active_trajectories.py test_utils_local.py test_byte_tracker_core.py -q` | PASS：15 passed；严格遥测空洞、文件 seek 帧号/EOF 语义保持，以及 Platform init/stride 配置门禁 |
| `python test_pipeline_inter_xqh.py` | PASS：56 PASS / 0 FAIL / 0 WARN |
| `console2`：`npm test -- --run` | PASS：8 files / 49 tests |
| `console2`：`npm run build` | PASS：5462 modules transformed |

Platform、console2 与根目录轻量回归均在最终实现后执行；`inter_xqh` 在 VideoReader 文件 seek 优化后再次补跑确认。

## 6. 关键截屏

三张截图均来自对应路口的 0625 早高峰真实 MJPEG 检测输出，分辨率为 1280×720。

- [解放东路-海右路](test-screenshots/mp4new-haiyou-20260715.png)，SHA-256：`1daa076cb3ea96de2072ee1b6db64c87305f0ddfcb71d51549ed5b592c4389f5`
- [解放东路-礼士路](test-screenshots/mp4new-lishi-20260715.png)，SHA-256：`b34a2702c02b0f1a52d378159c91979ae25748b65a0fc4451c17b6cdad53af7b`
- [新泺大街-崇华路](test-screenshots/mp4new-chonghua-20260715.png)，SHA-256：`0de5511cc62f7723b0a5deeb69d413691698cb8787da66f2def8c651f1c6bde8`
- [console2 三路口实时控制页](test-screenshots/mp4new-pipeline-management-20260715.png)，SHA-256：`9f524ebb35f1ef5d79ce5bc310732187155e19fba4fac4e7ac21c7ad60d6af95`

管理页截图由真实浏览器访问 `http://127.0.0.1:4177/drones` 获取；崇华路卡片为运行中真实检测框画面，海右路和礼士路卡片为待命状态，不使用静态演示图。

## 7. 其他观察

- 直接通过终端 `Ctrl-C` 停止 `main_optimized.py` 时，进程以 `KeyboardInterrupt` 退出，个别运行报告一个待清理的 shared-memory 对象；停止后未发现 8124-8126 监听残留。
- 含空格和中文的遥测路径必须按 Hydra 字符串值转义；该问题已由真实容器启动发现并加入 PipelineManager 回归。
- 高 stride 文件回放使用 `CAP_PROP_POS_FRAMES` 直接定位抽样帧；RTSP/摄像头仍使用 `grab()`，避免改变实时流语义。
- 多路并发启停审计曾发现 uvicorn 作为容器 PID 1 时无法回收孤立 worker；目标 Compose 已为 Platform 设置 `init: true`，由 Docker init 回收 EOF/停止/异常后的子孙进程，最终复测无 defunct Python 进程。
- RoadContext 仍为未标定；页面明确显示“道路未标定 · 仅检测/跟踪/遥测”。

## 8. 最终判定

- 视频解码、目标检测、跟踪、MJPEG 实时输出：**5/5 PASS**。
- 帧级核心指标：**50/50 帧检测为正、50/50 帧活跃跟踪为正**。
- 遥测偏移及时间覆盖：**4/5 PASS + 1 DEGRADED**。
- Mission/Pipeline、MJPEG、Kafka/WebSocket、管理页启停：**5/5 PASS**。
- 自然结束：**completed/source_eof PASS**。
- 交付边界：道路归属、车道级统计、权威 GIS 坐标 **NOT IN SCOPE**。

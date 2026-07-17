# 本地无人机模拟数据接入与全流程测试报告

> 日期：2026-07-16  
> 范围：`test_videos/inter_xqh` 1 组、`test_videos/mp4new` 5 组；正式本机 `road9`/Kafka/Platform/Console2/Nginx 拓扑。  
> 边界：本报告只证明正式本机开发闭环，不代表生产精度、容量、HA、TLS/SASL、RPO/RTO 或主平台门禁验收。

## 目录登记与零复制

- `platform/scripts/bootstrap_mp4new_sources.py` 已幂等登记 4 个路口、4 架模拟无人机和 6 个 SourceProfile；第二次 `--check` 为 `changed=0 / passed=true`。
- `inter_xqh` 遥测按 DJI `.srt` 解析；`mp4new/srt/*.txt` 明确登记为 `dji_cloud_json`，不伪装为字幕。
- 六组原始 MP4/遥测只保存 `storage_backend=server_asset`、allowlist 相对键、SHA-256 与字节数。测绘证据卷实测 `79MB`，managed 最大对象 `2,344,322 bytes`；六个原视频逻辑总量 `28,584,741,006 bytes`、最大单文件 `5,819,249,471 bytes`，卷内没有同大小对象。
- Pipeline GeoJSON 改写入独立持久卷 `/pipeline-output`，避免只读 `/project` 上的 EOF 写入失败；最终卷为 `4.0MB`、7 个 GeoJSON，最大 `868,837 bytes`。
- `/survey-evidence/{id}/content` 对 managed/server asset 均校验路径和哈希；server asset 持久化 size/mtime/ctime 快速指纹，未变化时无需重复扫描大文件，变化时回退到完整 SHA-256。单元回归覆盖路径穿越、零复制引用、快速指纹、缺失和哈希不一致的拒绝路径。
- 六个测绘批次在指纹回填后的查询耗时为 `2.2–7.9ms`，消除了页面曾因同步重算 4–6GB 视频哈希而超过 10 秒的问题。

## 六组测绘与关键帧

`platform/scripts/validate_local_replay_survey_flow.py` 逐组执行前置核验、目录来源导入、关键帧/BEV、量算、场景标注、技术复核和报告生成，最终 `passed=true`：

| SourceProfile | 遥测 | 批次 | 遥测覆盖 | 原始关键帧 | BEV | 量算 | 场景标注 | 报告 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `SRC-INTER-XQH-0403-PM` | `dji_srt` | selected/valid | 99.8993% | 6 | 6 | 4 | 1 | PDF/JSON/GeoJSON |
| `SRC-MP4NEW-HY-0624-PM` | `dji_cloud_json` | selected/valid | 99.7000% | 6 | 6 | 4 | 1 | PDF/JSON/GeoJSON |
| `SRC-MP4NEW-HY-0625-AM` | `dji_cloud_json` | selected/valid | 100.0000% | 6 | 6 | 4 | 1 | PDF/JSON/GeoJSON |
| `SRC-MP4NEW-LS-0624-PM` | `dji_cloud_json` | selected/degraded | 96.6587% | 6 | 6 | 4 | 1 | PDF/JSON/GeoJSON |
| `SRC-MP4NEW-LS-0625-AM` | `dji_cloud_json` | selected/valid | 100.0000% | 6 | 6 | 4 | 1 | PDF/JSON/GeoJSON |
| `SRC-MP4NEW-CH-0625-AM` | `dji_cloud_json` | selected/valid | 100.0000% | 6 | 6 | 4 | 1 | PDF/JSON/GeoJSON |

总计：36 张原始关键帧、36 张 BEV、24 项点/线/面/对象量算、6 项已确认场景标注和 6 份成果包。36 条源帧均关联原视频，36 条 BEV 均关联对应源帧，来源哈希、遥测、质量、homography 和 view transform 派生链完整。礼士路 0624 的 `telemetry_gap_34s` 原样保留为 degraded，没有插值伪造连续遥测。最终重启后逐组下载 6 原始帧 + 6 BEV + PDF/JSON/GeoJSON + 原始遥测，共 `6 × 16 = 96` 个内容响应；全部以 `X-Content-SHA256` 重新计算并匹配，`96/96 PASS`。六个原视频另以 1KB HTTP Range 请求验证 `206`、`server_asset` 和完整源哈希响应头，`6/6 PASS`，没有下载或复制原视频。

## Mission、态势与研判

- 验收专用 `PIPELINE_FRAME_STRIDE=300` 通过 Compose 环境覆盖使用，仓库默认值仍为 10。六组串行跑到自然 EOF，全部得到 `completed/source_eof`：

| SourceProfile | Mission | 自然 EOF 耗时 |
| --- | --- | ---: |
| `SRC-INTER-XQH-0403-PM` | `MSN-D10DD778BA2E` | 179.528s |
| `SRC-MP4NEW-HY-0624-PM` | `MSN-CCD54C384466` | 196.091s |
| `SRC-MP4NEW-HY-0625-AM` | `MSN-8F9B4965FC0C` | 140.172s |
| `SRC-MP4NEW-LS-0624-PM` | `MSN-5A15FAF30319` | 153.879s |
| `SRC-MP4NEW-LS-0625-AM` | `MSN-A09E19399B74` | 150.046s |
| `SRC-MP4NEW-CH-0625-AM` | `MSN-3B636C666D2F` | 152.111s |

- 每个 Mission 均检查真实 MJPEG JPEG、`uav_stats`、`uav_telemetry` WebSocket 和同无人机并发 409 门禁。早期并行/只读输出路径调试产生的失败 Mission 审计记录保留在 road9，最终验收只采用上述串行成功记录。
- 默认 stride=10 又对六组各跑约 22 秒连续检测窗口；六组峰值活动车辆/轨迹指标依次为 `179、160、166、157、68、300`，且各自交通指标行数均大于 0。`inter_xqh` 独立 100 帧真实 YOLO+SRT 回归为 `56 PASS / 0 FAIL / 0 WARN`、累计检测 8051 个目标。
- 本批素材实际冲突数为 0，因此研判明确记录“未检出事件”，没有制造测试冲突；代码路径已保证未来真实冲突会保存对应 JPEG 到统一证据包。

## 车道标注与重启恢复

- 四个路口各从本轮持久化真实关键帧创建 3840×2160 车道标注任务；保存后写入持久校准卷、4 条 `uav_lane_annotation_tasks` 和 4 条 `uav_visual_lane_bindings`。最终重启后又启动四个短窗口真实 Pipeline，Mission 分别为 `MSN-0889F14E687B`、`MSN-F516FFF89316`、`MSN-03F31A24FB38`、`MSN-8427FDA7DE58`；绑定文件路径完全一致，首个 `uav_stats` 均为 `lane_source=manual`、`lane_count=1`，结束后活动 Mission 为 0。实时稳定悬停触发逻辑保持不变。
- 按用户要求先以本机模式启动 Platform/Console2 完成功能与浏览器测试，再构建最终 Docker 镜像。完成 Platform、Console2、Kafka 与 road9 统一重启后，road9 实测仍有 4 架无人机、6 组视频/遥测来源、30 条 Mission 审计/执行记录、6 个测绘任务、36 个关键帧、6 个场景标注、4 个车道任务/绑定和 6 份报告；全部派生内容可读。
- Playwright 以干净的最终容器会话验证：数据源 `6`、礼士路 0624 的“降级/telemetry_gap_34s”；测绘页真实加载 6 张关键帧缩略图、主图和 `6/6` 变换；量算页显示真实 BEV、4 类量算和 `confirmed v2` 场景标注；报告页可打开真实 PDF；车道页可回看四路口 3840×2160 底图和 1 条已有车道；礼士路 24 小时轨迹页显示 4 个项目路口、200 条历史轨迹、0 个冲突事实，并明确坐标尚未冻结。干净会话浏览器控制台为 0 error / 0 warning。

## 自动化与边界

最终回归结果：

- Platform：`97 passed, 5 skipped, 10 subtests passed`；
- Console2：`50 passed`，Vite production build 通过；
- 根管道/运行时回归：`14 passed`；
- `python test_pipeline_inter_xqh.py`：`56 PASS / 0 FAIL / 0 WARN`；
- ADR-019：`--scope local --strict` 全部通过；
- `git diff --check`：通过。

## 四路口首页上图增量验收（2026-07-16）

- 从四路口本轮已登记遥测中读取 GPS 中位点作为本机验收坐标：兴庆航 `36.7029090, 117.0223260`，海右路 `36.6628016, 117.0930902`，礼士路 `36.6627830, 117.0953953`，崇华路 `36.6729919, 117.1210255`。
- 四点均以 `status=test + usage=local_acceptance_only + source=<SourceProfile> telemetry_median` 写入 road9；接口返回 `map_eligible=4/test_coordinates=4/isolated=0`，但总体健康继续为 `degraded`，未改变 RoadContext 的 `unverified` 状态。
- Console2 首页改用无人机四旋翼 SVG 图标，并以四点几何中心初始化视野；礼士路与海右路约 200 米近邻图标做对称视觉避让但不修改要素经纬度。坐标标签明确显示“验收测试坐标 4 处 · 遥测中位点 · WGS84”，不再显示无坐标空态。
- 最终 Docker Console2 镜像为 `sha256:8fbb139e3622e372aa6591cfa93e198a7cfc29ea466871bce36d549c06913846`。1357×912 本机浏览器实页确认四个四旋翼标记同屏可辨识，健康区显示项目路口/可上图路口/验收测试坐标均为 4，浏览器控制台 `0 error / 0 warning`。
- 增量门禁：Platform 坐标与目录契约 `6 passed`；Console2 全量 `53 passed`，production build 通过；ADR-019 local strict 和 `git diff --check` 通过。

镜像构建曾把 Docker 虚拟磁盘占满并导致 Kafka 无法写 KRaft snapshot；仅清理未使用构建缓存和本项目过期测试镜像后恢复，业务卷未删除。该事实进一步说明容量仍是生产门禁。已批准之外的正式道路坐标、测绘误差阈值、容量、HA、秘密管理、TLS/SASL、生产镜像 pin 和主平台签章/回执仍保持 blocked/unverified。

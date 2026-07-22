# GCJ-02 两阶段技术演示验收报告（2026-07-22）

## 结论

技术演示通过。系统已统一为 GCJ-02 + 高德地图，四个路口发布不可变 `lane_verified` 地图；
视频回归按用户最新要求以 2 条轨迹样本验收，不再等待 9 个来源全量结束。

本结论不是生产签署。生产仍需道路标线负责人审核、至少 100 条人工轨迹车道准确率复核和
是否执行其余来源全量回放的业务确认。

## 第一阶段

| 路口 | 地图版本 | Link/Lane | Link P95 | Lane 中位/P95 |
| --- | --- | ---: | ---: | ---: |
| 小清河北路与水屯路 | `CMV-1d3dedffa32145dca68c148d` | 8/32 | 0.955m | 0.3533/1.2318m |
| 解放东路与海右路 | `CMV-5442ffb9608c483bbc11c92e` | 8/30 | 0.8327m | 0.3747/0.9456m |
| 解放东路与礼士路 | `CMV-3d95098d2a7d4705992c93a8` | 7/19 | 0.7851m | 0.5671/0.8383m |
| 崇华路与新泺大街 | `CMV-e00cef599ed44e35add1aa67` | 8/23 | 0.4937m | 0.241/0.5942m |

共 31 Link、104 个本地稳定车道、9 个 verified SourceProfile 配准。拓扑、自交、重叠、方向、
停止线和技术残差门禁全部通过；YCX ID 仅作不透明 geomhash 来源引用。

## 第二阶段回归范围

v3 批次已有 5 个来源自然运行至 EOF，并按 `pipeline_id` 与数据库精确对账：

| SourceProfile | Pipeline | 轨迹数 |
| --- | --- | ---: |
| `SRC-INTER-XQH-0403-PM` | `pipe-1762eff3` | 3,629 |
| `SRC-MP4NEW-HY-0624-PM` | `pipe-771caebe` | 3,429 |
| `SRC-MP4NEW-HY-0625-AM` | `pipe-efa57ffd` | 2,557 |
| `SRC-MP4NEW2-HY-0715-PM` | `pipe-956c4f4a` | 1,750 |
| `SRC-MP4NEW-LS-0624-PM` | `pipe-2dd542b7` | 1,677 |

合计 13,042 条轨迹，已生成 5 个 completed Mission，记录视频、遥测、模型 SHA-256、地图版本和
转换版本。第 6 个来源按用户缩小范围后中止，其部分事实与 Kafka 尾部补写已清零；其余来源未运行。

## 两条轨迹样本

| TrackEvent | Track | 车道 | Link | 置信度 | 点数 | 车道距离 | GCJ-02 往返误差 |
| --- | ---: | --- | --- | ---: | ---: | ---: | ---: |
| `cdc65754c60425cd61734b3d686a8edb05e86300` | 1 | `local:011wwe0z19700001:a07:l02` | `12wwe0z1twwe0z1901` | 0.8393 | 62 | 0m | 0.0068m |
| `2f84ba4b07cbce05b47a7b41a516525481e53fcd` | 35530 | `local:011wwe0z19700001:a05:l01` | `12wwe0z19wwe0z1t01` | 0.8393 | 85 | 0m | 0.0057m |

抽样空间一致性 100%；小清河北路 3,629 条轨迹全部具有坐标和地图血缘，2,914 条具有正式车道
匹配，覆盖率 80.3%。两条样本的 ENU 与 GCJ-02 点数一致且无退役坐标键。

## 页面验收

Console2 `/gis` 已在真实浏览器中验证：路口坐标来自 checksum 精确关联的 verified RoadContext，
高德地图正常加载并显示“高德地图 · GCJ-02”，Mission、SourceProfile、路网版本和轨迹证据可见；
页面不再显示“坐标尚未冻结”或“高德地图服务不可用”。轨迹 REST 响应显式返回
`coordinate_system: "GCJ02"`，类型化地图/车道/ENU/GCJ-02 字段覆盖原始 payload。

## 结构化证据

- `docs/test_report_gcj02_stage1_20260721.json`
- `docs/test_report_gcj02_stage2_finalize_20260722.json`
- `docs/test_report_gcj02_stage2_trajectory_samples_20260722.json`
- `/private/tmp/TrafficAnalyzer-gcj02-rebuild-manifest.json`

## 自动验证

- Platform：`176 passed, 5 skipped, 10 subtests passed`。
- Console2：`99 passed`；Vite 生产构建成功，高德模块独立分包。
- 坐标/路网匹配/消息链：`14 passed`。
- 小清河北路真实视频前 100 帧：`56 PASS / 0 FAIL / 0 WARN`，检测、遥测、H 和运动补偿链通过。
- ADR-019：`--scope local --strict` 全部门禁通过。
- Console2 活动源码未发现 OSM、OpenLayers、`fromLonLat`、WGS84 或退役世界坐标字段。
- `git diff --check` 通过；仅报告既有 `FrameElement.py` CRLF 转 LF 提示。

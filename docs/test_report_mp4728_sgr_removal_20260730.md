# mp4728 停车车辆伪轨迹与能力边界回归（2026-07-30）

## 结论

状态：`local_engineering_passed / production_accuracy_not_evaluated`。

根因不是路边车辆真的移动，而是 Mission 在缺少额外 SourceGeoRegistration 记录时自动选择
`hover_only_legacy`；旧路径没有巡航背景视觉运动补偿，无人机平移被累计到停车车辆尾迹。当前实现
默认固定 `hover_cruise_v1`，只允许显式请求 legacy 回滚；世界坐标只由视频尺寸、相机参数和同步
遥测形成的当前帧矩阵决定，Runtime Road Map Bundle 只生成 Lane/Link 与匹配置信度。

## 代码与能力边界

- 删除 SourceGeoRegistration API、服务、Mission 选择/固定、Pipeline 参数及运行时环境注入；
  `RUNTIME_GEO_REGISTRATION_JSON` 在启动边界被显式清除。
- 保留已应用 Alembic `20260728_0020` 的表、外键和历史可空字段，不删除、不回写旧数据。
- 像素轨迹、geo、road、TCC 四层独立门控；速度、世界方向和 TCC 不读取地图、Lane ID 或 Link ID。
- 世界投影运行时只保留 `pixel_to_world_enu`；删除会混淆地图归属的 `pixel_to_map_enu` 别名。TCC
  还必须验证成熟图像关联，不能让刚出现的 TrackElement 越过轨迹门禁。
- 遥测缺失、超容差、姿态/高度无效或当前矩阵退化时，世界坐标、速度、方向安全置空，TCC 为 0；
  未知速度不参与车道候选平均速度，也不伪装为停车车辆。
- 无地图或匹配失败只清空 `lane_id/link_id/map_match_confidence`，不得改变上游世界事实。
- `uav_stats` 持久化四层布尔值和逐层原因；Mission/Pipeline 返回最新运行样本，外部注册的原生 MPS
  Pipeline 在没有 Mission `PipelineRecord` 时回退读取同一条持久化 Stats 事实；首帧前显式返回
  `null/runtime_sample_pending`。OpenAPI 的列表/详情/启动/注册响应均声明该契约。

## 自动化回归

- Platform：`232 passed / 5 skipped / 10 subtests`；唯一 warning 为 Starlette/httpx 弃用提示。
- 根目录全量：`203 passed`，其中显式比较同一世界轨迹有无 Lane/Link 字段时 TCC 事件与诊断完全一致。
- 能力矩阵与契约新增红—绿回归覆盖：成熟关联 TCC、无效逐帧遥测安全降级、世界矩阵唯一来源、
  四层能力持久化、Mission/Pipeline 实际值及 OpenAPI 声明。
- 根 Kafka/utils/ByteTrack：`25 passed`；Console2：`18 files / 149 tests`，production build 通过。
- Console2 默认并行全量两次均只有同一个未改动 Monitoring 用例越过 5 秒门限；该用例隔离运行通过，
  按既有单 worker 门禁复跑为 `149/149`。未修改前端超时或无关业务代码。
- XQH 生产链：设置既有 `PYTORCH_ENABLE_MPS_FALLBACK=1` 后 `55 PASS / 0 FAIL / 1 WARN`；warning
  为前 100 帧方向历史不足。MPS 未实现的 torchvision NMS 仅回退 CPU，检测主体仍在 MPS。
- 本次变更文件的 Ruff、compileall 和 `git diff --check` 通过。ADR-019 local strict 的代码/拓扑 9 项通过，仍由已有
  `local_runtime_evidence` 外部门禁阻断，未把该门禁标为通过。
- 原生 Platform 重启后 `/ready` 为数据库/Kafka/TimescaleDB/PipelineManager 全 healthy、活动 Pipeline 为 0；
  OpenAPI 无 SourceGeoRegistration 路由，默认 profile 为 `hover_cruise_v1`，并包含四层能力响应字段。

## mp4728 3m/s 自然 EOF

输入：`SRC-MP4728-JS-0728-3MS`，视频/遥测 SHA-256 分别为
`1d61ea4b...62409`、`9fbb0832...bd1c7`。使用原生 arm64 Python、MPS、`hover_cruise_v1`、
`frame_stride=10`、`imgsz=832`，全片运行至自然 EOF：

| 项目 | 结果 |
|---|---:|
| Pipeline / run | `pipe-23be5fff` / `native-mps-20260730T053328Z-SRC-MP4728-JS-0728-3MS` |
| 运行时间 / 自然 EOF | 558.523s / 是 |
| Stats / completed tracks / telemetry | 405 / 1,595 / 1,189 |
| Kafka publisher | 3,189 expected / 3,189 actual / 0 dropped |
| Kafka 与 road9 | 405 / 1,595 / 0 / 1,189 全部精确一致 |
| 轨迹点列对齐失败 | 0 |
| Lane/Link 匹配帧 | 0 |
| TCC 事件 | 0 |
| MPS inference median / p95 / max | 131.8 / 669.1 / 1,549.9ms |

该素材同步遥测覆盖率为 100%，但 AGL 超出当前可信范围，故 geo/TCC 按当前帧质量安全关闭；这是
遥测质量结论，不是地图缺失导致。有效遥测和有效当前矩阵、无 SGR、无地图仍能输出世界事实的合同
由单元能力矩阵覆盖。本轮没有外部位置/速度/身份真值，因此 IDF1、HOTA、正式 ID switch、位置
RMSE 和速度 MAE 均保持 `not_evaluated`。

第一次全片尝试 `pipe-bd38fc5b` 暴露自动车道候选统计对空速度直接比较的缺陷，在 50.457 秒退出；
该失败批次保留，不算 EOF 证据。新增回归后，未知速度既不参与平均值也不计为停车，第二批次完成。

## 168.835 秒同帧视觉证据

生产 ShowNode 视频第 506 个零基采样帧对应源时间约 168.835 秒。使用绿色 HSV 掩膜和相同的
Hough 长竖线规则：

| 区域 | 旧截图 | 新生产帧 |
|---|---:|---:|
| 路边停车区长竖尾迹组 | 12（最长 387px） | 0 |
| 新帧主车流走廊长轨迹线段 | — | 120 |

因此停车车辆伪长轨迹消失，同时真实车流连续尾迹仍保留；该视觉代理只验证本次回归现象，不代替
人工身份真值或生产跟踪精度验收。

证据：

- `output/native-mps/mp4728-sgr-removal-v2-20260730/summary.json`
- `output/native-mps/mp4728-sgr-removal-v2-20260730/SRC-MP4728-JS-0728-3MS/result.json`
- `output/native-mps/mp4728-sgr-removal-v2-20260730/SRC-MP4728-JS-0728-3MS/pipeline.log`
- `output/native-mps/mp4728-sgr-removal-v2-20260730/SRC-MP4728-JS-0728-3MS/frame-168.835.jpg`

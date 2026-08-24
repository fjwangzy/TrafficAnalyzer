# MP4820 TCC 误报修复方案与验收标准（2026-08-20）

## 1. 文档状态

- 状态：`待实施 / proposed`
- 范围：`SRC-MP4820-JS-0813-EW`、`SRC-MP4820-JS-0813-WE` 及同类低频 DJI JSON/TXT 遥测巡航源
- 关联路口：`INT_MP4820_JINGSHI_EAST_CORRIDOR`
- 关联任务：`docs/TASKS.md` 中 `T-507 mp4820 巡航 TCC 真实性验证`
- 实施方式：沿现有节点接口做局部前向修复，不重写检测器，不改变 canonical Topic、数据库拓扑或 image-first ByteTrack
- 当前结论：以下 3 条事件经原图、检测器图、事件 payload、活动轨迹和遥测切换点联合复核，均应视为当前算法误报；本文定义修复范围和验收门槛，不代表修复已经完成

## 2. 已确认问题

### 2.1 已知误报事件

| 事件 ID | 视频源时间 | 轨迹对 | 当前输出 | 画面与轨迹复核结论 |
|---|---:|---|---|---|
| `7ebd01967da75f4ce07d394afa6abf5a994c610f` | `23.290s` | `2328 / 3059` | TTC `0.38s`、PET `0.00s`、角度 `80.4°`、risk `100` | 双方近反向分离，像素尾迹夹角约 `179.9°`，不具备共同冲突区条件 |
| `198c8ff6d89cf35f9e369bef88d6980d768fbc95` | `24.691s` | `5282 / 5336` | TTC `0.47s`、PET `0.41s`、角度 `107.1°`、risk `100` | 双方近同向，像素尾迹夹角约 `1.3°`；非机动车最后小段世界方向被异常放大 |
| `d9ddc31470fcd652c434aa937f10ceac0e6d8777` | `25.225s` | `388 / 5887` | TTC `0.26s`、PET `0.02s`、角度 `95.5°`、risk `100` | 双方同向平行，像素尾迹夹角约 `0.5°`，不具备横向交汇条件 |

专项数据库复现当前结果为：

```text
FAIL: 3/3 visually rejected samples are still persisted as formal TCC events
```

该结果是本方案的首个红色回归基线。后续不得通过改事件 ID、延长去重时间、隐藏页面或停止持久化来规避。

### 2.2 根因链

1. `TelemetryFileReader.get_nearest()` 对低频 DJI 文件遥测执行最近邻选择。
2. 相邻遥测记录切换时，无人机位置以阶跃方式变化，而不是随视频帧连续变化。
3. 22.990s 和 24.992s 附近，同一帧内大量车辆的 ENU 位置同步跳变约 8–10m，但像素位置仅平滑移动约 4–5px。
4. `PostTrackingWorldProjectionNode` 将投影结果无连续性检查地写入每辆车世界历史。
5. `SpeedEstimationNode` 对含阶跃的最近世界点直接回归，且 `max_speed_kmh` 只增不减。
6. `ConflictDetectionNode` 取最后一个轨迹小段的方向，再拼接测速节点的速度大小；微小横向抖动因此可能被放大成高速横向运动。
7. 冲突角、TTC、PET、急减速和急转向均从同一条受污染世界轨迹派生，证据并不独立。
8. 事件 payload 未持久化 `min_same_time_distance_m` 等关键中间量，事件详情也未精确冻结当时双方输入轨迹，增加了审计难度。

### 2.3 系统级异常证据

本次 Pipeline `pipe-e156a4e6` 的 401 条已完成且含最高速度的轨迹中：

- `106` 条最高速度超过 `100km/h`；
- `6` 条超过 `200km/h`；
- 最高速度 P95 为 `163.1km/h`；
- 最大值为 `532.4km/h`。

这说明当前问题不是单个目标偶发抖动，而是世界投影和运动估计链路的系统性污染。

## 3. 修复目标与非目标

### 3.1 修复目标

1. 低频文件遥测在合格时间间隔内随视频帧连续采样，不再制造位置和姿态阶跃。
2. 投影不连续、视觉/位姿不一致或世界运动不可信时，正式速度、方向和 TCC 必须关闭。
3. 像素检测、图像关联、像素轨迹和通用车辆计数继续工作。
4. 世界速度和方向使用同一连续窗口的稳健估计，不再跨窗口拼接。
5. 已知 3 条误报固定为真实素材回归用例。
6. 所有新正式 TCC 事件具备足够的中间量和精确轨迹证据供复核。

### 3.2 非目标

- 不修改 YOLO 模型、类别映射或检测阈值。
- 不修改 image-first ByteTrack 关联算法，不把 H、ENU、遥测或地图输入 ByteTrack。
- 不改变 `main_optimized.py` 三进程入口和既有节点顺序。
- 不新增旧 Topic、旧 `msg_type`、旧数据库兼容或双写链路。
- 不把 Lane/Link 地图作为通用 TCC 前置条件。
- 本阶段不引入 `predicted/confirmed/rejected` 新事件生命周期。
- 本阶段不新建数据库表；新增审计量优先进入 canonical conflict payload。
- 没有外部批准的穷举真值时，不声明正式 Recall、IDF1、HOTA、ID switch、位置 RMSE 或速度 MAE。

## 4. 修复设计

### 4.1 R1：文件遥测连续插值

责任文件：

- `services/TelemetryFileReader.py`
- `services/dji_telemetry.py`
- `test/test_telemetry_file_reader.py`

保持 `get_nearest(frame_timestamp)` 外部接口不变，在内部增加相邻记录插值：

1. 通过视频源时间和 `time_offset_sec` 得到查询时刻。
2. 同时解析查询时刻前后的原始遥测记录。
3. 位置先转换到局部 ENU，再线性插值；不得直接把后一条坐标整帧替换前一条。
4. AGL、pitch、roll、水平/垂直速度按时间线性插值。
5. heading、attitude yaw、gimbal yaw 使用最短圆周角插值。
6. 镜头、激光状态、质量来源等离散字段只有前后兼容时才允许继承。
7. 两条记录间隔超过 `max_interpolation_gap_sec`、查询超出原始时间范围或任一关键值非法时，返回不可用于正式世界分析的结果，禁止外推。
8. 输出保留以下 lineage：

```text
telemetry_interpolated
telemetry_left_timestamp_sec
telemetry_right_timestamp_sec
telemetry_interpolation_ratio
telemetry_gap_sec
```

建议配置：

```yaml
telemetry:
  interpolation_enabled: true
  max_interpolation_gap_sec: 2.5
```

`2.5s` 仅对应当前 SourceProfile 已固化的最大同步容忍；其他来源必须按自身采样频率配置，不能把该值推广为生产通用真值。

### 4.2 R2：投影连续性和视觉一致性门禁

责任文件：

- `nodes/FlightGeoReferenceNode.py`
- `utils_local/homography.py`
- `test/test_flight_georeference.py`

复用现有 `pose_warp`、`camera_motion_warp` 和 `pose_visual_residual_p95_px`，不新建旁路投影器：

1. `require_visual_validation=true` 时，`visual_warp.status=degraded/unavailable` 不得进入正式 TCC。
2. `pose_visual_residual_exceeded` 纳入 TCC 阻断原因。
3. 发现投影不连续时输出 `projection_discontinuity`，当前帧：

```text
geo_analytics_eligible = false
tcc_analytics_eligible = false
```

4. 质量失败只结束当前世界运动分段，不结束、不重建图像 `association_id`。
5. 只有连续稳定至少 15 帧且持续至少 0.5s 后才恢复世界分析；恢复后使用新的世界运动分段 ID。
6. 质量状态和残差进入 `geo_reference_quality` 与 `tcc_diagnostics`。

### 4.3 R3：世界轨迹分段与异常点隔离

责任文件：

- `nodes/PostTrackingWorldProjectionNode.py`
- `nodes/SpeedEstimationNode.py`
- `test/test_post_tracking_world_projection.py`
- 新增或扩展速度专项测试

要求：

1. 世界历史按投影质量连续段保存；不同段不得共同参与速度、方向、转向或 TCC 计算。
2. 对逐段 `distance/dt` 同时执行绝对物理上限和 MAD 稳健离群判断。
3. 异常段应被拒绝，而不是把速度截断到上限。
4. 速度使用最近 `0.5–1.0s` 连续时间窗口回归，不再只依赖固定点数。
5. 有效点少于 3 个时，当前世界速度为 unavailable。
6. 将准入速度和诊断速度分开：

```text
rolling_max_speed_kmh   # 可用于当前业务准入
lifetime_max_speed_kmh  # 仅用于诊断
```

建议配置：

```yaml
speed_estimation:
  regression_window_sec: 0.8
  max_physical_speed_ms: 55.0
  outlier_mad_multiplier: 5.0
  min_valid_points: 3
```

### 4.4 R4：稳健方向和 TCC 准入

责任文件：

- `nodes/ConflictDetectionNode.py`
- `configs/app_config.yaml`
- `test/test_tcc_diagnostics.py`

方向估计：

1. 删除“最后一个轨迹段方向 × 另一个窗口回归速度大小”的组合。
2. 使用最近至少 `0.3s` 的同一连续世界运动段估计方向。
3. 净位移至少达到 `1.0m`；方向离散度超过门槛时输出 `heading_unreliable`。
4. 方向和速度必须来自同一窗口、同一世界运动段。

TCC 准入：

1. 不再使用终身 `max_speed_kmh >= 5` 作为当前移动资格。
2. 只累计当前连续世界运动段的轨迹长度。
3. 投影、速度或方向任一不可信时直接拒绝。
4. 保持现有正式业务阈值：

   - `prediction_type=path_intersection`；
   - `arrival_time_delta_sec <= 1.0s`；
   - `min_same_time_distance_m <= 0.8m`；
   - 标准冲突角 `30°–150°`；
   - `same_time_cpa` 默认关闭。

5. 新增稳定拒绝原因：

```text
projection_discontinuity
motion_segment_contaminated
speed_unreliable
heading_unreliable
rolling_speed_below_min
same_direction_parallel
opposite_direction_separated
```

建议配置：

```yaml
conflict_detection:
  motion_quality_guard_enabled: true
  heading_window_sec: 0.5
  min_heading_displacement_m: 1.0
  max_heading_dispersion_deg: 15.0
```

### 4.5 R5：消除循环证据并补齐事件审计量

责任文件：

- `nodes/ConflictDetectionNode.py`
- `nodes/KafkaProducerNode.py`
- `platform/app/services/metric_store.py`
- `platform/app/services/event_center.py`
- 对应契约和 Platform 测试

要求：

1. `hard_deceleration`、`hard_steering` 只能从过滤后的连续运动段计算。
2. 被判为异常的轨迹段不得生成行为证据。
3. `hard_ttc_or_pet` 表示预测强度，不得描述成独立的已观察避险行为。
4. 风险评分不得因同一异常同时产生短 TTC、急减速和急转向而自动达到 100。
5. conflict payload 至少补充：

```text
min_same_time_distance_m
motor_velocity_enu_ms
non_motor_velocity_enu_ms
motor_heading_confidence
non_motor_heading_confidence
projection_quality
motion_segment_id
algorithm_version
```

6. EventCenter 的 `related_tracks` 必须优先返回事件精确双方；其他同 Mission 轨迹单列为 `context_tracks`。如果本阶段不修改读模型，则必须保证事件 payload 自身足以独立复核，不能继续依赖“最近 50 条完成轨迹”解释事件。

## 5. 测试与验收标准

### 5.1 单元和模块硬门槛

| 编号 | 场景 | 通过条件 |
|---|---|---|
| UT-01 | 两条位置相距约 10m、时间相隔约 2s 的遥测记录按 30fps 采样 | 中间位置连续变化；不得出现 10m 单帧阶跃 |
| UT-02 | yaw `179° → -179°` | 经 `180°` 最短路径插值，不得绕行到 `0°` |
| UT-03 | 遥测间隔超过配置门槛 | 返回 unavailable；禁止外推 |
| UT-04 | pose warp 与 visual warp 一致 | 投影质量通过 |
| UT-05 | 注入全局 10m 投影阶跃 | 当前帧正式 TCC 为 0，原因包含 `projection_discontinuity`，图像 ID 不变 |
| UT-06 | 投影质量断点后恢复 | 稳定窗口满足前不得重新开放 TCC；恢复后使用新世界运动段 |
| UT-07 | 15m/s 匀速轨迹中插入一个 10m 离群点 | 速度误差不超过 10%，否则明确 unavailable；异常点不得进入 TCC |
| UT-08 | 最后一点加入 5cm 横向抖动 | 稳健方向变化不超过 10° |
| UT-09 | 同向平行，夹角 `0°–10°` | 不产生正式事件 |
| UT-10 | 反向分离，夹角 `170°–180°` | 不产生正式事件 |
| UT-11 | 90° 交叉、到达差 `<=1s`、同刻距离 `<=0.8m` | 产生正式 `path_intersection` |
| UT-12 | 数学路径有交点但同刻距离 `>0.8m` | 不产生正式事件 |
| UT-13 | 路径交点到达差 `>1s` | 不产生正式事件 |
| UT-14 | 任一方投影、速度或方向不可信 | 不产生正式事件，并给出稳定拒绝原因 |

聚焦测试命令：

```bash
python -m pytest \
  test/test_telemetry_file_reader.py \
  test/test_flight_georeference.py \
  test/test_post_tracking_world_projection.py \
  test/test_tcc_diagnostics.py -q
```

### 5.2 三个已知误报专项验收

完整重放相同 SourceProfile、视频、遥测和 offset，硬门槛如下：

| 事件 | 修复后预期 | 推荐拒绝原因 |
|---|---|---|
| `7ebd0196...` | 稳健方向识别为近反向分离，不再输出正式 TCC | `opposite_direction_separated` 或 `angle_above_max` |
| `198c8ff6...` | 双方识别为近同向，最后横向抖动不得形成 `107.1°` 方向 | `same_direction_parallel` 或 `angle_below_min` |
| `d9ddc314...` | 24.992s 遥测切换不再产生约 9.4m 同步跳变，不再输出正式 TCC | `same_direction_parallel` |

共同门槛：

```text
已知误报重新产生数 = 0/3
像素轨迹保留率 = 100%
因本次修复导致的 association_id 重置数 = 0
车辆计数和候选隔离泄漏数 = 0
```

### 5.3 MP4820 全素材工程验收

使用新的 `run_id/pipeline_id/output-dir`，不得 `--resume` 旧结果；两源串行运行到自然 EOF：

```bash
python scripts/run_native_mps_replays.py \
  --source SRC-MP4820-JS-0813-EW \
  --source SRC-MP4820-JS-0813-WE \
  --frame-stride 3 \
  --adaptive-imgsz \
  --tracking-profile hover_cruise_v1 \
  --output-dir output/native-mps/mp4820-tcc-remediation-<run-id>
```

回放门槛：

#### 输入与投影

- TCC eligible 帧的合格遥测插值覆盖率：`100%`。
- 遥测记录切换造成的固定地面投影附加阶跃：`<=0.25m`。
- 100ms 内、20 条及以上轨迹同时出现 `>3m` 世界跳变：`0 次`。
- `projection_discontinuity` 帧产生的正式 TCC：`0`。

#### 速度与轨迹

- `max_speed_kmh > 200` 的正式轨迹：`0`。
- `max_speed_kmh > 100` 的异常轨迹占比：从当前约 `26.4%` 降至 `<0.1%`；超过者必须有明确质量原因且不得进入 TCC。
- 异常世界段进入速度、方向或 TCC 的数量：`0`。
- 轨迹点、时间戳、帧号和质量谱系对齐失败：`0`。

#### TCC 与证据

- 3 条已知误报重新产生数：`0`。
- 正向合成 TCC 用例检出率：`100%`。
- 新正式事件 `min_same_time_distance_m` 完整率：`100%`。
- 新正式事件双方速度向量、方向置信度、投影质量和算法版本完整率：`100%`。
- 事件原图和检测图 hash、size、尺寸复算通过率：`100%`。
- 所有正式事件完成人工复核前，总体结论保持 `pending_review`。

#### 数据闭环和运行态

- 两源 `natural_eof=true`。
- Kafka 与 road9 按消息 ID、Topic、`source_profile_id + pipeline_id` 精确一致。
- 无旧 Topic、旧 `msg_type`、兼容 fallback 或跨源串线。
- 回放完成后 `pipelines_active=0`。
- Platform 端口、PID、`/ready` 和单实例归属已核对。

#### 性能

- Pipeline processing P95 相对同素材同配置基线退化 `<=10%`。
- 内存峰值增长 `<=15%`。
- 检测推理耗时不得因本次修复显著变化。
- 不新增视频源丢帧或 Kafka 丢消息。

### 5.4 人工复核包

使用现有脚本生成正式事件和确定性负样本复核包：

```bash
python scripts/build_mp4820_tcc_review.py \
  --run-dir output/native-mps/mp4820-tcc-remediation-<run-id> \
  --output-dir output/review/mp4820-tcc-remediation-<run-id> \
  --extract-clips \
  --technical-report output/review/mp4820-tcc-remediation-<run-id>/technical-report.md \
  --html-report output/review/mp4820-tcc-remediation-<run-id>/report.html
```

要求：

- 每条正式事件结论必须为 `confirmed`、`false_positive` 或 `uncertain`。
- `uncertain` 不得计入确认事件。
- 现有 3 条误报作为固定负样本保留，历史数据库复核状态只有在用户明确授权后才更新。
- 无外部穷举真值时，正式 Recall 继续为 `not_evaluated`。

### 5.5 全仓门禁

```bash
python -m pytest platform/tests -q
python -m pytest test/test_kafka_active_trajectories.py test/test_utils_local.py test/test_byte_tracker_core.py -q
cd console2 && npm test && npm run build
python test/test_pipeline_inter_xqh.py
python scripts/audit_adr019_retirement.py --scope local --strict
git diff --check
```

`test/test_pipeline_inter_xqh.py` 的工程基线为 `56 PASS / 0 FAIL / 0 WARN`；该基线不能替代 MP4820 误报专项、全素材自然 EOF 或人工复核。

## 6. 实施顺序

### P0：建立红色反馈环

1. 固化三个事件时段及预期误报结论。
2. 增加遥测阶跃、世界跳变、方向放大和同向/反向分离回归。
3. 保证测试能在旧代码上稳定失败。

### P1：修复根因

1. 实现文件遥测连续插值。
2. 将视觉/位姿不一致纳入正式世界/TCC 阻断。
3. 投影质量断点切分世界运动段。
4. 增加速度离群过滤和滚动速度资格。

### P2：修复 TCC 预测输入

1. 使用同窗口稳健速度与方向。
2. 删除终身最高速度准入。
3. 增加稳定拒绝原因和诊断计数。
4. 补齐 conflict payload 审计字段。

### P3：真实素材验收

1. 先运行三个窗口聚焦回归。
2. 再运行 EW/WE 两源自然 EOF。
3. 完成 Kafka/road9 对账、速度分布审计和全部正式事件人工复核。
4. 通过全部硬门槛后再按 SourceProfile 灰度启用。

## 7. 发布和回滚

建议保留短期配置开关：

```yaml
telemetry:
  interpolation_enabled: true

conflict_detection:
  motion_quality_guard_enabled: true
```

发布策略：

1. 新逻辑先用于 MP4820 本地回放，不影响其他 SourceProfile。
2. 通过真实素材门禁后按 SourceProfile 灰度。
3. 不对历史事件静默重算、删除或改写。

回滚策略：

1. 若新增逻辑出现异常，先关闭受影响来源的正式 TCC，保留像素轨迹和统计。
2. 可关闭新增插值/运动门禁用于只读诊断，但不得在已知阶跃遥测上恢复正式 TCC 输出。
3. 不回滚 Alembic、canonical Topic、历史质量事实或 image-first ByteTrack。

## 8. 风险与控制

| 风险 | 影响 | 控制措施 |
|---|---|---|
| 插值掩盖真实遥测缺口 | 错误恢复世界分析 | 超过最大间隔立即 fail closed；禁止外推；保留左右原始记录 lineage |
| 视觉门禁过严 | TCC eligible 覆盖下降 | 先按 SourceProfile 统计覆盖率和拒绝原因，不以放宽门槛换取事件数量 |
| 绝对速度上限误伤高速目标 | 合法高速轨迹被降级 | 绝对上限与 MAD 同时使用；异常时 unavailable，不改写真实值；按来源审计 |
| 稳健方向窗口过长 | 转弯响应延迟 | 使用时间窗口和最小位移双门槛；真实正向转弯样本必须纳入回归 |
| 新旧事件字段不一致 | 历史详情兼容问题 | 新字段保持可选；旧事实只读保留；新事件要求完整率 100% |
| 只修三个样本导致过拟合 | 其他场景漏检或误报 | 同时保留合成正向、同向、反向、错时、擦肩和质量降级矩阵；执行两源全量回放 |

### 8.1 实施期视觉复核追加门禁

按本方案完成首轮修复后，真实 MP4820 重放仍复现了两类照片即可否定的事件，因此将以下局部门禁纳入本次实施，而不是扩大为检测器重构：

1. 活动轨迹采用最近 30 帧业务类别滚动投票；当前帧映射类别与投票不一致或置信度低于 0.8 时，拒绝 TCC。
2. 冲突双方当前 bbox 必须完整处于画面内；目标已经出画而仅剩裁切框时，不得继续用历史世界速度外推正式事件。
3. 跨类别 bbox 的交集占较小框比例达到 0.8 时，按同一物体上的重复/嵌套检测拒绝，避免把车辆内部的 pedestrian/motor 伪检当作另一参与者。
4. 双方必须在当前采样帧被检测关联；lost-buffer 轨迹不得用上一次 bbox 和历史速度参与当前正式 TCC。
5. 普通交叉冲突要求双方稳健世界方向置信度至少 0.6、冲突夹角至少 60°；低置信方向和低夹角汇入/超车不得用速度差或普通减速升级为横向 TCC。
6. 新事件补充双方类别置信度和画面边界净距；漏斗新增 `class_unstable`、`participant_not_currently_observed`、`participant_not_fully_visible`、`nested_cross_class_detection`、`heading_unreliable`、`general_crossing_angle_too_shallow`。

上述门禁只消费现有跟踪节点的当前检测框、类别和源帧尺寸，不改 YOLO、ByteTrack、Topic、表结构或 Platform 主体。

## 9. 完成定义

只有同时满足以下条件，任务才能从 `待实施` 更新为 `本地工程通过`：

1. 三个已知误报不再输出正式 TCC。
2. 两个已知遥测切换点不再产生多车同步 8–10m 世界跳变。
3. 正向交叉合成用例仍 100% 检出。
4. 像素检测、图像关联、像素轨迹和通用车辆计数无回归。
5. 速度异常分布、事件审计字段和拒绝原因达到本文门槛。
6. EW/WE 两源自然 EOF、Kafka/road9 对账和运行态收口通过。
7. 所有新正式事件完成可审计人工复核。
8. `docs/ARCHITECTURE.md`、`docs/BUSINESS_LOGIC.md`、`docs/API_CONTRACTS.md`、`docs/TASKS.md` 和真实素材验收报告已按实际实现同步。
9. 没有外部批准真值时，交付结论严格写为：

```text
local_engineering_passed
production_accuracy_not_claimed
formal_recall_not_evaluated
```

## 10. 评审结论

本文方案是对现有检测链路的局部前向修复，不是颠覆性重构。修复集中在遥测采样、投影质量、世界运动估计和 TCC 准入四个现有 seam；检测器、图像跟踪、消息拓扑和数据库主体保持不变。中长期的两阶段事件生命周期和独立 TCC 决策模块不属于本阶段完成前置条件。

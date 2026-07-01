# 机非冲突未来轨迹预测设计

> 日期：2026-07-01
> 状态：已确认，进入实现
> 范围：`nodes/ConflictDetectionNode.py`、冲突检测配置、测试与相关文档

## 1. Context

现有 `ConflictDetectionNode` 采用相对运动 CPA/TTC，并保留当前距离 `proximity_threshold_m` 触发。该近距离兜底不符合当前业务定义：冲突点应是预测未来轨迹发生碰撞的情况，而不是单纯机非距离接近。

本设计将第一版范围收敛为纯运动学未来轨迹预测：优先修正业务语义与误报来源，不在本轮引入历史轨迹库、车道中心线或道路几何感知预测。

## 2. Goals

- 只在机非双方预测轨迹会在未来 `0-5s` 内发生时空同步接近时生成 `conflict` 事件。
- 当前距离较近但未来轨迹不会碰撞时不上报。
- `0-3s` 预测碰撞为 `critical`，`3-5s` 预测碰撞为 `warning`。
- 要求空间接近与到达时间接近同时成立：默认碰撞半径 `2.0m`，到达时间差容忍 `1.0s`。
- 保持 Kafka/WebSocket 事件字段兼容：继续输出 `ttc_sec`、`distance_m`、`severity`、双方位置与 `world_anchor_lat_lon`。

## 3. Non-Goals

- 不实现历史轨迹库匹配。
- 不沿 `lane_polygons` / `inferred_lanes` 做曲线预测。
- 不把近距离但无碰撞趋势的事件降级为 `close_call`。
- 不改变 topic 名称、平台消费者、前端冲突回放字段名。

## 4. Algorithm

对于每对 `(motor, non_motor)`：

1. 将双方当前 bbox 中心从像素坐标转为世界坐标米制坐标。
2. 读取双方 `track.velocity_ms`。任一速度缺失、非有限或相对速度低于最小阈值时跳过。
3. 在 `0..prediction_horizon_sec` 上按 `sample_interval_sec` 采样双方未来点：
   - `motor_future(t) = motor_pos + motor_velocity * t`
   - `non_motor_future(t) = non_motor_pos + non_motor_velocity * t`
4. 在同一采样时间 `t` 上计算双方距离，取最小未来距离。
5. 若最小距离 `<= collision_radius_m`，且双方到达时间差 `<= arrival_time_tolerance_sec`，生成事件。
6. `ttc_sec` 使用最早满足条件的未来时间。
7. `distance_m` 使用预测冲突时刻的未来距离，而不是当前距离。
8. 事件发送后该 motor/non_motor pair 进入 confirmed 状态，不重复上报，直到任一轨迹从 buffer 清理。

第一版直线预测在同一时间采样双方未来点，因此到达时间差天然为 `0`；保留 `arrival_time_tolerance_sec` 配置是为了后续改成路径交点/轨迹库预测时仍有稳定接口。

## 5. Configuration

`conflict_detection` 新增/保留配置：

- `prediction_horizon_sec: 5.0`
- `critical_horizon_sec: 3.0`
- `sample_interval_sec: 0.2`
- `collision_radius_m: 2.0`
- `arrival_time_tolerance_sec: 1.0`
- `relative_speed_min_ms: 0.5`

废弃旧配置触发语义：

- `proximity_threshold_m` 不再触发冲突。
- `ttc_threshold_sec` 由 `prediction_horizon_sec` 替代。
- `severity_levels` 不再按当前距离分类。

## 6. Testing

更新 `test_refactor_unit.py`：

- 近距离但未来不碰撞不上报。
- 0-3 秒内未来碰撞上报，severity 为 `critical`。
- 3-5 秒内未来碰撞上报，severity 为 `warning`。
- 未来最近点不进入碰撞半径不上报。
- 同一 pair 只上报一次。
- 两个 motor 或两个 non_motor 不生成机非冲突。

更新 `test_pipeline_no_yolo.py` 和 `test_pipeline_inter_xqh.py` 中的测试配置字段，避免旧字段继续定义过时语义。

## 7. Acceptance Criteria

- `ConflictDetectionNode` 不再使用当前距离阈值作为冲突触发条件。
- 默认配置表达 `0-5s` 未来轨迹预测口径。
- 事件输出保持下游兼容，前端仍能显示 `ttc_sec`、`distance_m`、severity 和双方位置。
- 聚焦测试通过。

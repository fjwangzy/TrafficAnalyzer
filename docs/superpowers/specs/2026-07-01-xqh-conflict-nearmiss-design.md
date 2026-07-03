# xqh 机非冲突 near-miss 误报压制设计

## 背景

当前 `ConflictDetectionNode` 已从“当前距离临界值”改为 `0-5s` 未来轨迹预测，但业务验证中仍出现大量误报。根因是几何预测只能说明机动车与非机动车未来路径可能交汇，不能证明该交汇属于业务定义中的 near-miss：同一时空资源竞争，并迫使一方急刹、急转、停止或让行。

本设计只覆盖 xqh 机非冲突检测口径，不扩散到平台页面、车道标注、其他检测器或 Kafka 消费逻辑。

## 已确认选择

- 第一版场景专项优先：只优化右转机非冲突和无保护左转冲突。
- 全程使用无车道标注参数：不依赖车道线、道路多边形或人工标注。
- 场景识别使用轨迹几何近似：输出字段使用 `suspected_*`，避免把无标注推断包装成强语义。
- near-miss 采用分层触发：极危险 TTC 可直接触发；极近 PET 只作为抢行强度，必须叠加避险行为证据。

## 判定漏斗

1. 轨迹质量门槛：要求有效单应性矩阵、双方世界坐标速度向量、最少历史轨迹点。
2. 预测方向：有历史轨迹时优先使用最近一个有效轨迹段作为未来方向，速度大小沿用测速节点输出；历史不足时才回退到 `track.velocity_ms`，避免线性回归测速方向制造虚假交点。
3. 候选交汇：在 `0-5s` 内检查同刻碰撞半径或预测路径交点。
4. 冲突角过滤：只保留 `30°~150°` 的横向/斜向冲突，过滤同向并行、追尾和近似正面对向。
5. 场景专项：仅保留 `suspected_right_turn_mv_nmv` 和 `suspected_unprotected_left_turn`。
6. near-miss 证据：`hard_ttc_or_pet`（TTC 极危险）可直接触发；`hard_pet` 需要叠加 `hard_deceleration`、`hard_steering` 或 `stop_or_yield`。

## 输出契约

保留既有字段：`motor_id`、`non_motor_id`、`distance_m`、`ttc_sec`、`arrival_time_delta_sec`、`motor_arrival_ttc_sec`、`non_motor_arrival_ttc_sec`、`severity`、`motor_speed_kmh`、`motor_position_m`、`non_motor_position_m`、`world_anchor_lat_lon`。

新增字段：

- `pet_sec`：双方到达冲突点的时间差近似值。
- `conflict_scene`：`suspected_right_turn_mv_nmv` 或 `suspected_unprotected_left_turn`。
- `conflict_angle_deg`：双方当前速度向量夹角。
- `evidence`：触发证据数组，如 `hard_ttc_or_pet`、`hard_pet`、`hard_deceleration`、`hard_steering`、`stop_or_yield`。
- `risk_score`：0-100 的风险分，用于后续排序和页面展示。

## 验收标准

- 危险 TTC/PET 交汇但不属于右转/左转专项场景时不上报。
- 疑似右转机非场景且 hard TTC 时上报 `critical`。
- PET 危险但 TTC 不极端且无避险行为证据时不上报。
- 有历史轨迹时，最近轨迹方向与测速回归方向不一致的错位轨迹不上报。
- 疑似无保护左转普通风险但无避险行为证据时不上报。
- 疑似无保护左转普通风险叠加急减速证据时上报。
- 同一 `motor_id` / `non_motor_id` pair 同级不重复上报，允许升级。
- 无道路/车道标注参数下，xqh 管道测试仍可运行并完成验收。

# 机非冲突事件 BEV 回放设计

> 日期：2026-07-01
> 状态：待用户审阅
> 范围：`traffic-fly-console/src/features/monitoring/` 单路口实时监测页
> 关联任务：T-416 机非分类配置化 + 监控冲突事件列表

## 1. Context

监控页已经通过 `intersection:{id}` WebSocket 接收 `stats`、`track_complete` 和 `conflict` 消息，并在右侧指标区展示最近 20 条冲突事件。当前问题是事件列表只像日志，不像可操作的现场复盘工具；用户需要点击冲突事件后，在上方 BEV 轨迹图中看到 motor / non_motor 双方如何接近冲突点。

本设计选择“事件回放层”：不新建页面，不改变 Kafka/WebSocket 契约，在现有 BEV 地图上增加一个临时的冲突回放上下文。

## 2. Goals

- 冲突事件列表可点击，选中后让 BEV 自动播放该事件的短时轨迹片段。
- 回放同时表达风险关系：双方轨迹、当前位置、冲突点、距离连线、TTC 风险圈、严重度。
- 提供播放控制：自动播放、暂停、重放、倍速、3s / 6s / 10s 窗口切换。
- 轨迹数据不足时仍播放已有片段，并明确显示“轨迹不足”状态。
- 保持现有实时监测能力：未选中事件时 BEV 继续作为实时态势图；退出回放后恢复原状。

## 3. Non-Goals

- 不修改 `conflict` Kafka/WebSocket 消息字段名，不要求后端新增 topic。
- 不实现完整事故调查工作台、历史筛选、视频剪辑或告警处置闭环。
- 不改变 GeoJSON 导出的现有含义；冲突回放层默认不进入导出。
- 不改变冲突检测算法、机非分类规则或阈值。

## 4. UX Design

### 4.1 Conflict List Interaction

右侧“冲突事件”列表中的每条事件变成可点击按钮式行。行内继续展示：

- `severity`
- 事件时间
- `ttc_sec`
- `distance_m`
- `motor_id`
- `non_motor_id`

选中事件后：

- 当前行高亮，使用 severity 对应颜色作为左侧状态条或浅色背景。
- 行内显示一个小的“回放中”状态。
- 再次点击同一事件不会重置播放；点击其他事件会切换到新事件并从头自动播放。

切换路口时清空 `conflictEvents`、取消选中事件、退出回放。

### 4.2 BEV Replay Overlay

BEV 图上新增最高层的 conflict replay layer。进入回放时：

- 当前事件 motor 轨迹使用冷色高亮。
- 当前事件 non_motor 轨迹使用暖色高亮。
- 其他实时、历史、已完成轨迹降低透明度，保留环境感但不抢焦点。
- 双方当前回放位置使用更大的点标记。
- 双方当前位置之间绘制距离连线，线中点显示 `distance_m`。
- 冲突点使用 severity 色的风险圈表示；`critical` 圈更强，`warning` 次之。
- BEV 顶部或左上角显示紧凑控制条：severity、TTC、距离、双方 ID、窗口、倍速、播放/暂停、重放、退出。

播放结束后停在冲突点附近的最后一帧，不自动退出，方便观察。

### 4.3 Playback Controls

默认行为：

- 选择事件后自动播放一次。
- 默认回放窗口为 6 秒。
- 默认倍速为 1x。

控制项：

- 播放 / 暂停。
- 重放，从片段起点重新播放。
- 倍速：0.5x / 1x / 2x。
- 窗口：3s / 6s / 10s。
- 退出回放，恢复实时 BEV。

控制条使用现有按钮、badge、font-mono-cto 风格，保持监控页的高密度运维界面气质。

## 5. Data Model

### 5.1 Existing Inputs

从 WebSocket 已有数据构建回放，不要求后端改约：

- `conflict`：事件元信息，包括 `motor_id`、`non_motor_id`、`motor_position_m`、`non_motor_position_m`、`distance_m`、`ttc_sec`、`severity`、`world_anchor_lat_lon`。
- `stats.active_trajectories`：当前活跃轨迹尾部快照。
- `track_complete`：车辆离场后的完整轨迹。
- monitoring 页本地 `sessionActiveTrajectories`：按 `track_id` 累积的活跃轨迹尾部点列。

### 5.2 Frontend Derived State

Monitoring 页新增状态：

- `selectedConflictEvent`: 当前选中的冲突事件或 `null`。
- `replayWindowSec`: `3 | 6 | 10`，默认 `6`。
- `playbackState`: `playing | paused | ended`。
- `playbackSpeed`: `0.5 | 1 | 2`，默认 `1`。
- `playbackStartedAt`: 浏览器时间戳，用于计算回放进度。

BEV 组件新增可选 props：

- `selectedConflictEvent`
- `conflictReplayTracks`
- `conflictReplayState`
- `onReplayStateChange`

也可以把这些 props 收敛为一个 `conflictReplay` 对象，避免 props 膨胀。

### 5.3 Replay Track Resolution

选择事件后，前端按 `motor_id` 和 `non_motor_id` 从以下来源找轨迹：

1. `sessionActiveTrajectories`
2. `activeTrajectories`
3. `completedTrajectories`

优先使用 `trajectory_world_m`；缺失世界坐标时，该轨迹不参与地图回放。`conflict` 消息里的双方位置仍可作为单点 fallback。

如果找到的轨迹点不足以覆盖完整窗口：

- 仍播放已有点段。
- 控制条显示“轨迹不足”。
- 如果只有单点，则显示双方点位、距离线和风险圈，不做线段动画。

## 6. Component Design

### 6.1 Monitoring Page

`traffic-fly-console/src/features/monitoring/index.tsx` 负责：

- 管理选中事件和播放控制状态。
- 将 conflict list 行改为可点击项。
- 在路口切换时重置回放状态。
- 从本地轨迹缓存中解析 motor / non_motor 的回放轨迹。
- 向 `BevMap` 传入 `conflictReplay` 对象。

### 6.2 BevMap

`traffic-fly-console/src/features/monitoring/bev-map.tsx` 负责：

- 增加独立 `conflictSource` / `conflictLayer`，zIndex 高于 active trajectory layer。
- 根据播放进度截取双方轨迹片段并重绘。
- 将 `motor_position_m` / `non_motor_position_m` 转为地图坐标，绘制距离线和风险圈。
- 回放开始时可轻微 fit 到双方轨迹范围，避免用户选中事件后看不到高亮；只在事件切换时 fit，不在每帧动画时 fit。
- 不修改历史、实时、active 三层数据源和 GeoJSON 导出。

### 6.3 Helpers

在 `bev-trajectory-utils.ts` 或新建同目录工具文件中补充纯函数：

- `findTrajectoryByTrackId(...)`
- `buildConflictReplayTracks(...)`
- `sliceTrajectoryForReplay(...)`
- `worldPointToLonLat(...)` 可复用现有 `worldToLonLat`

纯函数优先加单元测试，避免把回放逻辑写死在 React effect 内。

## 7. Error Handling And Edge Cases

- 无 `selectedConflictEvent`：BEV 行为与当前版本一致。
- 事件缺少 `motor_id` 或 `non_motor_id`：列表仍显示，点击后只显示事件点位和“轨迹不足”。
- 缺少 `world_anchor_lat_lon`：优先使用轨迹自身 anchor；仍缺失时使用路口中心 fallback。
- 两条轨迹都缺失世界坐标：不进入动画，只在控制条提示“缺少世界坐标”，并保留事件列表选中态。
- 新冲突事件到达：不打断当前回放，只插入列表顶部。
- 切换路口：清空事件、轨迹缓存和回放状态。
- 检测流停止：已选事件可继续查看已有回放；实时轨迹停止更新。

## 8. Testing Plan

### Unit Tests

更新或新增 `traffic-fly-console/src/features/monitoring/*test.ts`：

- 按 track id 从 active / session / completed 轨迹源中解析 motor / non_motor。
- `sliceTrajectoryForReplay` 在 3s / 6s / 10s 窗口下返回稳定片段。
- 轨迹不足时返回可展示状态，而不是空失败。
- 缺失世界坐标时输出明确 fallback 状态。

### Build Verification

在 `traffic-fly-console/` 运行：

```bash
npm run build
```

### Manual Verification

在本地平台与检测器启动后验证：

1. 监控页收到 `conflict` 后，事件列表出现新行。
2. 点击事件行，BEV 自动播放双方接近冲突点动画。
3. 暂停、重放、倍速、3s / 6s / 10s 切换可用。
4. 轨迹不足事件仍显示已有片段和“轨迹不足”。
5. 切换路口后列表与回放状态清空。

## 9. Acceptance Criteria

- 用户可以从冲突事件列表点击任一事件，并在同一屏 BEV 中看到对应回放。
- BEV 回放包含双方轨迹、双方当前位置、冲突点、距离线、TTC / distance / severity 信息。
- 回放控制支持自动播放、暂停、重放、倍速、3s / 6s / 10s 窗口。
- 轨迹不足时不隐藏事件，也不报错；界面展示可用片段和“轨迹不足”状态。
- 未选事件或退出回放后，BEV 原有实时/历史轨迹展示保持兼容。
- Kafka/WebSocket `conflict` 消息字段保持兼容。
- 前端构建通过。

## 10. Implementation Notes

- 建议先做纯函数和状态模型，再改 UI；这样能用单元测试保护轨迹匹配和窗口切片。
- OpenLayers 动画不需要引入新库，用 `requestAnimationFrame` 驱动 progress 即可。
- 控制条不要做成大面板，避免遮挡地图；保持紧凑、贴边、可快速退出。
- 列表项应使用原生 button 语义或带键盘可访问的交互元素。
- 避免在每一帧创建长期残留 Feature；回放层每帧可 clear + redraw 当前少量 feature。

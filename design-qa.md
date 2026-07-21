# Design QA

- source visual truth path: `browser:Comment 1 / 数据质量 · 实时` 与 `browser:Comment 1 / 检测器视频流没显示`
- implementation screenshot path: `Codex in-app browser capture / 2026-07-21 09:39 / SRC-MP4NEW2-CH-0715-PM`
- viewport: 1357 × 912 desktop, dark theme
- state: SourceProfile `SRC-MP4NEW2-CH-0715-PM`, Pipeline camera 13 running, detector main view

**Full-view comparison evidence**

- 标注前画面包含底部居中的“数据质量 · 实时/过期”胶囊；实现后 `.map-label.label-south` 节点为 0。
- 问题截图的检测主画面为空；实现后浏览器截图可见完整检测器叠框视频，DOM 读取自然尺寸为 1280 × 720。
- 顶部来源、双侧态势面板、BEV、事件区和时间轴的布局、字体、颜色及内容保持不变。

**Focused region comparison evidence**

- 中央视频区域：检测画面恢复，未新增遮挡或伪造占位图。
- 原数据质量浮层区域：节点和专用 CSS 均已删除，背景视频连续显示。

**Findings**

- 无剩余 P0/P1/P2 视觉差异。
- 字体与排版：沿用现有 Console2 字体层级，无变化。
- 间距与布局节奏：删除浮层未改变主画面、侧栏或时间轴尺寸。
- 色彩与视觉令牌：未新增颜色；移除原黄色质量胶囊。
- 图片质量与资产一致性：使用真实 MJPEG 检测画面，1280 × 720，无占位资产。
- 文案与内容：仅删除用户指定的“数据质量 · 实时/过期”；其他状态文案保留。

**Comparison history**

1. 初始：检测流连接可能保持空白，且数据质量胶囊仍在画面中央。
2. 修复：增加无首帧看门狗并删除浮层；重建 Console2 后真实流恢复，节点为 0，浏览器 console 无 error/warn。

**Implementation Checklist**

- [x] 删除数据质量浮层 JSX 与废弃样式。
- [x] 覆盖 MJPEG 无首帧连接的自动重连。
- [x] 生产构建及真实浏览器验证。

**Follow-up Polish**

- 无阻断项。

final result: passed

---

# Design QA · 实时轨迹数量主卡（2026-07-21）

- source visual truth path: `browser:Comment 1 / 6.6 / 10 拥堵指数 / 实时计算`
- implementation screenshot path: `Codex in-app browser capture / 2026-07-21 15:53 / SRC-MP4NEW-CH-0625-AM`
- viewport: 1357 × 713 desktop reference；实现以同一桌面断点复核，dark theme
- state: 崇华路运行中检测源，实时统计与 `active_trajectories` 持续更新

**Full-view comparison evidence**

- 左侧首卡保持原有 91px 卡高、圆形主数值、三段文案和右侧图标位置；两侧面板、视频、BEV 与时间轴均未改版。
- 原卡的 `/ 10`、`拥堵指数`、`中度拥堵`、`实时计算` 已替换为实时轨迹语义；浏览器实测显示 `248 条 / 实时轨迹数量 / 活动轨迹 / 实时更新`。
- DOM 同时显示右侧 `活动轨迹 248 · 世界坐标投放`，与主卡数量同源一致。

**Focused region comparison evidence**

- 左侧首卡：数值没有截断，`实时轨迹数量` 单行显示，圆环、文字列和图标无重叠。
- 该改动不涉及图片资产；检测器真实 MJPEG 画面仍完整显示。

**Findings**

- 无剩余 P0/P1/P2 视觉差异。
- 字体与排版：沿用现有字体、字重、字号与行高，长文案未换行。
- 间距与布局节奏：卡片尺寸、内边距、列宽、圆环和相邻指标网格保持不变。
- 色彩与视觉令牌：复用现有琥珀色状态令牌，没有新增颜色或渐变。
- 图片质量与资产一致性：无新资产；真实检测视频未受影响。
- 文案与内容：不再展示拥堵指标；主数值严格来自最新有效 `uav_stats.active_trajectories.length`，过期时显示暂无实时数据。

**Comparison history**

1. 初始：首卡展示拥堵指数、拥堵等级和 `/ 10`，与用户指定业务指标不符。
2. 修复：替换为实时轨迹数量和新鲜度状态；浏览器复核数量与右侧活动轨迹一致，无布局回归。

**Implementation Checklist**

- [x] 主卡改为实时轨迹数量。
- [x] 过期数据不冒充实时数量。
- [x] 保持现有布局和视觉令牌。
- [x] 回归测试和真实浏览器复核。

**Follow-up Polish**

- 无阻断项。

final result: passed

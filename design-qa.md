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

# 首页路口与路段态势地图 Design QA（2026-08-04）

## Source truth

- 参考图：`/var/folders/pn/nqzgl4zn26v8_864_4nws7_r0000gn/T/codex-clipboard-d94ad4e2-f822-4ff2-8adc-60033a4b533f.png`（2546 × 1674）
- 用户标注前：`console2/.design-qa/2026-08-04-dashboard-situation-final-kpi-1357x912.png`（1357 × 912，包含待删除的路口态势详情面板）
- 最终实现：`console2/.design-qa/2026-08-04-dashboard-without-situation-detail-1357x912.png`（1357 × 912）
- 稳定四色默认态：`console2/.design-qa/2026-08-04-dashboard-stable-color-grading-1168x912.png`（1168 × 912）
- 面板删除前后对照：`console2/.design-qa/2026-08-04-dashboard-detail-removal-comparison-2714x912.png`
- 全屏并排对照：`console2/.design-qa/2026-08-04-dashboard-situation-comparison-kpi-final.png`
- 地图聚焦对照：`console2/.design-qa/2026-08-04-dashboard-situation-map-focus-kpi-final.png`

## Environment and state

- route: `/`
- browser: Codex in-app Browser
- final viewport: 1357 × 912 CSS px，截图 1357 × 912，device pixel ratio 1；上一轮另保留 1965 × 1280 宽屏证据。
- state: authenticated admin，周五 07:55 典型时段，92 个服务器态势路口、147 条态势路段、1 个服务器匹配无人机覆盖路口、3 路视频源
- comparison: 参考图与实现图先分别等比缩放并置于同尺寸 1273 × 837 面板，再做同一输入下的全屏与地图聚焦对照；未把参考产品的左侧诊断栏强行复制到既有工作台，因为确认方案要求保留现有 KPI、地图和右侧业务卡片布局。

## Full-view comparison

实现沿用既有云瞳暗色工作台、顶部故事线、KPI 和右侧业务卡片，将中央地图升级为三层态势。视觉中心仍是地图；路网采用低亮度蓝黑底，路口按绿/黄/红/灰状态分级，项目路口保留外圈，无人机覆盖以独立蓝色 Phosphor Drone 图标和聚合数量置于最高图层。与参考图共同保持了高密度路网、状态色标识、暗色诊断语义和地图主导的信息层级。

周五 07:55 的前三个 KPI 均由服务器响应汇总；本轮实际响应为 92 个态势路口、33 个过饱和路口、22 条拥堵路段。机非冲突与治理提升继续明确标记为演示数据。无人机覆盖数量保留在地图标注中，不混入服务器态势 KPI。

## Focused comparison

- 路口层：95 个可见路口标记（92 个服务器态势路口与缺少态势的项目路口并集），颜色边界对应饱和度规则；项目路口外圈不覆盖指标色。
- 路段层：147 条服务器路段按延误指数绘制，LineString 与 MultiLineString 都转换为可交互路径，层级低于路口和无人机。
- 无人机层：只有能对应服务器态势路口的 1 个路口上图，聚合 3 路视频源；本地项目坐标仍可灰显，但不能让走廊或测试源伪装成服务器覆盖。
- 地图叠层：保留星期与 5 分钟时槽选择器以及状态图例；按用户标注删除路口名称、最大饱和度、服务水平、最差路段、速度、排队和监控按钮组成的 `.situation-map-detail`，地图不再被该面板遮挡。

## Interaction and browser checks

- 星期切换为周五、时间切换为 07:55 后，控件值稳定为 `day_of_week=5`、`step_index=95`，地图为 95 个路口标记、1 个服务器匹配无人机标记。
- 第一轮发现原生 `type=time` 在切换时可能短暂产生 `NaN` 并发出无效请求（P2）；已改为固定 288 项、每 5 分钟一步的选择器，复测通过。
- 点击普通路口后只更新地图选中态，URL 保持 `/`；`.situation-map-detail` 节点始终为 0，不再显示指标详情面板。
- 点击地图无人机图标后进入 `/monitoring?intersection_id=INT_MP4728_JINGSHI_CORRIDOR&source_profile_id=SRC-MP4729-JS-0729-3MS`，验证了聚合后的运行中/有效源选择与监控跳转。
- 删除详情面板后，时段工具条、状态图例、路口/路段/无人机图层均保持原布局与层级。
- 页面 `scrollWidth === innerWidth`、`scrollHeight === innerHeight`，同视口无横向或纵向溢出。
- 最终浏览器 Console 为 0 error / 0 warning。

## Findings and fixes

- P2 fixed：时间输入的瞬态空值会产生 `NaN`；替换为确定性的 5 分钟时槽选择器。
- P2 fixed：早期加载阶段项目路口和无人机覆盖数会暂时显示 0；最终状态随查询完成收敛为项目 4、服务器匹配覆盖 1、视频源 3，并保持服务器态势不回退 mock。
- P1 fixed：本地项目/测试坐标原可让未匹配服务器态势路口的视频源上图；现在路口并集显式保留 `has_server_situation` 来源标记，无人机层只接受服务器匹配路口。
- P2 historical：早期详情面板曾遮挡最西侧无人机标记，地图自动取景因此保留左侧安全区；当前详情面板已按新反馈删除。
- P2 fixed：用户标注的路口态势详情面板遮挡地图；已删除面板 JSX、专用样式和冗余路段计算，浏览器验证节点数为 0。
- P2 fixed：按当前上海时间进入周二 23:10 时，服务器数据只有绿色与灰色，视觉上像未分级；默认时段现固定为周五 07:55，同一服务器典型矩阵稳定呈现 56 绿、2 黄、33 红、4 灰。
- P3 accepted：参考图使用另一套左侧诊断信息架构；按已确认范围保留本项目顶部 KPI 与右侧演示卡片，仅复用地图密度、状态色、时段控制、图例与无人机叠加表达。

final result: passed

---

# Design QA · 路口项目工作台 B 方案（2026-07-22）

- source visual truth path: `/var/folders/pn/nqzgl4zn26v8_864_4nws7_r0000gn/T/codex-clipboard-7ea7bb8c-94bb-441b-a0b3-0456016637c5.png`
- current draft screenshot path: `/Users/yaoyao/.codex/visualizations/2026/07/22/019f8781-04fc-7642-8f7e-33281848d46e/16-current-draft-b-audit.png`
- published overview screenshot path: `/Users/yaoyao/.codex/visualizations/2026/07/22/019f8781-04fc-7642-8f7e-33281848d46e/18-overview-b-final-audit.png`
- version comparison screenshot path: `/Users/yaoyao/.codex/visualizations/2026/07/22/019f8781-04fc-7642-8f7e-33281848d46e/14-version-compare-open.png`
- normalized side-by-side path: `/Users/yaoyao/.codex/visualizations/2026/07/22/019f8781-04fc-7642-8f7e-33281848d46e/17-b-reference-current-final.png`
- viewport: reference 1586 × 992；implementation 1357 × 912，device scale 1；side-by-side 将 reference 等比归一到 1357 × 912
- state: 当前项目 `IPR-2316df5aa119c35953467a12`；概览使用 `lane_verified v1`、23 条车道、6/6 门禁，编辑器使用真实 `draft v2`、68% / 2/5 阶段、6/9 门禁；抽帧修复后已载入真实关键帧 `FRM-C4DF19FD1CF8`

**Full-view comparison evidence**

- 顶部项目栏、左侧档案与五阶段进度、中部五页签和主画布、右侧任务/质量/版本、底部唯一下一步动作均按 B 方案重排为单屏三栏工作台。
- 中央画布保持视觉主导地位；有关键帧时展示真实正拍影像和服务端车道几何，无关键帧时自动使用完整 GCJ-02 路网，不使用占位资产。
- 渠化拟合页按当前 `inter_id` 隔离关键帧任务；当前项目不再混入其他路口的 XQH 任务，旧 `/admin/calibration?tab=lanes` 深链仍保持兼容。
- 工作台补取完整地图详情，避免 workspace 摘要把 23 条车道误显示为“待拟合”；项目已有地图时不再与 bootstrap 竞态覆盖版本。

**Focused region comparison evidence**

- 左栏：档案字段、项目就绪度和五阶段与 B 稿信息层级一致；概览的 `lane_verified` 为 5/5，编辑器的 `draft v2` 为 68% / 2/5，不再用项目已发布状态掩盖正在编辑的草稿。
- 中栏：画布顶部选择器、右侧竖向工具、左下图例、右下迷你地图、底部编辑工具和下一步操作均落在 B 稿对应位置。
- 右栏：待办、关键帧素材、9 项质量门禁、高级配准参数和版本状态分卡呈现；素材面板默认收起，由“载入正拍关键帧”任务打开，不再挤掉质量与版本卡片。
- 概览“版本对比”可展开并选择真实 `draft v2` 对照 `lane_verified v1`；发布后的“进入运行应用”CTA 实际进入 Runtime 页签，不再错误回到拟合页。
- 车道编辑：单击任一参考/拟合车道后按 `link_id` 高亮并拖拽整组，双击改为琥珀色单车道编辑并出现顶点控制柄；删除、拆分、合并按钮随选择范围启停。

**Findings**

- 无剩余 P0/P1/P2 视觉或核心交互差异。
- 字体与排版：沿用 Console2 中文系统无衬线字体；顶部、分栏标题、标签和辅助文字的层级与 B 稿对齐。
- 间距与布局节奏：三栏比例、8px 卡片圆角、画布边界、页签和底部操作条在 1357 × 912 视口无裁切或重叠。
- 色彩与视觉令牌：使用深海军蓝底、蓝色交互态、绿色通过态和琥珀待办态；参考车道由初版绿色收紧为 B 稿蓝色低透明叠加。
- 图片与资产：保留真实正拍关键帧、现有品牌资产和 Phosphor 图标；无伪造插图、占位框或手绘 SVG 图标。
- 文案与内容：实现使用真实路口/版本/门禁动态数据；设计稿为已加载正拍影像的发布态，当前项目编辑器为无关键帧的草稿态，影像与完成度差异属于业务状态差异，不用假数据消除。
- 可访问性：主导航、画布选择器、版本对比面板、素材折叠和 CTA 均有语义化角色/名称；截图不能证明键盘遍历顺序、读屏完整性或色觉对比合规，这些仍需专项测试。

**Comparison history**

1. 初始实现：长纵向配置表单、画布首屏占比不足、右侧信息无明确层级，并混入非当前路口关键帧。
2. 第一轮工作台：完成 B 稿三栏结构和真实画布接入，但参考路网仍偏绿、发布状态仍显示待办。
3. 完成校对：补齐地图详情水合与 bootstrap 竞态防护，修正草稿阶段、素材折叠、6/6/9 项门禁、版本对比和 Runtime 路由；当前真实草稿/发布两种状态均无首屏纵向溢出。

**Audited flow**

1. 渠化拟合草稿：健康。真实 `draft v2` 显示 68% / 2/5、2 个待办和 5/9 门禁；素材面板默认收起。
2. 素材面板：健康。点击“载入正拍关键帧/关键帧与素材”展开现有抽帧和测绘关键帧路径，关闭后恢复 B 稿右栏密度。
3. 项目概览：健康。`lane_verified v1`、23 条车道、6/6 门禁和 Runtime 下一步一致。
4. 版本对比：健康。真实历史列表显示当前 v1 与草稿 v2，并可切换对照版本。
5. 运行应用：健康。右栏和底部 CTA 均进入 `?tab=runtime`，可见当前 `lane_verified` 与不可变 Bundle 规则。
6. Link 车道编辑：健康。真实 Link `12wwe297gwwe29k101` 单击选中 3 条车道；双击仅保留 1 条和 8 个控制柄；拆分后 3→4、删除后 4→3，重载后合并 3→1 且保留单车道编辑状态。733px 中栏下工具栏为 72px 双行布局，`scrollWidth=width`，无裁切。

**Implementation Checklist**

- [x] B 方案单屏三栏项目工作台及五页签。
- [x] 真实正拍关键帧、路网叠加、图层控制、拟合工具和版本操作。
- [x] 当前路口关键帧隔离与旧深链兼容。
- [x] 137 项 Console2 测试、生产构建、`git diff --check` 和真实浏览器 DOM/视觉验收。
- [x] Platform 全量 `201 passed / 5 skipped / 10 subtests passed`。
- [x] XQH 真实视频/SRT 管道回归 `56 PASS / 0 FAIL / 0 WARN`，GCJ-02 锚点约 `117.028271, 36.703260`。
- [x] 浏览器无脚本崩溃或错误横幅；既有编辑 tab 仅记录源码热更新时产生的 1 条 React dependency-array 长度变化警告，完整重载及后续选择/拆分/删除/合并未新增错误，生产构建通过。
- [ ] ADR-019 `--scope local --strict` 的代码与拓扑检查全部通过，但仓库级 `local_runtime_evidence` 仍是既有外部门禁；不属于本页面设计实现完成条件，也不冒充发布绿色。

**Follow-up Polish**

- P3：项目补齐行政区、所属道路和责任人字段后，左侧档案可自然达到 B 稿相同的信息密度；当前数据模型尚未提供这些事实，不阻断交付。

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

---

# 路网标注对标升级 Design QA

## Source truth

- 参考全局对齐：`/private/tmp/trafficanalyzer-road-annotation-reference-global-align.png`
- 参考局部控制柄：`/private/tmp/trafficanalyzer-road-annotation-reference-local-handles.png`
- 参考标线样式：`/private/tmp/trafficanalyzer-road-annotation-reference-marking-style.png`
- 实现全局对齐：`/private/tmp/trafficanalyzer-road-annotation-implementation-global.png`
- 实现曲线精调：`/private/tmp/trafficanalyzer-road-annotation-implementation-curve.png`
- 实现干净渠化图：`/private/tmp/trafficanalyzer-road-annotation-implementation-clean-pass3.png`
- 最终参数化设计器：`/private/tmp/trafficanalyzer-road-annotation-implementation-parameter-final.png`
- 崇华路候选重载：`/private/tmp/trafficanalyzer-road-annotation-chonghua-after-reload.png`
- 边界修复与最终保存重载：`/private/tmp/trafficanalyzer-road-editor-acceptance-20260803.png`

## Environment

- route: `/admin/calibration/editor?project_id=IPR-2316df5aa119c35953467a12&inter_id=011wwe29k1q00001`
- viewport: 1334 × 750 CSS px
- screenshot: 1334 × 750 px
- device pixel ratio: 1
- state: authenticated admin, 崇华路 v2 candidate, `FRM-C4DF19FD1CF8`, 23 lanes

## Full-view comparison

第一轮对照确认整体配准区保持固定无人机影像，覆盖层提供 X/Y、角度、统一缩放、透明度和复位；右侧任务、质量门禁及版本状态保持既有工作台信息架构。实现没有复制参考产品皮肤，而是复用了本项目暗色工作台和现有控件体系。

2026-08-03 浏览器复核反馈指出整体配准浮层遮挡画布。已将其改为默认 244×34px 的单行位姿摘要，主动展开后才显示 X/Y、角度、缩放、透明度与复位；展开态也收紧为 270px，并移除常驻说明文字，减少对正拍证据图的覆盖。

崇华路实数页面在保存并重载后同时呈现 23 条参考车道和 23 条拟合车道，状态为 `candidate`。发布动作保持禁用，符合不可变 `lane_verified` 与人工复核边界。

## Focused comparisons

### 曲线控制柄

选中单车道后可把指定边界段转换为三次 Bézier；两个控制柄可拖动，提交时转为确定性采样点。全局姿态变化和撤销重做均保持曲线控制点一致。

### 干净渠化图

第一轮发现道路底色、车道线和要素对比度偏低，模板在 3840 × 2160 画布中过小（P2）。第二、三轮提高道路与标线对比度，并按关键帧尺寸自适应进口长度、展宽和车道宽度；最终四进口模板在主画布占比清晰，crosswalk、channelizing island 和 lane marking 可辨识。

## Interaction and browser checks

- 整体 X 位移会改变车道 polygon，撤销后恢复到逐字符相同的 points。
- 生成四进口模板得到 16 条车道与 8 个要素，进口车道数改为 3 后联动为 17 条车道。
- 四个进口骨架均有拖拽手柄；拖动反向更新方向角和进口长度，再从同一 `editor_model` 重建几何。
- 1180 × 720 视口下 `scrollWidth === innerWidth`，无横向溢出。
- 崇华路 v2 保存后重载自动恢复 23 条拟合车道，当前状态保持 `candidate`。
- 右侧边缘 Link 可从 `maxX=3840` 向画面外拖到 `4731`；四个顶点统一 `ΔX=891px`、`ΔY=0`，未被影像边界夹紧或扭曲。验证后重载恢复未保存状态。
- 再次保存并重载后抽查车道 `points` 逐字符一致；页面为 23 条参考车道 + 23 条拟合车道，v2 保存为 `freeform` 像素模型。
- 原始 pixel → ENU 单应矩阵为只读诊断项；控制点为空，因此不据此声明地图精度。
- 浏览器验收过程未观察到未处理的页面异常或控制台错误。

## Findings

- P2 fixed: 干净渠化图对比度和模板尺度不足。
- P2 fixed: 保存成功后旧 workspace cache 一度把 `candidate` 状态覆盖回 `draft`。
- P2 fixed: 不同 Link 的合法转向流被全局车道面重叠检查误拒绝，现收紧为同一 Link 域内互斥。
- P1 fixed: 现有车道/Link/顶点曾被影像边界钳制，只能向画面中间拖；现有几何改为无界编辑坐标，新增绘制仍限定在证据图内。
- P1 fixed: 自由 Bézier 控制信息和 Feature 曾在无参数骨架时无法保存；新增 `freeform` 模式并完成保存重开回归。
- P2 fixed: 已发布版本派生原由 Console 自行复制，缺少服务端来源链；现改为 `derive-draft` 并重置复核。
- P1 fixed: 冷登录时 workspace 摘要曾先占用地图详情缓存键，完整 `editor_model` 到达后仍显示 0 条草稿；水合键现包含模型模式和像素几何数量，候选保护逻辑直接读取权威详情，冷登录重载恢复 23 条。
- P3 accepted: 真实崇华路关键帧没有批准控制点真值，质量面板保持待复核，发布门禁不解锁。

final result: passed

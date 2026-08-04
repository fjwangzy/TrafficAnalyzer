# 路网标注对标升级逐项验收（2026-08-03）

## 结论

计划中的第一期对齐/精调和第二期参数化设计器均已实现，并通过单元、Console 交互、Platform 接口及崇华路真实浏览器验收。当前结论是“工程实现通过”，不是“生产地图精度通过”：真实关键帧没有批准控制点真值，视觉配准与发布前人工复核仍保持未通过。

## 需求—证据矩阵

| 计划项 | 实现与契约 | 自动化/真实证据 | 状态 |
|---|---|---|---|
| 固定正拍图，统一覆盖层平移/旋转/缩放/透明度 | `ChannelizationCalibrationPage` + `registration_pose/v1` | pose 组合/逆变换、页面交互、服务端重算测试 | 通过 |
| 数值输入、复位、撤销/重做 | 整体配准面板与 editor history | geometry history + LiveModules | 通过 |
| Link/单车道/顶点精调且保持拓扑 | 既有 Lane draft 工具复用，整体变换同步 Lane/Feature/model | Link rigid drag、single-lane drag、split/merge tests | 通过 |
| 车道可向影像外拖拽 | 编辑既有几何不再传 image bounds；新增点仍受限 | 单元 + Console pointer；真实 Link `3840→4731`，四点 `ΔX=891/ΔY=0` | 通过 |
| 三次 Bézier 边界 | 控制柄保存在 pixel geometry；提交确定性采样 | curve sampling、submit、freeform reopen tests | 通过 |
| 原始 H 只读，服务端拥有最终组合权 | `H_final=H_task×inverse(T_pose)` | 客户端漂移 422、有效姿态重算测试 | 通过 |
| 旧 `polygon_px` 兼容 | `editor_model` 仍可选；再次保存补 `freeform` | Pydantic/fit payload 与真实旧候选重存 | 通过 |
| 参数化四进口骨架 | `editor_model(mode=parameterized)` | 16→17 车道联动、骨架反向更新测试 | 通过 |
| 逐车道转向、右转道、公交/潮汐属性 | 每个进口车道独立控件与生成属性 | geometry generation + Console UI build | 通过；专用 Runtime 规则明确未实现 |
| 模板化 Feature | crosswalk、channelizing island、waiting zone、stop line、lane boundary、lane marking | 生成测试 + Platform 正式 Feature 持久化 | 通过 |
| 影像叠加/干净渠化图共享模型和视口 | 同一 SVG `viewBox`，仅影像层开关 | Console clean-mode test | 通过 |
| 人工覆盖保护 | `manual_overrides` 复用当前 Lane/Feature | parameter generation test | 通过 |
| 发布不可变与派生草稿 | 服务端 `derive-draft`，记录来源并重置复核 | API endpoint test；源 `lane_verified` 状态/质量不变 | 通过 |
| Runtime 不消费 editor metadata | runtime-bundle 剔除 `editor_model` | 实时 v1 Bundle：23 lanes，metadata=false | 通过 |
| 不影响 trajectory/geo/speed/direction/TCC 独立门禁 | 仅校准 API、Console 与地图 JSON；Runtime Bundle 形状不扩张 | 42 个相关根测试 + XQH 基线 | 通过 |

## 崇华路真实验收

- 项目：`IPR-2316df5aa119c35953467a12`
- 路口：`011wwe29k1q00001`
- 关键帧：`FRM-C4DF19FD1CF8`，3840×2160
- v2 `CMV-295cb58c07cf4faf93cfb3fa`：`candidate`，23 条车道，`editor_model.mode=freeform`，23 条像素几何；保存前后抽查 SVG `points` 逐字符一致。
- Platform 重启后的冷登录/冷缓存重载再次恢复 23 条拟合车道；workspace 摘要不会再抢先阻断完整像素模型水合。
- v1 `CMV-e00cef599ed44e35add1aa67`：仍为 `lane_verified`，23 条车道；Runtime Bundle 仍为 23 条且 topology 不含 `editor_model`。
- 发布按钮仍因视觉配准精度与人工复核未通过而禁用；没有写入或冒充批准真值。
- 截图：`/private/tmp/trafficanalyzer-road-editor-acceptance-20260803.png`。

## 自动化门禁

- Console2：19 files / 166 tests passed；production build passed。
- Platform：259 passed / 5 skipped / 10 subtests passed。
- 相关根测试：42 passed。
- XQH：55 PASS / 0 FAIL / 1 WARN；warning 为前 100 帧方向统计为空。
- `git diff --check`：通过，仅报告用户既有 `elements/FrameElement.py` CRLF 提示。
- ADR-019 strict：所有代码/拓扑项通过；既有外部门禁 `local_runtime_evidence` 仍为 blocker，不将其写成绿色。

## 精度边界

截图、23 条完整性和像素级复现只证明工程链与交互可恢复。控制点为空且没有外部批准真值，因此地图精度、IDF1/HOTA、位置 RMSE、速度 MAE 与正式巡航准确率继续为 `not_evaluated`。

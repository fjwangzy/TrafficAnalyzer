# I4 执法线索垂直切片实施与审计（2026-07-15）

## 1. 当前运行态审计

本审计在 Console2 `4176` 当前运行实例完成，覆盖 `/enforcement`、`/enforcement/trucks`、`/enforcement/zones` 和候选区域表单。截图位于 `console2/.design-qa/i4-audit/`。

| 步骤 | 页面/任务 | 当前健康度 | 证据 | 关键发现 |
| --- | --- | --- | --- | --- |
| 1 | 线索列表与详情 | 阻断 | `01-clues.png` | KPI、线索、雷达、证据和投递状态全部硬编码；复核只修改 React 内存，刷新丢失。 |
| 2 | 货车专题 | 阻断 | `02-truck.png` | 实时车辆和统计为模拟值，没有 `as_of`、stale 或断链状态。 |
| 3 | 区域与规则 | 阻断 | `03-zones.png` | 演示几何被显示为已发布权威版本，本地候选与权威发布边界不真实。 |
| 4 | 候选区域表单 | 高风险 | `04-zone-form.png` | “新建候选”复用了当前已选区域数据；保存只发本地 toast，没有 revision、审计或持久化。 |

可访问性边界：当前页签是普通按钮而非 `tablist/tab`；抽屉和候选表单缺少完整 dialog 语义、可访问关闭名称和焦点管理。当前审计只覆盖桌面视口、DOM 语义和键鼠主路径，未宣称通过读屏器或移动端验收。

## 2. PRD → UI → 数据差距矩阵

| PRD 能力 | 当前 UI | 当前数据 | I4 本地工程切片 | 外部阻断 |
| --- | --- | --- | --- | --- |
| 候选围栏版本 | 展示“已发布”Mock | 无表 | `uav_enforcement_zones` 仅允许 `candidate/retired`；revision 并发和审计 | 权威来源、坐标与发布制度 |
| 候选规则版本 | 只显示规则名 | 无表 | `uav_enforcement_rules` 保存候选事实 schema，关联共性规则版本 | 规则条件、阈值、例外和审批 |
| AI 线索 | 三条 Mock | 无持久化 | `uav_ai_events(event_type=enforcement_clue)` + 一对一 `uav_enforcement_clues` | 正式规则引擎准确率与验收集 |
| 视频/雷达速度 | 演示值 | 无来源 | 视频速度保留来源/质量；雷达及融合默认为空且说明原因 | 雷达设备、检定、关联与融合合同 |
| 证据 | 通用夜景图 + 假哈希 | 测绘专用外键 | 共用 `uav_evidence_*`，扩展通用 owner；真实对象引用/哈希/完整性 | 法制效力、期限、原件调阅制度 |
| 人工复核 | 内存状态 | 刷新丢失 | admin 真实写库，revision 409，确认/驳回只表示 AI 技术复核 | 业务辖区与法制定案权限 |
| 主平台投递 | 假 delivered | disabled Adapter | 状态始终 `blocked/not_queued`，不生成成功回执 | S6 正式合同与联调 |
| 货车专题 | 假实时车辆 | 无事实源 | 从真实线索聚合；无数据展示 empty/stale，不补模拟值 | 生产实时覆盖率与业务阈值 |

## 3. 本次冻结的内部契约

### 3.1 模块边界

`EnforcementService` 是 S4 唯一应用接口，封装：候选区域/规则版本、AI 线索投影、证据完整性引用、技术复核、权限与审计。REST 和 Console2 不直接拼装领域状态。

### 3.2 状态与错误

- 本地区域/规则：`candidate → retired`；没有权威 Adapter 时不允许 `published`。
- 线索主状态由 `uav_ai_events` 保存；详情表不复制投递状态或复核状态。
- 复核：`pending → reviewed_confirmed/reviewed_rejected`，含原因、操作者、时间和 revision。
- 非管理员写操作 `403`；revision 冲突 `409`；状态/质量门禁 `422`；权威发布或主平台依赖不可用 `503`。
- `vehicle_class` 只允许 `truck/non_truck/unknown`。视频、雷达、融合字段禁止互相回填。

### 3.3 真实与受控验证边界

- `inter_xqh` 真实 MP4/SRT 只提供原始材料、时间和哈希证据；当前真实管道没有已批准执法规则，因此不得宣称检测到真实违法线索。
- 验收脚本可创建 `validation_fixture=true`、`quality_status=unverified` 的工程契约样本，用于验证事件、证据、复核和页面持久化。
- 权威路网、规则审批、雷达、法制效力和主平台投递在正式合同关闭前保持 `blocked/unverified`。

## 4. 完成门禁

1. migration 从空库和 `20260715_0007` 前向升级，完成一次 `0008 → 0007 → 0008` 回滚演练。
2. API 覆盖权限、revision 冲突、候选发布 503、字段门禁、复核持久化和审计。
3. Console2 三页签全部来自真实 API，覆盖 loading、empty、error、unauthorized、stale、unverified/blocked。
4. 使用 `inter_xqh` 真实材料创建受控未验证样本，核验哈希、持久化、复核和刷新一致性并保留截图。
5. Platform、Console2、构建、轻量回归、`inter_xqh` 56 项和 `git diff --check` 通过。

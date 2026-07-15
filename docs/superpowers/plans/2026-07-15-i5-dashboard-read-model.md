# I5 S8 主任首屏真实读模型实施记录（2026-07-15）

## 1. 审计结论

改造前 `console2/src/pages/DashboardPage.jsx` 直接读取 `mockData`，固定显示 `14/18` 监测覆盖、2 个重点风险、3 处重度拥堵、`3/4` 在线无人机、`92.4%` 可信度、3 条模拟待办和 4 个示例路口。共享顶栏还固定显示“济南市历下区 · 18 个项目路口”和 `10:55:28`。后端 `/intersections` 的 3 个内存路口同样不是 S8 项目范围真源，不能用于主任首屏。

## 2. 内部工程契约

- `DashboardReadModel` 只聚合 `road9` 的 RoadContext、TimescaleDB 指标/冲突、统一 AI 事件、Survey、Mission/Pipeline、Drone/Telemetry 和 EventDelivery 状态；不新建 Dashboard 业务真源表。
- 读接口固定为 `GET /api/v1/dashboard/overview`、`/intersections`、`/intersections/{inter_id}`、`/drones`。
- 所有响应携带 `schema_version/as_of`；overview 携带 `window_start/window_end/project_scope/road_data_versions/data_quality`。
- S8-TBD-001/005 未关闭时，监测覆盖、重度拥堵、无人机保障和综合可信度返回 `value=null`、事实分子/分母与 `unverified` 原因，不把缺失口径显示成 0 或百分比。
- 当前 OSM 开发底图只允许 `RoadContext.quality_status=verified`、`coordinate_reference.status=verified`、`display=WGS84` 且经纬度有效的路口上图。GCJ02、未验证或缺坐标记录进入隔离计数和配置待办；不使用数组序号、固定点或遥测锚点冒充权威城市点位。
- “正在监测”须同时具备新鲜态势、运行 Mission、运行 Pipeline 和已验证 RoadContext；不只凭进程状态。
- 待办只聚合 `ai_review/survey_delivery/integration_replay/configuration_check`；不复制主平台派警、处置、结案或处罚任务。

## 3. 当前实现与边界

- Console2 `/` 已完全移除 Dashboard `mockData`；共享顶栏在首页使用服务端授权范围、固定 30 分钟工程窗口和实时 `as_of`，不再展示固定试点范围/时间。
- 当前隔离 `road9` 没有 RoadContext 项目路口快照，因此真实页面显示“暂无可上图的权威路口坐标”、5 个 KPI 待冻结、1 项项目配置核验；这是正确 empty/blocked 状态，不是功能失败。
- PostgreSQL 集成用例使用事务内 WGS84 verified RoadContext 验证可上图分支，并确认 `monitoring_coverage.value` 仍为 `null`；用例结束后删除测试快照，不污染验收页面。
- I5-B 内部查询现已支持风险/监测/质量、WGS84 bbox、搜索、offset/limit；road9 依赖超时统一为 503，前端保留上一成功快照、有限重试，OSM 连续瓦片失败时退化为列表/KPI。
- 全局 `uav_alerts/uav_system` 增量、断线缺口 REST 回补、点位聚合/zoom、正式底图 Adapter、项目/辖区权限、批准 KPI、容量压测和 5 秒/30 秒正式主任任务仍属于 I5 后续或外部门禁。

## 4. 验收证据

- Platform Dashboard API：3 passed（含筛选/bbox/422/503）。
- Dashboard PostgreSQL integration：1 passed。
- Console2：45/45 passed，production build passed（含服务端筛选和底图失败降级）。
- 干净浏览器标签：真实登录、正式首页、权威坐标阻断态；0 error / 0 warn。
- 截图：`console2/.design-qa/2026-07-15-i5-dashboard-road9-authority-blocked.png`。

## 5. I5 剩余门禁

1. 冻结 S8-TBD-001/002/003/004/005/006：项目范围、在监/覆盖、风险/拥堵、质量、底图和 API 查询参数。
2. 接入获批 RoadContext 项目路口清单与底图 Adapter，完成正常、混合质量和版本不一致视觉验收。
3. 全局增量和断线 REST 缺口回补；在正式身份矩阵下覆盖 unauthorized，在可控依赖故障环境覆盖 partial timeout/stale/map failure。内部查询、503 和底图失败 UI 降级已完成。
4. 在批准设备/分辨率和数据集上完成 5 秒辨识、30 秒定位、容量与权限验收。

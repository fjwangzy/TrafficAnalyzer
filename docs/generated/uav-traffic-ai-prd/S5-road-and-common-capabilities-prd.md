# S5 路网与共性能力分册 PRD

| 项目 | 内容 |
| --- | --- |
| 文档定位 | S1–S4 的路网、坐标、版本、规则元数据和证据引用共性分册 |
| 版本/日期 | v0.3 / 2026-07-13 |
| 评审对象 | 路网数据负责人、GIS、交通业务、算法、平台、测试、运维、网安 |
| 当前状态 | RoadContext 内部接口、snapshot/绑定 DDL 与 road9/fixture Adapter 已实现；权威路网 schema/视图、SRID/坐标和版本合同待外部冻结 |
| 关键门禁 | S5-TBD-001～003/013 未关闭前不得将任何历史调查结构视为 `road9` 生产契约 |

> 本分册优先于业务分册冻结。本子项目复用智慧交通大项目既有路网主数据，不重复建设或维护权威路网底库。

> 2026-07-15 工程基线：Alembic `20260715_0003` 已创建 `uav_road_context_snapshots`、`uav_visual_lane_bindings` 与 `uav_device_intersection_bindings`；`RoadContext` 按 `inter_id + road_data_version` 返回不可变快照、checksum、坐标参考、路口/Link/车道、视觉绑定和质量状态。开发 fixture 明确返回 `unverified`，不能替代权威数据批准。

## 1. 目标、原则与非目标
### 1.1 目标
1. 以只读、版本化方式向 S1–S4 提供路口、Link、车道、道路和拓扑上下文。
2. 建立本地图像道路/车道与权威 inter_id/link_id/lane_id 的可审计绑定。
3. 建立像素、ENU、地理坐标与地图展示坐标之间的可追溯转换链和质量状态。
4. 任务运行期间冻结路网版本，远程源异常时通过已验证快照稳定降级。
5. 统一规则版本、预测元数据和证据引用的共性接口，业务判定仍由各分册负责。

### 1.2 强制原则
- PostgreSQL 连接 database 固定为 `road9`；`road9` 不是默认 schema，库内权威路网 schema/只读视图必须由数据负责人书面冻结。
- 早期 `ycx/road10` 调查仅作历史资产线索，不得作为 `road9` 连接参数、物理表名或字段契约的依据。
- 本项目在 `road9` 内创建的表全部使用 `uav_` 前缀；既有权威路网表属于外部资产，不要求改名，但只允许通过批准的只读视图/API消费。
- 禁止在逐帧检测、跟踪、统计或事件计算中远程查询生产路网库。
- 低置信、歧义或缺数据时必须输出 unmapped，主数据 ID 置空，不得用数组序号、road_N 或 local lane key 伪造。
- 主数据几何提供语义和候选匹配，不直接替代视觉 ROI、停止线、车道多边形、单应性或现场标定。
- 主数据 ID 必须与 road_data_version 一起保存；版本升级不得重写历史轨迹和事件。

### 1.3 非目标
- 不初始化、迁移、写回或修复智慧交通权威路网表；在 `road9` 创建 `uav_` 快照、绑定、匹配和审计表不属于向权威路网回写。
- 不依据 schema 名称大小自动选择“最新”或“权威”版本。
- 不在未知 SRID 或 GCJ02 语义下自动转换并输出高质量坐标。
- 不在本分册定义拥堵、冲突、测绘和执法业务规则或法制证据效力。
- 不以固定设备 ID 冒充无人机 device_id，不复制主平台组织和资产管理体系。

## 2. 角色与职责
| 角色 | 职责 |
| --- | --- |
| 路网数据负责人 | 确认权威源、版本、字段、代码、有效期和变更通知 |
| GIS/测绘人员 | 确认几何、坐标语义、控制点、转换链和误差口径 |
| 交通业务人员 | 确认进口/出口 Link、车道方向、转向和道路语义 |
| 标定/算法人员 | 维护视觉 ROI、车道绑定、地图匹配和质量阈值 |
| 平台/架构人员 | 建设只读适配器、快照、缓存和统一字段契约 |
| 运维/网安人员 | 管理只读账号、密钥、网络、刷新、监控和审计 |
| S1–S4 负责人 | 消费冻结上下文并正确处理 stale/missing/unmapped |

## 3. 数据源现状与目标资产
### 3.1 已冻结决策与历史调查边界

- 目标 PostgreSQL database 为 `road9`；本项目所有 PostgreSQL 连接、迁移和验收均以该 database 为边界。
- 2026-07-13 对 `ycx` 数据库及 `road10` 等 schema 的只读调查只证明曾观察到路口、Link、车道、版本和关系类资产，不能证明 `road9` 内存在同名对象，也不能证明其权威性、坐标语义或数据新鲜度。
- 正式设计前必须在 `road9` 重新执行只读目录盘点、样本核验和数据负责人确认，产出“database → schema/视图 → 逻辑领域”的映射清单。

### 3.2 `road9` 必需的权威路网逻辑视图

物理 schema、视图名、字段和代码值均为 `S5-TBD-001/002/003`，不得照搬历史 `road10` 表名。

| 逻辑领域 | 最低能力 | S1–S4 用途 |
| --- | --- | --- |
| 路网版本 | version_id、发布状态、有效期、发布时间、校验值 | 任务冻结、历史复现、升级/回滚 |
| 路口 | inter_id、名称/类型、空间范围、行政/业务属性 | 任务定位、路口聚合、页面展示 |
| 道路/路段 | road/rid 标识、名称、等级、方向、空间几何 | 路段归属、规则关联、GIS 展示 |
| Link | link_id、进口/出口角色、方向、几何、有效期 | 转向流、入口/出口和轨迹地图匹配 |
| 车道 | lane_id、所属 Link、类型、允许转向、序号、几何 | 车道统计、换道、围栏与证据定位 |
| 路口—Link—车道关系 | inter/link/lane、角色、拓扑、版本 | 防止跨版本或错误关系拼接 |
| Link 上下游拓扑 | from/to inter、前后继 Link、版本 | 轨迹连续性、冲突场景和走廊分析 |
| 设备关系 | 设备与 inter/link/lane 的有效期映射 | 固定设备交叉校验；不得冒充无人机 ID |

### 3.3 `road9` 中的 UAV 本地实体

以下是本项目自建物理表候选，全部使用 `uav_` 前缀；最终列、索引、外键和保留策略以数据库契约评审为准。

| 逻辑实体 | 目标表 | 说明 |
| --- | --- | --- |
| ROAD_CONTEXT_SNAPSHOT | `uav_road_context_snapshots` | 保存已验证路口级快照 manifest、版本、校验值和状态 |
| DEVICE_INTERSECTION_BINDING | `uav_device_intersection_bindings` | 保存无人机/任务与权威路口的有效期映射 |
| VISUAL_LANE_BINDING | `uav_visual_lane_bindings` | 保存本地车道到 inter/link/lane 的版本化绑定 |
| MAP_MATCH_RESULT | `uav_map_match_results` | 保存轨迹/事件匹配候选、方法、分数、revision 和拒判原因 |
| RULE_VERSION | `uav_rule_versions` | 保存规则版本、审批、生效和回滚元数据 |
| EVIDENCE | `uav_evidence_packages`、`uav_evidence_items` | 保存证据包元数据和不可变材料引用 |
| AUDIT | `uav_audit_logs` | 保存同步、发布、绑定、导出和回滚审计 |

高频指标、遥测、轨迹点和冲突时序统一进入 `road9` 的 TimescaleDB hypertable；不再为本分册新增 InfluxDB Measurement。

## 4. 领域模型与标识
| 实体 | 主标识/组合键 | 职责 |
| --- | --- | --- |
| ROAD_DATA_VERSION | version_id | 发布时刻、状态、有效期、来源、校验值 |
| INTERSECTION | inter_id + version_id | 权威路口及空间范围 |
| ROAD_LINK | inter_id + link_id + link_role + version_id | 路口进口/出口连接段 |
| LANE | inter_id + link_id + lane_id + version_id | 权威车道语义和拓扑 |
| ROAD/RID | road/rid ID + version_id | 道路名称、等级和路段关联 |
| ROAD_CONTEXT_SNAPSHOT | inter_id + version_id | 单路口可运行只读快照及 manifest |
| DEVICE_INTERSECTION_BINDING | device_id + inter_id + version | 无人机设备与路口任务映射 |
| VISUAL_LANE_BINDING | local_lane_key + calibration_id + version | 视觉车道到权威车道的绑定 |
| MAP_MATCH_RESULT | track/event ID + match revision | Link/车道候选、方法、分数和结果 |

标识规则：

- intersection_id/INT_camera_N、road_N 和 local_lane_key 仅作旧接口或图像配置别名。
- 权威 ID 不得脱离 road_data_version 单独解释。
- Link/车道拆分、合并、删除和重命名须保留有效期及旧版本引用，不在历史数据上替换 ID。
- device_id 由本项目管理，通过映射绑定 inter_id；固定设备关系只用于核验。

## 5. 总体数据流与任务冻结
1. 数据发布方发布已批准版本及变更说明。
2. RoadContextAdapter 通过只读视图/API 拉取指定 inter_id 的版本化路口、Link、车道和拓扑。
3. 适配器完成 schema、必填字段、关系、空间范围、坐标声明和校验值验证。
4. 验证成功后原子生成 ROAD_CONTEXT_SNAPSHOT，并按 inter_id + road_data_version 缓存。
5. 任务启动时选择已发布版本，加载快照、标定和视觉绑定，生成不可变 road context。
6. 每帧只访问任务内存/本地缓存；禁止同步调用远程路网库。
7. 轨迹执行地图匹配，S1–S4 输出主数据 ID、版本、方法、置信度和质量状态。
8. 新版本仅作用于新任务；运行中任务继续原版本，结束后保留版本引用。

## 6. 详细功能需求
| 编号 | 功能需求 | 优先级 | 状态 |
| --- | --- | --- | --- |
| S5-FR-001 | 支持权威源配置、只读访问和源 schema 版本校验 | P0 | 权威源待确认 |
| S5-FR-002 | 构建路口级版本快照、manifest、校验值和原子发布 | P0 | 目标新增 |
| S5-FR-003 | 按 inter_id + road_data_version 本地缓存，支持预热和回滚 | P0 | 目标新增 |
| S5-FR-004 | 任务启动冻结路网版本，运行期禁止隐式切换 | P0 | 目标新增 |
| S5-FR-101 | 提供路口、Link、车道、Road/RID 和拓扑统一领域对象 | P0 | 字段待确认 |
| S5-FR-102 | 保留来源字段、代码原值、有效期和逻辑删除语义 | P0 | 字典待确认 |
| S5-FR-201 | 建立版本化视觉车道绑定、候选、人工确认和退役状态 | P0 | 目标新增 |
| S5-FR-202 | 支持绑定差异比较、批量复核、回滚和审计 | P1 | 目标新增 |
| S5-FR-301 | 输出当前/入口/出口 Link 和可识别车道的地图匹配 | P0 | 目标新增 |
| S5-FR-302 | 输出候选、方法、置信度、歧义和 unmapped 原因 | P0 | 目标新增 |
| S5-FR-401 | 提供像素→ENU→地理坐标→GCJ02 的版本化转换和质量 | P0 | 坐标语义阻断 |
| S5-FR-402 | 支持控制点校验、误差报告和自动绑定门禁 | P0 | 阈值待确认 |
| S5-FR-501 | 提供规则配置 schema、版本、审批、生效和回滚元数据 | P1 | 共性框架 |
| S5-FR-502 | 提供证据不可变引用、哈希、父子派生和审计元数据 | P1 | 共性框架 |
| S5-FR-503 | 提供预测方法、版本、时域和质量的统一元数据接口 | P1 | 算法由 S2 验收 |

## 7. 只读适配、版本快照与缓存
- 正式接入优先使用数据方维护的只读视图/API，不长期耦合底层生产表。
- 服务身份只授予必要对象的 SELECT/API 读取权限；不得拥有建表、更新、删除或 schema 变更权限。
- 快照 manifest 至少记录 source、source_schema_version、road_data_version、inter_id、generated_at、source_published_at、记录数和 checksum。
- 快照发布采用“下载到临时版本→全量校验→原子激活”，失败不覆盖上一验证版本。
- 缓存按 inter_id + road_data_version 隔离；刷新在后台或任务启动前完成，不进入逐帧关键路径。
- 新版本先做字段、拓扑、坐标和视觉绑定差异检查，再允许新任务使用。
- 旧快照保留期限、容量和 retired 规则待确认；历史事件依赖的版本不可提前删除。

road_context_status：

| 状态 | 含义 | 行为 |
| --- | --- | --- |
| ok | 冻结版本与已验证快照一致 | 正常输出主数据 ID |
| stale | 远程源不可用，使用最近已验证且仍被策略允许的快照 | 保留 ID，显式标记新鲜度 |
| missing | 无可用快照 | AI 可继续本地计算，主数据 ID 为空 |
| version_mismatch | 任务版本、缓存或绑定版本不一致 | 禁止混用，置空受影响 ID 并告警 |

## 8. 视觉车道绑定
### 8.1 职责分层
- 主数据层：提供权威 ID、Link/车道拓扑、方向、类型、道路等级和规则关联。
- 视觉层：提供当前视角下 ROI、停止线、车道多边形、像素坐标和单应性。
- 标定层：描述相机、飞行姿态、控制点、适用时段及误差。

任何主数据几何在未通过坐标和精度验证前，只能用于候选匹配和展示，不能覆盖视觉 ROI、停止线、车道多边形或单应性。

### 8.2 绑定规则
- 绑定结构至少包含 local_lane_key、calibration_id、inter_id/link_id/lane_id、road_data_version、binding_method、binding_confidence、status、reviewer 和 reviewed_at。
- 优先级为：人工确认绑定 > 已验证主数据几何自动匹配 > 轨迹候选 > 模型候选。
- 自动结果先进入 candidate；达到批准门槛且无歧义才可按策略确认，否则为 unmapped。
- 路网或标定版本变化触发差异任务，不原地改写旧绑定。
- 人工校正必须记录变更前后值、理由、证据和审批，支持回滚。

## 9. 地图匹配
1. 使用统一坐标和任务冻结拓扑生成 Link/车道候选。
2. 综合空间距离、行驶方向、轨迹连续性、入口/出口拓扑和视觉车道绑定评分。
3. 分别输出当前位置 link_id/lane_id 和完成轨迹 entry/exit Link/车道。
4. 候选分数接近、方向冲突、越界或低于门槛时输出 unmapped，不强行择一。
5. map_match_method 仅使用 manual/master_geometry/trajectory/model/unmapped；组合方法可另带 evidence 列表。
6. road_N 可继续兼容展示，但不得参与权威 ID 推导或跨系统聚合。

地图匹配准确率、歧义差值、最小轨迹长度和人工抽检比例由 S5-TBD-005 冻结。

## 10. 坐标链与质量
目标转换链为：原始像素 → 稳像像素 → ENU 米制坐标 → 明确来源的地理坐标 → GCJ02 展示/交换坐标。

- 每一步记录 input/output coordinate system、source_srid、transform_version、anchor、calibration_id、timestamp 和 quality。
- 不得仅凭 EPSG/SRID 名称推断数据已是 GCJ02；数据库实际几何、WGS84/CGCS2000/GCJ02 关系须实测确认。
- 每个试点路口使用经确认控制点验证 RTK、路网几何、底图和视觉标定，输出残差、适用区域和时间。
- 超过批准误差时禁止自动车道绑定和高质量 GCJ02 输出；若 ENU 仍有效可保留本地计算并标记降级。
- 长轨迹、快速巡飞、斜视、RTK 退化和标定过期须分别评估，不能以单路口单帧结果代替。

建议的质量元数据包括 coordinate_quality_status、horizontal_error_estimate_m、control_point_set_id、calibration_age 和 transform_chain；最终枚举与阈值见 S5-TBD-003/007。

## 11. 共性规则、预测与证据边界
| 共性能力 | S5 负责 | 业务分册负责 |
| --- | --- | --- |
| 规则框架 | schema 校验、版本、审批、生效、原子切换、回滚、审计 | 规则条件、阈值、例外和业务结论 |
| 预测元数据 | prediction_method/version/horizon/quality 契约 | 算法、场景和 ADE/FDE 验收；LSTM 偏差由 S2 关闭 |
| 证据引用 | 不可变 ID、哈希、父子派生、存储状态、访问审计 | 必要材料、法制效力、保留期和调阅审批 |

规则热更新不得造成单次事件使用两套规则；每条结果保存准确 rule_version 和 effective_at。证据元数据不等于法定证据结论，S3/S4 的法制阻断项不由 S5 自动关闭。

## 12. 目标字段契约
> 以下字段为规划目标，不代表当前 `uav_*` Kafka 契约、`road9` 表或 Platform 已实现；旧 InfluxDB 字段不得继续作为目标 schema 来源。

| 分类 | 字段 |
| --- | --- |
| 路网版本 | road_data_version、road_context_status、road_snapshot_id、road_source、road_source_published_at |
| 主数据 ID | inter_id、link_id、lane_id、entry_link_id、exit_link_id、entry_lane_id、exit_lane_id |
| 地图匹配 | map_match_method、map_match_confidence、map_match_status、map_match_reasons、candidate_ids |
| 视觉绑定 | local_lane_key、calibration_id、binding_id/version/method/confidence/status |
| 坐标 | position_px、position_enu、position_gcj02、source_coordinate_system/srid、transform_version |
| 坐标质量 | coordinate_quality_status、horizontal_error_estimate_m、control_point_set_id |
| 共性版本 | rule_version、prediction_method/version、evidence_package_id、schema_version |

ID 为空时必须同时给出状态/原因；任何主数据 ID 都要能定位 road_data_version。既有 intersection_id 和 road_N 可保留兼容，但不得冒充权威字段。

## 13. 页面、人工校正与权限
1. 数据源状态：展示源、只读连接、最近成功同步、当前候选/已确认权威状态和告警，不展示密钥。
2. 版本中心：查看发布说明、快照校验、差异、缓存占用、使用中任务和回滚资格。
3. 路网浏览：按路口查看 Link/车道拓扑、代码原值、几何声明和有效期。
4. 视觉绑定：视频/底图双视图展示本地车道、候选权威车道、分数和差异，支持确认、驳回、重绑。
5. 坐标校验：管理控制点、查看残差、转换链和自动绑定门禁。
6. 运维诊断：查看 stale/missing/version_mismatch、unmapped、schema 漂移、同步耗时和失败原因。

权威源确认和版本发布由数据负责人负责；绑定校正由授权标定/业务人员执行；只读凭据和网络由运维管理；所有发布、校正、导出和回滚操作审计。

## 14. 异常与降级
| 异常 | 处理 |
| --- | --- |
| 远程源断连 | 使用策略允许的最近已验证快照并标记 stale；无快照则 missing |
| schema/必填字段变化 | 拒绝新快照，保留上一版本并告警 |
| checksum 或关系校验失败 | 不激活快照，隔离失败产物 |
| 任务/缓存/绑定版本不一致 | version_mismatch，禁止跨版本拼接 |
| 未确认 SRID/GCJ02 语义 | 禁止自动坐标转换和几何绑定，保持验收阻断 |
| 控制点误差超限 | 降低坐标质量，暂停自动绑定和依赖高精度的业务输出 |
| 地图匹配低置信或歧义 | 主数据 ID 置空，method/status=unmapped |
| 路网拓扑断裂或循环异常 | 隔离异常关系，Link/车道级能力降级并告警 |
| 视觉标定过期/视角变化 | 停用对应绑定，要求重新标定 |
| 本地缓存损坏 | 校验失败后重新拉取；不可用时 missing，不查询逐帧远程源 |
| 规则配置错误 | 拒绝发布并保留上一批准版本 |
| 证据存储不可用 | 业务分册按证据门禁处理，S5 记录状态和告警 |

## 15. 非功能与安全需求
| 编号 | 要求 |
| --- | --- |
| S5-NFR-001 | 逐帧关键路径仅访问内存/本地缓存，不依赖远程数据库可用性 |
| S5-NFR-002 | 快照可校验、原子激活、可回滚；历史版本引用可复现 |
| S5-NFR-003 | 路网加载、缓存命中、同步失败、未匹配率、坐标误差和版本分布可观测 |
| S5-NFR-004 | 正式凭据使用密钥管理或环境变量，文档、日志、API 和页面不得保存或输出明文密码 |
| S5-NFR-005 | 使用最小权限只读身份、网络白名单/隔离、传输保护、密钥轮换和访问审计 |
| S5-NFR-006 | 快照启动时延、刷新 SLA、缓存容量、并发任务和离线持续时间见 S5-TBD-004/008 |
| S5-NFR-007 | 输出 schema 向后兼容；新增字段先可选，消费者升级后再设为门禁 |

当前临时文档中的明文数据库凭据必须迁移到受控密钥系统并轮换；本分册不得记录其具体值。

## 16. 迁移与发布
1. DBA 在 `road9` 确认 TimescaleDB 扩展、目标 schema、权限、备份恢复和容量基线；数据方签署权威路网只读视图、字段、代码、几何、坐标和版本制度。
2. 在 `road9` 建设全部 `uav_` 表/Hypertable 与最小权限角色；建设 RoadContextAdapter、契约测试和脱敏测试数据。
3. 生成试点路口 `uav_road_context_snapshots`，建立 `uav_device_intersection_bindings` 和 `uav_visual_lane_bindings`。
4. 先在影子/双写模式输出新字段和新表，与 `road_N`、旧 ID 及旧时序数据对账，不改变业务判定。
5. 完成抽样校正、坐标控制点、断连、版本切换及 TimescaleDB 写读/备份恢复验收后，S1–S4 和平台 API 切读 `road9`。
6. 主平台消费者完成迁移后逐步降级旧字段；达到对账门槛和观察期后停止 InfluxDB/Telegraf 写入并退役 Grafana 链路，历史数据始终按原版本解释。

回滚时停止新版本任务、将新任务指向上一已验证快照；不得修改已运行任务和历史事件的 road_data_version。

## 17. 分层验收与用例
### 17.1 验收指标
| 层级 | 指标 |
| --- | --- |
| 数据契约 | 必填完整率、代码可解释率、拓扑校验率、版本/有效期正确率 |
| 快照缓存 | 校验成功率、加载时延、缓存命中率、原子切换、断连持续能力 |
| 视觉绑定 | inter/Link/车道准确率、unmapped 率、人工校正一致性和版本差异正确率 |
| 地图匹配 | 当前及 entry/exit Link/车道准确率、歧义识别率、低置信拒判率 |
| 坐标 | 控制点残差、P95 水平误差、有效覆盖和降级正确率 |
| 集成迁移 | schema、旧字段兼容、S1–S4 消费、主平台 ID 聚合和历史复现 |
| 安全运维 | 只读权限、密钥泄漏扫描、断连/schema 漂移告警和审计覆盖 |

### 17.2 核心验收用例
| 编号 | 场景与预期 |
| --- | --- |
| S5-AC-001 | 连接目标固定为 database=`road9`，但系统不得把 database 名自动当作 schema；只有批准的 schema/视图可成为权威源 |
| S5-AC-002 | 任务启动冻结版本：运行中发布新版本，当前任务不切换，新任务使用新版本 |
| S5-AC-003 | 远程源断连：逐帧管道不中断，使用已验证缓存并标记 stale |
| S5-AC-004 | 无缓存启动：本地 AI 可按能力降级，权威 ID 为空且状态 missing/unmapped |
| S5-AC-005 | schema 或 checksum 异常：新快照拒绝激活，上一版本不受影响 |
| S5-AC-006 | 自动车道匹配低置信/双候选接近：输出 unmapped，不强行选择 |
| S5-AC-007 | 人工确认绑定：优先级最高，变更和回滚全量审计 |
| S5-AC-008 | 主数据几何与视觉 ROI 有偏差：不得覆盖 ROI、停止线或单应性 |
| S5-AC-009 | SRID/GCJ02 未确认：禁止高质量坐标声明和自动空间绑定 |
| S5-AC-010 | 控制点误差超限：坐标降级且依赖高精度的业务能力被门禁 |
| S5-AC-011 | Link/车道拆分合并：历史事件仍按旧版本和旧 ID 可复现 |
| S5-AC-012 | 本地 road_N 与权威 lane_id 不一致：不得以 road_N 伪造 lane_id |
| S5-AC-013 | 规则热更新：单个事件只引用一套批准规则版本 |
| S5-AC-014 | 凭据与日志检查：文档、日志、错误信息和页面不出现明文秘密 |
| S5-AC-015 | S1–S4/主平台联调：统计、轨迹和事件保存同一版本下的正确 ID |
| S5-AC-016 | 数据库对象盘点：本项目自建表全部以 `uav_` 开头，非 `uav_` 既有路网对象只读且无写权限 |
| S5-AC-017 | TimescaleDB 验收：扩展、Hypertable、保留/压缩、备份恢复和普通 PostgreSQL 事务表协同通过 |

## 18. 风险、依赖与待补充台账
主要风险：把 `road9` database 名误当 schema、照搬历史 `road10` 结构、坐标语义误判、版本切换污染历史、TimescaleDB 参数或备份方案未验证、远程库抖动阻塞实时管道、错误自动绑定、明文凭据泄漏。依赖 DBA/Data/GIS 提供正式契约，S6 冻结主平台字段，S7 冻结迁移及验收环境。

| 编号 | 待补充内容 | 责任方 | 关闭依据 | 状态 |
| --- | --- | --- | --- | --- |
| S5-TBD-001 | `road9` 内正式权威路网 schema/只读视图、发布责任人及权威源切换机制 | 数据负责人 | `road9` 对象映射清单、书面确认和发布制度 | 【验收阻断】 |
| S5-TBD-002 | 主表字段、主键、代码、拓扑方向、有效期、逻辑删除和历史查询 | 数据负责人/GIS | 批准数据字典 | 【验收阻断】 |
| S5-TBD-003 | 几何列/类型、SRID、WGS84/CGCS2000/GCJ02 实际语义和转换方法 | GIS/数据负责人 | 坐标说明与实测报告 | 【验收阻断】 |
| S5-TBD-004 | 只读视图/API、鉴权、刷新周期、变更通知和 SLA | 数据平台/运维 | 接口规范与运维 SLA | 【外部依赖】 |
| S5-TBD-005 | 地图匹配/绑定阈值、歧义口径、抽检比例和人工校正流程 | 算法/业务/测试 | 批准评测和校正方案 | 【待补充】 |
| S5-TBD-006 | 权威路网版本对象的发布、失效、回滚、retired 和快照保留规则 | 数据负责人/平台 | 版本治理规范 | 【验收阻断】 |
| S5-TBD-007 | 控制点来源、坐标误差阈值、质量等级和高精度业务门禁 | GIS/测绘/测试 | 坐标验收方案 | 【验收阻断】 |
| S5-TBD-008 | 缓存预热、启动时延、容量、离线时长、过期和清理策略 | 架构/运维 | 性能与缓存方案 | 【待补充】 |
| S5-TBD-009 | intersection_id→inter_id、设备和初始车道绑定的审批流程 | 数据方/业务/平台 | 初始化映射清单 | 【待确认】 |
| S5-TBD-010 | 规则、预测和证据共性元数据 schema 及各分册责任边界 | S2/S3/S4/S6 | 跨分册契约 | 【待确认】 |
| S5-TBD-011 | road_N/旧 ID 消费方清单、双写周期和退役门槛 | 平台/数据消费者 | 迁移及回滚方案 | 【待补充】 |
| S5-TBD-012 | 明文凭据迁移、轮换完成和秘密扫描基线 | 运维/网安 | 轮换记录与扫描报告 | 【验收阻断】 |
| S5-TBD-013 | `road9` 目标 schema、TimescaleDB 版本/许可、Hypertable chunk、保留/压缩、备份恢复、高可用和容量参数 | DBA/架构/运维 | 批准 DDL、容量与灾备方案 | 【验收阻断】 |
| S5-TBD-014 | 现有用户/角色、无人机、任务、路口映射、管道、告警、标定/车道任务、视频源等内存/文件/数据库状态的迁库、运行内存、外部权威或退役处置，以及最终物理表模型 | 平台/架构/DBA/产品/统一身份方 | 状态处置矩阵、ERD、DDL 和迁移清单 | 【验收阻断】 |

## 19. 评审与上线门禁
进入开发前须关闭或形成可执行计划的 S5-TBD-001～005/013/014，并冻结领域对象、状态处置、`uav_` 物理命名和目标字段；试点前须关闭 S5-TBD-003/006/007/009/012/013/014；生产启用前须完成只读服务、版本快照、缓存降级、坐标控制点、人工校正、TimescaleDB、备份恢复、安全和 S1–S4/S6 联调验收。任何阻断项未关闭时，不得将候选 ID 或坐标作为权威业务结论，也不得下线旧数据链路。

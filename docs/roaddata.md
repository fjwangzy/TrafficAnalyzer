# 路网数据调查与目标接入说明

> 历史临时连接信息已从文档移除；原凭据须轮换。目标连接只声明 database=`road9`，主机、端口、账号和密钥由受控配置提供。

## 目标架构决策（2026-07-13）

- 无人机平台 PostgreSQL 连接 database 固定选择 `road9`；database 名不自动等同于 schema 名。
- 下文对 `ycx/road10` 的内容降级为历史只读调查证据，只能用于识别可能存在的路口、Link、车道、版本和关系数据域，不能作为 `road9` 的连接参数或生产表契约。
- 须在 database=`road9` 重新盘点 schema、只读视图、表、字段、主键、代码、几何类型、SRID、坐标语义、版本制度、数据量和发布责任人。
- 无人机平台自建表全部使用 `uav_` 前缀；权威路网既有表不强制改名但必须只读消费，本地快照、绑定、地图匹配和审计等表均使用 `uav_*`。
- `road9` 安装并启用 TimescaleDB 后承载无人机时序指标；InfluxDB、Telegraf、Grafana 完成迁移、对账、切读和观察期后退役。

## 历史只读调查结论（2026-07-13）

> 安全提示：本文件曾包含临时明文数据库凭据，现已脱敏；原凭据须轮换。正式集成必须改用密钥管理或环境变量，应用配置、日志和文档不得保存或输出明文密码。

### 连接信息校正

- 实际 PostgreSQL 数据库名为 `ycx`，服务端版本为 PostgreSQL 16.13。
- `database: pg+postgis` 表示数据库/驱动类型，不是可直接连接的数据库名。
- `schame: ycx` 与实际结构不一致；数据库中没有 `ycx` schema。
- 已发现的业务 schema 包括：`road`、`road2`～`road10`、`gaode`、`gaode_api`、`haixin_signal`、`hzroad`、`xianchang`、`test`。
- 本次只执行系统目录、表结构、约束和统计信息查询，未执行任何写操作。

### 候选路网主数据

从实体完整度、关联宽表和数据规模判断，历史调查中的 `road10` 曾是较完整的候选 schema。该判断已被 database=`road9` 的目标选择取代，仅用于帮助定义需要重新核验的逻辑数据域，不再是目标对接基线。

| 实体/关系 | 候选表 | 观测规模（约） | 关键业务用途 |
| --- | --- | ---: | --- |
| 数据版本 | `road10.dim_data_version` | 1 | 冻结一次任务使用的路网版本 |
| 路口 | `road10.dim_inter_info` | 8,335 | 提供统一 `inter_id`、路口属性和空间定位 |
| 道路连接段 Link | `road10.dim_link_info` | 20,094 | 表示路口进出口道路连接段，承载方向与拓扑 |
| 车道 | `road10.dim_lane_info` | 47,774 | 提供统一 `lane_id`、车道类型和转向属性 |
| 道路/RID | `road10.dim_rid_info` | 待确认 | 与高德道路及路段级分析建立关联 |
| 路口-Link关系 | `road10.dwd_tfc_rltn_wide_inter_ft_link` | 40,188 | `inter_id + link_id + link_role + version_id` |
| 路口-Link-车道关系 | `road10.dwd_tfc_rltn_wide_inter_ft_lane` | 95,548 | `inter_id + link_id + lane_id + link_role + version_id` |
| Link上下游路口 | `road10.dwd_tfc_rltn_wide_link_inter` | 当前统计为 0，待核验 | 计划提供 `link_id + f_inter_id + t_inter_id + version_id` |
| 设备-路口关系 | `road10.dwd_tfc_rltn_devc_inter` | 195,120 | 将无人机/摄像头或其他设备映射到路口 |
| 设备-车道关系 | `road10.dwd_tfc_rltn_devc_lane` | 2,529 | 将固定设备与 `lane_id/link_id` 对齐，可用于交叉校验 |

> 上表“观测规模”来自 PostgreSQL 统计信息，仅用于识别数据资产，不作为验收精确行数。

### 可补充使用的数据域

- `gaode`：存在大规模路口、道路、节点和路段数据，包括 `intersection_info_all`、`road_info_all`、`road_node`、`road_seqment`，适合提供底图、道路名称、道路层级和空间候选匹配。
- `haixin_signal`：存在信号机、车道参数、相位、阶段、周期和转向流量数据，可用于无人机观测与信号控制数据的交叉验证。
- `xianchang`：存在路口、link、车道、走廊和信控评估等历史/模型指标，可用于基线对比和效果评估，不应直接作为无人机实时识别的主数据源。
- `road`～`road9`、`hzroad`：这是历史 `ycx` database 内观察到的 schema；其中 schema=`road9` 与新选择的 database=`road9` 不是同一层级对象。未经重新调查和数据负责人确认，不得自动映射或按名称大小选择“最新版本”。

### 尚待确认

1. database=`road9` 内正式生产权威 schema/只读视图、路网版本对象及其发布、失效和回滚规则。
2. 路口、link、lane 几何字段的准确列名、几何类型、SRID及其与 GCJ02 的实际关系。
3. `link_role`、车道类型、转向编码、道路等级等代码表的业务含义。
4. 路口、link、lane 的逻辑删除、有效期和历史版本查询方式。
5. 是否提供稳定的只读视图/API；无人机子项目不应长期直连并耦合底层生产表。
6. 无人机路口 `intersection_id` 与主数据 `inter_id` 的初始化映射、人工校正和变更审批流程。

# MP4 + SRT 产品深度展示全流程真实验收报告

> 日期：2026-07-16～2026-07-17  
> 范围：本机开发闭环，不代表生产验收  
> 结论：事件中心、轨迹研判、事故测绘已具备可持续复现的真实数据展示能力

## 1. 验收口径

唯一业务数据路径为：

```text
已登记 MP4 + DJI SRT
  -> main_optimized.py 三进程检测管道
  -> canonical uav_* Kafka Topic
  -> Platform MetricStore 事务（inbox + 事实）
  -> PostgreSQL database=road9 / TimescaleDB
  -> REST + uav_* WebSocket
  -> Console2 事件中心 / 轨迹研判 / 事故测绘
```

检测器不写 SQLite，也不直写业务库。轨迹完成事实和真实冲突在进入 Kafka 前使用 fsync + 原子 rename 文件 spool；该目录只承担 broker 故障缓冲，不提供查询，不构成第二数据库。周期统计和遥测允许 best-effort，但每个统计事实记录 expected、actual、dropped、coverage 和 drop reason。

## 2. 真实数据源与运行结果

六套已登记 Source 均以真实 Mission 启动，逐套验证 MJPEG 首帧、`uav_stats`、`uav_telemetry`、重复启动 409 防重、人工停止和活动任务归零：

| Source | 验收 Mission | 结果 |
| --- | --- | --- |
| `SRC-INTER-XQH-0403-PM` | `MSN-4436DDDBA94A` | 通过 |
| `SRC-MP4NEW-HY-0625-AM` | `MSN-893909D3EB0A` | 通过 |
| `SRC-MP4NEW-LS-0625-AM` | `MSN-AD837383714C` | 通过 |
| `SRC-MP4NEW-CH-0625-AM` | `MSN-CFEB9BB47CAE` | 通过 |
| `SRC-MP4NEW-HY-0624-PM` | `MSN-E493086CEA62` | 通过 |
| `SRC-MP4NEW-LS-0624-PM` | `MSN-070E1B9584DE` | 通过；保留 `telemetry_gap_34s` 质量事实 |

另以 `SRC-INTER-XQH-0403-PM` 全视频自然 EOF 验收：Mission `MSN-3D72FA9F8281` 为 `completed/source_eof`；写入 878 条带完整 Mission/Source/Road lineage 的轨迹、4,390 个轨迹点、316 个不同业务时间，时间跨度为 `2026-04-03 06:29:01.592Z` 至 `06:44:03.471Z`。

## 3. road9 落库抽查

当前 migration 为 `20260716_0012`，活动 Mission 为 0。验收查询得到：

- `uav_track_events`：11,764 条；其中本轮新 lineage 轨迹 1,163 条，全部具有完整 road context；
- `uav_track_points`：73,170 点；其中新 lineage 轨迹点 20,165 点；
- `uav_traffic_metrics`：3,602 条，覆盖 12 个 Mission，`coverage_ratio` 实际范围 0.428571～1.0；
- `uav_ai_events`：持续拥堵 5、质量下降 4、测绘成果 6；
- `uav_survey_reports`：6 份；PDF/JSON/GeoJSON 各 6 个内容寻址证据；
- 事件关键帧 4 个，均保存 SHA-256、媒体类型、尺寸和来源事件关系。

新生成拥堵事件 `EVT-1d52d1c71187819c7e57ec3f64cdec19` 来自真实检测统计：拥堵指数 9.2，规则连续样本 30，expected/actual 58/58、dropped 0、coverage 1.0，并关联 1 个真实无人机关键帧。

## 4. 产品页面验收

- AI 事件中心：统一展示真实持续拥堵、遥测质量下降、测绘成果和真实冲突；支持类型、路口、风险和搜索筛选，详情保留规则、质量、lineage、证据和技术复核状态。
- 轨迹研判：默认“全部验收数据”，可按 Mission、Source、车型、方向和时间筛选；地图投放世界轨迹并显示 Track、业务时间、点数、速度、road version 和质量。正式库当前真实冲突为 0，页面如实显示空态，未注入伪事件。2026-07-17 针对首次进入短暂显示“0 条”的反馈，`DashboardReadModel` 改为在 PostgreSQL 内按路口/无人机选择最新事实，不再反序列化最多 5,000 + 5,000 条完整 JSON 记录；`/dashboard/intersections` 从 2.46–2.93s 降到 9.2–16.4ms，加载阶段不再把未返回数据标成 0。随后针对“计数有 500、地图仍无折线”的二次反馈，确认最新 500 条为缺世界坐标或仅 5 点、移动中位长度约 0.68m 的短片段；接口改为在 PostgreSQL LIMIT 前按 `spatial_ready` / `min_world_points` 过滤。最终 `INT_camera_1` 返回 285/285 条至少 6 点的世界轨迹，点数中位数 50；真实任务 `MSN-3421232DD4B9` 在页面投放 149/149 条彩色折线并清楚覆盖路口四向，浏览器 console 0 error / 0 warning。
- 事故测绘：六套数据各有真实任务、4 项点线面量算和 PDF/JSON/GeoJSON 成果；报告明确 `unverified`、误差口径待批准和“非责任认定书”边界，主平台投递继续由质量门禁阻断。
- 全新浏览器会话依次访问 `/events`、`/gis`、`/survey`，console 为 0 error / 0 warning。

关键截图：

- `output/playwright/event-center-real-evidence-1440x900.png`
- `output/playwright/trajectory-analysis-real-mission-1440x900.png`
- `output/playwright/accident-survey-real-report-1440x900.png`

## 5. 可靠性与恢复

- `ReliableKafkaPublisher` 单元回归覆盖 durable record 先原子落盘、发送失败保留、重启重新扫描并成功清除、best-effort 队列满时计数降质。
- 真实 Mission `MSN-6E575AC0B5E8` 运行中短停 Kafka，MJPEG 与检测进程保持；Kafka 恢复后任务正常收尾，活动 Mission 归零。
- 本次短故障窗口没有产生新的“已完成轨迹/真实冲突”durable 事实，因此未形成可观察的 spool 待回补文件；正向文件回补由自动化故障测试证明。后续生产门禁仍须执行长时 broker 故障、进程崩溃、磁盘满和容量压测。

## 6. 本轮改进

- 增加 Mission/Pipeline/Run/Source/Inter/Road/Quality 全链路 lineage 和轨迹点真实观测时间；
- 增加可靠 Kafka 发布深模块，替代仅内存队列且不引入 SQLite；
- 持续拥堵仅在第 30 个连续超阈值样本固化证据快照，避免详情展示“当前帧”漂移；
- 事件中心统一真实 AI 事件、冲突、质量下降和测绘成果；修复证据包 ORM 插入顺序；
- 轨迹页增加 Mission/Source/全部验收数据筛选，解决离线业务时间默认 1 小时不可见；
- 轨迹页加载状态区分“路口加载中 / 轨迹等待路口 / 轨迹加载中 / 加载失败”，失败态提供真实数据重试；Dashboard 最新指标和遥测使用 PostgreSQL `DISTINCT ON` 在数据库侧降行；
- 轨迹 API 增加 `spatial_ready` / `min_world_points`，在 PostgreSQL LIMIT 前筛选可投放事实；GIS 默认至少 6 个世界坐标点，并使用嵌入面板安全 padding，避免短片段和主监控布局参数让折线不可见；
- 测绘报告同步为事件事实并挂接三类成果证据；
- 修复 MJPEG 启动竞态、React Query 更新和测绘版本重复 `v` 展示。

## 7. 保留边界

本机产品深度展示闭环通过；以下仍不宣称完成：权威道路/坐标和测绘精度批准、冲突正样本业务签字、法制证据、主平台合同与投递、生产镜像/秘密/TLS/SASL/HA、容量、保留策略、备份恢复和 RPO/RTO。

## 8. 收尾状态（2026-07-17）

- 当前分支 `codex/2.0`，收尾检查 HEAD `23252d6`；工作树包含本阶段大量既有未提交改动，未执行提交、重置或清理。
- Platform `104 passed / 5 skipped / 10 subtests`，Console2 `56/56`，生产构建和 `scripts/audit_adr019_retirement.py --scope local --strict` 通过。
- 正式本机服务保持运行，`road9`、Kafka 和 Platform 健康，Console2 可从 `http://localhost:8080` 继续验收；未停止用户正在使用的服务。
- 本轮本地缺陷和文档同步已收尾；后续只继续外部验收门禁、生产化工作或明确新增需求。

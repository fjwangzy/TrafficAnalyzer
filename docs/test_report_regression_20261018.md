# 2026-10-18 本机系统功能回归

## 结论

**未通过整体回归门禁。** 隔离环境的数据库迁移、真实视频自然 EOF、Kafka 落库对账、回放 API、Cookie WebSocket 控制链和主要业务页面通过。现有 `8000` Platform 在重测试期间多次健康/登录超时，重任务结束后未经重启恢复；真实接口复验 **29 PASS / 1 BLOCKED**，MP4728 历史轨迹小窗回放仍超时。

工作树中的 Platform 自动化通过；根级套件有一项首次超时、独立复验通过；Console 默认等待条件下失败，延长异步等待后失败文件全部通过。ADR-019 严格审计仍有历史运行态证据版本阻断。未修改业务实现、生产配置、既有数据库或 Kafka offset；本次只增加测试证据与文档。

## 环境与隔离

- 分支 `codex/2.0`，HEAD `3bd8c5bf6753982eecea54d5c8cc7677850bb582`，针对当前含大量未提交改动的工作树验证，已有改动保留。
- Python `.venv-mps/bin/python` 3.11.15、macOS arm64、PyTorch 2.2.2，MPS 可用。检测设备保持 MPS；显式 `PYTORCH_ENABLE_MPS_FALLBACK=1` 仅允许既有不支持算子的回退。
- Node 26.0.0 / npm 11.12.1；复用依赖，未安装或升级包。
- 现有原生 Platform `8000` 初始 `/ready` 为 `replay_v2/ready`、活动 Pipeline 为 0；重测试期间超时，结束后恢复。该进程未重启，当前磁盘代码与长驻进程加载版本不保证完全相同。
- 根 Compose 的新隔离 project `traffic_regress_20261018` 仅启动 `road9` 和 Kafka，使用新独立卷、端口 `15432/19092`；原生 Platform 使用 `18010`。未在 Docker 中运行 Mac Platform。
- 隔离数据库为 `road9.public`，随机测试凭据仅在 Git 忽略的 `0600` 证据文件中；没有读取/修改生产 `.env`。Console 临时 `5174` 通过进程环境将 REST 指向隔离 Platform，未改 `.env` 或 Vite 配置。
- 日志、JUnit、机器结果位于 `output/regression/20261018/`，截图位于 `output/playwright/regression-20261018/`。这些本机产物不随文档自动分发，包含私有测试环境文件，不应直接打包公开。

## 自动化结果

| 验证 | 结果 | 证据（相对于证据目录） |
| --- | --- | --- |
| Platform 全量，显式关闭外部/写库门禁 | **399 passed / 0 failed / 9 skipped**，另 10 subtests passed，202.90 秒 | `platform.log`、`platform.xml`、`platform-summary.json` |
| 根 `test/` 全量 | **374 passed / 1 failed / 3 skipped**，358.62 秒 | `root.log`、`root.xml` |
| 根级唯一失败独立复验 | **1 passed**；原 30 秒子进程超时未复现 | `root-eof-reproduce.log` |
| 重构独立脚本 | 119 passed / 1 failed，与根级同一超时；不重复累计 | `refactor.log` |
| 无 YOLO 当前节点链，真实 200 帧 | **37 PASS / 0 FAIL / 0 WARN** | `no-yolo.log` |
| XQH 100 帧 MPS 旧基线 | **55 PASS / 0 FAIL / 1 WARN**，未达到文档 56/0/0 | `xqh.log` |
| Console 全量，最多 2 worker，原等待时限 | **231 passed / 51 failed**，25 文件，530.00 秒 | `console-test-workers2.log` |
| Console 两失败文件，单 worker / case 30 秒 | 116 passed / 11 failed，Testing Library 仍使用独立短等待 | `console-test-failedfiles-serial.log` |
| Console 两失败文件，单 worker / asyncUtilTimeout 10 秒 | **127/127 passed**；结合其余文件，282 个唯一用例均在记录条件下至少通过一次 | `console-test-async10s.log`、`console-summary.md` |
| Console 顺序构建 | **通过**，5305 模块，35.98 秒 | `console-build-sequential.log` |
| 独立空库两套迁移 | **通过**，TimescaleDB 2.28.2，canonical 5 个及 Replay V2 1 个超表 | `isolated/summary.json` |
| 显式真库集成 | **5 passed / 2 skipped**，覆盖态势、执法、指标事务、Replay V2 与测绘 | `isolated/summary.json` 及其引用日志 |
| ADR-019 本机严格审计 | **9 PASS / 1 BLOCKER** | `adr019-local.log` |

最早的 Console test/build 并发执行因资源压力主动停止，退出 130，原日志保留且不作为完整结果。根级/refactor 的唯一失败为 `test_shared_frame_survives_reader_tracker_close_until_show_unlinks`：子进程导入及共享内存检查超过硬编码 30 秒，无共享内存断言失败；独立复验通过。未更改测试断言或业务代码来获得通过。

Platform 的 9 个 skip 中，5 个 PG 集成在新隔离实例另行通过；两项 Mission 集成硬编码要求 `road9_i2_test`，且包含无条件清理控制面表，本次坚持 `road9` 约束而未执行。外部 Doris live 和本机缺可选 psycopg 的瀚高驱动测试未执行。根级另外 3 个 skip 是需显式启用的 ARM64 Console 真实容器用例。

## 真实视频与持久化

使用既有 XQH 前 20 秒派生片段、原 SRT、唯一生产入口 `main_optimized.py`，原生 MPS、stride 10、初始 imgsz 640，生成唯一 `SRC-REGRESS-XQH-20S-20261018`。这是 Replay V2 隔离链，未写 canonical 业务 Topic/事实表。

| 事实 | Kafka / road9 对账 |
| --- | --- |
| 统计 / 遥测 | 50 / 60，均完全一致 |
| 完成轨迹 | 191，完全一致 |
| 轨迹点 | 6761 / 6761，字段对齐失败 0 |
| 冲突候选 | 0；本短片未提供冲突正例 |
| 生命周期 | running、sealed 两消息归并为一条 sealed Mission |
| 发布排空 | 303 / 303，durable_pending=0 |
| 聚合 | intersection_5min=2、typical_5min_mm=2、turn_5min=5 |
| 回放 | API 返回 191 轨迹 / 6761 点，无截断；实窗查询约 3577ms |

机器结果 `isolated/eof-summary.json` 为 `passed=true`，对账 mismatch 为空。无正式路网，Lane/Link 聚合 0 不作为道路能力通过。世界点允许为空，coverage 0.270522 不作为位置精度结论。

验收总耗时 236.944 秒，检测进程约 202.9 秒；旧 XQH 100 帧脚本耗时 334.5 秒。测试时内存/压缩压力及其他 VM、浏览器负载明显，这些耗时均不作受控吞吐基准，亦不能证明全部延迟由并发导致。XQH 另有 NMS time limit 和 half 参数弃用日志。

XQH 的方向统计 WARN 还存在覆盖边界：旧脚本未接入当前 FlightGeoReference/PostTrackingWorldProjection 质量链，方向节点对地理资格不满足返回空统计；不能只解释为前 100 帧太短，也不能替代当前完整链方向验收。当前无 YOLO 链与短片 EOF 证据独立保留。

## 真实 API、WebSocket 与页面

- 现有 `8000`：后续 `/health`、匿名/无效认证、登录以及禁用系统代理的 curl 均在 10 秒超时。浏览器两次登录也出现前端 10 秒超时，无法执行该实例认证后的业务功能。见 `live-api-smoke.json`。
- 重任务结束后补测现有 `8000`：**29 PASS / 1 BLOCKED**。登录、认证拒绝、五模块列表、overview、Cookie WS 三 canonical 通道订阅及 ping/pong 恢复；读取无人机7、来源16、测绘任务13、事件150、告警27、飞行计划1、Mission125。XQH路口4个回放Mission，10秒/100点窗口200（2.287秒）；MP4728有1个sealed Mission，但10秒/100点窗口超过客户端10秒，尚未验证恢复。最后health200/0.021秒、ready所有依赖healthy；见 `live-api-after-heavy.json`。原失应与恢复证据分开，不能把任一阶段覆盖掉。
- 恢复后真实浏览器登录 `5173` 成功；XQH GIS显示4个路口/1427条汇总轨迹，当前窗口123条轨迹/3条冲突，页面标注质量与归因限制。实际点击播放后游标从T+10推进到T+13，最终在T+20秒暂停；只验证短时播放，不作为持续回放稳定性或冲突真值验收。见 `browser/gis-live-playback.txt`、`browser/gis-live-paused.yml`、`gis-live.png` / `gis-live-playback.png` 截图。
- 隔离 `18010`：登录成功，匿名及无效认证均为 401；健康、就绪、用户、管道、无人机、来源、Mission、计划、告警、执法与测绘列表及 dashboard overview 均返回 200。空列表如实显示。见 `isolated-api-smoke.json`。
- 隔离环境未配置外部 Doris；带完整参数的 situation API 返回 503 `DORIS_NOT_CONFIGURED`，首页显示读取失败。先前省略必填参数的 422 是测试请求校验对照，不算功能缺陷，也不算 Doris 验收。
- 当前 WS 代码拒绝 URL `access_token`（403），登录下发的 HttpOnly Cookie 握手、`uav_system` 订阅 ACK、ping/pong 通过；没有发布测试消息。见 `isolated-websocket.json`。
- 隔离浏览器完成登录、首页、轨迹研判、事件、测绘、执法、飞行任务、系统及监测入口检查；证据见 `browser/summary.json` 和截图。列表空态/无项目状态不能替代真实数据业务操作。
- GIS 读取 `/dashboard/intersections` 的项目快照，隔离实例该接口及项目表均为空；`/intersections` 的 3 条内存默认项不属于该数据源。页面的 0 路口符合当前隔离数据，未通过写库造项目来掩盖此限制。
- 隔离监测页因为没有登记 SourceProfile 而进入明确标注的 `SRC-DEMO-XQH` 固定演示；仅验证入口和渲染，不把演示指标、轨迹或冲突数字算作真实检测证据。
- 临时 Console 的 WS 代理仍固定到 `8000`，所以页面的实时连接不作为隔离 WS 通过证据；上面的直连 Cookie 握手单独验证了控制链。未验证新的实时 MJPEG 页面、事件人工复核或长时间轨迹播放。
- 收尾只停止本次 `18010` 原生进程和隔离 road9/Kafka 容器，`18010/15432/19092` 已释放；独立卷与证据保留，原有 `8000`、数据库/Kafka及其他容器保持。见 `isolated/cleanup.json`。
- 本次两台 Vite 临时服务及独立测试浏览器已关闭，未停止用户原有服务。文档秘密检查、私有测试环境0600检查和最终 `git diff --check` 通过。

## 失败、阻断与后续处理

1. **P1：MP4728 历史回放窗口仍超时。** 重任务结束后主要API恢复，但 `INT_MP4728_JINGSHI_CORRIDOR` / `MSN-RV2-2624faf14cbe` 的 `cursor_sec=10&window_sec=10&max_points=100` 超过10秒；XQH同形查询200。应先定位该Mission的查询/序列化成本，不能用缩减返回点数或健康200宣布回放恢复。
2. **P1：Replay V2 transport 身份冲突持续重试。** 只读查询证实 3 个 Topic 的 `(partition=0, offset=0)` 已绑定旧 message_id/hash，当前尝试消息身份不同。Replay V2 `persist` 只按 message_id 去重，唯一键错误被消费者 seek 回同位置、每次至少等待 1 秒再重试，未进入外层错误上限或隔离路径。日志快照累计 19,676 次该错误，不是本次测试制造的错误数。canonical 适配器已有 transport conflict 分支可作修复参照；未证明 Topic 重建历史或该问题与 HTTP 超时的因果关系。定位与行号见 `live-api-diagnosis.md`。
3. **P2：资源压力下服务响应与默认测试等待不稳定。** 重测试期间公共健康/登录失应，结束后恢复，未证明唯一因果；根级导入30秒、前端case5秒/Testing Library短等待也触发失败。单独复验及延长异步等待后通过，不等于原命令通过；未修时限或隐藏失败日志。
4. **P2：隔离 Kafka 健康探针超时。** `docker compose up --wait` 实际退出 1；同一 Java 探针手动运行 exit 0 但耗时 19.074 秒，超过 Compose 5 秒限制。镜像均 ARM64，Kafka API 与 303 条传输通过；启动等待仍不算通过。见 `isolated/kafka-healthcheck-diagnostic.json`。
5. **ADR-019 证据门禁。** 历史报告记录 revision `20260723_0019`，当前 head 为 `20260728_0020`；本次空库成功不自动改写该历史验收格式或证据，严格审计仍失败。

先处理 MP4728 回放超时与 live transport 冲突隔离并补失败先行回归，再复验原测试时限、资源压力下响应及 ADR 运行态证据；本轮没有替用户进行未经要求的业务修复、清库、offset 重置或重启。

## 验收边界

未运行完整 992 秒视频、外部 RTSP/MQTT、Doris live、瀚高/国密驱动、昇腾 NPU、生产网络与权限、HA/备份恢复或正式业务签署。两项 Mission 真库用例及 3 项容器门禁如上保留。无批准真值，IDF1/HOTA、正式 ID switch、位置 RMSE、速度 MAE、precision/recall 均为 `not_evaluated`，不创建人工轨迹标注工作包。

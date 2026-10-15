# 2026-10-04 需求回归测试报告

> 本文保留首轮回归的失败证据。后续修复及功能工程验收结果见
> `docs/test_report_functional_acceptance_20261004.md`（889 passed/0 failed/0 skipped）；
> 50项功能和23项场景的新证据索引见对应functional矩阵。

## 结论

本轮回归完成，结论为 **未通过整体回归门禁**。三套自动化测试合计
`862 passed / 1 failed / 6 skipped`，另有 `10 subtests passed`；两个独立脚本中断，
历史轨迹回放存在真实运行态阻断。Console2 全量测试和构建通过；XQH 前 100 帧基线
为 `55 PASS / 0 FAIL / 1 WARN`。ADR-019 本机严格审计为九项通过、一项既有证据门禁阻断。

需求基线为 `outputs/20260922_uav_acceptance/易出行无人机智能感知与智算模型需求规格说明书-用户需求验收版-V1.2-commit.docx`
第四章正文的五个模块、50 项功能和 23 项验收场景。本文的“自动化相关用例通过”只表示
现有测试被执行，不等于逐项完成用户操作、真实素材验收或正式签署。

## 环境与证据

- 仓库：`/Users/yaoyao/ai/TrafficAnalyzer`；分支：`codex/2.0`；代码 HEAD：`440d649b5a71f9b3d14733426620e11eba5c1c7e`。
- 开始时已有 `docs/TASKS.md` 修改及 `req/.DS_Store`、`req/报价/` 未跟踪文件，全部保留。
- 最终 Python 验证使用 `.venv-mps/bin/python`：Python 3.11、原生 macOS arm64、PyTorch 2.2.2、MPS 可用。
- 初轮默认 Python 为 Conda Python 3.12.11/x86_64。Platform 和基础测试通过后，Platform 全量及根级全量在原生环境执行，以原生结果为最终口径。
- Node.js `v26.0.0`；Console2 使用已有依赖；未安装或升级依赖。
- 使用已有原生 Platform `127.0.0.1:8000`，测试预览在 `127.0.0.1:5175`。
- 原始日志、JUnit XML、需求文本、API 状态和截图位于 `output/regression/20261004/`；该目录为本机生成证据，文档提交不会自动携带这些文件。

## 命令及结果

| 验证 | 实际命令 | 结果 | 证据 |
|---|---|---|---|
| Platform 全量 | `.venv-mps/bin/python -m pytest platform/tests -q -rs --junitxml=output/regression/20261004/platform-native.xml` | 327 passed、6 skipped、10 subtests passed；退出 0 | `platform-native.log`、`platform-native.xml` |
| 根级全量 | `PYTORCH_ENABLE_MPS_FALLBACK=1 .venv-mps/bin/python -m pytest test -q -rs --junitxml=output/regression/20261004/root-native.xml` | 283 passed、1 failed；退出 1 | `root-native.log`、`root-native.xml` |
| 根指令中的七个基础测试文件 | `python -m pytest test/test_kafka_active_trajectories.py test/test_utils_local.py test/test_byte_tracker_core.py test/test_main_optimized_eof.py test/test_road9_compose_runtime.py test/test_telemetry_file_reader.py test/test_video_reader_frame_stride.py -q` | 50 passed；退出 0，已被根级全量覆盖，不重复累计 | `core.log`、`core.xml` |
| Console2 全量 | `cd console2 && npm test` | 24 files、252 passed；退出 0 | `console-test.log` |
| Console2 构建 | `cd console2 && npm run build` | production build 成功；退出 0 | `console-build.log` |
| XQH 视频/SRT 基线 | `PYTORCH_ENABLE_MPS_FALLBACK=1 .venv-mps/bin/python test/test_pipeline_inter_xqh.py` | 55 PASS、0 FAIL、1 WARN；退出 0 | `inter-xqh-native.log` |
| 重构独立脚本 | `.venv-mps/bin/python test/test_refactor_unit.py` | `speed_kmh=None` 做除法，脚本中断；退出 1 | `refactor-script.log` |
| 无 YOLO 独立脚本 | `.venv-mps/bin/python test/test_pipeline_no_yolo.py` | `speed_kmh=None` 与 0 比较，脚本中断；退出 1 | `no-yolo-script.log` |
| ADR-019 | `python scripts/audit_adr019_retirement.py --scope local --strict` | 9 pass、1 blocker；退出 1 | `adr019-local.log` |
| 已运行服务 | `GET /health`、`GET /ready` | 均为 200；database/Kafka/TimescaleDB/pipeline_manager healthy，活动 Pipeline 为 0 | `health.json`、`ready.json` |
| 实际业务 API | 登录后只读 GET，通过 OpenAPI 发现列表入口 | 8 个列表/摘要入口 200；两个路口 replay-missions 均为 503 | `live-api-smoke.json` |
| 工作区检查 | `git diff --check` | 通过 | 完成文档更新后再次执行 |

Platform 有一条 Starlette/httpx 弃用警告；npm 提示现有用户配置 `home` 后续版本不支持。
这些提示不造成此次自动化测试或构建失败。

## 按需求模块验证

| 需求模块 | 本轮自动化证据 | 本轮真实页面/数据观察 | 用户验收缺口 |
|---|---|---|---|
| S1 路口态势，UR-S1-001～010；UR-AC-S1-01～04 | 核心 API、轨迹分析、坐标/速度、车道匹配、排队质量、监控/回放前端用例已运行；XQH 100 帧有检测和遥测 | 工作台地图加载；监测页显示登记来源、离线/遥测过期/等待数据和历史统计；轨迹研判页面失败 | 轨迹 Mission 列表 503 阻断回放；100 帧无方向统计；未执行实时视频中断和全链路自然 EOF 对账 |
| S2 换道与冲突，UR-S2-001～010；UR-AC-S2-01～05 | 换道识别/普通转弯排除、22 项 TCC 诊断、证据发布、风险升级与去重相关用例通过 | AI 事件中心显示 150 条历史事件，包含 TTC/PET、已驳回/待复核和质量状态；监控页可见双方证据入口 | 100 帧素材没有换道/冲突；本轮未新增真视频正例、提交复核或验证持久化审计 |
| S3 事故测绘，UR-S3-001～010；UR-AC-S3-01～05 | 测绘几何、面积/周长、标注版本/audit、证据校验、PDF 标注图、事件关联测绘测试通过 | 测绘列表读取 13 个已有任务，显示状态、成果版本与报告生成状态 | 未创建新现场任务或导入新资料；人工技术复核、退回、报告下载完整操作链未重做 |
| S4 执法候选，UR-S4-001～010；UR-AC-S4-01～04 | 区域/规则权限、候选边界、货车与速度候选、证据发布用例通过 | 区域、规则、线索 API 均返回真实空列表；页面为 0 条线索，提供类型/复核状态筛选 | 缺运行态区域/规则/线索正例，不能确认真实货车、违停/滞留和人工复核闭环；相关真库用例跳过 |
| S9 任务与来源，UR-S9-001～010；UR-AC-S9-01～05 | 单次/周期、跨午夜/例外、来源校验、状态与错误保留、停止权限及执行器测试通过 | 无人机 7、来源 16、计划 1、Mission 122，活动任务 0；离线状态与最后遥测分开显示 | 未向现有库创建/修改任务；并发防重与重启恢复的两项真库用例跳过；未执行外部 RTSP/MQTT |

需求逐项映射见本报告同目录的 `regression_requirement_matrix_20261004.csv`。
该矩阵列出全部 50 项需求、相关测试证据和未执行环节；它是证据索引，不是功能全部通过的声明。

## 失败与阻断

### REG-001：历史轨迹回放在现有运行态不可用（P1）

- 打开 `/gis?period=latest30m`，页面默认路口为 `011wwe0z19700001`，显示
  `历史轨迹分析不可用 / ReplayRepository unavailable`，播放历史回放按钮禁用。
- 登录后直接 GET `/api/v1/trajectories/011wwe0z19700001/replay-missions` 及
  `/api/v1/trajectories/INT_camera_1/replay-missions`，均返回 `503` 和同一错误。
- 同时 `/ready` 仍返回 200，说明当前健康检查不能代表回放功能可用。
- 关联需求：UR-S1-006、UR-S1-009、UR-AC-S1-04。
- 源码证据：`platform/app/api/v1/trajectories.py:32` 在 repository 缺失时返回 503；
  `platform/app/main.py:103` 仅在数据库可用且 runtime profile 为 `replay_v2` 时创建该对象。
  **推断**：优先检查当前服务运行档与 Console2 的 Replay V2 页面依赖是否一致；本轮未改运行档或重启服务，未确认最终根因。
- 截图：`output/regression/20261004/gis-error.jpg`；DOM：`gis-dom.txt`；API：`live-api-smoke.json`。

### REG-002：遥测速度缺失测试夹具不完整（P2）

- 失败用例：`test/test_telemetry_time_quality.py::test_srt_and_json_do_not_invent_zero_motion_when_speed_is_absent`。
- 测试通过 `object.__new__(TelemetryFileReader)` 跳过构造，只设置 `agl_policy`，未设置
  `camera_lens_policy`。调用 `services/TelemetryFileReader.py:135` 时产生 AttributeError。
- 正常构造函数在第 41 行初始化该属性；因此证据指向测试夹具与现有构造契约不一致，
  不能将这一异常直接解释为正常 JSON 读取失败。
- 独立命令 `.venv-mps/bin/python -m pytest test/test_telemetry_time_quality.py::test_srt_and_json_do_not_invent_zero_motion_when_speed_is_absent -q`
  再次退出 1，证据为 `telemetry-failure-repro.log`。本轮未修改测试或运行时代码。

### REG-003/004：两个脚本沿用不可空速度假设（P2）

- `test/test_refactor_unit.py:103` 使用无标定的像素轨迹，将 `speed_kmh` 除以 3.6；
  当前结果为 None，第一组验证即中断，后续检查未执行。
- `test/test_pipeline_no_yolo.py:405` 判断 `track.speed_kmh > 0`，结果为 None 时中断，
  Phase 5 及后续流程未完成；之前素材读取、H 矩阵和运动补偿检查成功不能替代完整脚本通过。
- 当前速度契约回归 `test/test_speed_estimation_coordinate_contract.py` 明确要求缺逐帧世界事实时
  `speed_kmh=None`，且本轮通过。修复方向应让测试素材提供合格世界事实、明确测试运行档，
  或验证不可用结果；不得为通过旧脚本而把像素速度伪装成 km/h。

### 既有门禁及未运行项

- ADR-019 `local_runtime_evidence` 仍为 blocker；代码/Compose 检查通过不关闭它。本轮没有清库、
  重建、迁移、挂载旧资产或清理旧卷，未重新生成空库/Kafka 空状态验收。
- Platform 六个 skip 来自 dashboard、enforcement、metric、Replay V2 各一个真库用例及两个 Mission
  真库用例。它们要求显式 `RUN_PG_INTEGRATION=1`，其中 Mission 要求可丢弃数据库；本轮沿用默认隔离，
  不在已有业务库执行这些写入用例，真实数据验证只执行只读查询。
- 独立运行态 E2E 脚本与 pytest 分开收集；本轮未运行其旧端口/旧运行档配置，未发布 Kafka 测试消息，
  未完成 `main_optimized.py` 三进程自然 EOF → Kafka → road9 → 页面全量对账。
- 本轮不构成正式生产验收。没有批准真值时，IDF1/HOTA、正式 ID switch、位置 RMSE、速度 MAE
  继续为 `not_evaluated`；100 帧 7.3 fps 只是本次单进程基线耗时，不代表生产吞吐能力。

## XQH 本轮观测

素材和 `weights/uav_best.pt` 均存在。原生 MPS 运行处理 100 帧，耗时 13.7 秒（7.3 fps），
100/100 帧有检测，累计检测 8,044 个，遥测及 H 矩阵均为 100/100，运动补偿为 90/100。
完成轨迹、换道、冲突均为 0，最终 `cars_amount=87`。

未设置 `PYTORCH_ENABLE_MPS_FALLBACK=1` 的初次执行为 `49 PASS / 1 FAIL / 0 WARN`：
`torchvision::nms` 在此 PyTorch/MPS 组合上未实现。复测显式打开已有文档记录的算子 fallback，
检测设备仍为 MPS，仅不支持的算子回退。未将检测器设备改为 CPU。

`direction_stats` 前 100 帧为空产生一条警告，与最近报告一致；未达到根 AGENTS.md 的
历史理想值 `56 PASS / 0 FAIL / 0 WARN`。此脚本是有限帧单进程基线，不能证明完整视频自然 EOF。

## 后续复验顺序

1. 处理 REG-001 的运行档/回放依赖，复验两路口 replay-missions、任务选择和真实轨迹播放，
   同步检查健康信息是否足以反映必需业务能力。
2. 修正 REG-002 测试夹具及 REG-003/004 素材/可空速度假设，重新执行根级全量与两个独立脚本。
3. 在明确隔离的本机 road9 测试环境运行六项真库用例，再按 23 个验收场景执行真实操作链，
   特别是事件复核、测绘版本/报告、执法正例及任务重启/并发恢复。

本轮只新增测试报告与文档记录；没有提交、推送、部署或修改业务实现。

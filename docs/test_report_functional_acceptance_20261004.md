# 2026-10-04 修复与功能验收推进报告

## 结论与范围

首轮回归发现的问题已修复，并补齐实际回放、空库初始化、真库事务、真实素材测绘和自然 EOF 数据对账。
最终三套自动化验证为 **889 passed / 0 failed / 0 skipped**，另有 **10 subtests passed**。
其中 Platform 真库用例在独立 `road9` 上显式启用，没有写入已有业务库。

这是本机工程验收，不是50项用户功能全部签署通过。需求基线仍为 V1.2-commit 正文的五个模块、
50项功能和23项验收场景。真实断流、外部 RTSP/MQTT、业务规则适用性和正式签署仍需补齐；
没有批准真值时，正式检测/跟踪/位置/速度精度继续为 `not_evaluated`，不建立人工轨迹标注工作包。

## 实施内容

| 问题 | 最终改动 | 证明 |
|---|---|---|
| REG-001 回放仓库未初始化 | 原生脚本和根本机入口默认 `replay_v2`；就绪响应报告运行档及回放能力，启动检查档位一致 | 两路口回放任务/点接口恢复200；真实页面选择 Mission 后播放至T+27秒 |
| REG-002 遥测测试缺字段 | 测试使用真实构造函数和文件读取，不手工拼不完整对象 | 根级全量通过 |
| REG-003 旧重构脚本误把像素速度当km/h | 复用当前速度、生命周期、统计、TCC、渲染及EOF维护套件 | 独立入口118 passed |
| REG-004 无YOLO脚本未接当前投影链 | 补齐图像运动/ByteTrack/地理参考/后投影；缺世界事实明确验证可空速度 | 200帧真实视频+JSON遥测+合成检测为37 PASS/0 FAIL/0 WARN |
| 空库迁移重复DDL、canonical创建V2表 | canonical基线排除V2表，历史增量避免重复创建当前基线对象；V2约束和字段按实际存在状态新增 | 根Compose独立空库两套迁移成功，5+1个hypertable；SQLite基线回归验证namespace隔离 |
| GCJ-02范围筛选读取旧lon/lat | bbox读取现行 `center_gcj02`，不添加旧坐标适配字段 | 真库坐标与范围筛选通过 |
| 共享帧重复unregister | reader/tracker只close，show唯一unlink；共享进程树不逐句柄移除资源注册 | 重叠句柄回归通过；最新短片完整管道无resource_tracker KeyError |
| 禁停时间误累计、失去观测仍累计 | 只累计连续低速、有效当帧位置；未知速度/失观测/时间断点重置；GCJ02不回用旧有效尾点，未知标签保持unknown | 快速穿越、未知速度、丢失位置、源时间空洞等失败先复现，再全部通过 |
| EOF留3415条持久消息却返回成功 | 每Pipeline缓存有序spool队列，避免逐条重扫文件；配置120秒有界排空；剩余持久消息使EOF失败，周期消息超时记录drop reason | 300条集中发送与故障用例通过；3415条恢复发送4.421秒、剩余0；最新短片发送覆盖1.0 |
| 验收器仍采用旧shadow协议 | 当前BEV允许200条/30点有界实时尾迹；生命周期running→sealed为两条消息、一条Mission事实；默认8000与原生Python环境 | 新协议、超限、生命周期及逻辑事实对账回归通过，最新管道验收退出0 |

## 最终验证

| 验证 | 结果 | 本机证据 |
|---|---|---|
| `.venv-mps/bin/python -m pytest test -q` | 298 passed | `output/acceptance/20261004/root.log`、`root.xml` |
| 隔离库 `RUN_PG_INTEGRATION=1 ... -m pytest platform/tests -q -rs` | 339 passed、0 skipped、10 subtests passed | `platform-full.log`、`platform-full.xml` |
| Console2 `npm test` | 24 files / 252 passed | `console.log` |
| Console2 `npm run build` | 成功 | `console-build.log` |
| 重构独立入口 | 118 passed（包含在根级套件，不重复累计） | `refactor.log` |
| 无YOLO真实素材链 | 37 PASS / 0 FAIL / 0 WARN | `no-yolo.log` |
| XQH前100帧基线 | 55 PASS / 0 FAIL / 1 WARN | `xqh.log`；方向统计为空仍为既有警告 |
| 当前实现20秒完整管道 | 自然EOF、发送排空、封存及对账通过 | `eof-current-final/SRC-ACCEPTANCE-XQH-20S/result.json` |
| Ruff、shell语法、diff check | 通过 | `ruff.log`、`bash -n scripts/mac_local_platform.sh`、`git diff --check` |

Python为原生macOS arm64 `.venv-mps`，检测器使用MPS；不支持的NMS算子通过已有显式
`PYTORCH_ENABLE_MPS_FALLBACK=1` 处理。Platform没有放入Docker。前端源码未修改。
Starlette/httpx、Alembic配置及Ultralytics half参数有弃用提示，不作生产版本兼容承诺。

## 完整XQH与恢复过程

原始992秒MP4/SRT以stride10、原生MPS、唯一生产入口 `main_optimized.py` 完整自然EOF。
首轮执行约28分钟，退出时留下3415条持久消息，首轮验收明确失败，原始失败结果保留。
该轮仍使用共享内存修复前的进程代码，日志中的resource_tracker异常没有被隐藏。

修复后的发送器重新打开该Pipeline专属spool，3415/3415条在4.421秒内补发，
`coverage_ratio=1.0`、`durable_pending=0`。补发和重新验证不重做图像推理，也不替换原始观测。

| Kafka观测/业务事实 | 对账结果 |
|---|---|
| 统计样本 | 1111 = road9 1111 |
| 完成journey | 4644 = road9 4644 |
| 冲突候选 | 10 = road9 10；不表示10个已确认真阳性 |
| 遥测样本 | 2479 = road9 2479 |
| 生命周期 | running、sealed两条消息更新一条Mission，最终sealed |
| 实际/典型聚合 | intersection_5min=9、typical_5min_mm=9、turn_5min=20 |
| 轨迹点 | source=128888、retained=128888，字段/数量对齐失败0 |
| 消息隔离 | canonical topic写入变化0；实时Stats尾迹符合当前有界契约 |

恢复后的证据为 `eof-recovered-validation.json`；原始失败证据为
`eof/SRC-INTER-XQH-0403-PM/result.json`。本轮没有lane_verified路网，不能把零Lane/Link聚合当成正式道路验收。

最新代码另用原视频前20秒派生片段完整复跑，约21秒自然EOF：统计8、journey191、遥测30、
running/sealed消息2，全部与真库对应；发送器231/231、剩余0，无共享内存KeyError。
这证明当前退出/传输修复，不冒充用最新代码再次完成全992秒推理。

## 真实素材S3功能闭环

通过独立Platform REST创建任务 `SVY-20261004-6018D1`，预检后导入原视频前20秒派生片段和原SRT。
实际worker解析600帧、遥测覆盖1.0，提取6个关键帧，6/6有米制变换；原始材料以allowlist相对key与SHA-256追溯。
绝对路径导入被422拒绝，正确相对key导入返回202，未扩展素材allowlist。

- 选择关键帧，创建线段与面积、现场对象标注，提交技术复核后模拟退回并保留原因。
- 线段从revision1的31.6772m修订为revision2的36.9568m；区域为111.4942m²、周长42.2363m。
  数值验证量算链路和单位，不是已知实物距离/面积的精度验收。
- 再次提交并模拟技术复核，生成 `RPT-3D584082E6B3`；鉴权下载PDF为726468 bytes、`%PDF`开头，
  SHA-256为 `3de11bb1f10f40db308086bb6b0b350ddc3e96173f2424ca17f74b7d1716d7db`。
- 质量保持unverified；正式交付按预期422“质量阈值未批准”，没有向主平台发消息，也没有代替人员签署。

接口状态、请求顺序、版本、报告与哈希见 `survey-api-state.json`，下载文件见 `survey-api-report.pdf`。
另新增S3真库用例验证受控几何、修改历史、审计、报告完整性及交付门禁，事务回滚且证据使用临时对象目录。

## 需求证据与验收边界

`functional_requirement_matrix_20261004.csv` 索引全部50项功能；
`functional_acceptance_matrix_20261004.csv` 索引23项场景，区分真实接口/页面验证、合成/真库自动化和待现场复验项。
测试数量不能换算为需求全部覆盖率。

- S1：回放与历史查询恢复；缺路网不伪造正式Lane/Link。真实视频断流后的页面操作尚未现场演练。
- S2：真实候选、证据发布和TCC门禁有工程证据；换道正例/普通转弯排除及复核状态以自动化验证为主，未宣称精度。
- S3：已跑真实素材导入、worker、选帧、量算、退回修订、模拟复核、PDF下载和交付阻断完整接口链；正式测绘参考与签署未完成。
- S4：规则/候选/证据幂等、确认→驳回→版本冲突的真库流程及持续低速门禁通过；实际视频规则适用性和正式执法依据未批准。
- S9：来源、周期/跨午夜/冲突、并发防重、EOF/错误持久化和失败重试新记录通过；真库测试执行器为受控FakePipeline，不等于外部飞控/RTSP/MQTT验收。
- ADR-019既有 `local_runtime_evidence` 门禁和生产安全、容量、保留、HA、RPO/RTO继续保留。本轮没有重建或清空已有业务库，也没有操作旧存储。
- 初始迁移仍需长期冻结为不随模型漂移的DDL；本轮验证当前空库路径，不宣称未来模型变更自动安全。

## 环境收尾

独立验证复用根Compose，project=`traffic_accept_20261004`，database=`road9`，端口15432/19092；
Platform原生运行于18010。独立密码保存在本机权限0600的runtime文件，不写入报告。
临时Platform/前端和验证容器验证后停止，独立卷与测试素材/证据保留以便复验；已有8000 Platform保持
replay_v2 ready且活动Pipeline为0。没有提交、推送或部署到生产。

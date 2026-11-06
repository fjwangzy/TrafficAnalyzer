# 四进程FPS优化：源码与本机验证（2026-11-04）

本轮已实现P1显示/归档视图拆分，以及P2的位置门控批量计算。源码已更新，未替换任何已交付tar.gz、未修改现场服务/数据库或发布新包。关联整体、状态/速度/冲突后续优化及生产五分钟A/B尚未完成。

原版参照为完整包2026.11.04.1内的services/PipelineEgress.py，SHA-256为ee4db42ec9b21ad8b7c21b7414005b3ac120bf9841df1b8143507ad8415f906b，与本轮修改前副本一致。完整结果、源码SHA和日志SHA见[validation.json](../output/fps-optimization-20261104/validation.json)。

## 1. 实际改动

### 数据交接

EgressClient.frame改为freeze_egress_views：帧元数据只从P2权威状态规范化一次，分别构建P3最小显示视图与P4归档事实。P3保留身份/道路/速度标签/成熟资格、最多30个像素尾迹及只读关联预览；ENU/GCJ-02、分类历史、质量历史、外观裁剪不再进入显示Track视图。P4仍保留原有业务元数据与水位，历史尾部仍由已接收增量按原点数恢复，不重新投影。

归档事实在返回显示视图前已同步pickle为独立bytes，跨消费者不会共享可变字典；P2原始状态独立保留。候选事实、事件、证据、annotation、共享内存描述保持。固定输入对照已核对归档事实语义一致，并检查原始状态/显示对象后续修改不会污染已发送数据。

新增egress.freeze_metadata、freeze_tracks、freeze_previews与按消息种类区分的serialize阶段，便于现场拆分发送前开销。协议、序号/hash、32批/1024点、持久ACK/10秒停滞、双EOF、关键消息排空预算未改。

### 位置门控

保留原Kalman project与原2行前向替代公式，只把同批轨迹的Cholesky与距离运算合并处理。每块最多64行，按检测数进一步控制临时数组规模（至少一行）；不构建无限增长的三维全量矩阵。

仅基础KalmanFilter、二维位置门控、至少8轨迹及浮点cost矩阵使用批量路径。四维门控、小输入、自定义filter仍用原路径。阈值邻域行回到原逐行距离计算；Cholesky失败回原路径，保留原失败语义。chi-square阈值、inf掩码、匹配阶段、指派与业务门禁未改，未关闭shadow诊断。

该优化针对门控子阶段，不等于整个关联耗时已经从144ms降到某个数值。

## 2. 本机测量

使用保存的原版与当前实现交替运行真实EgressClient.frame，每种250车负载热身20次、每版100次，正常启用GC。每次仅最后一点未发送，包含实际association显示/世界坐标/质量历史结构。ACK由内存sink立即返回，因此不包含磁盘、网络、检测和跟踪算法的成本。

初始脚手架存在GC/对象分配干扰，未使用其A/A时延结论；改用稳定sink并补A/A校准。最终A/A中位数差异约1.2%和0.9%，完整原始结果保留。下表为最终含新增阶段日志的代码：

| 环境与负载 | 原版交接中位ms | 新版ms | 降幅 |
| --- | ---: | ---: | ---: |
| Mac原生，250车×500点 | 41.95 | 11.51 | 72.6% |
| Mac原生，250车×5000点 | 45.40 | 11.79 | 74.0% |
| Linux ARM64私有运行库，250车×500点 | 37.05 | 12.60 | 66.0% |
| Linux ARM64私有运行库，250车×5000点 | 37.18 | 12.68 | 65.9% |

两种历史长度下，显示pickle字节均从1,380,474降至318,655（减少76.9%）；归档发送字节保持113,299。显示字节不随完整历史线性增加。归档字节相同之外，另有字段级语义一致性断言，不只比较大小。

当前代码细分日志在本机热身后微基准中位开销约0.4–0.6%，未覆盖现场冷启动或所有/proc读取情况。GC导致的P95长尾仍存在，例如ARM64长历史新版交接P95约102ms，不能据中位数宣称长尾或端到端FPS已经解决。各阶段P95、当前线程CPU和原始JSON均保留。

位置门控每组100次真实函数调用，成本矩阵逐元素一致：

| 环境，轨迹×检测 | 原版中位ms | 批量中位ms | 降幅 |
| --- | ---: | ---: | ---: |
| Mac，297×197 | 5.40 | 2.01 | 62.7% |
| Linux ARM64私有运行库，297×197 | 7.12 | 1.96 | 72.4% |
| Linux ARM64私有运行库，500×500 | 13.78 | 4.69 | 66.0% |

这些是合成状态下的真实子路径测量，Linux工具环境使用Alpine工具镜像承载包内私有加载器/Python和当前源码、断网/只读、cpuset0–3；不是UOS/310P3实机，不直接换算生产FPS。

## 3. 已执行验证

- `.venv-mps/bin/python -m pytest ...`：636 passed、11 skipped、10 subtests passed；包括Platform、传输/采样/EOF、显示、ByteTrack、原生控制器、Kafka可靠发送和归档。
- 新四进程回归覆盖：实际handoff载荷红测先失败，优化后通过；归档事实逐字段与旧契约一致，原状态隔离；成熟/候选、冲突、有/无视觉补偿共8组真实ShowNode逐像素对照；速度/道路标签与证据内容/hash对照；同版本回退开关事实一致。
- 新位置门控回归：12组297×197随机SPD矩阵逐元素成本一致，阈值邻域、空/小输入、float32/64成本、四维原路径、自定义filter及非正定错误。真实GroundTrajectoryTracker固定120帧/50目标、含遮挡，开/关优化的ID、框、类别、轨迹及诊断序列一致。
- Linux ARM64真实main_optimized.py：四worker、显式CPU合成视频、共享内存和自然EOF通过；强杀第四worker后整管道失败、journal与未确认包保留、无伪成功、所属SHM清理通过。
- 最终源码只读覆盖现有私有运行库，在根Compose派生的隔离PG/Kafka/Console运行：空库/显式init-db/双head门禁、鉴权API/WebSocket/媒体与新版Console资源、四worker真实Kafka→PG入库通过。300原始点→167保留点，均值/P85仍与全量摘要一致。临时服务/卷已清理，原开发PG/Kafka保留。
- 本轮修改位置lint及diff检查通过。matching.py原有cv2/time未使用、O命名共3个lint问题仍在，本轮未清理无关代码。

## 4. 真实素材回归的限制

运行现有`test/test_pipeline_inter_xqh.py`，使用现有uav_best.pt和真实小清河视频/SRT，记录100帧检测/跟踪/业务链。结果为55 PASS / 0 FAIL / 1 WARN，告警为direction_stats为空。替换回本轮修改前原门控再执行，同样55/0/1。

因此未达到历史56 PASS / 0 FAIL / 0 WARN门槛，不标记为该基线全绿；前100帧没有覆盖有方向统计的全部条件。两轮素材运行也不是固定检测逐帧完全差分、完整自然EOF或五分钟FPS测量；日志中的瞬时FPS不作为优化收益。外部真值精度指标继续not_evaluated。

## 5. 本机复跑与开关

```sh
.venv-mps/bin/python scripts/benchmark_pipeline_transport.py \
  --baseline dist/traffic-analyzer-native-2026.11.04.1/app/services/PipelineEgress.py \
  --output output/fps-optimization-local-repeat --iterations 100

.venv-mps/bin/python scripts/benchmark_association_gate.py \
  --output output/fps-optimization-local-repeat/gate.json --iterations 100

.venv-mps/bin/python -m pytest \
  test/test_four_process_transport_optimization.py test/test_position_gate_batch.py -q
```

新任务配置：`pipeline.transport_views_optimized`（环境变量PIPELINE_TRANSPORT_VIEWS_OPTIMIZED）与`tracking_node.batch_position_gate`（BATCH_POSITION_GATE）默认true。可在同一兼容源码版本中逐项关闭做受控对照；三进程默认拓扑/设备不变。不要在运行中切换Mission实现，不通过修改已校验包源码开关。未来完整包需同时带入配置与代码，原2026.11.04.1归档未被修改，不能在旧包上设置新开关期待生效。

## 6. 未完成与下一步

完整生产固定检测/遥测逐帧业务比较驱动、P2总服务时间与现场至少五分钟同源A/B尚未完成，不能宣布1.7–2.0或2–3 FPS目标达成。状态/速度/冲突未修改，关联总阶段80–110ms目标未验证。后续先补方向统计/成熟高负载场景和完整回放，再根据新增细分日志决定下一热点；不继续凭推测改业务算法。

本轮没有新增依赖/DDL、没有重建生产任务或重新发布归档。需要现场部署时交付新的完整包，保持v2摘要兼容、模型/认证/迁移/质量门禁，沿用失败保留与回退机制。

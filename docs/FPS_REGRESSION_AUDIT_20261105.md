# 2026-11-05 4.1→4.2 性能回归审计

## 结论与责任边界

4.2 将接收端完整轨迹改为 SQLite 数组，却没有缓存在线尾迹，导致每帧按轨迹×7字段做查询和 JSON 解码。486条轨迹即3402次SELECT；本轮四版本、两种轨迹规模、交替三轮的真实接收端组件复测稳定复现退化。此前以发送端微基准和单进程假ACK推断端到端收益，遗漏了这个发布回归。

这证明4.2归档组件存在回归，不证明现场两次不同素材/目标数量的FPS差距全部由SQLite造成。SQLite事务并非每条INSERT提交；PacketJournal每包fsync另计。保留持久ACK和有界内存，不能以去持久化掩盖吞吐问题。

## 本轮交付

- `benchmark_egress_receiver.py` 同时读取4.1/4.2/4.3/工作区源码，记录SHA256；默认三轮正反顺序对照，`--journal` 实际执行PacketJournal写入、flush、fsync；关闭全部轨迹并逐条核对frame序列，关闭后模拟发布回收。报告追加、恢复、journal和关闭的总耗时与P50/P95/P99。它仍是组件基准，批量关闭压力不能替代真实离场时序。
- `PIPELINE_PERF_AUDIT=1` 开启每worker阶段窗口计数/总耗时/有界4096样本P50/P95/P99；30秒输出一次`PERF_SUMMARY`。新增SQL批写、点JSON编解码、journal写入/fsync、关闭轨迹、合流等待和帧龄探针；Kafka已有`egress.kafka_delivery`。窗口百分位不能直接合并，嵌套计时不能相加。
- `compare_fps_profile.py` 改为每帧P2非重叠阶段求和后取中位数，拒绝缺少逐帧数据；检测trace哈希不同拒绝可比结论。单进程预算的倒数只是预算上限。
- `profile_pipeline_fps.py` 新增`--record-detections`/`--replay-detections`。流式JSONL包含视频内容SHA、stride/起始位置、逐帧时间和完整检测字段；重放绕过检测模型，允许对同一输入分别开关批量warp、增量投影和网格预筛。它始终是节点剖析，不是四进程验收。
- `run_fps_audit.py` 从指定app根调用唯一生产入口，使用独立输出/归档/spool，记录源码、模型、视频、遥测哈希与开关。每秒采集进程树CPU/RSS/可用IO计数；`--render` 在独立loopback端口启用显示。显式Kafka参数要求隔离project和专用端口；runner不初始化数据库，不启动消费者，不代表Kafka→PG验收。
- `summarize_fps_audit.py` 汇总窗口、四种worker局部调用率与资源趋势。`EGRESS_STATUS`新增`committed`，仅在本地commit_frame成功返回后推进；验收脚本拒绝用tracker/show输入水位代替提交。该值仍不是Kafka交付/PG回执。

详细探针会有测量开销；对照两侧使用相同探针设置，现场常态关闭。保留原30秒阶段日志。帧龄按FrameElement.timestamp_date到egress本地处理结束计量，不是原视频拍摄到数据库入库的延迟。

## 可复跑命令

```bash
.venv-mps/bin/python scripts/benchmark_egress_receiver.py \
  --quick --journal --repeats 3 --iterations 3 \
  --output output/fps-audit-20261105/receiver-journal.json

.venv-mps/bin/python scripts/run_fps_audit.py \
  --video '<固定视频>' --telemetry '<固定SRT>' --weight weights/uav_best.pt \
  --render --duration 390 --out '<新的独立输出目录>'
.venv-mps/bin/python scripts/summarize_fps_audit.py '<输出目录>'

# 节点归因：先记录一次，再对同一个trace重放，其他参数保持一致。
.venv-mps/bin/python scripts/profile_pipeline_fps.py --video '<固定视频>' \
  --telemetry-srt '<固定SRT>' --device mps --frames 300 \
  --record-detections /tmp/fps-detections.jsonl --out '<record目录>'
TRACKER_BATCH_WARP=0 WORLD_PROJECTION_INCREMENTAL=false CONFLICT_GRID_PREFILTER=false \
.venv-mps/bin/python scripts/profile_pipeline_fps.py --video '<固定视频>' \
  --telemetry-srt '<固定SRT>' --device mps --frames 300 \
  --replay-detections /tmp/fps-detections.jsonl --out '<off目录>'
# ON：去掉三个环境变量，重放同一个trace并写新的on目录，再比较stages.json。
```

生产A/B必须在同一UOS/310P3、同视频区间、同模型/阈值/stride/道路开关下，每个版本至少三次，稳定窗口≥300秒；保留原包和数据。检查提交≥3FPS、后半≥前半90%、满队列<10%，并核对真实Kafka交付和PG回执、轨迹/摘要/事件。macOS队列深度可能为-1，未知值不作通过；没有足够时长或缺少commit水位也不通过。两小时长稳仍是独立门禁。

## 尚未完成的验收

现场UOS/310P3无法由本机代替。本轮没有部署生产、数据库DDL或更改生产连接，也没有完成四版本×稀疏/拥堵真实素材×三轮五分钟及两小时长稳。真实Kafka→PG链路继续使用隔离集成环境和`test/incremental_replay_integration.py`，必须有逐条回执与统计对账才可计入入库验收。

旧的181.5秒现场日志只能复算输入进度约0.705FPS、满队列采样71.4%、后半约0.666FPS；没有commit水位，新验收器正确返回not_evaluated。不能再称为业务提交完成率。

## 本机真实入口采集（不作生产验收）

`output/fps-audit-20261105/main4-local/` 保存中间探针版本的源码清单、原始日志、逐秒资源和audit.json。实际执行约349.9秒，四worker正常结束（EGRESS_COMPLETE），进程返回0；本地提交水位窗口301.52秒内推进823帧，约2.729FPS，前半2.393、后半3.064。Kafka和显示关闭，且采集期间同机运行组件/回归/录制任务，有明显争用，不能作为独立性能基线或生产提速结论。macOS队列深度为-1，门禁正确未通过。该运行证明新增水位/分项计时/资源采集可用于真实入口，不能证明≥3FPS。

早期窗口中egress.restore_tails约二十多ms、journal fsync均值低于1ms，但轨迹关闭P95可达百ms以上，P2交接也存在慢尾部；应在隔离负载下复测关闭集中到达与序列化/合流背压。因调用嵌套和主机竞争，本轮不以这些窗口推导单项优化收益。后续细化了SQL读取/ACK延迟/帧龄探针，须以源码清单区分运行时版本。

## 固定检测输入与剩余成本

真实inter_xqh视频录制45帧（5帧预热、40帧计时），录制/OFF重放/ON重放的检测trace SHA均为`bca69adfadd342876b08be88400862752df7da628f723dbb1a1b8d6472557929`，重放轨迹/检测中位数为252/150。逐帧P2预算中位数63.8→46.4ms（对应`replay-ab.json`）；这是短节点剖析，不是业务吞吐。未改的图像运动等阶段也有漂移，因此不能将全部17.5ms归因于开关；该片段冲突耗时接近零，也不能验证密集冲突网格的性能。后者仍依靠现有大场景差分测试，现场需选有有效候选对的素材。

当前`frame_delta`是在`freeze_egress_views`全量冻结之后再拆静态/动态字段，减少wire字节并不等于免除了P2逐轨迹冻结。`DeltaTracks.finish`还会把关闭轨迹的全部字段从SQLite读回并物化；轨迹集中离场可能形成短时停顿。这两项属于剩余测量重点，不应把“缓存命中、SELECT为0”外推成整个管道无瓶颈。

本轮通过：细分探针/检测trace/验收水位/独立收发缓存等核心回归；156项跟踪批处理、世界投影、冲突、可靠发布及EOF回归；43项Kafka活动轨迹/工具/ByteTrack/遥测/stride回归；3项有界历史回归（含新增900帧场景中超过128点截断后短暂丢失再激活，与未截断路径逐帧业务及最终归档一致）。静态检查与git diff --check通过。未运行生产NPU、两小时长稳和真实Kafka→PG性能验收。

## 无并行测试的接收端复测

停止本轮其他测试/剖析任务后，再执行三轮正反顺序、两种规模、四版本的真实journal组件复测，六组全部通过。输出`output/fps-audit-20261105/receiver-journal-final.json`，各轮尾迹SHA相同，关闭后的完整frame序列均核对通过。下表为三轮“追加每源步中位数＋恢复中位数”的中位数，仍是组件预算，并非整管道帧时间；journal和关闭分布单独保存在原JSON。

| 轨迹数×点数 | 4.1 | 4.2 | 4.3 | 工作区 | 4.2恢复SELECT/帧 | 工作区恢复SELECT/帧 |
|---|---:|---:|---:|---:|---:|---:|
| 280×160 | 18.55ms | 293.95ms | 57.37ms | 23.02ms | 1960 | 0 |
| 486×160 | 30.90ms | 529.74ms | 106.06ms | 45.37ms | 3402 | 0 |

当前工作区组件明显优于4.2，但仍未达到4.1内存数组的成本，且不能据此移除磁盘保真与有界内存设计。原4.1不受同样内存边界约束。诊断runner优先使用已安装psutil；没有时使用系统ps采样并标明CPU为生命周期均值，IO未知，不新增原生运行时依赖。

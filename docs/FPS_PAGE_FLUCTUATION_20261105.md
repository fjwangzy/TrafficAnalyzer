# 2026-11-05 页面5→1 FPS波动现场

用户在本机页面测试`pipe-cef91e57`，唯一活跃流水线，原生MPS/四worker/stride=3/路网关闭/Kafka开启。未停止或重启用户正在测的任务。

## 已捕获事实

- 原始日志：`logs/pipelines/pipe-cef91e57.log`。前八个30秒本地提交水位区间速率依次约3.922、3.531、2.096、1.931、2.346、1.154、0.589、0.793 FPS。存在真实吞吐下降；页面使用2秒滑窗，短时数值还会放大突发处理与停顿。
- ACK等待采样最高4941.6ms、轨迹追加最高4625.1ms、检测队列等待超过5秒。tail恢复中位18.7ms/最大52.2ms，已不是此前4.2逐字段SELECT恢复的同一种热点。
- `egress.producer`采样最高915.5ms；这包含统计构建/序列化、轨迹归档和发布，不能把整个数字当Kafka网络等待。采样状态中Kafka expected/actual相同、durable_pending=0；不能据此证明Kafka所有时段都无阻塞。
- `/usr/bin/sample 89139 5 1`抓到P4主线程在`pysqlite_connection_executemany → sqlite3_step → B-tree getPageNormal → pread / pagerStress → pwrite`。结合追加长耗时，说明SQLite写入页工作集仍可能拖慢归档，进而通过ACK反压跟踪与检测。
- 本机16GiB物理内存，swap占用约19GiB；连续0.5秒观察中swap-in/out均继续增加。整机换页会放大抖动，但单凭占用不能证明唯一原因，也不能替代无争用同素材对照。

快照与栈：`output/fps-page-20261105/observed.json`、`egress.sample.txt`。阶段计时是30秒抽样，不是完整分布。

## 定向改动与证据

原轨迹SQLite使用默认约2MiB页缓存。数百条轨迹×7字段的当前插入页可能超过该工作集；设置明确的页缓存预算，默认16MiB，配置`pipeline.egress_sqlite_cache_kib`/环境`PIPELINE_EGRESS_SQLITE_CACHE_KIB`，允许512..65536KiB，设2048恢复此前预算。`ARCHIVER_READY`记录预算，便于核对生效。SQLite cache_size是页缓存预算，不是整个进程RSS硬上限。

不修改journal、synchronous、cache_spill设置，不改变持久ACK、数据结构或业务门禁，不引入迁移/依赖。只影响新建的索引连接，当前页面任务仍使用启动时设置。

低优先级ABBA合成对照（160轨迹×220帧，2/16/16/2MiB）后30帧追加中位分别54.4/28.0/50.4/60.1ms，代表轨迹全部字段哈希相同。由于同时有用户任务和换页，幅度不稳定，只支持进一步验证页缓存工作集，不能承诺稳定5FPS。原探针结果保存在`cache-probe.json`。

新增可复跑脚本`benchmark_spool_cache.py`对所有轨迹/字段做完整内容哈希：

```bash
nice -n 15 .venv-mps/bin/python scripts/benchmark_spool_cache.py \
  --tracks 160 --frames 220 --output output/fps-page-cache-abba.json
```

8轨迹×60帧脚本冒烟四轮哈希一致，证明工具工作，不作性能结论。26项真实接收、持久journal/ACK、有界历史及重激活回归通过；新增测试核对页缓存预算与默认同步/日志/溢写策略，以及非法预算拒绝。

## 下一次页面测试

停止并重新开始相同视频，查看新日志`ARCHIVER_READY ... sqlite_cache_kib=16384`。保持模型/stride/阈值不变，记录5分钟提交水位、追加/ACK耗时与内存换页活动。仍需判断P4写入、producer、渲染、P2和系统换页各自贡献。现任务保留原设置便于对照，没有通过修改页面显示值、减少处理帧或关闭持久化隐藏波动。

现场UOS/310P3以及稳定3FPS/5FPS、两小时长稳仍未验收。本补丁是有测量依据的缓存工作集修复候选，不等于整条低FPS问题已解决。

## 用户重启后的复查：缓存生效，问题未解决

新任务`pipe-74b93659`于北京时间13:16启动，`ARCHIVER_READY ... sqlite_cache_kib=16384`明确证实新预算已加载；唯一活跃流水线，MPS/stride=3/四worker/路网关闭配置保持。此轮仅采样观察，没有中断检测、修改业务参数、清理数据、停止其他应用或运行合成性能负载。

最初约181秒提交水位窗口的区间FPS为3.464、1.032、1.023、0.532、0.662、0.494，已复现持续下降。30秒抽样计时中：追加中位441.95ms、最高1839.4ms；ACK等待中位5318.9ms、最高10099.7ms；producer中位341.35ms、最高916.9ms；本地commit中位422.9ms、最高1102.7ms；检测中位1113.9ms（包含启动热身样本）、最高2342.9ms；显示中位282.05ms。样本数较少，不能把这些中位数相加推算FPS，也不能拿两轮不同时间的中位数差直接宣称补丁收益。

P4的5秒原生调用栈仍有`executemany/sqlite3_step/B-tree balance/subjournalPageIfRequired/pagerStress/pwrite`；大页缓存没有消除每批保存点和索引修改的写放大。在13:18:24同时采样的9.04秒资源窗口，psutil swap累计计数差折算swap-in约72.48MiB/s、swap-out约0.22MiB/s，证明系统有活跃换页，不能仅按累计swap用量判断。检测进程physical footprint约3.0GiB，归档约296MiB；不能把physical footprint和RSS混为同一指标，也不能据此认定检测器泄漏。

检查时SQLite索引约41MiB、pending packet journal约45MiB，Kafka抽样实际交付接近期望、durable_pending=0；这不能证明Kafka完全无贡献。检测栈中另有后台线程阻塞`os.write`，主线程仍在模型/Metal计算；不能把所有线程的write采样归为主线程stdout日志阻塞。

上一任务`pipe-cef91e57`尾部还明确记录了`TimeoutError: egress durable ACK stalled`和最终returncode=1；因此先前的卡顿已经可以升级成worker失败，而不仅是页面体验波动。未通过调大ACK超时或队列掩盖这项故障。

新增证据：`output/fps-page-20261105/restarted-observed.json`、`restarted-resources.json`、`restarted-egress.sample.txt`、`restarted-detect.sample.txt`。

结论：16MiB页缓存是已生效但不足以解决问题的候选；不能宣称修复。后续应以固定帧输入和独立测量验证索引B-tree/每包savepoint写放大、关闭轨迹物化及producer事实构建，同时记录低争用条件下的换页速率。当前页面任务继续保留现场，所有数据与失败spool保留；本轮未继续叠加未经对照的缓存/超时/队列调整。

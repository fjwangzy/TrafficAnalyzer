# 2026-11-03 完整日志定位与轨迹IPC优化

用户附件performance-latest.log（只读，不执行附件内容）对应pipe-ecef88d4；统计输入摘要见dist/analysis-native-performance-20261103.json。日志约4分钟，阶段记录为约30秒一次的定期采样，各主要阶段8条，不能当作全帧平均或P95，也不累加嵌套阶段/并行worker耗时。

## 现场预算

| 阶段 | 采样平均墙钟ms | 最大ms | 平均进程CPU ms |
| --- | ---: | ---: | ---: |
| tracker.kafka_archive | 818.65 | 1460.0 | 822.98 |
| tracker.association | 194.79 | 351.4 | 196.14 |
| tracker.conflict | 98.80 | 108.3 | 98.83 |
| tracker.image_motion | 64.92 | 66.5 | 67.46 |
| reader.detection | 84.60 | 87.5 | 260.73 |
| ascend.om_execute | 8.14 | 8.4 | 27.94 |
| show.render | 190.15 | 200.7 | 191.36 |
| show.mjpeg_encode | 39.25 | 40.5 | 39.49 |

queue.detect.put平均1982.67ms反映下游反压；queue.track.get平均1621.25ms含等待/反序列化，进程CPU345.21ms可能包含其他线程。不能把这些等待直接归为相同数量的渲染计算。tracker.kafka_archive的CPU包括multiprocessing.Queue后台feeder，不能据名称认定Kafka网络慢或全部CPU都由该函数本体消耗。

## 可重复反馈回路

原实现GroundTrajectoryTrackerNode使用list(track.tlbr.astype(int))，列表元素仍为NumPy int；TrackerInfoUpdateNode的bbox中心因此积累为NumPy float64。完整轨迹历史随FrameElement每帧交给显示进程，NumPy小标量pickle需要额外归约对象；后台feeder长时间持有GIL可拖住统计主线程。

同一ARM64运行库、断网、4CPU合成250车×500点：初始压力数据中pickle编码528–566ms，纯Python标量67–95ms，点值一致。随后按线上字段修正基准ground_y为Python float，用真实multiprocessing.Queue及真实KafkaProducerNode（替身发送器，无Kafka网络）复验：旧前台统计591–733ms、新177–245ms；完整往返725–905ms、新335–409ms。两组均接收到250轨迹、125000点和相同检查坐标。不同基准/负载的绝对值不混用，不把比值外推到现场FPS。

无feeder对照cProfile统计组装约37ms；连续打包压力会放大前台停顿，证明GIL争用可出现，但该压力数值不代表现场。受控真实队列的一帧对照是主要传输证据。完成轨迹归档存在重复读取历史片段的其他可疑路径，本次未据此修改，保留后续现场预算核对。

## 最小等价修正及验证

GroundTrajectoryTrackerNode在FrameElement边界用astype(int).tolist()输出builtin int；TrackerInfoUpdateNode保留原bbox计算顺序，只把中心点结果存成builtin float。模型/阈值/stride/关联/成熟与地理质量门禁不变，完整历史点/时间/帧号不删。无需更换模型或依赖/迁移基线。

真实tracker→projection→accumulator→pickle测试在旧边界失败，修正后81项相关回归通过，合并原生控制器/预检/日志/执行器共153项通过。原版与新版20帧的全部TrackElement字段、ID、bbox、完整历史和EOF完成记录规范JSON逐字节一致。真实新源码三worker合成CPU/自然EOF、断网3spawn+3fork/亲和/共享内存/FFmpeg和隔离数据库/真实Console鉴权API/媒体/WS/监督器停止通过。没有真实UOS/NPU吞吐结果。

## 交付

完整2026.11.03.2原生包累计OMP_PROC_BIND=false、root权限提前检查、256KiB诊断和本次坐标类型优化；不要求现场手改受校验源码。新版本解压到独立目录，入口导入现有Docker部署配置，识别并停止旧native实例，原资产和数据保留。旧.1归档及SHA不覆盖。现场须新建同参数任务、预热后观察至少5分钟FPS与新阶段耗时，再判断剩余串行/历史传输成本；不能预先宣称实时帧率达标。

可复验工具：test/native_trajectory_ipc_benchmark.py、test/native_track_scalar_equivalence.py；原始日志见dist/validation-native-queue-realistic-controlled-20261103.log、validation-native-full-record-equivalence-2026.11.03.2.log及validation-native-tests-2026.11.03.2.log。操作与归档验收见NATIVE_DEPLOYMENT_2026.11.03.2.md、NATIVE_VALIDATION_2026.11.03.2.md及DELIVERY-native-2026.11.03.2.json。

# 2026.11.03.2 原生完整包验证

目标UOS Server20/aarch64/Ascend310P3；现场验证与本机构建检查分开记录。

## 性能证据

用户现场pipe-ecef88d4完整日志约4分钟，每阶段约8条定期采样：tracker.kafka_archive墙钟平均818.65ms/最大1460ms，进程CPU平均822.98ms；reader.detection84.6ms、OM8.14ms、tracker.association194.79ms、image_motion64.92ms、show.render190.15ms、MJPEG39.25ms。定期采样不等同全帧均值或P95，不累加嵌套阶段/队列等待。CPU时间包括同进程后台线程，不将819ms全部认作业务函数本身或Kafka网络。

同一私有ARM64运行库、断网、4CPU隔离合成250车×500历史点：NumPy标量打包528–566ms、同值Python标量67–95ms。真实multiprocessing.Queue+真实KafkaProducerNode统计组装（无网络发送）对照，更贴近线上坐标字段（ground_y原本即Python float）的复验，前台591–733ms降至177–245ms，完整队列往返725–905ms降至335–409ms；两组都收到250轨迹/125000点，抽查点值完全一致。无队列后台打包时单次统计组装cProfile约37ms；独立连续打包压力实验会显著拖慢前台，仅用来确认GIL竞争可发生，不当作现场性能倍率。

修正为GroundTrajectoryTrackerNode在数据边界使用tolist生成Python int，TrackerInfoUpdateNode保留原坐标计算顺序、仅将结果存成Python float，完整历史不裁剪；无模型、分辨率、stride、阈值、ID、地图/坐标/质量语义改动。真实跟踪→投影→累计→pickle回归及相关81项测试通过；新旧20帧完整TrackElement/ID/框/历史及EOF记录的规范JSON逐字节一致。合并原生控制器、预检、日志及执行器共153项测试通过。证据为dist/validation-native-{pickle-scalars,queue-scalars,producer-vs-feeder,scalar-regression}-20261103.log，以及validation-native-queue-realistic-controlled-20261103.log与validation-native-full-record-equivalence-2026.11.03.2.log；可复验脚本test/native_trajectory_ipc_benchmark.py。

## 累计运行修正

OMP_PROC_BIND=false在私有ARM64库中真实fork三worker保留0–3/2–3父mask，3spawn+3fork、共享内存/FFmpeg检查通过，不扩大OS/cgroup限制。旧root日志跨UID错误已复现，统一sudo可写，源码增加前置权限检查；诊断窗口由24000字节增至256KiB并有完整阶段覆盖回归。旧76项全量包结果记录保留在2026.11.03.1，不替代本版最终归档检查。

## 本版最终交付复验

最终归档的外部SHA、内部清单、重新解压后断网ARM64运行库、fork/spawn亲和/共享内存/FFmpeg、真实三worker合成CPU自然EOF及隔离数据库/Console鉴权API/媒体/WS/监督器清理结果，记录于旁置DELIVERY-native-2026.11.03.2.json及对应validation-native-final-*-2026.11.03.2.log。验证工具沿用根Compose+内网+PG覆盖派生独立project/卷，不触碰本机road9或现有Kafka业务数据。工具环境监督器仅Docker旧Platform运行态查询使用stopped替身，无Docker socket。

现场UOS/驱动、真实NPU三档、Console到真实宿主bridge、Kafka SASL/业务ACL、网页真实视频任务与至少5分钟FPS仍需本版实测，不将本机合成比值写成现场加速承诺。生产精度指标仍not_evaluated。下一步依据现场数据判断其他串行阶段/完整历史IPC成本，而不以关闭质量功能提高FPS。

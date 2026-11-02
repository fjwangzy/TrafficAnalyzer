# 2026.10.17-intranet.3 同机临时数据库完整发布验证

## 2026-10-20 模型清单变量遗漏修复

首版安装器过滤ASCEND_*时误删ASCEND_MODEL_MANIFEST，PIPELINE_ASCEND_MANIFEST仍保留。用户现场switch-host报MODEL_PATH_CONFIG，并授权简单问题直接给修改命令，不要求补丁包。已安装现场在宿主包根目录将state/site.json的environment.ASCEND_MODEL_MANIFEST设为同对象PIPELINE_ASCEND_MANIFEST的现有值，权限保持600；然后重新switch-host，无需install/init-db，不跳过模型清单/PT/OM哈希与NPU门禁。不要回传含密码的site.json。

后续源码修正：安装时保留并翻译ASCEND_MODEL_MANIFEST；env_for为既有缺项状态从已翻译的PIPELINE_ASCEND_MANIFEST补齐，显式值保持。聚焦测试25 passed；ARM64私有原生Python使用真实三档OM清单及PT验证哈希通过，无设备环境在后续ASCEND_DEVICE_MISSING门禁停止，NPU推理仍未评估。原4.4GiB归档及SHA保留，不重新覆盖。


## 2026-10-20 宿主原生Platform排查包验证

- 用户宿主UOS Server20/Python3.12.12；包内同基线Python3.11.15/CANN9/私有glibc加载器，不替换系统库或Python，不改Mac开发配置。归档不带生产.env、模型或视频。
- ARM64 Alpine工具容器（无系统glibc/Python、无网络、只读本包、/tmp独立）验证原生Python、NumPy1.26.4/SciPy1.17.1/PyTorch2.2.2/OpenCV4.9、cython_bbox/lap、Python子进程、共享内存及FFmpeg/FFprobe通过；完整源码/管道import通过。厂商libpq实际私有路径加载通过，psycopg3.2.13、libpq120007。
- 复用根Compose+内网/PG覆盖、独立project与临时DATA_ROOT的隔离PG验证：原生连接实际ycx_prod.drone正确；空库validate_database拒绝且创建0应用表；单独显式init_db完成canonical20261019_0021和ReplayV220261019_rv2_0005，16源/7无人机；其后原生source_check --database通过。临时DB容器和网络已移除，数据目录保留，不触及本机road9。
- 安装/回退/路径映射/密码美元符字面量/DB容器IP变化拒绝/原生检测器loopback绑定/既有发布预检和日志回归合计57 passed；shell语法、Python编译、git diff --check通过。现场state目录700、含凭据文件600，Console代理鉴权不变。
- 实际NPU驱动未挂到工具容器，libascendcl探针按预期报告缺libascend_hal.so；不伪造driver或把pyACL/NPU推理标为通过。UOS实机兼容、真实NPU三档推理、Console跨网桥到宿主路由、内网Kafka ACL及同视频吞吐仍not_evaluated。未执行生产安装/启停。
- 原始证据：dist/validation-host-native-runtime-2026.10.20.1.log、validation-host-native-imports-2026.10.20.1.log、validation-host-native-database-2026.10.20.1.log、validation-host-tests-2026.10.20.1.log。


## 2026-10-19 .4后ByteTrack离线剖析及SIMD支持

用户报告.4后FPS约1，已离开内网，暂不能提供新阶段日志；“ByteTrack把单核打满”保留为待验假设，不据此声明根因或继续发包。

- 原ARM64镜像隔离network=none工具容器，OpenCV useOptimized=True、CPU baseline NEON FP16，包含NEON_DOTPROD/NEON_FP16/NEON_BF16编译分派，JPEG使用libjpeg-turbo 2.1.3-62。NumPy在本机ARM VM运行时NEON/ASIMD系列特性为True；不能把本机额外扩展可用性外推至现场CPU。
- 4CPU、直接导入.4包的BYTETracker，规则网格初始化304条轨迹，后续每帧164候选、x方向移动1像素、置信度0.9、motor类组、4帧，cProfile开启。双BLAS各1线程update为105.421/34.943/34.771/32.863ms；双64线程为65.582/40.495/39.681/42.927ms，每次输出164轨迹断言通过。线程设置仅在工具容器，不改生产env。
- 该合成输入预热后约33–43ms/帧，未复现1秒跟踪；不能代表现实遮挡/候选规模、CPU或整个管道。剖析的累计热点包括逐轨迹shadow gate、Kalman更新/预测及stage上下文，说明有批量化/原生化候选，不足以认定这些是现场主要开销。IoU由cython_bbox、分配由lapjv原生执行。
- 结构化观测保留于dist/validation-bytetrack-profile-neon-arm64-20261019.json。本轮未改运行代码/原生依赖或重打包，未运行真实NPU/XQH/mp4728全片。核查依据为运行时实际构建信息及官方OpenCV CPU优化配置、NumPy SIMD分派说明，不提供基于-MCPU=native等本机特化产物供未知现场CPU直接部署。

后续C/C++或库重编须独立运行时基线发布，保持数值/门限掩码、ID、EOF等价和目标ARM验证；不能通过同基线源码包绕过ADR-041。

## 2026-10-19 .4候选标签ROI绘制验证

用户报告应用.3后FPS约0.9，尚未提供该新任务阶段日志。本轮仅修复已独立复现的候选绘制浪费，不将它认定为现场当前主瓶颈，也未操作生产。

- 本机真实ShowNode._draw_candidate_box、200候选4K图旧版1211.725ms，断言小于100ms失败。新增整帧混合工作量回归和headless无用resize回归均先失败；另补本地窗口缩放保留测试。最小修改仅标签ROI复制/混合（右下端点+1）以及将窗口resize移到原imshow条件内。
- `.venv-mps/bin/python -m pytest test/test_show_node_class_colors.py test/test_main_optimized_eof.py -q`：31 passed。共享内存/EOF与绘制、窗口、候选/正式样式原回归通过，独立只读审查无阻断问题。未修改Flask编码、模型、关联门禁、抽帧或数值库线程。
- 原ARM64镜像、无网络、4CPU、源码只读：200候选4K旧.3为1388.256ms，新ROI为22.733ms。固定种子41，1×1、100×140、720p和4K随机背景，每种10次绘制，覆盖四角裁剪和重叠；每一步与原.3完整图逐像素一致。证据dist/validation-render-roi-arm64-20261019.log。
- 累计.4包实际ShowNode.py再次在同镜像导入复验，日志记录包内源码路径，旧1333.519ms/新23.401ms，全部像素对照通过。证据dist/validation-render-roi-package4-arm64-20261019.log；诊断脚本dist/repro-render-roi-arm64-20261019.py，用`docker run --rm -i --network none --cpus 4 -v "$PWD:/work:ro" -w /work/dist/traffic-analyzer-direct-copy-2026.10.19.4/application/app --entrypoint python traffic-analyzer-platform:2026.10.19-intranet.1-arm64 -u - < dist/repro-render-roi-arm64-20261019.py`复跑，需原.3/.4目录。
- .4仅替换.3的运行时nodes/ShowNode.py，另更新版本/说明/校验清单，保持相同镜像与35项依赖/迁移基线。源码包校验通过，不含私有.env、模型、视频；9,405,410字节归档SHA256为9628191ac2d5b3e08fa98e0df4e5768628f6c08144a7703a1299f9e7fa69e3d5，原.3归档不变。

该性能数字只代表合成候选绘制阶段，不代表现场候选数量、CPU/调度或整体管道FPS；尚未重跑真实NPU、XQH/mp4728全片或外部精度验收。现场下一步用新日志确认主耗时，并以实际挂载APP_RELEASE=2026.10.19-render.4和ShowNode SHA核对源码；继承的启动/就绪contract=20261019.3不作为.4包版本证明。

## 2026-10-19 高线程ARM对照复现与复用.3

用户确认新文件111113.txt对应现场仍只应用直接复制.1/.2，尚未应用.3。本轮不修改运行代码或重新封包，复用已包含二维影子手工前代的.3；现场加载新代码和吞吐恢复仍待stop/start后新任务验收。

- 原镜像`traffic-analyzer-platform:2026.10.19-intranet.1-arm64`，`--network none --cpus 4`、工作树只读挂载；使用实际matching.gate_cost_matrix及直接复制.2/.3包内KalmanFilter。固定种子41，304轨迹×164候选。仅在工具容器内把NumPy/SciPy线程池分别设64或1，不修改生产env/Compose。设64后进程有128个存活线程；设1后线程仍存活，不把存活数等同活跃数。
- 双64线程：.2墙钟22921.335ms/进程CPU86734.887ms，.3为12.128ms/47.624ms。双1线程：.2为11.924ms/19.248ms，.3为9.088ms/9.088ms。旧版逐轨迹小矩阵求解的高线程开销已在同一ARM运行时复现；.3消除该对照中的长停顿。四组完整门控矩阵精确一致，拒绝46456对，未关闭shadow或改门限。该合成比例不代表现场整体加速比例或FPS。
- 证据`dist/validation-shadow-highthreads-arm64-20261019.log`；诊断脚本`dist/repro-shadow-highthreads-arm64-20261019.py`仅供隔离容器复跑：`docker run --rm -i --network none --cpus 4 -v "$PWD:/work:ro" -w /work --entrypoint python traffic-analyzer-platform:2026.10.19-intranet.1-arm64 -u - < dist/repro-shadow-highthreads-arm64-20261019.py`。要求dist内已有原.2/.3包目录，线程控制不进入应用启动流程。
- `.venv-mps/bin/python -m pytest test/test_kalman_gating.py test/test_byte_tracker_core.py -q`：15 passed。默认.venv缺pytest，改用既有.venv-mps，未安装或变更依赖。
- .3归档SHA256仍为`66da6bc83b92e17705f12f78a953cc95cb17560b6bbd44b968c5ab4c06861ae3`；完整源码清单、35项依赖/迁移基线验证通过，包内kalman_filter.py与当前工作树一致。原包及现场配置未改动。

没有运行真实NPU、XQH/mp4728全片或外部精度验收；不新增现场恢复结论。下一步应用现有.3，核对两个20261019.3启动/就绪标记及shadow_gate耗时，不扩大代码或生产线程变更。

## 2026-10-19 补充现场日志pipe-7f2c9e37（尚未应用.3）

用户提供`新文件6666.txt`并明确尚未应用直接复制2026.10.19.3。这40行日志覆盖北京时间20:27:58至20:28:24，不能作为.3修复失败或已恢复的证据；片段没有启动/就绪标记，也没有异常栈或最终退出结果。

- 184轨迹×139候选、25576对的二维影子门控在5.881秒时累计5.714秒进程CPU；约26秒后才记录到第50行，片段在该行求解BEGIN结束，整体完成时间未知。CPU时间包括同进程其他线程，不能全部认作求解线程自身消耗。
- 同帧检测491.4ms，Ascend推理整体54.8ms、其中OM执行8.8ms，CPU NMS203.6ms；本片段直接显示的主要长等待在CPU跟踪路径，不能据此验收持续NPU性能。
- reader入队曾等待56.512秒/77.9ms CPU，后续再次等待超过8.091秒；show等待跟踪输出约10秒后再次等待，符合跟踪处理不及时、上下游队列等待。首次56.512秒入队发生在本次门控前，不把它全部归因于本次门控。render3.809秒/173.5ms CPU、MJPEG编码2.678秒/53.5ms CPU，墙钟耗时不能等同计算量。
- 三个worker均报告cpu_allowed=1，严格表示各自日志采样线程的亲和范围只有一个逻辑CPU；sched_getaffinity(0)读取调用线程，BEGIN/END与watchdog WAIT可来自不同线程。不证明三个worker或进程内全部线程绑定同一CPU。tracker的68是进程总线程数，不能全部认作活跃BLAS线程；配额/限流unavailable不等于无限制。

本轮未修改运行代码或操作现场。重跑二维/四维数值、空候选、输入不变及正定校验等8项测试全部通过；.3归档SHA256通过，包内二维求解、执行器与视频节点均与当前源码一致。现场先覆盖实际/app挂载来源、重启并新建任务，核实20261019.3两端标记与连续画面，再评估门控耗时；CPU亲和来源和数值库线程实况仍待现场核查，不承诺本机结果等同生产恢复。

## 2026-10-19 .2应用后仍失败与.3验证

用户明确已应用.2，新日志pipe-836dbb51仍于12:13:36 UTC发生120秒MJPEG就绪超时；随后影子门控80.445秒/77.487秒CPU以interrupted结束。二维、177候选的一次solve_triangular实测688.4ms，cpu_allowed=1、cpu_threads=68。缺启动段，不能凭尾部确定实际命令/挂载；现场异常仍未被本机.2测试解释。

.3就绪信号使用初始化时创建的pipeline.video logger，测试覆盖stdout与旧disabled父入口；不接受阶段名或进程存活代替绑定后标记。新增两端startup_contract/ready_contract便于确认实际运行版本。Console仅创建/重试Mission允许180秒，普通API10秒不变。影子二维Cholesky求解保留原分解及正定失败，改为两行向量前代，避开逐轨迹trtrs；四维与正式更新保持。

- 失败回归先复现旧disabled吞信号、10秒请求配置和二维线程求解路径；修复后Python聚焦92 passed/1 subtest passed，前端25文件284项通过，生产构建通过，git diff --check通过。
- 原ARM64镜像独立network=none、cpuset=0单逻辑CPU、源码只读工具容器，从真实main_optimized.py启动三进程，约2.9秒收到新MJPEG_READY并读取15089字节完整初始化JPEG；停止发生于reader预热期间，无模型/NPU推理。证据dist/validation-real-entry-ready-20261019-after3.log。受控stop的-15不是启动失败。
- 同镜像同单核173×177对照：旧求解5.691ms、新3.544ms；随机相关协方差数值rtol/atol 1e-12一致，门限掩码一致，4帧173条跟踪ID/框一致。未复现现场80秒，不将跨环境数字当作现场加速比例。证据dist/validation-shadow-equivalence-arm64-20261019.log。
- .3直接复制包累计此前修复、更新视频节点/执行器/二维求解及Console资源，保持精确镜像与35项依赖/迁移基线；须覆盖容器实际/app来源，重新启动两个应用并刷新网页。

最终包复验：.2和.3在相同ARM64镜像、单CPU、真实三进程入口均能就绪并读取完整15089字节JPEG，短时检查无worker失败；因此现场.2失败原因仍未复现。最初裸工具容器遗漏生产GEOJSON_OUTPUT_DIR，在只读包中导致GeoJson初始化失败，该次不计通过；补齐与生产相同的可写输出环境后两版复验通过。证据为dist/validation-real-entry-ready-package2-complete-20261019.log和package3-complete同名日志。

包内240项文件及归档SHA通过；复制说明使用现有容器inspect的实际/app宿主路径，工具自检证明部署根与不同实际挂载副本均完整更新、私有env/数据不变，不同依赖基线在停止前拒绝。复制自检的Docker生命周期是替身调用，不能视为生产更新成功；真实镜像入口测试独立如上。证据dist/validation-copy-guide3-20261019.log及validation-startup-package3-20261019.json。原归档保持不变。

本机验证不等于现场恢复；未运行真实NPU、XQH/mp4728全片或正式精度，cpu亲和/线程竞争的系统来源与现场实际源码路径仍待新标记及日志确认。

## 2026-10-19 补充现场日志pipe-205334aa（尚未应用直接复制.2）

用户提供`新文件32222323.txt`并明确尚未应用2026.10.19.2，因此该日志不能作为stdout就绪修复失败的证据。以下时间为北京时间（原日志UTC加8）：

- 20:03:53.851开始PIPELINE_LAUNCH，20:04:03.796的POST /missions返回499、duration=10.001；20:04:17.963才到PIPELINE_START，子进程启动导入约24.1秒。当前Console api默认timeout=10000，createMission未覆盖；与浏览器先行取消吻合。Nginx API代理read timeout为3600秒，不能归为Nginx十秒超时。需要单独修正同步任务启动请求的等待预算，直接复制.2未包含该修复。
- bytetrack.shadow_gate在173轨迹×177候选（30621对）时持续80.565秒，CPU累计77.501秒，最终status=interrupted；shadow_row第113行耗时560.3毫秒。慢阶段已定位到影子Mahalanobis诊断，不再仅凭被打断的SciPy栈猜测。它不参与正式关联资格，但当前同步计算会阻塞下游。
- 跟踪worker的cpu_allowed=1、cpu_threads约68：进程亲和范围只有一个逻辑CPU，线程数为全进程总数。高度怀疑小矩阵求解的多线程竞争/调度成本，尚无线程库实测及受控单变量对照，不能将68全部认定为BLAS线程。cpu_quota及限流计数不可读，不代表没有CPU配额或限流，也不能判断限制来自宿主还是容器。
- reader的queue.detect.put等待35.46秒而CPU仅50.4毫秒，是跟踪慢导致队列反压的证据。20:05:53.863先发生120秒MJPEG就绪超时，随后Platform终止进程；SystemExit143/-15及10个共享内存对象清理告警属于后续退出现象，不能据此判定SciPy先异常或共享内存不足。

本轮仅检查日志与现有调用配置、同步调查结论，未修改运行代码、重打包或操作生产；现场先应用.2核实MJPEG_READY，前端请求等待与CPU亲和/数值库线程问题仍独立待修复/验证。

## 2026-10-19 Hydra视频就绪信号缺失

现场附件pipe-9ae147c8证明模型执行、首帧分析、绘制及JPEG编码完成，未出现MJPEG_READY；用户补充网页报超时、任务未启动。代码复现确认Hydra disabled将预先创建的VideoServer logger.disabled设为True，现有root日志配置不清除此状态。仅改none也不能恢复hydra_logging已禁用的logger，因此两入口采用stdout模式。

- 新增真实Hydra配置→fork worker→VideoServer监听→LocalPipelineExecutor就绪→HTTP完整JPEG回归；旧参数10秒超时失败，新参数通过。执行器/Manager/Replay验收runner/日志/EOF聚焦58 passed、1 subtest passed。
- 原镜像`traffic-analyzer-platform:2026.10.19-intranet.1-arm64`，独立`--network none --cpus 2`工具容器内，旧模式已能读取703字节完整MJPEG帧但5秒握手超时；新模式约0.33秒收到MJPEG_READY并读取同样完整帧。证据`dist/validation-mjpeg-logging-arm64-20261019.log`。测试使用小尺寸初始化黑帧，只证明真实监听/握手/传输，不代表真实视频/NPU推理验收；工具停止产生的-15属受控清理。
- 直接复制2026.10.19.2仅在上版2026.10.19.1累计交付上变更executor一行参数及版本/说明/校验清单，复用既有镜像和依赖/迁移。原归档保持不变。
- 未连接或更新生产机，未运行XQH/mp4728全片、真实NPU或正式精度；35秒以上跟踪等待仍待新分段日志。不能把本修复等同于现场完整功能或性能恢复。

## 2026-10-19 跟踪慢阶段诊断与直接复制发布

用户明确选择同基线直接复制application目录，不要求执行prepare/apply升级器。当前直接复制版基于2026.10.19-intranet.1全量的相同镜像ID/依赖/迁移，累计就绪信号/共享内存清理/Console403修复及本次诊断，不包含生产.env、模型、视频。交付目录`traffic-analyzer-direct-copy-2026.10.19.1`中的application覆盖现场同名目录，配套SHA256SUMS覆盖发布根清单，停止后复制、再启动两个应用；不启动init-db、不构建/拉镜像。若已有app/current源码指针，按该目录README同步覆盖当前源码副本，避免仍运行旧挂载。原始完整包归档SHA保持不变。

现有中断栈位于Mahalanobis影子诊断的scipy.linalg.solve_triangular，可能是候选/轨迹规模、BLAS多线程调度、CPU限制或同机抢占；不能由中断位置认定单次solve就耗时81秒。相同ARM64镜像、2CPU受控工具容器中128轨迹×256候选、128次调用，默认约8.5ms/7进程线程、仅OPENBLAS_NUM_THREADS=1约2.7ms/1线程；未复现现场81秒，不将此合成观察作为现场根因或擅自改线程配置。

新增日志保持首轮/30秒采样和5秒未完成证据，不逐车刷屏：

- ASSOCIATION_CPU_ENV：NumPy/SciPy版本、匹配后端与有限CPU线程环境变量白名单；不输出全量环境。
- bytetrack.predict / distance / shadow_gate / shadow_row / mahalanobis_solve / assignment / kalman_update：轨迹/候选/矩阵规模、正在处理的行或求解维数、匹配后端/阈值。
- STAGE_BEGIN/WAIT/END：elapsed_ms墙钟与cpu_ms进程累计CPU消耗、cpu_threads进程全部线程数、cpu_allowed亲和CPU数、cpu_quota配额、nr_throttled/throttled_usec限流累计计数。cgroup-v1/不可读项明确unavailable；CPU计时包括同进程其他线程，内外嵌套阶段不可相加，cgroup计数可能含同容器其他worker，只能比较相邻样本的变化。
- 嵌套小阶段持续切换时仍报告超过5秒的父阶段；SIGTERM等中断的STAGE_END标为status=interrupted，不冒充正常完成。

现场复现一次后提供同一Pipeline日志中ASSOCIATION_CPU_ENV、bytetrack.*与STAGE_WAIT/END；判断slow shadow/solve、正式Kalman更新、矩阵分配或CPU限流，再进行单变量性能验证。没有修改跟踪算法、阈值、身份/地理质量门禁，也未关闭影子诊断。

## 2026-10-19 MJPEG就绪超时与psm清理

用户补充日志最早失败为120秒就绪超时，之后Platform SIGTERM才出现SystemExit143/-15、共享内存清理警告；片段已有画面编码与OM执行完成。复现了完整日志就绪标记先被4000字符尾部截断再检查导致误等待，回归先失败后修复；缺标记正反例仍保持门禁。另在实际ARM64镜像复现Linux fork独立resource_tracker重复清理，改为父进程fork前启动统一跟踪器后消失。

聚焦43项/1subtest、ARM64就绪正反例及fork、只读完整源码导入通过；新增源码包仅改main_optimized.py、pipeline_executor.py、累计Console入口及版本/指南/清单。镜像ID/依赖/两套迁移基线未变。完整SHA及逐文件核验通过，证据dist/VALIDATION-STARTUP-2026.10.19-intranet.2.json。未执行生产apply/NPU实测，也未证明现场原标记确被截断；tracker.association约81秒慢阶段仍未解决。

## 2026-10-19 Console源码权限403

真实新ARM64 Console镜像中，Linux层html目录700/文件600时，旧入口/index.html返回403（dist/reproduce-console-403-2026.10.19.log）。新入口复制公开资源至容器运行时目录并归一化权限，正常/受限两种模式及配置失败共3项真实容器用例通过；覆盖首页、login、index、runtime、JS、日志轮转/查询口令脱敏和宿主源码未修改。

修复器与源码/Compose回归33项通过；实际完整单文件修复在隔离Compose运行，Console容器ID更换、HTML/runtime/实际首屏资源全部可读，Platform从未启动、env/Compose字节不变、内外SHA有效且无应用目录pycache污染。临时容器与数据已清理，证据dist/validation-console403-repair-20261019.log。生产实际执行结果及拒读路径仍待现场，不声称NPU/业务链路验收。

## 2026-10-18 标准logging与宿主源码版（2026.10.18-intranet.1）

- Python运行路径使用标准logging及UTC毫秒/级别/PID/Pipeline/logger格式，生产节点与入口的print/进度条改为分级日志；环境配置只记录变量名，不记录其值。检测器输出保留真实级别及异常栈，按Pipeline单点轮转，API的4000字符tail和MJPEG_READY就绪契约保留。
- 日志覆盖容器启动/预检/init-db、Platform/Uvicorn、检测器三个worker、源码升级及Nginx。检测/OM加载执行/CPU NMS/分析归档/队列/渲染有低频BEGIN、超过5秒的WAIT与END；文件20MiB加5份备份，Python日志0600，Docker输出继续可用。Nginx原生错误经query/URL凭据过滤后写stderr和宿主，访问日志只记无query的URI。
- 真实原intranet.3 ARM64 Console镜像执行宿主只读资源/umask077/独立runtime-config/启动失败落盘/轮转/upstream错误token脱敏：2 passed。另在.5镜像完成早期只读资源与权限回归。未改地图业务或生产NPU参数。
- 后端日志/执行器/EOF/几何/Ascend/源码升级/旧发布启动/只读诊断组合94 passed、1 subtest；日志/执行器的最后加固另定向通过，升级器新增启动失败采集CANN入口日志用例通过。前端构建契约12 passed及production build通过；git diff --check、shell/Python语法检查通过。
- 从实际旧Platform镜像读取并逐字比较33个依赖/迁移基线文件；完整/app只读挂载的源码检查已在原ARM64镜像中执行，网络关闭，只编译/导入，不启动Platform服务、不连数据库、不运行NPU。容器输出经logging写入宿主目录，退出0。prepare检查日志单独落source-check，避免与运行中Platform争用轮转文件。
- 源码包包含228个文件及最新Console构建资源，复用原两镜像，排除私有env/模型/视频。正式文件、大小、SHA以`dist/VALIDATION-APP-SOURCE-2026.10.18-intranet.1.json`和归档.sha256为准。旧离线镜像/私有发布归档保持。

升级器对原env/Compose/SHA保持不变，阻止新增/改动migration与依赖、不执行DDL；单测覆盖校验拒绝、重复prepare、只读schema检查、停应用后预检、失败恢复、重复apply保留回滚点及回退镜像模式。未在现场执行apply/rollback或做真实NPU/网络/数据库健康验收，不能据此宣称慢帧已修复。

## 2026-10-18 生产慢帧静态判断（未定位现场根因）

用户当前不在内网，本轮只检查代码、实际intranet.3 ARM64镜像及已有现场记录，未连接生产、运行NPU或修改运行参数。
镜像内Ascend后端、主入口、DetectionNode、app_config、PipelineManager与执行器均与当前源码一致；没有静默CPU YOLO回退。
三档OM只在初始化全部加载，每帧整图仅执行选中的一档，无切片或逐帧三模型串行。

- 启动后持续慢帧：首先怀疑共享资源及CPU段阻塞。既有现场记录中device0占用42358/44278MB，多数为vLLM，检测器约393MB；这证明同卡负载存在，不证明显存占用就是计算延迟根因。预处理/CPU NMS、解码、跟踪及绘图仍在CPU；`inference_ms`包含预处理、ACL执行和NMS，不是NPU纯执行时间。
- 越跑越慢：生产replay_v2每帧同步更新manifest；每归档一条完成轨迹，`MissionTrajectoryArchive.record_segment`又读取、校验全部历史片段重算点数。调用真实方法的临时计数探针确认10条累计55次、20条210次历史片段文件读取，符合N(N+1)/2。大量完成轨迹、长历史或慢盘可放大停顿，但不能解释全新Mission第一帧即慢。
- 两级8帧队列的put均无超时，下游归档/绘图/输出变慢会反压检测；排队同时增加端到端延迟，不能把整条管道出帧间隔等同于模型耗时。完整常驻轨迹历史也随FrameElement跨进程传递，存在增长开销。
- 自建Ascend路径在CPU调用NMS。生产pin的Ultralytics8.4.102若未预载torchvision会走Python+Torch循环；max_det=300及时间限制均在内部NMS返回后检查。本机相同torch2.2.2/Ultralytics8.4.102单线程合成10000个不重叠候选耗时1552.5ms，只证明该路径可进入，不能外推生产分钟级。
- 本机隔离合成242目标：ByteTrack约83ms、4K图像运动约80ms、极端近距离机非配对TCC约1054ms（均p50）。正常算法规模本身未复现分钟级；生产CPU调度、BLAS线程数、内存和持续NPU负载未知。
- RTSP读取无显式超时，仅在实时源卡顿而本地MP4正常时提高优先级。Kafka普通发送为异步；CPU外观模型仅在自然EOF封存执行；启动120秒超时、一次5秒预热、stride=3及MJPEG15FPS上限均不是每帧分钟级节流。

后续最小归因应对照同一时段的ACL执行/CPU NMS、分析/归档、queue put和不同JPEG画面间隔；单独的0FPS或瞬时AICore0%不足以定位。
官方分支核对：[Ultralytics v8.4.102 NMS源码](https://raw.githubusercontent.com/ultralytics/ultralytics/v8.4.102/ultralytics/utils/nms.py)。本轮未重封镜像或离线包，不宣称吞吐已恢复。

## 2026-10-18 BEV静默自动降级（用户最新要求，未发布）

- BEV专项25/25通过：SDK拒绝/构造/地图操作异常、资源事件、本地地理/像素/空状态、清理与持续更新、候选/选中/淡化/端点样式。production build及git diff --check通过。
- 真实浏览器强制地图SDK拒绝：地理轨迹2条、像素轨迹1条、空网格等待均正常；无服务不可用/加载失败/重试文本，没有请求地图SDK/瓦片外网资源。此为本地受控异常验证，不是生产内网服务验收。
- LiveModules 57通过/1失败；失败是独立快照用例：整套运行找不到“保存事件与流量快照”按钮，单独复跑则按钮可点但保存结果为空（595行）。此套件mock了BEV组件，地图用例已通过，未把整个套件报告为全通过。
- 本轮不改检测/NPU/MPS/Kafka/数据库，未重跑真实检测视频；既有离线镜像尚未包含此轮代码，尚未生产部署。

## 2026-10-18 BEV错误隔离、低FPS与无日志诊断（未发布）

- FPS定向及诊断单元测试23通过；地图/适配器24通过，Router与地图组合93通过，新增普通29.7及低0.008FPS主/副视图交互2通过（该次按名称筛选，另56项未执行）。前端production build通过；git diff --check通过。
- 官方MineMap2.1.0在真实浏览器验证项目Polyline/CircleMarker及fitBounds接口；使用空样式隔离网络，未把该检查描述为现场17000方案/瓦片验收。
- 原intranet.3 ARM64镜像内直接启动项目VideoServer，由只读工具采样3秒实收42个完整JPEG、两个不同画面；帧去重与超时退出通过，不改变视频服务15FPS上限。
- 新诊断SQL已在本机road9只读执行并读出Mission/登记视频端口；本机命令环境为live，正确返回requires_replay_v2_profile，未冒充生产采样成功。生产Compose显式配置replay_v2，脚本须在实际platform容器内执行。
- 用户仅报告现场首屏正常、BEV不可用、约几分钟一帧、242轨迹/207目标/0FPS；没有现场资源错误或持续采样，无法确认卡顿归因。新源码未打入既有离线镜像，不声称现场已恢复，未改NPU/MPS参数、DB数据或Kafka offset。


## 2026-10-18 最新：Console 2026.10.18.4 静态资源403修复

用户报告/login和index Permission denied。镜像内资源存在，本机通过禁止旧HTML目录访问复现相同403；此前只验证新容器不足，新增实际升级及私有umask回归。
资源改为镜像专用/opt/traffic-console/html，目录755、文件644，生成runtime-config.js后显式644；入口脚本50-console-runtime-config.sh独立于旧静态覆盖脚本。
269项前端回归通过；旧目录000拒读+umask077的真实Nginx测试、首页/login/index/runtime/初始JS/CSS均200；实际Compose2.24.7由旧403升级到新healthy/200。
新包traffic-analyzer-console-2026.10.18.4-offline.tar.gz不做备份、不修改原发布文件，仅重建Console并等待HTML/runtime健康检查，失败不报告成功。旧.3保留历史但本次使用.4。
现场完整拒读路径尚未获得，未声称已确认SELinux根因；生产应用后的结果仍须现场确认。

## 2026-10-18 最新：独立Console镜像2026.10.18.3

用户要求重新出Console镜像，本次不做备份。`traffic-analyzer-console-2026.10.18.3-offline.tar.gz`约30.5MB，包含完整ARM64镜像、单服务覆盖配置和start.sh。
在当前发布目录解压后执行包内start.sh，脚本用系统docker compose导入/只重建console2，不调用原./docker-compose校验入口，不修改原.env/docker-compose.yaml/SHA256SUMS。
补充配置将Console镜像固定为traffic-analyzer-console:2026.10.18.3-arm64，清除旧静态资源/入口脚本挂载，以运行镜像内置版本；保留原地图连接、发布端口及所有其他服务。以后重建Console也使用该覆盖配置或start.sh。
包含深色MineMap、画布布局和同源MJPEG代理修复。无需使用旧console-fix静态补充包。Platform、数据库、检测器及NPU配置不变。
本机无静态挂载的新镜像真实浏览器显示深色地图，画布803px，Nginx和/ready通过；ARM64导出/重新导入、Compose2.24.7及生产凭据扫描通过，复用269项前端回归。生产内网/NPU实际吞吐仍待现场。

### 2026-10-18 现场NPU进程归属确认

用户提供的docker top将NPU PID2370369对应到XQH检测子进程，其父进程为管道2369453、Platform为2344885；命令显式detection_node.device=ascend、imgsz=960，并使用XQH SRT。
与npu-smi同PID约393MB一致，确认容器设备挂载、Ascend选择及模型设备上下文加载链路生效。单次AICore0%不作“未使用NPU”结论；持续执行/吞吐及实时统计断点仍需最新原始统计和日志，不以此替代完整实机验收。

### 2026-10-18 NPU复核补充

原镜像保留官方CANN默认entrypoint，正常入口加载set_env后可找到acl.so；强制`--entrypoint python3`跳过环境时find_spec为空，不能将该旁路诊断误判为生产NPU配置失败。
用户现场设备节点已映射、device=ascend/id=0，npu-smi存在python3 PID2370369约393MB但归属未确认，AICore单次0%不作未生效结论。配置及错误传播24项通过，不替代310P3实机证据。

## 2026-10-18 生产问题本机复现与Console补充修复

- 用户追加四维图新深色要求已实施：只调整矢量底图图层，保留道路宽度/等级、浅色文字与深色halo，业务轨迹/风险/无人机配色保持；真实公网SDK背景色#091321、轨迹#ff7043、瓦片与GeoJSON覆盖物均通过。
- 原生产Console镜像/CSP + 原生MPS XQH真实复现：检测器直连localhost视频被CSP拦截，页面重连失败。修复后同源鉴权代理实际解码1280×720，未放宽认证或开放检测器端口。
- 公网原生MineMap及项目适配层均实测SDK2.1.6、样式/矢量瓦片、GeoJSON线与控件。发现SDK CSS后加载覆盖项目定位，工作台容器实测0px；修复后803px并显示真实道路/标记。公网分域服务为显式配置，生产.env仍原内网默认。
- Console269 passed/build通过；47项发布/视频/预检测试通过；离线补充包准备逻辑3 passed（只改Console、保留私有env/数据库/Platform、可重复执行及未知更改拒绝）。CSS用真实浏览器尺寸与地图画面验证。
- 路网关闭的真实XQH/MPS短片仍输出FPS7.1、均速20.9km/h、方向/TCC诊断；不等于全片或NPU验收。
- 本机原数据库保留历史inbox，而Kafka新offset已回到181，旧inbox最大5548，触发唯一键阻断，造成有Kafka统计而DB/页面无数据。该原因只在本机证实，未擅自清表/跳offset/重写历史，也不直接推定生产同因。
- 用户确认生产无FPS；生产日志、只读diagnose_live输出及专用公网配置仍待补充。当前交付只证明地图布局/视频路径修复和诊断工具，不能宣称生产实时指标已恢复。

本版按用户授权加入同机PostgreSQL17.10/PostGIS3.6.4/TimescaleDB2.28.2 ARM64镜像。
主配置使用`road9:5432/ycx_prod.drone`、sysdba、Timescale必需；HG完整连接另存私有`.env.hg`，不连接生产HG或执行生产DDL。

- 本机原生Platform真PG+公网Doris：400 passed、3 skipped、10 subtests（缺SRT一项、隔离库清表夹具两项）。
- 根级发布、启动、备份失败清理及管道聚焦回归：89 passed；两项发布文件回归31 passed已包含其中。
- 新数据库真实初始化及重复迁移通过，16视频源/7无人机/1管理员；首次新增39，重复新增0。六张正式超表均建立。
- 发布Platform镜像使用厂商ARM64 libpq连接新数据库，统计、回放、Dashboard、执法与巡查五个真实数据库集成场景：5 passed。
- PostGIS ST_Transform与GiST、Timescale额外隔离探针超表写读通过。重启数据库后探针1行、16源、7无人机均保留。
- 实际pg_dump自定义格式备份成功；在同一隔离实例另建空库，创建两扩展，执行timescaledb_pre_restore、完整pg_restore与timescaledb_post_restore后，探针1行、16源、7无人机及七张超表（六正式+一测试）一致。
  这只证明同版本PG+扩展恢复，不证明可直接恢复到HG。测试探针及测试数据不进入镜像/发布包。
- 实际Compose2.24.7解析四服务拓扑，数据库无宿主端口、独立DATA_ROOT/postgres绑定，init-db等待数据库健康；启动顺序与失败停止分支已回归。
- Platform/Console/模型转换工具内容ID与intranet.2相同，保留此前镜像驱动和前端266项、构建与Nginx代理验证；本轮不重复未变前端和真实视频。
- 原本机road9/Kafka及原生MPS默认保持。独立测试project只启动临时数据库及一次性工具容器，没有在Mac容器内运行开发Platform服务。

包内完整校验工具、备份、HG切换手册与两份私有配置保留；秘密仅在600权限根`.env`、`.env.hg`，源码/镜像不含生产秘密。
最终大小、SHA和归档实检以`DELIVERY-2026.10.17-intranet.3.json`、`VALIDATION-2026.10.17-intranet.3.json`为准。
生产主机无SSH会话，尚未实际启动；内网连接/Kafka业务ACL/MineMap/310P3实推理仍为not_evaluated。单机备份不能替代HA与RPO/RTO验收。

---

# 2026.10.17-intranet.2 最新生产配置与完整发布验证

用户将生产瀚高改为 `sysdba@37.12.14.133:5866/ycx_prod`、schema `drone`，口令只在600权限私有.env。
本版为完整ARM64镜像包，包含全部修复、检查工具和启动脚本；无需操作intranet.1或手工打旧补丁。
本机road9/MPS及公网Doris不变；生产Doris仍内网37.12.11.127:9030/ycx_xc，Kafka/MineMap/JWT/系统管理员保持原配置。

- 本机Platform真PG+公网Doris联合：400 passed、3 skipped、10 subtests；跳过为1项缺SRT、2项隔离库清表夹具。
- 发布/预检/配置/管道聚焦：84 passed；新镜像内驱动/配置/Doris/路网/诊断重点：73 passed。
- 新镜像使用厂商ARM64 libpq，对根Compose独立project/端口/卷中的`sysdba / ycx_prod.drone`首次及重复初始化均通过；
  首次建立16源/7无人机/1管理员，重复新增0。未启用Timescale时普通PG模式正确。
- 新预检以Settings核对实际库/schema；真实权限、版本表、search_path均为drone。缺schema的初始化被拒绝，未向public写UAV表。
- Compose2.24.7实际解析platform/init-db的新账号、口令字面值（含感叹号）、数据库和schema一致；私有env600。
- 增补并实测`CHECK_TOOLS.md`、`db_readonly_checks.sql`及镜像中的topic_acl工具，预检/初始化/状态/日志/镜像/资源校验工具完整保留。
- Console镜像ID与intranet.1相同，复用该镜像266项前端、构建、Nginx及代理/鉴权结果；未重跑未变化的前端或真实视频。
  XQH最近一次仍为55 PASS/0 FAIL/1 WARN（前100帧方向统计为空），不将其算作本轮新实跑。

包的最终大小、SHA、秘密隔离和文件清单以`DELIVERY-2026.10.17-intranet.2.json`及`VALIDATION-2026.10.17-intranet.2.json`为准。
本机隔离PG验证不代替真实瀚高SM3认证；未连接或执行生产DDL。库/schema仍需DBA预建授权。
生产路网暂停和Timescale可选保持false/false；内网网络、Kafka业务ACL、MineMap及NPU实机验收仍待现场。

---

# 2026.10.17-intranet.1 ARM64发布验证

日期：2026-10-17（Asia/Shanghai）。新镜像完整包含瀚高方言/schema修复、普通PG/Timescale可选、
集中预检、生产路网暂停、Doris统一读路网/路况及Console运行时配置。
本机公网Doris `8.149.139.113:9030` 与生产内网 `37.12.11.127:9030` 分开；生产使用既有内网账号，
`ycx_xc`及两张带index表名一致。私有包根`.env`填齐连接及认证，不在本文列出口令。

| 本轮验证 | 实际结果 |
| --- | --- |
| 本机Platform（真PG+公网Doris） | 399 passed / 3 skipped / 10 subtests；跳过1项缺保留SRT、2项需一次性隔离库的Mission清表夹具 |
| 根级发布/预检/EOF/消息回归 | 80 passed |
| Console2 | 266 passed，production build通过 |
| inter_xqh原生MPS | 55 PASS / 0 FAIL / 1 WARN；前100帧direction_stats空，未放宽检测或切换CPU |
| 新ARM64镜像内重点回归 | 72 passed；测试依赖只读挂载，不进入生产镜像 |
| 新镜像驱动/应用 | 厂商aarch64国密libpq及依赖加载、FastAPI/检测器/NMS/两套迁移head导入通过 |
| 新镜像真实迁移 | 复用根Compose的独立project、临时端口、独立卷；无Timescale的xinchan.ycx_drone第一次及重复初始化成功 |
| 重复seed | 16源/7无人机/1管理员；首轮inserted39，第二轮inserted0 |
| 新镜像Doris读取 | 公网SELECT返回8510路口/21070路段，同版本20260501、共同月份202609，唯一ID对账通过 |
| Console镜像 | Nginx语法通过，静态及runtime-config HTTP200；代理本机原生/ready=200，未登录API=401 |
| 现场Compose2.24.7 | 单文件三服务、离线镜像策略、600私有env、完整内网Doris配置和关闭开关均通过 |
| 模型资源 | 源PT、三档OM及独立资源归档SHA一致，复用既有模型包 |

新基础镜像使用原固定ARM64 digest；构建器先校验本机对应digest与架构，缺失才拉取。
新镜像已重新记录Python/系统依赖清单；不会把开发态Platform放入Docker运行，Mac MPS默认保持。
`ROAD_FEATURES_ENABLED=false`与`DB_TIMESCALE_REQUIRED=false`继续保留；本机公共Doris账号不覆盖生产既有内网账号。

归档最终完整性、秘密隔离及外层哈希以同目录`VALIDATION-2026.10.17-intranet.1.json`、`DELIVERY-2026.10.17-intranet.1.json`
及`.sha256`为准；其生成在封包与解包核验之后。内网SM3认证、Kafka业务ACL、MineMap瓦片及310P3模型实际数值/吞吐仍待现场。
ADR-019结构项继续通过，历史local_runtime_evidence阻断保留，不把其当作本次回归失败或改写历史证据。
本次只跑XQH前100帧；未重跑mp4728全片或产生精度真值结论。Doris全城图层性能和历史礼士ID缺口见Doris专项报告。

---

# 历史：2026.10.16-intranet.4 ARM64验证报告

日期：2026-10-16（Asia/Shanghai）。应用版本：**2026.10.16-intranet.4**。
目标：Linux aarch64/ARM64、Ascend310P3、CANN9.0.0，瀚高xinchan.ycx_drone，YCX同库road11只读。

**ARM64应用镜像与封包前检查已通过，现场验收尚未完成。** 封包后的归档哈希、凭据扫描及镜像重载结果以交付同目录`VALIDATION-2026.10.16-intranet.4.json`为准。旧intranet.2的amd64归档仅保留历史，不能安装到aarch64主机。

| 检查 | 结果及边界 |
|---|---|
| 官方基础镜像 | CANN9.0.0/310P/Ubuntu22.04/Python3.11、Node22、Nginx1.27全部重新锁定ARM64子manifest digest，见base-images.json |
| 厂商库架构/加载 | 用户提供libpq.so.5，ELF183/aarch64；原始SHA=e128a03ce65132b999217054c88a2efdfc9347bfd98311315b976a9ec8793a1e；纯Python psycopg3.2.13在实际CANN镜像加载vendor libpq120007成功 |
| ARM64兼容依赖 | libssl.so.1.1/libcrypto.so.1.1来自Ubuntu官方ARM64 libssl1.1 1.1.1f-1ubuntu2.24，下载包SHA与官方索引核对；不替换系统OpenSSL3。来源和三库SHA随包ARM64_SOURCE.json |
| 错误架构拒绝 | 原x86_64厂商库、实际已存在的amd64 Platform镜像及x86主机启动均被拒绝；20项部署/配置/资源/回滚回归通过 |
| 本机Platform回归 | 336 passed、7个显式数据库集成场景跳过、10 subtests passed |
| 实际ARM64镜像API回归 | 336 passed、7个显式数据库集成场景跳过、10 subtests passed；测试依赖、源码布局夹具及资源均仅用于只读挂载的临时诊断容器，不写入生产镜像 |
| 前端回归 | Console264项通过，ARM64镜像Vite构建成功 |
| 数据库/初始化 | 复用根Compose的独立project/卷：厂商ARM64 libpq连标准PG，特殊字符/中文密码通过；7台无人机、16视频源、16遥测源、6 hypertable位于ycx_drone，public中0个UAV表 |
| 重复导入 | 第二次初始化inserted=0，现场修改名称/源enabled=false及管理员密码哈希均保留；不迁移任务、轨迹或告警历史 |
| 实际ARM64代理 | nginx -t、SPA、ready/health、2.2MB上传哈希、HTTP媒体Cookie、HLS鉴权转发、MJPEG重写/鉴权、WebSocket101、内网MineMap运行配置/CSP通过；使用隔离HTTP夹具，不冒充真实生产视频/地图验收 |
| CPU辅助推理 | 实际ARM64 Torch2.2.2（无CUDA）完成空图CPU辅助预测、512维外观编码和非空torchvision NMS；主检测仍固定Ascend，不回退CPU |
| 视频解码 | 实际ARM64镜像解码XQH及mp4728各一帧成功，均2160×3840×3，覆盖H.264与HEVC文件读取；不代表昇腾检测吞吐 |
| 三档OM | ARM64 CANN9.0.0 ATC对640/960/1280全部解析成功，SoC=Ascend310P3，custom AICPU kernel store及host so store均0字节；继续复用intranet.4独立模型资源，现场启动仍强制三档实际推理 |
| 视频/遥测分离 | 29个文件独立资源包49,600,542,720字节，原归档及逐成员SHA已通过；本次未修改大资源，无需重复打包/拷贝 |
| 生产数据库连接 | 在原生ARM64 CANN中以厂商libpq做了一次只读连接尝试，ConnectionTimeout，未执行生产DDL/DML；主机TCP可达不等于容器PG认证可用，SM3/白名单/实际YCX表及TimescaleDB仍需现场check |
| 生产Kafka | 此次仅做主机TCP可达检查；SASL/PLAIN软件与历史隔离协议测试有证据，生产认证/ACL/advertised地址及断连恢复仍待现场 |
| 内网地图 | Key按用户确认复用，地址37.8.188.98:21009、方案17000；参考服务真实样式/瓦片/点击已有历史证据，内网17000实际授权、CORS及空间对齐仍待现场 |
| 本地模式 | 原生macOS Platform/MPS及Console开发方式不改，本地.env不覆盖；现有Platform ready、0活跃任务，数据库与Kafka健康 |
| 宿主机配置 | 本次未增加Docker内存、未重启开发基础设施；沿用已恢复的4.75GiB配置，磁盘上限沿用已授权的256GB |

## 交付与验证记录

- `VALIDATION-INIT-2026.10.16-intranet.4.json`：独立初始化/重复导入。
- `VALIDATION-PROXY-2026.10.16-intranet.4.json`：实际ARM64 Console代理。
- `VALIDATION-RUNTIME-2026.10.16-intranet.4-arm64.json`：CPU辅助与视频解码。
- `VALIDATION-OM-ARM64-2026.10.16.json`：三档OM结构解析。
- `VALIDATION-HIGHGO-ARM64-LIVE-2026.10.16.json`：实际厂商库加载及生产连接超时边界。
- `VALIDATION-2026.10.16-intranet.4.json`：封包后不可变文件/凭据/镜像重载验证。

现场首次使用`./docker-compose up -d`导入离线镜像和独立模型资源，预检通过后由init-db迁移并启动两个常驻服务。原生Compose无法从tar自动导入镜像；隔离现场不拉取镜像、不安装依赖。私有根.env存放实际连接及初始密码，600权限；可编辑.env不列入内部SHA，外层归档SHA保护原始交付。

所有临时数据库和代理验证均复用根Compose、独立project/端口/卷，结束后仅清理自己的资源。真实NPU推理、完整视频数据链路、生产SM3/Kafka/YCX/地图及真值准确率为not_evaluated；不把ATC解析、空图或工程测试当作准确率/实机性能验收。

历史amd64版本和intranet.3源码准备记录保留，均不作为本版ARM64正式交付；原始模型编译/资源校验记录仍见intranet.4资源版。包内报告为封包时快照，封包后完整性检查另在交付同目录记录，已封存归档不回写。

## 封包后最终检查

ARM64私有归档5,086,658,019字节，33个内容文件：不可变文件SHA、实际凭据仅根.env、.env原值解析、3张ARM64镜像重新导入后ID均通过。源码归档20,783,488字节、518个内容成员校验/凭据扫描通过。原生ARM64管道运行回归57项通过，另1项只读脚本布局夹具补齐后通过；未改产品代码或跳过失败用例。所有临时验证容器/专用卷已清理，本机原生Platform ready、0活跃任务。

正式交付为ARM64 intranet.4，模型与视频继续复用已校验的独立资源包，不覆盖/改写旧amd64归档。生产连接认证、NPU实机及内网地图继续待现场验收。

ADR-019严格本机审计复查：9项结构检查通过，历史local_runtime_evidence仍因旧基线证据版本不匹配而block；没有改写历史报告或清空本地库来制造通过。该历史证据项与本次ARM64归档完整性检查分开记录。

## Compose 2.24.7现场兼容性修复

现场报告镜像导入后`unknown flag: --environment`。已用官方Compose 2.24.7二进制实际复现，原启动脚本版本门槛允许2.24.4却依赖较新CLI参数，属于交付脚本缺陷。继续使用系统已安装的2.24.7；补丁不含Compose二进制，也不重建镜像或改写已封存大归档。

删除`config --environment`调用，使用Compose自身解析dotenv，将六项非秘密启动参数传给已导入ARM64 Platform镜像中的Python标准库。工具容器设置`pull_policy: never`、`network_mode: none`，没有挂载、设备或数据库/Kafka凭据，不启动应用服务。Shell不执行`.env`内容。单独`prepare`需先`load`；正常`up`顺序已满足。

官方Compose 2.24.4、现场同版2.24.7、本机2.29.7均完成实际ARM64工具容器的资源准备、重复执行、中文/美元符号/引号路径、访问来源生成、600权限与临时文件清理验证。下载的旧Compose仅放本机临时目录用于测试，经过官方发布SHA核对，没有安装到系统或交付包。部署/配置回归23项通过，Shell语法和`git diff --check`通过。

小补丁`traffic-analyzer-compose-hotfix-2026.10.16.tar.gz`核对已发布原始脚本SHA，备份脚本/根Compose/清单并只更新对应两个校验行；覆盖原始、重复应用、两文件更新中断后的修复、未知修改拒绝和损坏补丁拒绝场景。原始脚本SHA已从intranet.4实际归档核对。另外修正原始包devices对象格式及缺失PIPELINE_IMGSZ时的整数空值：仅转换设备为字符串、增加960默认值，保留自定义字段；对实际已封存原包应用补丁后，官方2.24.7的config解析、特殊字符凭据转义、init-db依赖、禁止pull策略和up参数验证通过。构建/源覆盖渲染使用2.29.7；2.24.7不支持源覆盖中extends引用带depends_on的服务，现场使用已生成单文件，无此渲染步骤。细节记录`dist/VALIDATION-COMPOSE-ENV-HOTFIX-2026.10.16.json`。生产SM3/Kafka/NPU/内网地图验收边界保持不变。

## 现场预检AssertionError诊断补充

新增独立诊断脚本，stderr逐阶段标记、stdout保留JSON结果；异常只输出类型和代码位置。两个回归验证凭据不出现在异常输出以及libraries-only契约；在实际ARM64 CANN镜像只读挂载脚本后，厂商psycopg/libpq加载检查通过。该验证没有昇腾设备，不代表三档OM实机或生产连接通过。现场调用栈待提供，SQLAlchemy版本解析仅为候选原因。

## 瀚高数字版本方言修复与线上项目比对

现场栈定位SQLAlchemy `_get_server_version_info`。线上“指标产出分析”的hg_client.py直接psycopg2.connect，业务uow和迁移复用，驱动目录由Dockerfile内置；未使用SQLAlchemy。保留现有ARM64国密libpq/异步psycopg3，新增专用方言以SHOW server_version_num读取实际内核版本；runtime、Alembic两套迁移统一Settings URL，本地asyncpg不变。

- 本机Platform：346 passed、8 skipped、10 subtests。8个跳过中7项原有数据库场景，1项为Mac未安装可选psycopg；后者在实际ARM64镜像11项专门回归中通过。
- 部署/诊断/补丁：26项通过；验证保留.env、已有挂载和环境变量、重复应用、未知修改拒绝与文件SHA。
- 原断言：以非PostgreSQL产品横幅SQL响应夹具复现；没有声称该字符串就是实际瀚高完整横幅。
- 真实数据库隔离集成：复用根Compose、独立project/网络/卷、真实厂商ARM64 libpq连接PG17+TimescaleDB；特殊字符/中文密码、schema、事务回滚、基础/V2迁移和重复seed均通过。仅修改自己的隔离数据库；测试后临时容器/卷/网络已清理。
- 原归档打补丁：实际ARM64 intranet.4原包先应用Compose补丁再应用本补丁两次，官方2.24.7解析及只读挂载通过；所有不可变小文件哈希、现场路径参数和私有.env字节/600权限保留。

证据：dist/VALIDATION-HIGHGO-VERSION-HOTFIX-2026.10.16.json。未重新连接生产数据库或运行生产DDL；生产其余扩展/权限、YCX/Kafka及完整业务链路仍需现场继续验收。现场栈执行顺序说明此前三档模型预检已运行至完成，不能将此作为完整视频性能或准确率验收。

## 2026-10-17修复激活及一次执行流程

现场重复栈仍指向旧预检runtime_check.py:107/51、stock PGDialect的版本解析。无法从该栈确定现场用了哪一份Compose，不将猜测当作根因。新增一次执行脚本自动累计应用既有补丁，使用明确project-directory/env-file/-f，分别验证实际platform/init-db加载的配置/方言/解析方法、迁移引擎选择及新版预检，再运行生产入口；失败生成自动安全报告。

原归档在隔离临时目录经系统同版Compose 2.24.7及现有ARM64镜像实际加载验证，两角色为HighGoPsycopgDialect；两次累计修复通过，私有.env字节/600权限保留，损坏载荷在部署文件变更前拒绝，临时工具清理通过。部署/诊断/安装回归28项通过。Mac在最后生产Linux门禁处停止，未运行开发态Platform容器，没有将最终启动记为成功。临时网络只清理此次测试创建的空网络，本机DB/Kafka保留。版本16已封存补丁未改写。

证据：dist/VALIDATION-HIGHGO-REPAIR-2026.10.17.json。现场代码加载状态、真实瀚高剩余权限/扩展、YCX/Kafka及最终站点启动仍待现场一次执行结果。

一次执行脚本最终启动显式使用--force-recreate（已核对2.24.7支持），用于更新应用进程和只读文件挂载；不重建镜像，不重启外部数据库/Kafka。真实Linux/NPU启动仍未在本机执行。

## 2026-10-17会话schema补充

现场已通过新方言加载及三档OM，失败位置为预检database/schema不匹配。新增专用方言的连接后autocommit SET SESSION search_path，并由URL传入、过滤应用schema；覆盖迁移与运行，本地asyncpg不变。预检打印不含密码的实际database/schema、search_path及schema存在/USAGE/CREATE状态，再保留原门禁；预检不创建或授权schema/扩展。

本机Platform 348 passed、8 skipped、10 subtests；实际ARM64方言13项通过，部署/诊断33项通过。真实厂商ARM库连根Compose隔离PG17/TimescaleDB，在不传启动options时仍正确进入ycx_drone，连接回滚后保持、default_schema_name正确；基础/V2迁移及重复初始化通过。实际移走测试schema、非superuser无USAGE两种状态诊断通过且没有密码输出。旧版修复→新版升级→重复执行、SHA/600权限及.env保留通过。真实现场数据库/schema字段尚未提供，不宣称已确认schema缺失或线上startup options失效；当前修复不代替DBA预建。

## 2026-10-17分项环境诊断交付

交付单文件traffic-analyzer-repair-environment-2026.10.17.sh，累计升级配置、方言、数据库核心、预检、初始化与共享诊断模块（两角色均只读挂载）。独立基础设施检查提前到NPU依赖容器加载检查之前；最终完整预检仍为启动门禁。预检汇总passed/failed/warning/skipped/pending_init，输出中文错误码/原因/动作/安全证据；未知原因明确标记，不输出异常原文、SQL参数或连接串。初始化使用raise_on_error保留异常链，普通本地bool契约不变。失败自动提取受控DIAGNOSTIC日志、容器退出/OOMKilled状态及地图/入口配置提示，不转储原始服务日志或Key。

验证结果：本机Platform378 passed、8 skipped、10 subtests；实际ARM64诊断/方言52项；部署/预检/安装36项。真实厂商ARM64 libpq连接根Compose隔离PG17/TimescaleDB：同一次报告包含YCX缺表、PostGIS函数缺失和Kafka不可达，后续YCX表仍通过；错误DB密码分类为DB_AUTH且不遮蔽独立YCX/Kafka；schema缺失不遮蔽Timescale及其他服务；savepoint与只读事务回滚恢复、待初始化状态、严格初始化/重复seed和凭据不出报告通过。Mac原生模式未改变。

原始归档→旧版本修复→schema修复→环境诊断升级→重复执行的实际Compose2.24.7/ARM64工具容器验证通过；损坏内嵌载荷拒绝，.env字节/600权限和数据目录保留。Mac最后仍按生产Linux门禁停止，没有启动开发态Platform容器；生产站点完整启动与实机业务验收尚未完成。Kafka认证/权限类使用已安装版本实际异常类型测试；隔离集成Kafka为不可达故障注入，没有发布消息或验证生产ACL。只读元数据不能证明RLS或业务写入成功，报告明确区分。

证据：dist/VALIDATION-ENVIRONMENT-REPAIR-2026.10.17.json、dist/VALIDATION-ENVIRONMENT-BATCH-2026.10.17.json。脚本124538字节，SHA256=3db049a610ca73a17e4f964cdabe7c1d0fcb823154d9b294c4511dc563e4af38。原镜像/模型/视频归档保持封存。

## 现场报告highgo-repair-report.HUL4md（历史门禁，已由ADR-037调整）

本次为真实现场报告证据：最终30项通过、5项失败、1警告、1待初始化。库实际为xinchan、schema=ycx_drone、search_path=ycx_drone,public，schema存在且USAGE/CREATE为true；三档OM空图推理、7目录写入、厂商驱动与新方言加载均通过。YCX三张基础路网表可查；Kafka SASL_PLAINTEXT/PLAIN及元数据读取通过，296个可见Topic，不等于发布/事务/消费者组ACL通过。

阻断：xinchan没有启用timescaledb；road11.dim_data_version及xianchang的两张典型态势表按当前名称解析不到（42P01）；YCX会话PostGIS_Version函数解析不到（42883）。其中Timescale扩展服务器安装/控制文件可用性未知，PostGIS未安装与安装在其他schema/可见性问题尚不能区分；xianchang原为沿用默认配置，尚未确认生产实际指标schema。不得让DBA按猜测新建空的外部表，也不以普通PG表替代Timescale绕过门禁。

应用表数0，两套版本表均待初始化，符合预检失败尚未执行init-db的顺序，不另列为迁移失败。现场仍未达到整站启动验收；真实视频、性能/真值及浏览器地图仍未由本报告证明。

已生成dist/dba-check-2026.10.17/README.md、01_readonly_dependencies.sql及REPORT_ANALYSIS.json。只读SQL集中查服务端内核、扩展可用/启用/namespace、同名及近似外部表位置/字段、函数位置/权限。已在复用根Compose的独立PG17实例、只读事务、ON_ERROR_STOP下逐查询验证，缺对象仍能完成其他目录查询；未连接生产或执行生产DDL。角色权限列只代表执行SQL的角色，DBA角色结果不能替代应用角色授权验证。

## 2026-10-17 可选依赖与路网关闭累计修复

用户确认两张指标表属于Doris，授权Timescale/PostGIS/路网版本表降级，继而要求暂关闭路网功能。
已实现ADR-037：生产flag=false/false/doris，前端隐藏平台治理一级/标定入口并阻断深链；后端校准/导入API拒绝、
自动标注任务关闭、检测子进程不加载路网包/车道模型与推断。原数据保留，本地默认不变。
参考项目Doris MySQL连接补入私有.env，只读错误为警告；未声称内网连接或指标schema已验证。
缺Timescale普通PG迁移/两次初始化、真实canonical/V2幂等落库与查询、sealed Mission回放集成通过；
DBA启用后转换六超表/重复执行且既有数据保留通过，使用实际ARM64厂商libpq与隔离根Compose PG17。
Python综合435通过/8跳过/10子测试、补充22及Doris错误7通过；前端265通过/构建通过。
真实MPS视频按原启动NMS fallback参数复跑55通过/0失败/1警告（前100帧direction_stats空）；
直接不带该环境参数曾遇torchvision::nms MPS不支持，未篡改本机依赖或检测设备。
实际2.24.7原包→旧补丁→新补丁→重复执行、.env连接与路径保留/缺参补齐/600、损坏拒绝通过；
实际Console镜像静态文件与flag验证通过，没有在Mac启动开发态Platform容器。
交付dist/traffic-analyzer-repair-degraded-2026.10.17.sh，16418974字节，SHA256=7fbe05cdae4fcb48d9e0e828be4dd3008258a9f5a576c1cd19293be4980edccc；私有600。
证据dist/VALIDATION-DEGRADED-2026.10.17.json及README-DEPLOY-DEGRADED-2026.10.17.md。
生产Doris/此修复整站启动、Kafka业务ACL、内网地图、真实任务性能及无真值精度仍未验收；原大归档封存。

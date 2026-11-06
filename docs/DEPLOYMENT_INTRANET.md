> 2026-11-04 最新原生累计前后端完整包见[NATIVE_DEPLOYMENT_2026.11.04.1.md](NATIVE_DEPLOYMENT_2026.11.04.1.md)，现有Console服务使用包内新版页面资源。

> 2026-11-03 上一原生完整包为2026.11.03.3，同时包含四进程与event-faithful/v2；启动与数据版本降级门禁见[NATIVE_DEPLOYMENT_2026.11.03.3.md](NATIVE_DEPLOYMENT_2026.11.03.3.md)。以下Compose交付说明保留原有范围。

# TrafficAnalyzer 内网生产部署手册

## 2026-11-03 原生2026.11.03.2累计性能交付

新完整包累计fork绑定、root权限诊断、日志窗口和同值坐标传输优化；不手改受校验源码，不裁剪轨迹或改阈值。操作见[NATIVE_DEPLOYMENT_2026.11.03.2.md](NATIVE_DEPLOYMENT_2026.11.03.2.md)，证据和边界见NATIVE_VALIDATION_2026.11.03.2.md；旧包保持，不把本机IPC基准当作生产FPS。


## 2026-11-03 Platform与检测器完整原生包

用户授权仅Platform和检测器脱离Docker，Console/数据库/Kafka及资产目录保留。完整包首次`./traffic start --deployment-root <现有部署根>`自动完成配置导入、预检与切换，后续手动启停，无自启；说明见[NATIVE_DEPLOYMENT.md](NATIVE_DEPLOYMENT.md)，验证边界见[NATIVE_DEPLOYMENT_VALIDATION.md](NATIVE_DEPLOYMENT_VALIDATION.md)。旧宿主排查包保留历史，不作为新包安装前置条件。没有新的现场日志或NPU访问，不将原生部署等同约1FPS问题已解决。


## 2026-10-20 Platform宿主原生对照包

用户授权为排查Docker将Platform与检测子进程迁出容器，其他服务保留。用户确认UOS Server20/Python3.12.12；本包自带同基线Python3.11/CANN9和私有ELF加载器，不替换宿主Python。完整安装、prepare、switch-host及rollback见[独立操作指南](HOST_PLATFORM_RUNBOOK_20261020.md)。复用当前Compose/私有连接/数据/模型和视频，保留显式init-db及依赖迁移门禁；Mac默认不变。此为短期对照，不据此认定Docker是性能根因或宣称UOS现场通过。

## 2026-10-20 鲲鹏920 CPU0满载现场操作

独立操作文档见[CPU0满载排查与调优操作指南](KUNPENG920_CPU_TUNING_RUNBOOK_20261020.md)，可单独复制到内网。
用户最新lscpu确认96物理核、双路48核、4个NUMA节点各24核；历史“100核”为此前用户描述，不作为本次拓扑。
先只读核查容器CPU范围/配额和宿主PID下各线程affinity，再按条件进行单变量对照。线程参数使用额外覆盖文件，
不直接编辑受校验发布文件，不把单核满载等同一核限制；本轮只交付文档，未操作现场或修改运行配置。

## 2026-10-19 Docker运行方式与性能边界

用户询问Docker是否可能导致约1FPS。Linux ARM64宿主运行相同架构镜像时，容器进程共享宿主内核；与本机Mac Docker Desktop的Linux虚拟机环境不同，不能将两者测量直接等同。需要区分容器CPU quota/cpuset或上级cgroup、线程亲和、内存/共享内存及IO、NPU设备/驱动映射，以及错误架构镜像经QEMU仿真，而不能由“Docker启动”或“单核忙”直接推断性能原因。

本次只读核对仓库生产根Compose、内网及源码覆盖：没有写死cpus/cpuset/cpu_quota/cpu_period/mem_limit；Platform shm_size=512m，内网覆盖映射Ascend设备及宿主驱动。发布镜像已有ARM64校验，但这些文件/本机镜像事实不替代现场实际容器、上级cgroup和当前worker核查。旧现场日志OM执行8.4ms只支持当时NPU执行阶段较短，不证明.4新任务整体正常。当前不建议仅因Docker而改宿主原生生产拓扑；先以相同输入/依赖做受控对照，保持设备及认证门禁。参考Docker官方容器资源约束与多平台仿真说明。

## 2026-10-19 .4后约1FPS与NEON核查

用户确认应用.4后FPS约1，已离开内网，推测ByteTrack占满单核；没有该新任务日志，暂不把推测当根因。原ARM64运行时镜像核查OpenCV useOptimized=True，编译baseline=NEON FP16，并包含NEON_DOTPROD/NEON_FP16/NEON_BF16分派；JPEG为libjpeg-turbo。NumPy在本机ARM虚拟机报告NEON/ASIMD可用，具体可用扩展仍以现场CPU为准，不存在待开启的统一NEON开关。

同镜像4CPU、直接导入.4包实际BYTETracker.update，初始化304轨迹后每帧164候选、4帧合成位置移动，启用cProfile。双BLAS各1线程四帧105.421/34.943/34.771/32.863ms，双64线程65.582/40.495/39.681/42.927ms；预热后约33–43ms。本对照未复现跟踪1秒/帧，不代表真实候选分布、CPU型号、运动估计/投影/渲染或整管道FPS。IoU和分配已使用cython_bbox/lapjv原生实现；逐轨迹影子门控、Kalman及日志阶段调用可作为批量化/原生化候选，尚无现场收益结论。

当前不新增原生库或另造源码补丁。未来若引入C/C++扩展或重编NumPy/OpenCV，按ADR-041作为原生依赖/运行时基线变化另行发布，不能混入同基线直接复制包。需保留数值、门限掩码、逐帧ID与EOF对照，以及实际ARM运行时加载和性能验证。核查证据见DEPLOYMENT_INTRANET_VALIDATION.md。

## 2026-10-19 应用.3后0.9FPS与.4绘制优化

用户已应用.3，报告网页FPS约0.9；此前48–52秒的旧日志不能用于定位这次新任务的主瓶颈，已请求新阶段日志。代码检查另发现候选标签逐个复制并透明混合整张4K图，已用可复现对照确认其独立开销。原ARM64镜像4CPU、200候选标签4K为1388.256ms，改为仅处理标签ROI后22.733ms；随机背景、四角裁剪、重叠标签及1×1/小图/720p/4K逐像素一致。关闭imshow时同时跳过无用窗口缩放，保存/证据/MJPEG仍用原尺寸结果。

累计包`dist/traffic-analyzer-direct-copy-2026.10.19.4.tar.gz`完整继承.3，运行时仅改ShowNode.py；镜像、35项依赖/迁移、模型/抽帧/阈值/线程配置均未变化。按包内COPY_README更新实际/app来源，stop/start后新建任务；实际挂载APP_RELEASE版本为2026.10.19-render.4，并比对ShowNode文件SHA。启动/就绪日志仍继承contract=20261019.3，它们不能单独证明.4已加载。无需init-db或重建镜像。实际包内源码ARM复验1333.519ms对23.401ms且像素一致，31项绘制/EOF回归通过。

目前没有应用.3后同一任务的新阶段日志，也未部署.4或运行真实NPU；不能宣称候选绘制就是当前0.9FPS主瓶颈，或将该单阶段加速比例外推为整体FPS。新日志继续比较show.render/mjpeg、tracker.association/shadow_gate、reader.detection与队列反压。详细证据及归档SHA见DEPLOYMENT_INTRANET_VALIDATION.md。

## 2026-10-19 确认现场未应用.3：先使用现有修复包

用户在最新日志后明确确认只执行过直接复制.1/.2，.3尚未执行。因此先应用既有`dist/traffic-analyzer-direct-copy-2026.10.19.3.tar.gz`，不另造.4、不新增运行代码或盲改生产线程配置。该包已包含二维影子诊断的等价手工前代，避免旧版逐轨迹调用线程化`solve_triangular`。按包内COPY_README核对实际/app挂载、停止两应用、复制完整application及校验清单、start后新建检测；原任务进程不会因磁盘文件覆盖自动加载新代码。检查同一新Pipeline的startup_contract/ready_contract=20261019.3和新的shadow_gate耗时。

原ARM64镜像、独立无网络/只读源码工具容器、4CPU下，以真实gate_cost_matrix和包内KalmanFilter执行304轨迹×164候选；NumPy与SciPy线程池各显式设64，仅用于诊断容器。旧.2为22921.335毫秒、.3为12.128毫秒；两库各1线程时旧.2为11.924毫秒、.3为9.088毫秒。四组门控矩阵完全一致，均拒绝46456对。旧版高线程开销及.3修复在同一ARM运行时对照成立；该隔离合成规模测试不等于现场CPU型号、实际轨迹分布或整管道FPS验收。证据与复跑命令见DEPLOYMENT_INTRANET_VALIDATION.md。本轮未部署或重启现场，未修改NPU、阈值、影子诊断开关或Mac默认。

## 2026-10-19 最新现场日志：影子门控占据跟踪耗时

用户提供`新文件111113.txt`，Pipeline为`pipe-7f2c9e37`，片段覆盖北京时间20:56:29–21:01:43；本次仅分析日志，未连接现场、修改运行参数或发布代码。6次完整采样中，`tracker.association`为48.016–52.417秒，内层`bytetrack.shadow_gate`为47.911–52.269秒，各次占关联阶段超过99%；`bytetrack.mahalanobis_solve`的11次采样为122.6–224.9毫秒。慢点已定位至影子马氏距离门控，不能再笼统归于昇腾推理。

同期`ascend.om_execute`的6次采样均为8.4毫秒，`reader.detection`为80.9–84.6毫秒，`show.render`为248.8–978.9毫秒，`show.mjpeg_encode`为45.5–182.9毫秒。reader的`queue.detect.put`等待48.117–52.420秒，show反复等待`queue.track.get`，与跟踪阶段阻塞造成的上下游等待一致。以上是低频采样，不代表全量性能分位数；渲染仍有成本，但不是该片段几十秒卡顿的主要来源。

跟踪worker的日志PID为459（容器内PID），`cpu_threads=131`、采样线程`cpu_allowed=9`；影子门控的进程累计CPU时间约为墙钟的8.84–8.86倍，说明该阶段期间进程消耗约8.8核的平均CPU处理量，与此前仅凭外部观察推断“只用一核”不同。线程数是存活数量，CPU计时包含该进程其他线程；不能由此直接证明具体BLAS调用或全部线程的亲和范围。线程池调度/忙等及现场加载版本仍需对照验证，片段没有启动版本标记，不据此认定已运行或未运行.3修复。

这6次约50秒的关联耗时支持约0.02 FPS的处理量级；用户本次报告网页0.21 FPS，两者相差约10倍，需对齐同一Pipeline和时间窗口，不能宣称0.21已被日志证实。下一步核对现场实际加载的`kalman_filter.py`版本与NumPy/SciPy线程库配置，再对跟踪数值库做单变量线程对照；保留影子诊断、匹配阈值及身份/地理门禁，不扩大NPU参数或本机MPS变更范围。尚未确认具体数值库根因或现场恢复。

## 2026-10-19 CPU亲和范围与多核核查

用户确认宿主有100核。`cpu_allowed`是诊断读数，不是应用配置：实现使用`sched_getaffinity(0)`，严格表示当前日志采样线程允许的逻辑CPU数量，不能由1推出全部进程线程都挤在同一CPU。仓库生产根Compose、内网及源码overlay没有设置cpuset/cpus/quota或taskset；构建/对照工具容器的单核设置不属于生产Platform。

在现场部署根目录先只读检查；若当前通过app-compose管理源码版本，用`./app-compose ps -q platform`取得同一现用服务的容器ID：

```sh
cid=$(docker compose ps -q platform)
docker inspect "$cid" --format 'cpuset={{.HostConfig.CpusetCpus}} nano_cpus={{.HostConfig.NanoCpus}} quota={{.HostConfig.CpuQuota}} period={{.HostConfig.CpuPeriod}}'
```

cpuset控制CPU编号范围，cpus/quota控制CPU时间额度；空cpuset及未设quota不排除父cgroup或线程自己的亲和限制。若现场确认容器cpuset限制为单核，且CPU0–15都在线并被上级允许，可用`docker update --cpuset-cpus=0-15 "$cid"`动态扩为16个逻辑CPU；已有一核时间配额还需分别调整，不能只改cpuset。若容器本已允许多核，应先核对实际detector PID下`/proc/<pid>/task/*/status`中的`Cpus_allowed_list`，不能仅由日志读数盲改容器或设100个数值库线程。

用户随后返回`cpuset= nano_cpus=0 quota=0 period=0`：仅确认该容器HostConfig没有显式CPU限制，暂不执行上述条件性update。检测任务运行时可先用`docker top "$cid" -eo pid,ppid,comm`查宿主PID，再用`sudo taskset -apc <实际宿主PID>`只读查询相关进程全部线程；此处不给CPU列表参数，因此不会修改绑定。宿主PID不能直接使用容器日志中的459等PID替代。若全部线程同核，继续追父进程/运行库/上级cpuset；若各线程分布多核，则采样读数1不足以说明整个worker被限制为一核。

用户补充`docker stats --no-stream platform`显示CPU114.06%，内存/IO未见异常。Linux口径下该容器在本次采样期间累计约使用1.1406个逻辑CPU的处理量，包含Platform及检测器等全部容器进程；这不是CPU可用数量，也不能证明一核限制、上级无配额或其余宿主CPU空闲。若采样时正发生跟踪卡顿，该观察与CPU热点串行执行或线程亲和限制均可相符，仍须上述各线程mask核查，不据此盲设16/100核或增加BLAS线程。CPU百分比计算依据：[Docker Engine API](https://docs.docker.com/reference/api/engine/version/v1.40/)。

用户进一步观察CPU负载集中在同一个核心，结合采样线程cpu_allowed=1，优先验证线程亲和限制，但仍不能排除串行热点。若`taskset -apc <跟踪进程宿主PID>`确认该进程各线程仅允许同一个CPU，先保留原绑定；在CPU0–15确实属于现场有效范围时，可仅针对跟踪进程用`sudo taskset -apc 0-15 <跟踪进程宿主PID>`做一次临时对照，再查询绑定并比较shadow_gate/queue.detect.put耗时。不要直接修改整个容器全部NPU线程。`-a`覆盖现存全部线程；没有`-a`只改主线程会遗漏其他线程。上级cpuset仍会约束请求范围，若只生效一个CPU须继续查上级限制；若范围已放开但仍单核忙，继续排查串行热点。该对照不自动持久化，也不会把串行Python改为并行；当前无现场执行结果，不声明根因已确认或恢复。

动态更新可能在容器重建后被Compose配置覆盖，确定有效后应纳入实际生产配置及发布清单；子进程继承父调用线程的affinity，容器范围扩大也不保证解除运行库自身绑核，须核验新任务各线程及阶段耗时。未连接生产、不修改本机MPS默认、不重启任何现场服务；允许更多CPU不保证吞吐按核数增长。

依据：[Docker资源限制](https://docs.docker.com/engine/containers/resource_constraints/)、[Docker update](https://docs.docker.com/reference/cli/docker/container/update/)、[Linux线程affinity与继承](https://man7.org/linux/man-pages/man2/sched_setaffinity.2.html)。

## 2026-10-19 应用.2后仍超时：累计修复.3

用户应用直接复制.2后，pipe-836dbb51仍在120秒就绪超时后被终止，影子二维求解每次约688ms。日志仅含尾部，尚不能确认现场实际加载的启动参数、源码挂载或首次就绪信号；不把本机.2验证当作现场恢复。新包为`dist/traffic-analyzer-direct-copy-2026.10.19.3.tar.gz`。

.3把VideoServer的就绪logger改为Hydra配置完成后创建的`pipeline.video`，即使父Platform仍使用旧disabled启动参数也须在真实socket绑定后发送标记。日志增加`PIPELINE_LAUNCH startup_contract=20261019.3`及`MJPEG_READY ... ready_contract=20261019.3`，分别确认Platform实际加载新代码及子进程使用新视频节点。创建/重试Mission专用等待改180秒，普通API仍10秒，服务端原120秒就绪门禁不变。

二维Mahalanobis影子诊断改为Cholesky后的两行前代，避免每条轨迹调用线程化trtrs；保留原Cholesky校验、距离/门限/影子计数，四维及正式Kalman更新不变，不关闭影子诊断或改MPS/NPU参数。数值、门限掩码及173条轨迹ID对照见验证报告；未在本机复现现场80秒，不承诺现场吞吐。

按包内COPY_README先确认现有容器`/app`的宿主来源，停止两个应用后同步覆盖实际挂载的application副本及部署根清单，再start并强制刷新网页。只覆盖部署根application可能遗漏已启用app/current或其他实际挂载副本；日志必须出现上述两个新标记。包复用intranet.1精确镜像/35项依赖迁移基线，不含私有配置/模型/视频，不执行init-db，旧包保留。

## 2026-10-19 网页任务启动超时修复（直接复制2026.10.19.2）

用户日志pipe-9ae147c8中init.mjpeg已结束、show.mjpeg_encode已完成，但没有MJPEG_READY，网页报超时且任务未启动。已复现启动入口的`hydra/job_logging=disabled`禁用了导入时创建的`nodes.FlaskServerVideoNode` logger，Linux fork继承后即使配置root INFO仍不能发送就绪信号。启动入口现改`hydra/job_logging=stdout`，继续由原标准logging统一格式/脱敏，不延长超时或绕过就绪门禁。

累计直接复制包`dist/traffic-analyzer-direct-copy-2026.10.19.2.tar.gz`复用2026.10.19-intranet.1相同镜像/依赖/迁移及此前诊断、共享内存和Console403修复，仅追加一处启动参数修改。按包内COPY_README停止两个应用，复制application及外层SHA256SUMS，已有app/current时同步当前副本，再start；保留生产.env、模型、视频和数据，不执行init-db。不能用于不同依赖/迁移基线的旧发布。

事故测绘抽帧不依赖这条检测器就绪握手，抽帧正常不能证明检测任务已启动。日志另有tracker.association超过35秒及CPU绘制/编码慢，修复就绪后仍须以新分段日志定位，不能据此声明吞吐恢复。验证见DEPLOYMENT_INTRANET_VALIDATION.md。

## 2026-10-19 跟踪慢阶段诊断与直接复制发布

用户明确选择同基线直接复制application目录，不要求执行prepare/apply升级器。当前直接复制版基于2026.10.19-intranet.1全量的相同镜像ID/依赖/迁移，累计就绪信号/共享内存清理/Console403修复及本次诊断，不包含生产.env、模型、视频。交付目录`traffic-analyzer-direct-copy-2026.10.19.1`中的application覆盖现场同名目录，配套SHA256SUMS覆盖发布根清单，停止后复制、再启动两个应用；不启动init-db、不构建/拉镜像。若已有app/current源码指针，按该目录README同步覆盖当前源码副本，避免仍运行旧挂载。原始完整包归档SHA保持不变。

现有中断栈位于Mahalanobis影子诊断的scipy.linalg.solve_triangular，可能是候选/轨迹规模、BLAS多线程调度、CPU限制或同机抢占；不能由中断位置认定单次solve就耗时81秒。相同ARM64镜像、2CPU受控工具容器中128轨迹×256候选、128次调用，默认约8.5ms/7进程线程、仅OPENBLAS_NUM_THREADS=1约2.7ms/1线程；未复现现场81秒，不将此合成观察作为现场根因或擅自改线程配置。

新增日志保持首轮/30秒采样和5秒未完成证据，不逐车刷屏：

- ASSOCIATION_CPU_ENV：NumPy/SciPy版本、匹配后端与有限CPU线程环境变量白名单；不输出全量环境。
- bytetrack.predict / distance / shadow_gate / shadow_row / mahalanobis_solve / assignment / kalman_update：轨迹/候选/矩阵规模、正在处理的行或求解维数、匹配后端/阈值。
- STAGE_BEGIN/WAIT/END：elapsed_ms墙钟与cpu_ms进程累计CPU消耗、cpu_threads进程全部线程数、cpu_allowed亲和CPU数、cpu_quota配额、nr_throttled/throttled_usec限流累计计数。cgroup-v1/不可读项明确unavailable；CPU计时包括同进程其他线程，内外嵌套阶段不可相加，cgroup计数可能含同容器其他worker，只能比较相邻样本的变化。
- 嵌套小阶段持续切换时仍报告超过5秒的父阶段；SIGTERM等中断的STAGE_END标为status=interrupted，不冒充正常完成。

现场复现一次后提供同一Pipeline日志中ASSOCIATION_CPU_ENV、bytetrack.*与STAGE_WAIT/END；判断slow shadow/solve、正式Kalman更新、矩阵分配或CPU限流，再进行单变量性能验证。没有修改跟踪算法、阈值、身份/地理质量门禁，也未关闭影子诊断。

## 2026-10-19 检测器就绪超时与共享内存清理

现场pipe-d0c6d2f2日志显示10:35 UTC已经执行show.mjpeg_encode，10:36:25 UTC先报`detector MJPEG server did not become ready within 120s`，随后Platform SIGTERM，才出现SystemExit143、returncode=-15与psm不存在警告。不能将被SIGTERM打断的scipy栈当作scipy先抛错，也不能据清理警告认定共享内存不足；该片段未包含首次MJPEG_READY日志。

已复现就绪识别缺陷：一次日志突发超过4000字符尾部容量时，执行器先截尾再查MJPEG_READY会漏掉实际标记，误等到超时。现在先在完整且已脱敏的输入中识别，再截取诊断尾部；仍须真实标记，不放宽120秒门禁。此机制与现场已有编码却超时吻合，完整现场起始日志尚不足以证明该次标记确实被截断。

同时修复Linux fork各worker独立资源跟踪器重复清理：父进程在fork前ensure_running，reader/tracker只close，show仍为唯一unlink者；不使用unregister补丁或屏蔽警告。已通过真实Linux ARM64 fork回归。

交付`2026.10.19-intranet.2-app-source`复用intranet.1的精确镜像ID、依赖和两套迁移；仅更新main_optimized.py、pipeline_executor.py及累计Console403入口，包含指南。按新源码包README执行prepare/apply；会重建Platform/Console，需在无运行任务时操作，不运行DDL、不修改私有env、模型/视频/数据库。

日志还显示tracker.association等待81.4秒、NPU OM执行504ms；处理吞吐仍需另行受控定位，修复就绪识别不代表该慢阶段已恢复。

## 2026-10-19 全量源码版Console静态文件403修复

现场报告8009前台403、Console日志无权限。本机在Linux文件系统强制静态目录700/文件600，复现旧入口启动/配置检查通过但Nginx worker读取index.html返回403。此前仅测试容器umask与打包权限，没有覆盖解压/复制后实际Linux文件权限被收紧。尚未取得现场具体文件/模式，不能以本机复现认定现场唯一原因。

入口现将公开HTML/JS/CSS复制到容器`/var/run/traffic-console/html`，目录755/文件644，由Nginx worker读取；宿主源码继续只读且不修改其权限。运行时配置单独可写，模板/生成文件权限、鉴权、CSP和日志脱敏保持。

把`traffic-analyzer-console-403-repair-2026.10.19.py`及同名`.sha256`放到2026.10.19全量包的解压目录，在该目录执行：

```sh
sha256sum -c traffic-analyzer-console-403-repair-2026.10.19.py.sha256
python3 traffic-analyzer-console-403-repair-2026.10.19.py
```

脚本需Python3.10+及Docker/Compose，复用包内升级器；验证已知旧入口哈希、完整应用清单及外层受影响项，备份三个小文件并同步内外SHA，检测中断/不同现场改动时拒绝覆盖。已启用源码版时同时更新当前版本与全量基线。只重建Console并逐一校验HTML/runtime/首屏资源；不运行迁移、不重启Platform/检测器、不修改.env/Compose/模型/视频/数据。重复执行可校验并重建；备份在`.console-403-backup-20261019`。脚本失败不会宣称恢复成功。

新源码后续封包自动包含修复；原5.2GiB全量归档保持原SHA，已有包使用此小修复即可。若修复后仍有403，须以实际Nginx拒读路径/宿主强制访问控制证据继续诊断，不能关闭SELinux或扩大数据目录权限。验证见DEPLOYMENT_INTRANET_VALIDATION.md。

## 2026-10-19 单节点Kafka预检超时排查

现场报告中，`kafka.authentication_and_metadata`在30秒总时限内超时，伴随
`37.12.14.66:9093`、`37.12.14.68:9093`连接失败；同节点宿主机CLI可列Topic。
此证据尚不能确认密码错误或Kafka集群故障。先在与预检相同的Platform服务网络中只读测试
全部配置broker的TCP连接，并核对实际生效的bootstrap、SASL_PLAINTEXT/PLAIN及凭据配置；
TCP通过后继续核对broker返回的advertised地址与CLI认证配置。宿主机成功不能替代容器验证，
列Topic也不证明业务Topic/Group ACL。当时根因与修复待容器侧结果确认，不能跳过启动门禁；后续已验证恢复见下文。

为避免反复切换内网，新增独立`deploy/intranet/diagnose_kafka.py`及
`deploy/intranet/KAFKA_DIAGNOSIS.md`：一次收集两侧TCP、逐broker/advertised认证元数据、
30/60秒检查、只读协调器查询、检测器客户端及Docker/防火墙证据，支持带原client.properties的
Java CLI对照。工具放发布目录之外，不覆盖受校验源码；仅创建/清理专属工具容器，不重启业务或修改连接配置。

2026-10-19 17:55现场报告`kafka-diagnosis-20261019-175526-d9935a`已确认一个明确阻断点：
宿主`37.12.14.85`的`net.ipv4.ip_forward=0`，Platform使用`172.28.0.0/16`桥接网络。
宿主连接`.67/.69:9093`约5至6毫秒成功，工具容器两地址TCP均3秒超时；未取得Kafka元数据，
不能据此判定SASL口令或业务ACL失败。先由现场管理员临时启用IP转发并复跑工具，成功后按主机制度持久化。
iptables三项返回4，说明规则未成功读取，不等于规则为空；nft输出为空不能排除legacy规则。
若转发启用后仍失败，继续核对实际防火墙后端、FORWARD与NAT，而不是清空规则或重启整机。
既有运行容器使用四个bootstrap且镜像ID与当前两地址工具容器不同，网络恢复后须核对部署版本/配置；
当时报告没有验证`.66/.68`的工具容器连接，没有执行Java CLI对照，尚未证明现场修复完成。

**现场已确认恢复（2026-10-19）：**用户直接把`/proc/sys/net/ipv4/ip_forward`写为1后确认问题解决。
原因是宿主机自己发起的CLI连接不需要跨接口转发，Docker桥接容器访问外部Kafka则需要；
该主机转发关闭导致容器TCP超时。此前KafkaConnectionError/NoBrokersAvailable属于此网络阻断的后续表现。
最初`sysctl -w`的“文件不存在”具体原因未确认，但`cat /proc/sys/net/ipv4/ip_forward`能读取0，
直接写该文件已成功；不能把前一个命令错误解释成内核不支持转发。

长期配置由现场运维在使用systemd的Linux宿主机保存：

```sh
printf 'net.ipv4.ip_forward = 1\n' | sudo tee /etc/sysctl.d/99-traffic-analyzer-forwarding.conf
cat /proc/sys/net/ipv4/ip_forward
```

当前运行值已由现场写为1，保存文件供`systemd-sysctl`开机加载，无需为此立即重启Docker/生产机。
运维须核对其他sysctl配置及安全加固/配置管理任务，避免之后再次写成0；同一参数受文件顺序及后续任务覆盖。
其他生产节点也核对该值，维护窗口重启后确认仍为1并复验容器Kafka连接。
开启全局转发时保留现有防火墙隔离与NAT策略。当前仅确认临时修复有效；关闭开关的来源、持久化安装及重启后验证尚未取得证据。

## 2026-10-19 全量源码基线与自行打包

新版 `2026.10.19-intranet.1` 全量交付包含ARM64离线镜像、宿主只读源码和Console资源，不包含模型/视频；首次即挂载 `application/app`，Platform/init-db使用同版代码及标准日志入口。复用同机PG与现有私有连接、ASSET_ROOT/DATA_ROOT；首次 `./docker-compose up -d` 显式执行canonical `20261019_0021`、Replay V2 `20261019_rv2_0005`迁移，不能向旧基线仅覆盖源码。
后续依赖/迁移不变时，基于本次镜像ID生成 `app-package`，prepare/apply后使用 `./app-compose` 管理应用。构建电脑从头制作全量包、源码包、生产解压部署和回退的完整命令见 [本地打包指南](RELEASE_PACKAGING_GUIDE.md)。现场验收独立于本机封包验证。

## 2026-10-19 首页登记视频图标不再随检测任务消失

生产关闭路网后，首页不能再依赖路口坐标快照定位登记视频。新版本由`/sources.recording_position`提供
配对素材遥测中的GCJ-02录制位置，离线标“素材位置”，任务结束保留最后/素材位置，不伪装成飞行中。
ROAD_FEATURES_ENABLED=false及MineMap配置不变，无有效GPS则不造点。
本次未发布现场包，验证与累计发布基线注意事项见`WORKBENCH_SOURCE_MARKERS_20261019.md`。

## 2026-10-19 测绘服务器来源全部失效修复

生产已挂视频且检测可播放时，还须区分来源缓存与测绘路径：旧seed可遗留首次缺素材的invalid，
旧测绘导入不能接受登记的`/app/test_videos/...`。修复后来源列表自动重检启用本地invalid/unknown记录，
seed重检已有记录但保留现场路径/配置/禁用开关；测绘把登记的固定容器目录转相对素材key并保留白名单。
已知遥测缺口仍degraded，不能强制批量改valid。缺素材或路径越界仍按真实错误处理。
本机415项Platform与41项部署回归通过，现场尚未更新；详见`SURVEY_PRODUCTION_SOURCES_20261019.md`。
当前累计源码的迁移基线须匹配现场，不能绕过ADR-041直接覆盖文件。

## 2026-10-18 宿主源码挂载与统一日志（2026.10.18-intranet.1）

本次应用源码升级包复用已导入的`2026.10.17-intranet.3-arm64` Platform和Console运行时镜像，包含完整后端源码及已构建的最新Console资源，不包含镜像、模型、视频或私有配置。宿主需要Python3.10+及Compose2.24.4+；无需pip安装或联网构建。本机macOS原生MPS启动方式不变。

将包和校验文件传到现场，解压后执行（`--deployment-root`指向现场原有`.env`及Compose所在目录）：

```sh
sha256sum -c traffic-analyzer-2026.10.18-intranet.1-app-source.tar.gz.sha256
tar -xzf traffic-analyzer-2026.10.18-intranet.1-app-source.tar.gz
cd traffic-analyzer-2026.10.18-intranet.1-app-source
python3 upgrade_source.py --deployment-root /data2/drone/traffic-analyzer prepare
python3 upgrade_source.py --deployment-root /data2/drone/traffic-analyzer apply
```

`prepare`核验源码SHA、精确运行时镜像ID/架构、两套迁移文件及依赖基线，并在已有镜像中检查语法、导入与数据库版本；不执行NPU推理、不停服务、不执行DDL。
`apply`先完成准备，再停止Platform/Console及其检测任务，执行真实模型与连接预检，随后强制重建这两个服务并等待健康；失败恢复上一版应用配置。数据库服务、原`.env`/`.env.hg`、模型、视频及业务数据目录不变。请在可中断任务的维护窗口执行；这不是任务无中断热更新。

源码保留在原部署目录`app/releases/<版本>/app`并只读挂到容器`/app`；Platform与init-db使用同一版完整源码。Console的html、Nginx模板和启动配置脚本也从该版宿主目录只读挂载，生成的`runtime-config.js`保存在容器`/var/run/traffic-console`，避免只读目录写入或旧静态目录权限造成403。

启用后在原部署目录使用新入口，原`./docker-compose`保留为旧镜像启动入口，不用于管理源码版：

```sh
./app-compose ps
./app-compose logs --tail 200 platform console2
./app-compose up -d
python3 app/upgrade_source.py --deployment-root "$PWD" rollback
```

Python应用统一使用标准库`logging`，格式包含时间、级别、PID、Pipeline标识、logger名称；日志按职责分流并保留stdout/stderr以供`docker logs`或采集器读取：

| 宿主路径（以原`.env`的DATA_ROOT为准） | 内容 |
| --- | --- |
| `DATA_ROOT/logs/platform.log` | Platform/Uvicorn应用、启动、接口及异常日志 |
| `DATA_ROOT/logs/pipelines/<pipeline_id>.log` | 检测器及三个worker完整输出、启动/退出、阶段耗时和异常堆栈 |
| `DATA_ROOT/logs/containers/` | 容器启动、预检、init-db和源码检查输出 |
| `DATA_ROOT/logs/deployment/source-upgrade.log` | 源码准备、切换与恢复过程 |
| `DATA_ROOT/logs/nginx/` | Console启动、访问及错误日志 |

Python文件按20MiB轮转并保留5份备份；Nginx每30秒检查大小并轮转，单次高流量可能短暂超过20MiB；Docker stdout也采用20MB、6文件限制。检测器每个Pipeline分别保留日志，历史任务越多总体占用越大，应按现场日志保留制度归档清理。受管日志按私有权限保存；Python输出过滤凭据，Nginx访问日志不记query，错误输出过滤常见query凭据及URL用户密码。

慢帧排查先在当前Pipeline日志找`STAGE_BEGIN`、`STAGE_WAIT`、`STAGE_END`：阶段超过5秒首次报告等待，随后约30秒一次；正常阶段只按低频采样，避免逐帧刷屏。`ascend.om_load`/`ascend.om_execute`/`ascend.cpu_nms`区分模型加载、设备执行和CPU后处理，`tracker.kafka_archive`定位统计/归档，`queue.detect.put`/`queue.track.put`定位下游反压。`PIPELINE_LAUNCH`后没有worker启动记录时重点检查解释器/依赖导入。

后续业务代码、日志、前端功能可按相同流程仅传新源码包；Python/原生依赖、数据库迁移、OM或CANN/驱动变化需要相应运行时/数据库/模型升级，工具拒绝用源码包跨越这些边界。本次未修改生产推理参数，也没有证明NPU资源争抢已经解决。

## 2026-10-18 BEV自动降级（用户最新要求，尚未部署）

BEV不再展示地图错误或要求手动重试。SDK加载、瓦片资源或地图操作异常时自动切为本地深色网格与实时轨迹：GCJ-02路径仅为显示做北向上局部投影；缺少地理路径时使用真实像素路径；无路径则等待实时轨迹。后续轨迹更新、候选虚线与选中样式继续，不自动转公网地图，不变更canonical坐标或业务质量门禁。异常地图实例清理后保持本地视图，避免反复重试影响检测页面。
本次只是源码，旧离线镜像不自动更新；生产卡顿诊断工具仍适用。

## 2026-10-18 BEV与慢帧排查（历史阶段：错误提示已被上述降级替代）

BEV此前任意地图SDK error都会销毁整图；当前源码保留地图与轨迹更新并显示底图资源错误，加载/构造失败仍显示服务不可用。已复核官方MineMap2.1.0的基础线/端点覆盖物API，但未访问现场内网资源，不能据此确认具体失败瓦片或鉴权原因。
FPS此前只保留两秒内帧，处理间隔超过两秒便返回0，且用帧数而非间隔数导致高估。当前源码改为monotonic、保留跨窗口间隔及三位小数，前端小于0.1时显示三位。修正显示不等于修复吞吐；未调整NPU模型/业务门禁/本机MPS。

无需查看日志：将本次单文件diagnose-live-2026.10.18.2.py放在现有生产发布目录，检测运行时执行：

```sh
./docker-compose exec -T platform python3 - < diagnose-live-2026.10.18.2.py > live-diagnosis.json
```

通常10至30秒，输出工具本身采集结果，不要求读已有日志、不需要重启。检查detector_video的frames_received/distinct_frames、kafka_records_added_during_video_sample、statistics_age_seconds、statistics.inference_ms与pipeline_processing_ms。直接视频持续收包但画面相同，说明MJPEG连接活着；静止画面也可能相同，不能单独认定检测死锁。Kafka无新增需进一步定位管道；Kafka有新增而DB/页面停滞需定位消费/写库/WS；内部画面更新正常而浏览器慢需查代理/网络。
脚本只读、无业务消费组、不提交offset，不输出秘密和原始JPEG。生产几分钟一帧的根因仍未确认，不能靠降低检测分辨率或跳offset替代诊断。现有2026.10.18.4等镜像归档不包含本次源码改动。

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

## 2026-10-18 Console离线补充包

`traffic-analyzer-console-fix-2026.10.18.2.tar.gz`适用于已部署的2026.10.17完整包：仅重建Console静态目录及入口脚本挂载、补充只读诊断，不更换数据库/Platform镜像或生产.env，不停检测器。
修复MineMap后加载CSS覆盖定位造成画布高度0，以及生产浏览器直连容器localhost MJPEG被拦截/无法路由的问题；生产画面改走同源`/api/v1/video/camera/{camera_id}`，保留HttpOnly媒体会话鉴权，Mac开发仍直连。
应用脚本先核对原Compose SHA，备份Compose/SHA256SUMS后只改Console配置并重建该服务；修改过但未更新SHA的现场Compose会拒绝覆盖。

公网服务可显式配置`MINEMAP_SDK_BASE_URL`、`MINEMAP_SERVICE_URL`、`MINEMAP_SERVER_DOMAIN`、`MINEMAP_STYLE_URL`；空值沿用现场内网2.1.0默认，不自动切公网。
本机公网验证使用官方服务及方案11001，不将其写入生产配置；原生产17000的实际服务参数仍须现场核对。Map Key只保存在原私有.env/运行时文件。
现场指标缺FPS时使用`deploy/intranet/diagnose_live.py`对照Kafka统计与DB样本；先读取日志，不能靠重建页面、清库或跳offset掩盖消费失败。工具命令见CHECK_TOOLS.md。

应用版本：**2026.10.17-intranet.3**。目标：Linux aarch64/ARM64、Ascend 310P3、CANN9.0.0、Docker Compose≥2.24.4。完整离线包含数据库、Platform、Console与模型转换工具四个ARM64镜像，无需操作旧包或旧补丁。

## 当前：同机临时数据库

经用户授权，现场HG扩展问题解决前，生产无人机数据暂写同机Docker PostgreSQL17.10 + PostGIS3.6.4 + TimescaleDB2.28.2。
仍使用`ycx_prod.drone`与sysdba，私有口令在主`.env`；DB_HOST=road9（Compose服务名），DB_PORT=5432，DB_TIMESCALE_REQUIRED=true。
`ROAD_FEATURES_ENABLED=false`保持；外部路网/路况仍只读内网Doris，不转入临时库。本机原生road9/MPS配置不变。

根Compose加`deploy/intranet/compose.yaml`和`compose.postgres.yaml`生成发布四服务：`road9`、`init-db`、`platform`、`console2`。
首次运行`./docker-compose up -d`自动导入离线镜像、准备独立模型资源，启动数据库并等待两扩展健康，再执行预检、一次性迁移和应用启动。
数据库初始化创建应用库/schema及两扩展；已有数据目录不会重建或清空。数据库不映射宿主机端口，数据保存在主`.env`的`DATA_ROOT/postgres`，更换解压目录时须保留同一DATA_ROOT。
不要把旧HG的物理数据目录挂入此容器，也不要覆盖已有非本版本PG目录。新建目录由数据库入口初始化，不能用于原地升级PG大版本。

Timescale恢复六张应用超表；V2样本沿用7天压缩/90天保留策略，超期数据可能被自动清理。核心PostGIS几何/坐标转换/GiST已实测；不包含项目未使用的raster/GDAL、SFCGAL。
数据库基础镜像digest、PostGIS源码SHA和来源见`deploy/intranet/database/base-image.json`。现场不编译、不联网下载。

```sh
./docker-compose up -d
./docker-compose ps
sh deploy/intranet/backup-db.sh
```

完整检查工具见`deploy/intranet/CHECK_TOOLS.md`，备份及HG切换说明见`deploy/intranet/HIGHGO_CUTOVER.md`。
HG原连接完整保留于600权限`.env.hg`，外部三服务拓扑为`docker-compose.hg.yaml`。**切回HG须停写、备份、完成兼容性验证和数据迁移对账；仅换连接不会带走临时库数据。** 不自动连接或修改HG。
Doris内网37.12.11.127:9030/ycx_xc、Kafka、MineMap及16源/7无人机配置均保留；独立模型与视频包继续复用。

本机已验证新数据库、重复迁移、真实业务写读、空间/时序、重启持久化和同版本完整备份恢复；生产SSH、内网网络及NPU实机仍待现场验收。
生产为单机数据库，无HA；备份应另存受控位置，容量与恢复目标另行验收。完整结果见[验证报告](DEPLOYMENT_INTRANET_VALIDATION.md)。

以下旧版本段落为历史，其外部HG启动、Timescale可选及三服务描述不适用于本版主配置。

## 历史：2026.10.17-intranet.2 生产配置

本版完整包含所有既有修复与检查工具，不需要操作intranet.1或任何旧补丁。
生产瀚高仍为 `37.12.14.133:5866`，账号改为 `sysdba`，数据库 `ycx_prod`，schema `drone`。
完整口令仅写入私有包根`.env`的`ROAD9_PASSWORD`（根Compose将其传为`DB_PASSWORD`），权限600；文档不记录口令。
Doris继续使用生产内网 `37.12.11.127:9030/ycx_xc`；Kafka、MineMap、JWT及管理员密码保持原值。

预检、权限、版本表及初始化以`.env`配置的库/schema核对实际会话，不再写死旧目标。
依然拒绝生产指向本机road9、public或系统schema；不自动建生产库/schema、不安装扩展、不迁移旧库数据。
DBA须预备`ycx_prod`中的`drone`并向sysdba提供应用迁移/读写所需权限。
若需要DBA准备schema，可在正确数据库中执行 `CREATE SCHEMA IF NOT EXISTS drone AUTHORIZATION sysdba;`。

包内 `deploy/intranet/CHECK_TOOLS.md` 列出完整校验、镜像导入、资源准备、分项连接/驱动/NPU预检、初始化、
状态/日志及Kafka ACL清单命令；附 `db_readonly_checks.sql` 供DBA只读核验。
根目录执行 `./docker-compose up -d` 即可；原独立模型/视频包复用，现场资源与数据目录保持。
下方带旧版本号的目标及校验记录仅作历史，不覆盖本节。

## 新包直接部署

本版本为包含全部当前修复的新镜像包，先将已有独立模型包和视频资源放在约定位置，解压后进入新目录执行：

```sh
./docker-compose up -d
```

当前根`.env`已填入同机临时数据库、生产内网Doris、Kafka、MineMap及资源目录，权限600。不要再执行下面的历史补丁。
现有现场若修改过资源/数据目录，升级时保留现场`.env`中对应实际值；旧包及业务资源保留。
本机公网验证不代表内网Doris或昇腾实机已验收。

## 历史现场：2026-10-17旧包累计修复（新包无需执行）

现场目录为 `/data2/drone/traffic-analyzer`，继续使用现有 ARM64 镜像及独立资源。
拷入 `traffic-analyzer-repair-degraded-2026.10.17.sh` 后只需执行：

```sh
sh /data2/drone/traffic-analyzer/traffic-analyzer-repair-degraded-2026.10.17.sh
```

脚本包含前次 Compose/瀚高/诊断修复、离线 PyMySQL 和重新构建的 Console 文件；不拉镜像、
不安装网络依赖。备份后更新源码只读挂载和 Console 静态文件挂载，累计维护 SHA256SUMS。
根 `.env` 保持 600：保留 DB/Kafka 密码、Key、`ASSET_ROOT`（包括现场 `../traffic-analyzer-asserts`）
和数据路径；将三个已授权开关设为 `ROAD_FEATURES_ENABLED=false`、
`DB_TIMESCALE_REQUIRED=false`、`YCX_METRICS_BACKEND=doris`，仅补缺 Doris 连接项。
新连接来自“指标产出分析”的 MySQL 通道（默认 9030），数据库名采用其配置 `ycx_xc`；
真实两张指标表的位置/权限未在内网实查，若不同修改 `.env` 的 `DORIS_DATABASE`。
脚本内嵌私有连接值，按私有文件传输，不提交 Git、不公开转发。

- 路网标注/导入 API、自动标注任务和运行时匹配关闭；不加载路网包、不运行车道模型、
  车道分析及自动车道推断。Console 隐藏“平台治理”一级入口与标定入口，旧标定/项目链接显示已关闭；
  系统设置图标保留。MineMap底图、视频检测/跟踪、独立遥测世界投影、统计、告警和回放保留。
- PostGIS 和 `road11.dim_data_version` 不作为平台启动条件，路网关闭时直接跳过。
  将来恢复路网时：缺空间函数则暂停导入/空间图层；缺版本表可显式传入 `road_data_version`
  或配置已确认的 `YCX_ROAD_VERSION`。不猜测 MAX(version)、不创建空的外部表、不伪造几何。
- 两张 `dws_inter_*_5min_mm` 指标表只从 Doris 查询，不再去瀚高找。Doris不可用仅警告；
  典型态势地图层随当前路网功能一起关闭，不以零值或 mock 冒充数据。
- TimescaleDB 未启用时使用现有普通 PostgreSQL 表路径，真实迁移、幂等写入、历史读取继续；
  `/ready` 可为 ready，同时 `services.timescaledb=degraded`。**没有超表分块、压缩和自动保留策略，
  需要监控容量并备份；不能把该模式声称为 Timescale 已验收。**
- DBA之后在 xinchan 启用匹配扩展后，备份并在维护窗口执行
  `docker compose run --rm --no-deps init-db`。显式初始化将现有数据原地转为六张超表并校验；
  V2样本恢复7天压缩/90天保留策略，超过保留期的数据可能被策略清理。不要重置迁移版本或删表。
  转换可能持锁。扩展已经安装但 API/权限不兼容时仍报真实错误并回滚DDL，不吞掉错误。

应用库连接/schema/权限/迁移、Kafka认证及模型/设备仍为启动门禁。修复脚本自动完成预检、
初始化和重建服务；结果统一落在本机 `highgo-repair-report.*`。原始镜像/模型/视频归档不改写。

## 1. 解压和启动

将以下文件拷到生产机同一目录，例如`/opt/releases/`：

- `traffic-analyzer-2026.10.16-intranet.4-linux-arm64.tar.gz`及其`.sha256`：**私有应用部署包，含已填连接信息的`.env`**。
- `traffic-analyzer-models-2026.10.15-intranet.4-ascend310p3.tar.gz`：独立模型资源包，继续复用。三档OM已在ARM64 CANN9.0.0中解析成功，未嵌入主机共享库；首次启动仍强制执行310P3实际推理预检。
- 实际视频与同目录SRT/JSON遥测文件，另行拷贝。

确认第2节的主机、数据库和网络条件已具备后执行：

```sh
cd /opt/releases
sha256sum -c traffic-analyzer-2026.10.16-intranet.4-linux-arm64.tar.gz.sha256
tar -xzf traffic-analyzer-2026.10.16-intranet.4-linux-arm64.tar.gz
cd traffic-analyzer-2026.10.16-intranet.4-linux-arm64
./docker-compose up -d
```

随包`./docker-compose`先校验文件、检查设备、导入缺失的离线镜像、校验并导入独立模型包、生成明确的访问IP白名单、执行外部连接与三档模型检查；随后调用系统Compose，先运行一次性`init-db`，成功后启动两个常驻服务`platform`、`console2`。命令等待服务健康；失败返回非零，不报告启动成功。

浏览器打开 **`http://生产IP:8009`**，账号`admin`，初始密码见根目录`.env`的`BOOTSTRAP_ADMIN_PASSWORD`。首次登录后修改密码。已有管理员不会被重复初始化覆盖。

**系统原生Compose无法自动导入tar镜像。** 首次使用上述带`./`的入口；准备完成后，原生`docker compose up -d`或已安装的V2 `docker-compose up -d`均可读取根目录同一份Compose和`.env`。不要在隔离现场加`--build`或执行`pull`。旧版Python Compose V1不支持本包。

现场使用系统已安装的Compose **2.24.7**；交付包不附带Compose二进制。`./docker-compose`为本项目的离线启动脚本，调用系统工具。配置读取使用已导入Platform镜像中的Python标准库，在无网络、无数据挂载的一次性工具容器内完成，仅传入访问来源和资源目录六项参数，不启动Platform服务。

默认资源及数据目录在解压目录的上一级，后续更换版本不会删数据：

```text
/opt/releases/
├── traffic-analyzer-2026.10.16-intranet.4-linux-arm64/
│   ├── .env                         # 私有现场配置，600权限
│   ├── docker-compose.yaml          # 从根Compose+覆盖配置生成
│   ├── docker-compose               # 首次离线启动入口
│   └── images/runtime.tar           # Platform、Console、离线模型转换工具
├── traffic-analyzer-models-2026.10.15-intranet.4-ascend310p3.tar.gz
├── traffic-analyzer-assets/
│   ├── weights/                     # 启动入口从模型包校验并导入
│   └── videos/                      # 拷贝视频及匹配的SRT/JSON
└── traffic-analyzer-data/
    ├── hls/                         # 输出
    ├── output/
    ├── spool/                       # Kafka持久化重试
    ├── calibration/
    ├── survey/                      # 上传、勘察及证据
    ├── trajectory-archive/
    └── logs/
```

当前16个视频源、7台测试无人机已列入初始化，保留源ID、默认选择、遥测格式及时间偏移。仅在目标记录缺失时插入，不覆盖现场同ID记录，不导入任务/告警/轨迹历史。视频未拷齐时源据实标为不可用；拷齐后在控制台重新验证视频源。

另附`traffic-analyzer-videos-2026.10.16-test-sources.tar`及SHA，包含这16个配置引用的29个文件（约49.6GB，部分源共用文件），大文件不进入应用包。保留视频归档和解压文件合计约100GB，另留镜像与业务数据空间。启动前可这样导入：

```sh
mkdir -p ../traffic-analyzer-assets/videos
(cd .. && sha256sum -c traffic-analyzer-videos-2026.10.16-test-sources.tar.sha256)
tar -xf ../traffic-analyzer-videos-2026.10.16-test-sources.tar -C ../traffic-analyzer-assets/videos
(cd ../traffic-analyzer-assets/videos && sha256sum -c ../../traffic-analyzer-2026.10.16-intranet.4-linux-arm64/deploy/intranet/VIDEO_SHA256SUMS)
```

也可按`deploy/intranet/VIDEO_FILES.txt`从现有test_videos逐文件复制，保留相对目录。视频可在启动前自行创建`../traffic-analyzer-assets/videos`并拷入，也可启动后拷入。任务中填写**容器内路径**`/app/test_videos/文件名.mp4`，不填Mac路径。`weights`和输入视频挂载只读；数据目录可写。已有非空但不完整的weights目录会拒绝自动覆盖，避免破坏现场资源。

若启动提示“weights目录已有不完整资源”，表示`${ASSET_ROOT}/weights/ascend/manifest.json`未找到，但weights已有内容；不能据此认定现有权重损坏。正确结构为`ASSET_ROOT/weights/ascend/manifest.json`及同目录640/960/1280三档OM，源PT在`ASSET_ROOT/weights/`。不要把模型资源包外层目录放在weights里面，也不要省略ascend子目录。

先确认完整独立模型包`traffic-analyzer-models-2026.10.15-intranet.4-ascend310p3.tar.gz`在部署解压目录或上一级。已有文件保留为独立备份，再让入口重新校验导入；无需更新镜像或关闭校验。现场用户提供的`ASSET_ROOT=../traffic-analyzer-asserts`按原拼写使用；在部署解压目录执行：

```sh
model=traffic-analyzer-models-2026.10.15-intranet.4-ascend310p3.tar.gz
if [ -f "$model" ] || [ -f "../$model" ]; then
    backup=$(mktemp -d ../traffic-analyzer-asserts/weights-backup.XXXXXX) &&
    mv -- ../traffic-analyzer-asserts/weights "$backup/weights" &&
    ./docker-compose up -d
else
    echo "请先拷贝完整模型包：$model"
fi
```

上述路径只适用于该现场配置，其他现场应按`.env`的ASSET_ROOT替换。备份完整保留原weights，视频目录不移动；导入失败时保留备份并检查提示，不删除原资源。若模型包SHA不符需重新拷贝完整模型归档。已验证临时夹具中非空目录拒绝覆盖、备份后校验导入、原文件保留及重复准备；现场目录清单尚未提供，原文件具体缺少什么仍待核对。


## 2. 主机、数据库和网络准备

宿主机须安装配套310P3驱动/固件，`npu-smi info`正常；设备默认`/dev/davinci0`及`davinci_manager`、`devmm_svm`、`hisi_hdc`存在，驱动目录`/usr/local/Ascend/driver`和`/etc/ascend_install.info`可读。容器固定CANN9.0.0，不自动升级宿主机驱动。驱动/固件配套及实机性能须现场核验。

应用只使用一个入口：

```text
浏览器 http://生产IP:8009 → Console2（内置静态服务及API/WS/媒体代理）
                            → platform:8000 → 310P3检测子进程
                                            → 瀚高ycx_prod.drone / Kafka / Doris路网与路况
```

已去掉独立Nginx容器；Console镜像内保留已有轻量Nginx提供SPA与反向代理。Platform不直接发布宿主机端口；API、WebSocket、MJPEG、HLS和上传统一经8009，继续执行登录与媒体鉴权。持久化轨迹、证据与spool不因容器重建删除。

网络需放行：

| 来源 | 目标 | 用途 |
|---|---|---|
| 操作员浏览器 | 生产机8009 | 控制台/API/媒体 |
| 生产容器出口 | 37.12.14.133:5866 | 瀚高SM3认证、UAV应用数据 |
| 生产容器出口 | 37.12.11.127:9030 | Doris路网及路况只读查询（沿用既有内网连接） |
| 生产容器出口 | 37.12.14.66—69:9093 | Kafka SASL_PLAINTEXT/PLAIN；包括advertised地址 |
| 操作员浏览器 | 37.8.188.98:21009 | MineMap SDK、样式、瓦片、字形和精灵 |

HTTP与SASL_PLAINTEXT不提供传输加密，本次部署限定在指定隔离内网。CORS保留明确来源；不设置通配符，不取消JWT/HttpOnly或视频权限。

### DBA预备

应用目标：`37.12.14.133:5866 / ycx_prod / drone`。DBA先在`ycx_prod`准备应用schema；TimescaleDB按上述生产可选模式处理，再运行启动命令。角色名以实际分配为准：

```sql
CREATE SCHEMA IF NOT EXISTS drone AUTHORIZATION sysdba;
CREATE EXTENSION IF NOT EXISTS timescaledb;
SELECT current_database(), version();
SELECT extversion FROM pg_extension WHERE extname='timescaledb';
SELECT has_schema_privilege('sysdba','drone','USAGE'),
       has_schema_privilege('sysdba','drone','CREATE');
```

迁移账号须可在`drone`创建/修改表、索引、函数、触发器和序列；扩展支持`create_hypertable(..., by_range(...))`接口。应用不自动建库、不安装扩展、不导入本地历史数据。

`init-db`一次性容器执行基础及Replay V2迁移并在账号缺失时创建管理员。常驻Platform为`DB_AUTO_MIGRATE=false`，只校验版本；Docker重启不会自动迁移。若现场必须分离迁移与运行账号，先使用DDL账号依次执行`./docker-compose load`、`./docker-compose prepare`、`./docker-compose run --rm --no-deps init-db`，随后更换根`.env`为运行账号，DBA授予对象及默认读写权限后启动。

YCX使用同一瀚高database=xinchan、路网schema=road11，严格只读。本次路网功能关闭，不要求PostGIS/版本表可用。两张典型指标表实际在Doris，由DORIS_MYSQL_*与DORIS_DATABASE配置；YCX_METRICS_SCHEMA只保留本地原有PostgreSQL读模型使用。

### Kafka

根`.env`已按附件填9093集群及SASL/PLAIN凭据，不降级无认证端口。检测统计、TCC证据、执法线索发布和平台消费者共用认证配置。每个实际SourceProfile `source_key`的Topic权限如下：

| Topic | 权限 |
|---|---|
| `uav_replay_v2_statistics_{source_key}` | Write / Read / Describe |
| `uav_replay_v2_track_complete_{source_key}` | Write / Read / Describe |
| `uav_replay_v2_conflicts_{source_key}` | Write / Read / Describe |
| `uav_replay_v2_telemetry_{source_key}` | Write / Read / Describe |
| `uav_replay_v2_mission_{source_key}` | Write / Read / Describe |
| `uav_replay_v2_enforcement_clues_{source_key}` | Write / Describe；当前消费者不订阅候选线索Topic |
| 消费者组`uav-platform-replay-v2` | Read / Describe |

当前16个视频源的96个具体Topic及消费者组权限已列在`deploy/intranet/TEST_SOURCE_TOPIC_ACL.json`。运维预建Topic并确定分区、副本和保留期；如需清单，可在有Python的运维电脑执行随包`python3 deploy/intranet/topic_acl.py --source-key 实际源ID`。预检验证认证与元数据访问，生产读写ACL和断连恢复仍需真实任务验收。

## 3. 根目录.env配置

本次私有包已填数据库、Kafka、YCX路网、内网MineMap Key，并生成独立JWT密钥及管理员初始密码。**本包按私有配置传输、存储；不要上传公共仓库或转发日志中的配置输出。** `.env`权限600，镜像及源码包不包含秘密，原开发`.env`不改动。

| 参数 | 说明 |
|---|---|
| `DB_HOST/PORT/NAME/SCHEMA/USER` | 应用瀚高目标，固定xinchan.ycx_drone |
| `ROAD9_PASSWORD` | 为复用根Compose沿用变量名，实际是本次xinchan密码；不启动road9容器 |
| `KAFKA_BOOTSTRAP / KAFKA_SASL_*` | 9093认证集群 |
| `YCX_DB_* / YCX_ROAD_VERSION` | 瀚高road11只读；路网关闭时不使用 |
| `DORIS_MYSQL_* / DORIS_DATABASE` | Doris MySQL通道和指标库，均为可选读取 |
| `ROAD_FEATURES_ENABLED / DB_TIMESCALE_REQUIRED` | 当前生产均false；本地代码默认true |
| `MINEMAP_DOMAIN / SOLUTION / KEY` | 内网21009、17000及已确认可复用的Key |
| `PUBLIC_HOST / CORS_ORIGINS` | 初始auto；入口按到DB的路由源IP生成明确JSON白名单 |
| `CONSOLE_PORT` | 默认8009 |
| `ASSET_ROOT / DATA_ROOT` | 默认解压目录的上一级独立目录，可改绝对路径 |
| `ASCEND_DAVINCI_DEVICE / ASCEND_DEVICE_ID` | 设备节点及ACL逻辑设备号，默认0 |
| `BOOTSTRAP_ADMIN_PASSWORD / JWT_SECRET_KEY` | 初始管理员密码及签名密钥，跨升级保留JWT |

多网卡/NAT/域名访问时，首次启动前将`PUBLIC_HOST`填为浏览器实际访问IP/域名，保留`CORS_ORIGINS=auto`；程序不会猜测外部NAT地址。也可显式填JSON列表，例如`CORS_ORIGINS='["http://37.x.x.x:8009"]'`。首次生成后不会反复改写已有白名单。改端口或访问地址时同步修改白名单。

配置按Docker dotenv语法读取，不执行`source .env`。包含美元符、引号或反斜杠的密码由封包工具处理转义，避免手工去掉转义字符。`.env`是允许修改文件，不列入内部SHA256SUMS；外层归档校验保护最初交付副本，其他文件保持校验。

## 4. 内网地图

生产固定MineMap：`http://37.8.188.98:21009`、方案`17000`、SDK/CSS路径`/minemapapi/v2.1.0/`。Key已写私有`.env`，用户确认与参考服务可复用。所有地图页面共用SDK的`minemap.key`及覆盖物适配，GCJ-02不重复转换；生产不加载公网高德或公网地图回退。

Console按地图origin生成CSP；修改配置后重建Console容器（无需构建镜像）：

```sh
./docker-compose up -d
```

浏览器必须能访问21009；地图端应允许实际8009来源及Key访问17000。现场在浏览器Network核对SDK/CSS、`/service/solu/style/id/17000`、瓦片、字形、精灵均走内网，地图服务样式不得残留公网资源。检查点位、单击进入监控、轨迹、回放、车道及正射影像叠加。无实时路况/卫星资源时据实显示，不伪造图层。

参考项目`vue_frontend`与私有`prod.env`已用于真实参考方案12878验证：样式和瓦片加载、1661个视口要素、点位点击通过；**本机无法访问生产内网21009，生产17000授权和空间对齐待现场验收**。参考配置仅取地图字段，不覆盖本次数据库配置。

## 5. 验收和日常操作

```sh
./docker-compose ps -a
./docker-compose logs --tail 200 init-db platform console2
curl --fail http://127.0.0.1:8009/ready
./docker-compose check             # 重做只读连接/设备/模型检查
./docker-compose down              # 停止，保留持久化数据
./docker-compose up -d             # 再次启动
```

`init-db`正常状态为Exited(0)，Platform和Console均应healthy。`check`会执行三档OM空图推理、厂商库加载、瀚高/TimescaleDB、YCX只读查询和Kafka认证元数据检查；不迁移、不发布业务消息。失败不静默改用CPU。可用`./docker-compose prepare`单独准备资源和访问来源（需先用`./docker-compose load`导入镜像），`./docker-compose load`只导入镜像，`./docker-compose verify`核对不可变交付文件。

通过预检后仍须用真实视频/SRT创建任务，验证登录与上传、检测、消息落库后广播、WS、视频权限、MJPEG/HLS、统计与轨迹回放、自然EOF、主动停止、告警证据和spool断连重放。没有冲突时接受真实空态，不造事件。断开公网后再跑完整任务。310P3对相同输入比较转换前后框/类别/空检测，记录三档吞吐、内存、差异；无批准真值时IDF1/HOTA、正式ID switch、位置RMSE及速度MAE为`not_evaluated`。

## 6. 备份、升级和应用回滚

备份`xinchan.ycx_drone`及DATA_ROOT中的证据、标定、归档和spool，记录应用版本、迁移版本、模型哈希。使用配套瀚高/TimescaleDB备份恢复流程；不以开发库覆盖生产，spool和archive不可当缓存删除。

升级前停止新任务，等待任务结束及spool排空，保留旧包与数据库/数据目录备份。停止旧版本`./docker-compose down`，解压新包，**将现有`.env`复制到新目录并保留原密码/JWT/目录/Compose project，只更新两个IMAGE值为新包`.env.example`中的标签**，然后`./docker-compose up -d`。资源清单变化时先准备对应独立模型包，不覆盖在用资源。

仅回滚应用时，停止当前容器，保留当前现场`.env`，将PLATFORM_IMAGE与CONSOLE_IMAGE改为已导入且兼容当前schema的旧版本标签，再用原生`docker compose up -d --no-deps --no-build --pull never platform console2`启动（跳过init-db）。包入口校验固定发布镜像ID，改为旧标签后不使用其自动导入流程。**不会自动执行database downgrade或删除数据**；旧应用版本检查拒绝时停止回滚，按已确认的数据库恢复方案处理。

## 7. 故障定位

| 现象 | 检查 |
|---|---|
| 缺少模型包/模型哈希不符 | 独立资源包是否在解压目录或上一级；完整权重目录是否匹配MODEL_SHA256SUMS；不会自动下载 |
| 缺少设备/ACL初始化失败 | aarch64主机、310P3驱动固件、CANN9.0.0、设备号/映射和内存 |
| 认证方式13不支持 | 是否加载镜像中/opt/highgo/lib厂商libpq；不能替换成标准二进制libpq |
| DB连接失败 | 白名单/NAT出口、5866、凭据、SSL设置及SM3支持；预检不输出带密码DSN |
| 初始化失败/版本不一致 | DBA是否预建schema/TimescaleDB、DDL权限；查看init-db日志，不手改版本表 |
| Kafka bootstrap可达仍失败 | SASL账号、Topic/Group ACL、advertised地址和9093可达性 |
| 访问IP识别不对 | 设置PUBLIC_HOST并把CORS_ORIGINS重新设auto，或手工填明确JSON列表 |
| 登录后媒体无权限 | 同源8009、HTTP Cookie、实际Origin；不移除鉴权 |
| 地图空白 | 浏览器到21009、Key/17000授权、CORS、CSP以及样式的外域引用 |
| 原生Compose找不到镜像 | 首次使用./docker-compose up -d，或先./docker-compose load；禁止联网pull |
| `unknown flag: --environment` | intranet.4原始启动脚本误用了现场Compose不支持的参数。将`traffic-analyzer-compose-hotfix-2026.10.16.tar.gz`拷入已解压的部署目录，按下方命令应用小补丁。继续使用系统Compose 2.24.7，复用已导入的镜像。 |
| `service.platform.devices.0 must be a string` | 旧发布生成器保留了新版Compose规范化后的设备对象，现场Compose只接受字符串。将发布根Compose的platform.devices改为`源路径:目标路径:rwm`字符串列表，保留ASCEND_DAVINCI_DEVICE变量。生成器已修复；既有归档不会自动更新，正式替换文件须同步发布SHA256SUMS，否则包入口校验会拒绝启动。先用`docker compose config -q`验证。 |

intranet.4原始包的Compose兼容性补丁，在**已解压的部署目录**执行：

```sh
sha256sum -c traffic-analyzer-compose-hotfix-2026.10.16.tar.gz.sha256
tar -xzf traffic-analyzer-compose-hotfix-2026.10.16.tar.gz
sh traffic-analyzer-compose-hotfix-2026.10.16/apply.sh "$PWD"
./docker-compose up -d
```

补丁核对原发布脚本或已修复脚本的SHA，备份脚本与清单，替换`deploy/intranet/compose-bootstrap.sh`、转换根Compose的设备映射格式并补齐PIPELINE_IMGSZ默认值，更新对应两行校验值；现场`.env`、镜像和持久化数据保留。自定义设备路径及其他Compose配置保留；转换由已导入的固定ARM64镜像执行，无网络和目录挂载。未知脚本修改、补丁损坏或未记录的Compose修改时拒绝覆盖。原始大归档保持封存，首次部署此原始包也应先应用本补丁。

遇到旧镜像仅显示`Preflight failed (AssertionError)`时，先定位调用栈，不关闭断言、不跳过预检。Ultralytics把配置写到/tmp的提示本身不能确定失败原因。新诊断脚本按libraries、模型清单/源哈希、设备/模型加载、640/960/1280推理、数据库/schema、YCX只读查询、Kafka认证逐步报告；异常仅输出类型及代码文件/行号/函数，不输出异常文本、源码行或局部变量，以免泄漏DSN/密码。

既有镜像可使用独立文件`traffic-analyzer-preflight-diagnostic-2026.10.16.py`及SHA，无需更换镜像。将文件放入部署目录后运行：

```sh
sha256sum -c traffic-analyzer-preflight-diagnostic-2026.10.16.py.sha256
docker compose run --rm --no-deps -T \
  -v "$PWD/traffic-analyzer-preflight-diagnostic-2026.10.16.py:/tmp/preflight-diagnostic.py:ro" \
  platform python3 /tmp/preflight-diagnostic.py
```

该命令重复原有三档模型及只读数据库/Kafka预检，不执行迁移、不发布消息。请提供最后的Preflight步骤及代码位置；仅凭AssertionError不能认定为NPU或认证问题。已发现SQLAlchemy的PG版本字符串解析也可能抛此类型，未取得现场栈前仅作为候选，不实施数据库兼容猜测。

### 分项环境检查与集中异常提示（2026-10-17）

为避免逐个失败后反复现场操作，最新单文件为`traffic-analyzer-repair-environment-2026.10.17.sh`。拷到部署目录后一次执行：

```sh
sh /data2/drone/traffic-analyzer/traffic-analyzer-repair-environment-2026.10.17.sh
```

保留现有.env、ASSET_ROOT、DATA_ROOT、镜像和业务数据。脚本累计更新SHA管理的源码，备份原文件；先用无NPU设备依赖的init-db工具容器对DB/YCX/Kafka做只读分项检查，再验证实际应用代码加载，最后由完整预检作为启动门禁。基础设施早期失败仍收集后续可检查项；最终完整检查有失败时不启动应用。常驻应用容器只在预检通过后重建。

每项报告`stage/status/code/title/action/facts`，状态分为passed、failed、warning、skipped、pending_init。失败、依赖未执行和初始化待执行不会混为成功。stdout保存完整JSON（schema_version=uav.deployment-checks/v1），末尾stderr集中输出中文问题和处理建议；部署根目录`highgo-repair-report.*`保留完整自动报告，权限600。

| 范围 | 精确区分/检查内容 |
|---|---|
| 配置 | 必填/类型/枚举、CORS JSON、生产密码/JWT、SASL账号、应用库与schema |
| 镜像/驱动 | Linux ARM64、厂商libpq路径/架构/依赖、纯Python psycopg；CANN9.0.0和设备/模型加载阶段 |
| 模型 | 清单/源权重/三档OM校验、640/960/1280分别推理、原生昇腾错误码；不猜测未知错误码含义 |
| 持久化目录 | HLS、输出、spool、标定、上传、归档、日志目录的实际可写性及可用空间；仅创建随即删除的小临时文件 |
| 数据库 | 认证、白名单/SSL、DNS、拒绝连接/超时、实际库/schema、schema存在和USAGE、Timescale扩展及信息视图 |
| 权限/迁移 | 现有应用表CRUD及序列USAGE、已知迁移版本、需要初始化时的CREATE权限；未知版本拒绝，不降级或改版本表 |
| YCX / Doris | 路网关闭时跳过YCX；启用时各表/PostGIS只读查询为警告。两张指标表单独经Doris探测，不阻塞 |
| Kafka | SASL口令/机制、连接/超时、Topic/Group/Cluster/事务ID权限错误分别分类；仅只读认证/元数据，不发布消息或加入业务消费者组 |
| 初始化 | 基础迁移/管理员、Replay V2、版本验证、源导入具体阶段，保留底层SQLSTATE而非吞掉异常后只返回False |
| 容器启动 | 端口占用、磁盘满、缺镜像/挂载/设备、架构错误，以及安全的状态/退出码/OOMKilled信息；137不直接等同OOM |

数据库各项使用只读事务和savepoint隔离，一个查询失败不使后续独立查询处于事务错误状态。应用库不可达仍检查YCX和Kafka；schema缺失仍检查Timescale扩展。必要依赖不可用时明确标记skipped。连接与异步查询有时间上限，关闭连接/设备失败也进入报告。

示例（内容来自环境检查，不含口令）：

```text
DIAGNOSTIC [DB_SCHEMA_MISSING] database.schema: xinchan中的ycx_drone尚未预建 | 处理：由DBA预建并授权 | 证据：{"schema":"ycx_drone","exists":false}
DIAGNOSTIC [TABLE_NOT_FOUND] ycx.road11.dim_link_info: 查询所需表不存在 | 处理：核对YCX库/schema和数据版本
DIAGNOSTIC [KAFKA_AUTH] kafka.authentication_and_metadata: Kafka SASL认证失败 | 处理：核对Kafka账号/口令及PLAIN配置
```

分类优先使用[PostgreSQL SQLSTATE](https://www.postgresql.org/docs/current/errcodes-appendix.html)和实际Kafka异常类；连接建立时驱动可能没有SQLSTATE，此时仅匹配已知认证/白名单/SSL/DNS签名。原始异常文本、SQL参数、局部变量和完整连接串均不输出；对象名仅取结构化诊断中的合法标识符。无法确定的异常标为ENV_UNKNOWN，并保留类型与代码位置，不编造根因。

边界：只读元数据不能证明Kafka发布、事务/消费者组ACL或完整业务链路通过，因此会明确警告未验证；数据库ACL可读检查不代替真实业务/RLS验收。首次缺版本表可记pending_init，仍由显式init-db迁移。没有预建schema、扩展或权限时不会擅自创建/授权。原生SDK崩溃或容器无法创建时部分检查可能无法执行，报告会区分已完成与未执行。1GiB低空间提示不是容量验收标准。Mac原生/MPS默认启动不变。

### 已进入database.connect_and_schema后失败（2026-10-17）

现场日志已显示新预检和三档OM推理完成，在旧诊断的`runtime_check.py:72`失败；该位置专指实际database/schema不等于xinchan.ycx_drone，TimescaleDB和Kafka尚未检查。没有实际字段值前，不将schema缺失、无权限或启动参数被覆盖任一种原因当作定论。

补充修复参考线上项目的连接后SET：专用方言从URL接收应用schema，在每个连接建立后、SQLAlchemy初始化前以autocommit方式执行`SET SESSION search_path TO "配置schema", public`；随后恢复原autocommit，避免连接池rollback撤销会话设置。此方式覆盖运行及两套迁移；本地asyncpg保持不变。URL的application_schema参数由专用方言移除，不传给libpq，并严格验证标识符。参考[SQLAlchemy连接时设置search_path](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#setting-alternate-search-paths-on-connect)。

新版预检自动输出不含凭据的Preflight database JSON：配置及实际database/schema、search_path、ycx_drone是否存在、USAGE/CREATE权限。失败时连接池也会释放。仍保留错误库/schema拒绝；预检不自动创建schema、扩展，不给无权限账号授权，不向public退回建表。

将新的单文件脚本放到部署目录，只执行：

```sh
sh /data2/drone/traffic-analyzer/traffic-analyzer-repair-schema-2026.10.17.sh
```

此脚本累计安装前序修复并升级已由SHA管理的旧overlay；未登记的改动仍拒绝覆盖。旧源码备份到.highgo-version-hotfix-backup/sources-before-schema-fix，现有.env/资产/数据保留。实际代码加载验证通过后继续原预检和强制重建启动；失败自动报告具体库/schema/权限状态。如果schema确实未预建或USAGE缺失，仍须DBA完成预置，不能以应用补丁绕过。

已用实际ARM64厂商libpq、根Compose隔离PG17/TimescaleDB验证：即使省略启动options仍进入ycx_drone、回滚后schema保留、dialect默认schema一致、两套迁移与重复初始化通过；额外验证schema不存在和非superuser无USAGE两种状态能明确分类且不创建/授权。已有旧版单文件修复升级后重复执行、SHA及.env保留已验证。证据见dist/VALIDATION-HIGHGO-SCHEMA-2026.10.17.json及dist/VALIDATION-HIGHGO-SCHEMA-REPAIR-2026.10.17.json，生产实际字段仍需本次现场执行输出。

### 已打补丁仍出现旧栈：一次执行修复启动（2026-10-17）

现场再次报告旧版`runtime_check.py:107/51`及SQLAlchemy `base.py:4079`。这些位置对应旧预检；没有现场加载元数据时，不能仅凭重复栈断定具体哪个Compose/挂载未生效。停止逐条要求现场手工诊断，改为单文件`traffic-analyzer-repair-highgo-2026.10.17.sh`一次执行。

将此脚本拷到现有部署目录后只执行：

```sh
sh /data2/drone/traffic-analyzer/traffic-analyzer-repair-highgo-2026.10.17.sh
```

脚本内含带SHA校验的离线修复代码，无需手工解压；固定使用脚本所在部署目录的`.env`和`docker-compose.yaml`。它依次核对现有ARM64镜像、修复Compose兼容性、安装HighGo源码挂载，并分别在**实际platform/init-db工具容器**中验证配置文件路径、专用方言、版本解析方法来源、迁移引擎方言及新版预检标志，全部通过后才执行原有预检，并用--force-recreate重建应用容器后启动，确保既有容器不会继续使用旧进程或文件挂载。代码加载验证不连接数据库、不运行迁移；正常启动仍按原流程执行显式迁移。读取数字版本时使用真实server_version_num，加载验证的数字响应只是无网络自检夹具，不写入数据库版本状态。

脚本保留既有.env、资源/数据目录及备份策略；修复工具临时目录退出时清理，报告文件`highgo-repair-report.*`保存在部署根目录，权限600。任一步失败返回非零，自动显示最后100行并提供完整报告路径；不会在旧解析器仍生效时报告修复成功或继续启动。版本16归档保持封存；本脚本同时覆盖此前Compose与HighGo修复，无需再次逐项应用。

验证覆盖原始归档、Compose 2.24.7实际ARM64工具容器、两个角色的运行/迁移方言和预检激活、重复执行、私有.env字节/600权限保留、临时目录清理及损坏内嵌载荷拒绝。Mac验证在最后Linux生产主机门禁处明确停止，没有启动开发态Platform；没有声称生产NPU/SM3/YCX/Kafka或整站启动完成。详细记录见dist/VALIDATION-HIGHGO-REPAIR-2026.10.17.json。

### 瀚高版本字符串断言修复（intranet.4既有镜像）

若安全诊断定位`sqlalchemy/dialects/postgresql/base.py`的`_get_server_version_info`断言，连接已进入SQLAlchemy初始化。已比对线上“指标产出分析”：`hg_client.py:152`直接用psycopg2连接、设置并核验schema，`services/uow.py`与`migrate.py`复用该入口；没有SQLAlchemy版本横幅解析。该项目的国密驱动方案有效，但它没有覆盖本项目异步ORM新增的版本识别步骤。本项目继续使用已确认的ARM64厂商libpq和纯Python psycopg3。

生产`DB_DRIVER=psycopg`现在注册专用异步方言`postgresql+highgo_psycopg`，通过`SHOW server_version_num`读取实际PG内核数字，按PG 10前后版本编码规则转换；无效值明确失败。预检、平台、基础及Replay V2迁移统一经Settings.database_url选择此方言，不写死版本、不修改SQLAlchemy安装包、不关闭断言。YCX原生只读连接不经过此解析；本地asyncpg URL不变。

将小补丁`traffic-analyzer-highgo-version-hotfix-2026.10.16.tar.gz`及SHA拷入现场，已完成Compose 2.24.7补丁且原ARM64镜像已导入时执行：

```sh
cd /data2/drone/traffic-analyzer
sha256sum -c traffic-analyzer-highgo-version-hotfix-2026.10.16.tar.gz.sha256
tar -xzf traffic-analyzer-highgo-version-hotfix-2026.10.16.tar.gz
sh traffic-analyzer-highgo-version-hotfix-2026.10.16/apply.sh "$PWD"
./docker-compose up -d
```

补丁以现有镜像中的Python离线校验/安装三个小源文件，在platform/init-db添加精确只读文件挂载，并更新对应SHA；备份根Compose和SHA于`.highgo-version-hotfix-backup`。`.env`、ASSET_ROOT=../traffic-analyzer-asserts及其他现场配置保留，模型/视频/持久化数据不移动。部署版本必须保留`deploy/intranet/highgo-version-hotfix`目录。已运行旧Platform会因挂载配置变化由Compose重建；安装阶段不访问DB/Kafka，普通up仍执行预检与显式初始化。需要应用回退时恢复该备份的Compose和SHA，不执行数据库降级。强制终止安装若造成校验不一致，恢复备份两文件后再应用。

已用实际ARM64镜像和厂商libpq连接根Compose隔离PG17/TimescaleDB，验证schema、事务回滚、基础/V2迁移及重复初始化；厂商横幅造成的原断言使用SQL响应夹具复现。该隔离PG不冒充生产瀚高。实际原归档逐步应用两个补丁后，2.24.7配置解析、只读挂载、既有参数/私有.env保留及所有不可变小文件校验通过，现场仍需继续up确认其余服务。

## 8. 构建与模型转换（仅构建人员）

正式镜像从锁定digest的官方CANN9.0.0/310P/Ubuntu22.04/Python3.11、Node22和Nginx Alpine构建，见`deploy/intranet/base-images.json`。原厂x86_64参考资料的32文件仍保留历史来源，不进入ARM64镜像。用户补充的aarch64 libpq已归档，所需libssl.so.1.1/libcrypto.so.1.1来自Ubuntu官方ARM64 libssl1.1包1.1.1f-1ubuntu2.24，并与官方包索引SHA256核对；三库来源/哈希见随包`deploy/highgo-reference/ARM64_SOURCE.json`。仅放入/opt/highgo/lib，不替换系统OpenSSL3，不伪造跨版本库软链接。aarch64国密libpq及依赖暂存于`deploy/intranet/highgo-driver/arm64`，通过ELF/ldd/实际加载验证后才构建完整包；采用纯Python psycopg3调用厂商库，本地asyncpg保持默认。联网构建机至少预留60GiB Docker存储。构建/源Compose覆盖渲染使用已验证的Compose 2.29.7；现场2.24.7读取生成后的单文件，不执行覆盖渲染或构建。

```sh
python3 scripts/build_intranet_release.py build --version 2026.10.16-intranet.4
python3 scripts/build_intranet_release.py package --version 2026.10.16-intranet.4 \
  --deployment-env deploy/intranet/deployment.private.env \
  --model-manifest dist/model-resources-v4/ascend/manifest.json \
  --model-resource-archive dist/traffic-analyzer-models-2026.10.15-intranet.4-ascend310p3.tar.gz
python3 scripts/build_intranet_release.py source --version 2026.10.16-intranet.4
```

部署Compose由维护的根Compose和薄覆盖配置自动合并生成，运行时仅保留init-db、Platform、Console；不维护另一套源码拓扑。缺镜像、驱动或模型关联文件时私有完整封包失败。源码准备包不含镜像/私有.env，不能直接部署。

现有独立资源含原始`yolo11s-visdrone.pt`（EOF后CPU外观编码需要）、640/960/1280三档ONNX/OM及类别/版本/参数/哈希。检测保持`main_optimized.py`三进程结构和现有高度自适应语义，主检测用pyACL，缺设备或模型拒绝任务。辅助车道模型当前关闭，启用前须另提供资源与适配。

仅模型变更时再转换：

```sh
python3 scripts/build_intranet_release.py models --version 新资源版本 \
  --weights weights/yolo11s-visdrone.pt --model-output /绝对路径/新资源/ascend
```

转换固定batch1/NCHW/opset13、图外NMS，ONNX1.16.2/protobuf3.20.3，三档串行ATC Ascend310P3。转换机Docker至少10GiB内存，容器限8GiB/含swap10GiB。离线工具镜像已随包，可在独立构建机禁网运行`/app/scripts/convert_ascend_models.py`；不在生产启动时重复编译或联网下载。

本地开发仍使用`scripts/mac_local_platform.sh up`和`cd console2 && npm run dev`，MPS及road9默认连接不变。公开依据：[CANN镜像清单](https://raw.githubusercontent.com/Ascend/cann-container-image/main/supported_tags.md)、[Psycopg安装](https://www.psycopg.org/psycopg3/docs/basic/install.html)。

## 2026-10-17 Doris 读库更新（ADR-038）

路网及路口/路段指标统一配置 `DORIS_MYSQL_HOST/PORT/USER/PASSWORD` 和 `DORIS_DATABASE=ycx_xc`，
两张指标表固定为用户确认的 `dws_tfc_inter_index_m_5mi` / `dws_tfc_link_index_m_5mi`。
`YCX_DB_*` 不再是发布必填项，瀚高仅承载 `xinchan.ycx_drone` 无人机应用数据。
预检只读检查Doris维表、启用版本和两张指标表，不检查瀚高PostGIS/road11。
`ROAD_FEATURES_ENABLED=false` 继续保留生产暂停状态；接入公网的本机环境不代表内网可达或新包已发布。
以前版本交付说明中 `road11/xianchang` 读库为历史配置，不恢复运行时连接。

## 历史：2026.10.17-intranet.1 连接与发布配置

本机与生产使用同一 Doris 库 `ycx_xc` 和两张 `*_index_m_5mi` 表；只切换地址及各自已有账号。
本机 `platform/.env` 使用 `8.149.139.113:9030`，生产私有包根 `.env` 使用 `37.12.11.127:9030`。
生产沿用先前授权的内网 Doris 账号，不用本机公网 root 凭据覆盖；密码只保存在600权限私有 `.env`。

| 配置组 | 已填内容/行为 |
| --- | --- |
| Doris | `DORIS_MYSQL_HOST=37.12.11.127`、端口9030、`DORIS_DATABASE=ycx_xc`，账号/密码见根`.env` |
| 瀚高 | `DB_HOST=37.12.14.133`、端口5866、`xinchan.ycx_drone`、`DB_DRIVER=psycopg`；UAV应用读写 |
| Kafka | 既有37.12.14.66—69:9093、SASL_PLAINTEXT/PLAIN；账号/密码见根`.env` |
| MineMap | `http://37.8.188.98:21009`、solution17000；实际Key见根`.env`，8009统一代理入口 |
| 资源/数据 | `ASSET_ROOT=../traffic-analyzer-assets`、`DATA_ROOT=../traffic-analyzer-data`；现场若改过路径须保留现场实际值 |
| 降级开关 | `ROAD_FEATURES_ENABLED=false`、`DB_TIMESCALE_REQUIRED=false`、`YCX_METRICS_BACKEND=doris` |
| 浏览器来源 | `PUBLIC_HOST=auto`、`CORS_ORIGINS=auto`；离线启动入口解析现场地址后写回具体来源 |
| 模型/视频 | 继续复用已校验的独立模型包和29个视频遥测文件，不内嵌到应用镜像 |

交付为包含完整新镜像的独立ARM64发布包，已累计此前修复；新包无需再次运行旧补丁。
在新解压目录运行 `./docker-compose up -d`；旧包与业务资源目录保留，不覆盖现场已有数据。
若现场现用`.env`曾修改过资源路径或其他连接，升级时保留实际值并核对上述Doris配置。
生产实机SM3、Kafka业务ACL、内网Doris/MineMap可达性及昇腾推理仍由现场启动预检与业务验收确认。


## 2026-11-04 增量轨迹后续工程验证

运行期短窗口关系、按受影响窗口的分页聚合、源片段摘要对账、生产路网关闭四进程的ACK后历史裁剪、GeoJSON落盘导出及固定Topic显式初始化/只读检查已实现。Replay迁移head更新为20261104_rv2_0007，所有运行态需验证共享回执/Replay迁移。普通启动不DDL、不创建Topic；旧数据与旧Topic保留。验证范围、历史隔离清理事故和未完成的现场/故障验收详见[增量轨迹进度](INCREMENTAL_TRAJECTORIES_20261104.md)；完整包按2026.11.04.2验收候选交付，不宣称已达到现场30%FPS目标。

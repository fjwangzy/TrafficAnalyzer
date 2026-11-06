> 最新累计前后端完整包为[2026.11.04.1](NATIVE_DEPLOYMENT_2026.11.04.1.md)，包含重新构建的Console资源并自动切换现有容器挂载。

# Platform／检测器原生完整部署（2026.11.03.1）

上一完整原生包为[2026.11.03.3](NATIVE_DEPLOYMENT_2026.11.03.3.md)，累计权限/绑核/IPC修正，并同时启用四进程与事件保真v2采样；本页.1命令保留历史参考，新的交付请用页首2026.11.04.1说明。产生v2数据后禁止退回不识别摘要的旧消费者。

适用既有 UOS Server 20、Linux aarch64、Ascend 310P3 主机。完整包自带 Python 3.11.15、CANN 9.0.0 用户态运行库及 FFmpeg；不使用系统 Python，不联网安装，不要求先安装旧宿主包或补丁。宿主必须保留匹配的昇腾驱动/固件及设备权限，解压目录不能为 noexec。Console、数据库、Kafka继续保留原服务。模型、视频、私有生产连接和数据目录复用现场资源，不包含在新包内。无开机自启。

## 解压并启动

现场旧Docker生成的日志、spool及输出通常归root，日志文件会强制保持600。此部署应统一使用root（普通账号通过sudo执行traffic），同时满足Docker/设备与/app链接权限；不要混用不同账号启停。先在网页停止检测/测绘任务。将新包解压到独立目录，不覆盖旧部署或旧原生目录。建议至少预留 25GiB 空间。

```sh
sha256sum -c traffic-analyzer-native-2026.11.03.1.tar.gz.sha256
tar -xzf traffic-analyzer-native-2026.11.03.1.tar.gz
cd traffic-analyzer-native-2026.11.03.1
# 仅替换为现有部署根目录（包含私有 .env），不是旧宿主排查包目录。
sudo ./traffic start --deployment-root /data2/drone/traffic-analyzer-2026.10.19-intranet.1-linux-arm64
```

首次一条命令完成文件校验、配置/资源导入、源码及依赖/数据库两个迁移 head 检查、旧 Platform停止、NPU与连接预检、原生启动及现有 Console代理切换。成功输出 START_SUCCEEDED，浏览器仍用原 `http://服务器IP:8009`；登录后选择原视频/SRT或实时源创建任务，检测器自动原生启动。不会在启动时自动创建检测任务。普通 start/restart不执行迁移。

后续在新包目录执行：

```sh
sudo ./traffic status
sudo ./traffic stop
sudo ./traffic start
sudo ./traffic restart
sudo ./traffic check
sudo ./traffic diagnose
# 停止本包原生应用，恢复首次切换前的应用/代理状态：
sudo ./traffic rollback
```

`stop`只停止本包原生 Platform及其检测子进程，网页保留但 API暂不可用。首次切换失败会自动尝试恢复，并分别输出 START_FAILED与RESTORE_SUCCEEDED或RESTORE_FAILED。中途断电留下 switching状态时先执行 rollback，再重试 start。不要同时用旧 docker-compose/app-compose/host-platform 启动第二套 Platform；旧包和现场数据继续保留。

## 检查与故障证据

日志仍在现场原 DATA_ROOT/logs：`containers/platform.log`、`containers/preflight.log`、`containers/source-check.log`以及`pipelines/*.log`。标准logging带时间、PID、Pipeline及异常栈；日志轮转沿用20MiB、6份。控制器输出具体失败阶段和日志位置；启动失败自动写本包 `state/diagnosis.json`，也可用 `./traffic diagnose`重新采集。

本包 state目录700，其中配置/快照/诊断600，含现场凭据，不要回传整目录。诊断日志自动脱敏，分享前仍需复查。`state/launcher.log`记录解释器/监督进程错误。ELF加载器无法启动时，shell直接报告文件缺失/执行权限，或由加载器报告缺失动态库；检查完整解压、noexec及架构。

平台仅绑定现有共享Docker网桥的8000；检测器内部MJPEG只绑定127.0.0.1，经平台鉴权代理访问。Console必须能通过该网桥访问宿主；不能通过关闭防火墙/SELinux解决。数据库地址每次启动重新解析，实际database/schema仍受生产身份校验。若整个网桥重建（网关变化），先回退，再在新解压目录重新首次启动，保留旧状态供恢复。

如报告数据库版本不匹配，先核对部署基线与备份，停止所有新旧Platform，再显式执行 `./traffic init-db`，成功后 start。此命令会执行迁移，不能作为任意启动故障的默认处理。禁止改版本表、绕过门禁或重新建库。

## 2026-11-03 现场既有root日志权限问题

用户反馈普通账号原生启动无法打开Docker留下的root日志。已在隔离ARM64环境复现：root:600日志在open处报EACCES；即便临时放开写入，也会在日志处理器fchmod(600)处报EPERM。推荐在当前完整包目录直接`sudo ./traffic start`（首次保留`--deployment-root`），其后stop/restart/check/diagnose/rollback也统一sudo，无需补丁、无需重解压或执行init-db。不要chmod777或递归chown整个DATA_ROOT；数据库和保留Console仍有自己的属主约束。

后续源码新增RUNTIME_PERMISSION提前检查：在state chmod和业务日志初始化前验证当前用户、可写目录、既有私有日志及标定JSON，提示具体路径/UID及sudo处理，不自动修改原数据权限。当前已交付2026.11.03.1归档与SHA保持原字节，该源码改进尚未重新封包；本段sudo操作直接适用于当前包。

## CPU与性能

后续现场复测已确认三worker mask恢复0–95，但FPS仍偶到1.7。当前JSON的24KB管道尾部截断关键阶段；更长只读导出方法和当前证据见[NATIVE_PERFORMANCE_AFTER_AFFINITY_20261103.md](NATIVE_PERFORMANCE_AFTER_AFFINITY_20261103.md)。源码诊断窗口已增至256KiB，原包未覆盖，此变更不等同于性能优化。


**CPU0问题已有包内复现：** PyTorch/OpenMP在fork时收缩子进程亲和范围，设置原生state环境`OMP_PROC_BIND=false`可阻止收缩。现场证据、修正和验证边界见[NATIVE_CPU_AFFINITY_20261103.md](NATIVE_CPU_AFFINITY_20261103.md)。旧归档不覆盖；修改后须重启平台并新建任务。


2026-11-03现场反馈：原生启动成功后仍约1FPS、CPU0满载；该观测不足以证明Docker根因或所有线程都绑定CPU0。保持当前任务运行至少60秒，在包目录执行`sudo ./traffic diagnose`，并用`sudo ps -eLo pid,ppid,tid,psr,pcpu,comm --sort=-pcpu | head -25`记录热点线程。diagnosis.json含worker各线程mask、cgroup父级限制和最近阶段日志；先采集后判断是否需要针对特定线程作亲和对照，不直接批量改绑或增大数值库线程。现场证据尚待取得。


原生入口不设置taskset或cpuset；数值库线程默认各1，避免小矩阵多线程开销，不修改昇腾内部线程绑定。日志/diagnose记录各线程亲和、在线CPU及可读取的cgroup父级限制；不可读项为unavailable，不等于无限制。串行计算不会因允许更多核自动并行。

真实任务运行后至少观察5分钟稳定阶段：结合pipeline日志中的ascend.om_execute、tracker、show.render、show.mjpeg_encode及queue等待，核对实际处理FPS、CPU和NPU使用率。需对照相同视频/模型/分辨率/stride；网页展示FPS不能单独证明所有阶段吞吐。当前没有本次UOS/NPU现场结果，不承诺原生部署能解决约1FPS。

## 构建与边界

```sh
python3 scripts/build_host_platform.py --native-release --version 2026.11.03.1
```

构建端可从固定ARM64运行镜像提取运行库；交付后Platform和检测器完全在宿主运行，不执行镜像。完整包包含内外SHA256、HOST_RELEASE.json、VALIDATION.md和硬件无关runtime_smoke.py；未包含旧补丁入口或安装状态。迁移/依赖与打包运行库按ADR-041核验，Mac原生MPS和本地.env不变。生产ROAD_FEATURES_ENABLED及DB_TIMESCALE_REQUIRED等例外保持现场配置，不重置为开发值。


2026-11-05新增完整验证候选：2026.11.05.1，操作与实际验证限制见[NATIVE_DEPLOYMENT_2026.11.05.1.md](NATIVE_DEPLOYMENT_2026.11.05.1.md)。保留SQLite；未改迁移/依赖基线，未替代现场验收。

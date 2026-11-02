# 鲲鹏 920：CPU0 满载排查与调优操作指南

日期：2026-10-20。适用：TrafficAnalyzer 内网 Linux ARM64、Ascend 310P3、CANN 9.0.0。

**先执行第 1～5 节只读检查。第 6～8 节是有条件的变更，逐项对照，不整篇连续执行。** 本文可以单独复制到内网，不依赖外网。本文发布时尚未操作生产、修改业务阈值或证明性能改善。

## 1. 已确认的硬件与判断原则

现场 `lscpu.txt`：96 个物理核、2 路×48 核、每核 1 线程，最高报告频率 2.6GHz。

| NUMA 节点 | CPU 编号 | 核数 |
| --- | --- | ---: |
| node0 | 0–23 | 24 |
| node1 | 24–47 | 24 |
| node2 | 48–71 | 24 |
| node3 | 72–95 | 24 |

- 当前环境暴露 NEON/ASIMD、FP16、点积等指令能力，没有暴露 SVE；本轮不改 SIMD、编译器或运行库。
- `CPU min MHz=200` 不是当前运行频率；`boost disabled` 不能单独证明节能策略或异常降频。
- `OPENBLAS_NUM_THREADS=1`、`OMP_NUM_THREADS=1` 限制库内并行数量，不会指定 CPU0，也不限制整个三进程流水线只能用一个核。
- 单核 100% 既可能是线程 affinity 被限制，也可能是串行热点。允许更多核不保证这个阶段自动并行。
- 保持 `confidence=0.05`、模型、推理尺寸/自适应策略、stride、地图及业务质量门禁不变。

## 2. 找到正在运行的 Platform 容器（只读）

以下在 **Linux 宿主机终端**执行，不在容器终端执行。Docker 权限不足时，由有权限的运维人员执行同一命令。

```bash
docker ps --format 'table {{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}'

# 替换为上面实际运行的 Platform 容器名或 ID。
TA_PLATFORM_CONTAINER='请替换为实际Platform容器名或ID'

docker inspect --format 'id={{.Id}} image={{.Image}} running={{.State.Running}}' "$TA_PLATFORM_CONTAINER"
```

确认 `running=true` 且镜像属于现用 TrafficAnalyzer Platform。后续沿用同一个终端中的变量。不要选 Console、数据库或诊断容器。

## 3. 检查容器 CPU 核集合和配额（只读）

```bash
docker inspect --format 'cpuset={{.HostConfig.CpusetCpus}} cpuset_mems={{.HostConfig.CpusetMems}} nano_cpus={{.HostConfig.NanoCpus}} quota={{.HostConfig.CpuQuota}} period={{.HostConfig.CpuPeriod}}' "$TA_PLATFORM_CONTAINER"

# 连续观察 15 秒，确认发生 CPU0 满载的是同一时间窗口。
docker stats --no-stream "$TA_PLATFORM_CONTAINER"
sleep 15
docker stats --no-stream "$TA_PLATFORM_CONTAINER"
```

| 输出 | 解释 |
| --- | --- |
| `cpuset=0` | 容器显式只允许 CPU0；需要先处理这层限制 |
| `cpuset=0-7` | 允许 CPU0～7，但不保证这些核独占或全部被利用 |
| `cpuset=` 空 | 容器未显式指定核集合，仍需检查上级 cgroup 和线程 affinity |
| `nano_cpus=1000000000` | Docker 设置了约 1 核 CPU 时间额度 |
| `quota=100000 period=100000` | 配额约 1 核；`quota/period` 为核额度 |
| `nano_cpus=0 quota=0 period=0` | HostConfig 未显式设置这些限制；不等于整条资源层级无限制 |

`docker stats` 的 CPU 约 100% 表示该容器本次采样累计消耗约一个逻辑 CPU 的处理量，不能据此判断可用核数。

下面只读取常见 cgroup 文件。v2 的 `cpu.max` 第一列为 `max` 表示该层未设 CPU 带宽上限；数字则用第一列除以第二列。v1 用 quota/period；quota=-1 表示该层未设上限。路径不存在时跳过，不安装工具。

```bash
docker exec "$TA_PLATFORM_CONTAINER" sh -c '
cat /proc/self/cgroup
for f in \
  /sys/fs/cgroup/cpu.max \
  /sys/fs/cgroup/cpu.stat \
  /sys/fs/cgroup/cpuset.cpus.effective \
  /sys/fs/cgroup/cpuset.mems.effective \
  /sys/fs/cgroup/cpu/cpu.cfs_quota_us \
  /sys/fs/cgroup/cpu/cpu.cfs_period_us \
  /sys/fs/cgroup/cpu/cpu.stat \
  /sys/fs/cgroup/cpu,cpuacct/cpu.cfs_quota_us \
  /sys/fs/cgroup/cpu,cpuacct/cpu.cfs_period_us \
  /sys/fs/cgroup/cpu,cpuacct/cpu.stat \
  /sys/fs/cgroup/cpuset/cpuset.cpus; do
  if [ -r "$f" ]; then
    printf "\n%s\n" "$f"
    cat "$f"
  fi
done'
```

间隔 15 秒再执行上面整块，比较 `nr_throttled`、`throttled_usec`（v2）或 `throttled_time`（v1）的增量。它们是累计值、单位不同。若文件缺失或容器挂载并非 cgroup 根，不能按“无配额”解释；需要管理员根据 `/proc/<宿主PID>/cgroup` 核对真实路径及父级限制。

## 4. 找高 CPU 进程，检查所有线程（只读）

任务运行、CPU0 满载时执行：

```bash
docker top "$TA_PLATFORM_CONTAINER" -eo pid,ppid,pcpu,psr,comm
```

- `PID`：这里是 **宿主机 PID**；`PSR` 是最近运行的 CPU 编号，`PCPU` 帮助筛选高 CPU 进程。
- `PSR=0` 只表示最近在 CPU0 上运行，不能单独证明被固定绑定。
- 从中找到持续高 CPU 的 Python 进程。再次执行确认，必要时用下面的线程统计定位。

```bash
# 12345 只是示例，必须替换为上一步的实际高CPU宿主机PID。
TA_HOT_PID=12345

# 仅查询：这里没有给出新的CPU列表，不会改绑核。
LC_ALL=C taskset -apc "$TA_HOT_PID"

# 对照容器日志PID，并看主线程资源范围。
awk '/^(Name|Pid|PPid|NSpid|Threads|Cpus_allowed_list|Mems_allowed_list):/' "/proc/$TA_HOT_PID/status"

# 观察各线程；PSR不是允许范围，允许范围以上面的taskset输出为准。
ps -L -p "$TA_HOT_PID" -o pid,tid,psr,pcpu,comm

# 系统已有pidstat时，再采集15秒；没有则跳过。
if command -v pidstat >/dev/null 2>&1; then
  pidstat -t -p "$TA_HOT_PID" 1 15
fi
```

对 reader、tracker、show 等不同 Python 进程分别核查，不能只检查一个 PID 就推断整个容器。通过 `NSpid` 对应容器日志中的 PID；老内核没有该字段时不直接混用两种 PID。线程数是存活数，不等于活跃 BLAS 线程数。

## 5. 按检查结果选择分支

| 结果 | 应采取的下一步 |
| --- | --- |
| 容器 cpuset 只有 `0` | 先记录原值，再按第 6 节扩大容器允许范围做单变量对照 |
| 容器允许多核，但热点进程所有线程 affinity 都只有 `0` | 按第 7 节对确认的跟踪进程做临时对照；查父进程/启动脚本/库的绑定来源 |
| 容器存在约 1 核配额且限流增长 | 先查配额来源；核池扩大不能代替放宽时间配额 |
| 允许范围和配额充足，仅一个线程持续满载 | 更像串行热点；记录具体阶段，不能承诺改cpuset或增加BLAS线程可提速 |
| 部分线程单核，其他线程多核 | 分线程判断；不能统一将全部线程改为相同mask |

阶段日志重点：`reader.detection`、`ascend.cpu_nms`、`tracker.association`、`bytetrack.shadow_gate`、`show.render`、`show.mjpeg_encode` 及队列等待。比较同一个新 Pipeline、相同视频窗口，区分计算与上游/下游等待。

## 6. 仅当容器 cpuset 限制单核：临时放宽与回滚

**本节会修改运行中容器的资源范围。只在已确认限制、核集合允许使用时执行。** 不改变模型、NPU 设备、数据卷或数据库。先完成只读采集，选择单一变量做对照。

以下 `4-11` 是 node0 内的 8 核实验例子，不是已确认的 NPU 本地最优核集合。必须核实这些核在线、被上级允许，且不与现场既有资源隔离安排冲突。若已有 cpuset_mems，也要核对节点内存可用性，不在本轮一起修改。

```bash
# 保存原来的CPU范围。只有本节变量尚未保存过时执行，避免覆盖回滚值。
TA_OLD_CPUSET=$(docker inspect --format '{{.HostConfig.CpusetCpus}}' "$TA_PLATFORM_CONTAINER")
printf 'original cpuset=%s\n' "$TA_OLD_CPUSET"

# 确认本轮选择4-11之后才执行。
docker update --cpuset-cpus=4-11 "$TA_PLATFORM_CONTAINER"

docker inspect --format 'cpuset={{.HostConfig.CpusetCpus}}' "$TA_PLATFORM_CONTAINER"
LC_ALL=C taskset -apc "$TA_HOT_PID"
```

已有线程自己的窄 affinity 可能继续存在。扩大容器范围后仍需检查，不自动对全部线程再做改绑。若实际只允许少量核或命令失败，先查父级资源约束，不继续叠加其他设置。

回滚本节修改：

```bash
# 使用同一终端中保存的原值；原值为空时也要保留引号。
docker update --cpuset-cpus="$TA_OLD_CPUSET" "$TA_PLATFORM_CONTAINER"
docker inspect --format 'cpuset={{.HostConfig.CpusetCpus}}' "$TA_PLATFORM_CONTAINER"
```

本节不自动修改 quota。若检查确认限流，需另行记录并评估原 NanoCpus/CpuQuota/CpuPeriod 后再做独立配额对照，不提供未经现场核对的统一配额修改命令。动态 docker update 不会写回 Compose，未来重建可能恢复原配置；有效配置应另行纳入受控发布。

## 7. 仅当跟踪进程全部线程都只允许CPU0：临时对照与回滚

**本节会修改选定进程的全部现存线程 affinity。只适用于第 4 节已确认“全部都是0”的跟踪进程。** 若 mask 不同，不执行下面的统一设置/回滚。不要选择 Platform 父进程、reader/NPU 进程或整个容器进行批量改绑。

选定跟踪进程应结合高 CPU、父子关系、NSpid 与阶段日志共同确认。过程中 PID 若退出、任务重建或容器重启，原 PID 立即作废，应重新识别。`4-11` 仍只是已核实可用时的实验核池。

```bash
# 先再次确认每个线程原范围均为0，并保留输出。
LC_ALL=C taskset -apc "$TA_HOT_PID"

# 确认“该PID确为跟踪进程、全部线程原mask=0、4-11可用”后执行。
sudo taskset -apc 4-11 "$TA_HOT_PID"
LC_ALL=C taskset -apc "$TA_HOT_PID"
```

观察同一任务后续 30～60 秒阶段耗时、FPS和线程分布。若开放范围后仍只有一个线程满载，说明该热点不会因此自动并行；继续定位阶段。不要为了观察到多核就把 BLAS 改成 96 线程。

本节回滚仅适用于修改前全部线程原mask均为0、进程仍是同一个任务的情形：

```bash
sudo taskset -apc 0 "$TA_HOT_PID"
LC_ALL=C taskset -apc "$TA_HOT_PID"
```

该操作是诊断实验，不持久化、不证明最佳NUMA位置，也不应未经观察写入启动脚本。未来新建线程仍需核验；不是所有线程都一定从当前已修改的线程创建。

## 8. 线程池1线程：独立覆盖文件实验

如果准备验证 `OPENBLAS_NUM_THREADS=1`、`OMP_NUM_THREADS=1`，先回滚前面所有动态实验，固定同一核池和配额。若当前两个变量已经为1，则不必重复重建。

只查看相关变量，不导出整个容器环境：

```bash
docker exec "$TA_PLATFORM_CONTAINER" python3 -c 'import os; print("OPENBLAS_NUM_THREADS="+os.environ.get("OPENBLAS_NUM_THREADS","<unset>")); print("OMP_NUM_THREADS="+os.environ.get("OMP_NUM_THREADS","<unset>"))'
```

在**原生产部署根目录**操作。先核对当前容器使用的项目和文件链，仅查询这几项标签：

```bash
docker inspect --format 'project={{index .Config.Labels "com.docker.compose.project"}} working_dir={{index .Config.Labels "com.docker.compose.project.working_dir"}} config_files={{index .Config.Labels "com.docker.compose.project.config_files"}}' "$TA_PLATFORM_CONTAINER"
pwd
TA_COMPOSE_PROJECT=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$TA_PLATFORM_CONTAINER")
printf 'original compose project=%s\n' "$TA_COMPOSE_PROJECT"
case "$TA_COMPOSE_PROJECT" in
  ''|'<no value>') printf '停止：未取得有效项目名。\n' >&2; unset TA_COMPOSE_PROJECT ;;
esac
```

确认项目名非空且不是 `<no value>`，当前目录与原部署目录一致，入口对应这组基础文件。否则停止本节，不猜测项目名。不要直接编辑受校验的原 `docker-compose.yaml`、源码包文件或 SHA256SUMS。新增一个独立实验覆盖文件，只包含两个环境变量：

```bash
# 若同名文件已存在则停止，先核对原内容，避免覆盖已有实验。
TA_CPU_OVERRIDE=''
if test ! -e cpu-threads-test.yaml && (set -C; cat > cpu-threads-test.yaml <<'YAML'
services:
  platform:
    environment:
      OPENBLAS_NUM_THREADS: "1"
      OMP_NUM_THREADS: "1"
YAML
); then
  TA_CPU_OVERRIDE="$PWD/cpu-threads-test.yaml"
else
  printf '停止：未创建新的实验覆盖文件，不能继续重建。\n' >&2
fi
```

**如果文件创建失败或文件原已存在，不继续后面的重建。** 配置只用于本次实验；两个变量也会影响 Platform 内的 CPU 外观模型，应同时检查该功能和API耗时。

### 8.1 选择当前实际使用的启动入口

只选一条分支。以下入口行为已与当前仓库脚本核对；若现场入口来自其他版本，先检查其说明，不假定一致。

**A. 当前用 `./app-compose` 管理源码版：**

```bash
# 只校验合并配置，不输出含密码的完整config。
./app-compose --project-name "${TA_COMPOSE_PROJECT:?先核对原项目名}" -f "${TA_CPU_OVERRIDE:?先完成实验文件创建}" config --quiet
```

**B. 当前用 `./docker-compose` 管理原完整包：**

```bash
./docker-compose --project-name "${TA_COMPOSE_PROJECT:?先核对原项目名}" -f "${TA_CPU_OVERRIDE:?先完成实验文件创建}" config --quiet
```

仅在返回成功后，在网页正常停止正在运行的检测任务，等待任务停止。这个步骤避免重建 Platform 时直接中断活动任务；本轮不执行 down、删卷、init-db、prepare/apply、拉镜像或重建镜像。

然后选择与上面一致的入口重建 Platform：

**A：源码版，仅执行本块：**

```bash
./app-compose --project-name "${TA_COMPOSE_PROJECT:?先核对原项目名}" -f "${TA_CPU_OVERRIDE:?先完成实验文件创建}" up -d --no-deps --no-build --pull never --force-recreate platform
```

**B：原完整包，仅执行本块：**

```bash
./docker-compose --project-name "${TA_COMPOSE_PROJECT:?先核对原项目名}" -f "${TA_CPU_OVERRIDE:?先完成实验文件创建}" up -d --no-deps --no-build --pull never --force-recreate platform
```

两个命令是二选一，不连续执行。使用从现用容器读取的项目名，`-f` 位于 `up` 前，保证附加覆盖文件参与合并；当前源码入口对首参数为 `up` 的调用有专用两服务启动分支，所以这里保留以 `--project-name` 起始的完整透传写法。覆盖文件没有改动 command、镜像、挂载或认证信息，继续复用原入口的基础文件链与源码环境。

### 8.2 验证新容器、新任务

重新运行 `docker ps`，更新 `TA_PLATFORM_CONTAINER` 为新的容器名/ID，然后：

```bash
docker inspect --format 'image={{.Image}} running={{.State.Running}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}not-configured{{end}}' "$TA_PLATFORM_CONTAINER"
docker exec "$TA_PLATFORM_CONTAINER" python3 -c 'import os; print("OPENBLAS_NUM_THREADS="+os.environ.get("OPENBLAS_NUM_THREADS","<unset>")); print("OMP_NUM_THREADS="+os.environ.get("OMP_NUM_THREADS","<unset>"))'
```

确认镜像未变、服务就绪后，在网页新建相同参数的任务。所有旧 PID 作废。查看新任务的 `ASSOCIATION_CPU_ENV` 和阶段日志。环境变量是配置证据；实际 PyTorch/BLAS 线程数仍应核对，库/API可以覆盖默认值。

仅 `restart` 不会更新容器环境；新建 `docker exec` 探针的设置也不等同于已有worker实际线程数。

### 8.3 回滚线程覆盖实验

网页停止实验检测任务后，使用原基础文件链重新创建 Platform，不带实验 `-f`。以下仍二选一：

**A：源码版，保留原入口记录的基础文件及源码覆盖：**

```bash
./app-compose --project-name "${TA_COMPOSE_PROJECT:?先核对原项目名}" up -d --no-deps --no-build --pull never --force-recreate platform
```

**B：原完整包，沿用原部署根配置：**

```bash
./docker-compose --project-name "${TA_COMPOSE_PROJECT:?先核对原项目名}" up -d --no-deps --no-build --pull never --force-recreate platform
```

这两条写法要求入口及其记录的基础文件链确实与第8节开头核对的现用容器一致。如果现场原本还手工附加了未被入口记录的其他覆盖文件，先由维护人员按原链顺序补齐，不用裸 `docker compose up` 猜测配置。不要把原根文件再次追加到源码覆盖之后，以免反向覆盖源码挂载/环境。

回滚后重新识别容器并核对原两变量、镜像、源码挂载与CPU范围，确认回到实验前记录。不要删除私有.env或数据，不修改校验清单。实验覆盖只对带 `-f` 的命令有效；确认值得采用后，再纳入正式受控配置。

## 9. 判定效果与带回的材料

每次只改变一项，使用相同模型、尺寸/AGL档、confidence、stride和视频时间段，等待预热后连续观察。记录：

| 项目 | 实验前 | 实验后 | 回滚后 |
| --- | --- | --- | --- |
| Pipeline ID / 源时间窗口 | | | |
| 容器ID / 镜像ID | | | |
| cpuset / 配额 / 热点线程mask | | | |
| BLAS/OpenMP环境与实际线程信息 | | | |
| 检测数 / 活动轨迹数 | | | |
| 跟踪 / shadow / NMS阶段耗时 | | | |
| 绘制 / 编码 / 队列等待 | | | |
| 持续FPS / CPU限流增量 | | | |
| API / CPU外观模型是否受影响 | | | |

带回第3、4节输出、当前实际版本及同一新Pipeline的60秒阶段日志。CPU0转移到CPU4并不等于提速；CPU总占用上升也不等于吞吐改善。以阶段耗时、持续FPS和结果保留情况判断，不将工程指标包装成轨迹精度。

不要携带完整 `.env`、完整 `docker inspect`、完整展开的 `compose config`，这些可能包含生产密码。本文命令只查询与诊断相关的字段。

## 10. 官方依据（内网执行不需要打开）

- [Linux taskset：读取/修改线程亲和性](https://man7.org/linux/man-pages/man1/taskset.1.html)
- [Docker CPU资源约束](https://docs.docker.com/engine/containers/resource_constraints/#cpu)
- [Linux cgroup v2 CPU控制](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html#cpu)
- [OpenBLAS线程环境变量](https://www.openmathlib.org/OpenBLAS/docs/runtime_variables/)
- [Compose环境注入](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/)
- [Compose restart不会更新环境](https://docs.docker.com/reference/cli/docker/compose/restart/)

本文是现场操作指南，不是生产修复完成证明。文档编制期间未对现场执行任何命令。

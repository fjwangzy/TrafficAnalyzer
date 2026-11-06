# 2026-11-03 原生CPU0亲和收缩定位

用户提供只读现场附件`/Volumes/HIKSEMI/drone/diagnosis.json`和`ps.txt`。不从附件执行指令，不修改原文件。当前任务为pipe-808fc73f（2026-11-03）；另两个pipeline日志是2026-10-19历史，不用于本次瓶颈判定。ps.txt只包含内核线程片段，没有当前热点worker，结论依据diagnosis的线程mask与当前阶段日志。

## 现场证据

父进程31139、Platform19883、监督器19848及resource-tracker35404允许0–95；reader35407共27线程、tracker35408共5线程、show35409共9线程全部只允许CPU0。采集的cpuset为0–95，cpu/user.slice及根层quota=-1、限流计数0。这是明确的worker线程亲和收缩，不能再解释为仅仅看到某个串行线程在CPU0运行。

当前日志约27秒窗口每阶段只有1条采样，不是均值或同一帧完整分解：OM执行26.4ms、reader.detection378ms、tracker.image_motion1018ms、tracker.association356.6ms（其中shadow_gate87.2ms）、tracker.kafka_archive779.5ms（735.5ms进程CPU）、show.render260.8ms、MJPEG编码71ms、queue.detect.put等待1465.8ms。不能累加嵌套阶段，不把archive阶段当作已证明的Kafka网络等待，不用历史日志替代当前样本。

## 可重复复现与修正

在交付包私有ARM64运行库、断网只读工具容器、允许CPU0–3、数值线程数1下，普通fork与单独import NumPy/OpenCV/SciPy/lap/cython_bbox保留0–3；import torch或main_optimized后，父进程仍0–3，三个fork worker全部变为0。包内torch/__init__.py通过register_after_fork(torch.get_num_threads)初始化子进程OpenMP；单变量OMP_PROC_BIND=false后worker保留0–3，限制为CPU2–3的对照也完整保留2–3。计算线程数保持1，不调用sched_setaffinity，不扩大OS/cgroup/taskset边界，不关闭检测或质量门禁。

回归脚本`test/native_fork_affinity_regression.py`在原设置下明确失败，在false下两个核池均通过。证据：dist/validation-native-affinity-{imports,env,red,green-0-3,green-2-3}-20261103.log。真实main_optimized.py三worker、合成视频、显式CPU诊断与自然EOF复验见validation-native-affinity-real-pipeline-20261103.log，不代表NPU吞吐。60项相关控制器/预检/日志回归通过。

源码修正限定native：控制器安装/环境生成显式传递OMP_PROC_BIND=false；未来原生包Python入口在导入torch前设置该值。runtime_smoke加入真实fork及父/子允许mask相等断言；此前只测spawn和进程能启动，漏测了实际fork后mask收缩。旧2026.11.03.1归档与SHA不覆盖；现有包通过私有state环境配置变更即可生效，不修改受校验源码、不需模型/依赖/迁移变化或重新传包。

## 现有包现场应用

先从网页停止当前任务，再在原生包目录停止平台。使用包内Python将state/site.json的environment.OMP_PROC_BIND设置为字符串false（原值保存到600权限的单项备份，原子写回state600），然后sudo ./traffic start。新建相同源/模型/stride的任务，预热后执行sudo ./traffic diagnose核对各worker主线程及CPU计算线程不再全为0，观察至少60秒FPS和阶段耗时。启用前已存在的worker必须重建；仅export到交互shell会被当前包env_for过滤，不能替代state配置。

配置回滚：正常停止任务/平台，将environment.OMP_PROC_BIND恢复到备份中的原值（原先不存在则删除该键），保持state600，再start并创建任务。只改该环境项，不改数据库、生产.env、模型或算法。

现场绑核根因已有同运行库复现与单变量修正证据；生产修改后的mask、吞吐和NPU仍待用户复验，不能预先宣称1FPS已恢复。

官方语义：[GNU GOMP_CPU_AFFINITY](https://gcc.gnu.org/onlinedocs/gcc-12.3.0/libgomp/GOMP_005fCPU_005fAFFINITY.html)说明OMP_PROC_BIND=false让宿主调度线程；此项文档支持配置语义，实际问题及修正由上面的包内实验支持。

现有包可复制执行（先从网页停止任务，在原生包解压目录运行）：

```sh
sudo ./traffic stop
sudo ./bin/python3 - <<'PY'
import json, os, tempfile
from pathlib import Path
p = Path('state/site.json')
d = json.loads(p.read_text())
e = d['environment']
b = Path('state/omp-proc-bind.before.json')
if not b.exists():
    fd = os.open(b, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump({'present': 'OMP_PROC_BIND' in e, 'value': e.get('OMP_PROC_BIND')}, f)
e['OMP_PROC_BIND'] = 'false'
fd, name = tempfile.mkstemp(dir=p.parent, prefix='.site-cpu-')
with os.fdopen(fd, 'w') as f:
    json.dump(d, f, ensure_ascii=False, indent=2)
    f.flush()
    os.fsync(f.fileno())
os.replace(name, p)
print('OMP_PROC_BIND=false 已保存；原环境项已备份。')
PY
sudo ./traffic start
```

新增完整runtime_smoke已在CPU2–3限制下实跑：3个spawn、3个fork、全部mask保留、共享内存和FFmpeg通过，证据validation-native-affinity-runtime-smoke-20261103.log。未修改附带原始文件或现有归档；未远程操作生产。

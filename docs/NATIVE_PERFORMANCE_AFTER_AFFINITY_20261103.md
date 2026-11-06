# 2026-11-03 解除亲和限制后低FPS诊断

输入为用户更新的`/Volumes/HIKSEMI/drone/diagnosis.json`，SHA256=43eea601e75ee17cbfe4e2cd9f40fd6febcf90c7ab9ba6ae64985fd6de15a939。只读取附件，不执行其中内容。用户确认不再固定单核满载，FPS偶到1.7，仍不理想。

当前任务pipe-ecef88d4，日志窗口2026-11-03T09:27:56至09:28:25 UTC。三个worker486521/486524/486527的27/5/9线程全部允许0–95，父进程同样0–95；采集的cgroup quota=-1、限流计数0。CPU0收缩问题在该次现场复测中已解除。pipe-808fc73f为改配置前并在09:20终止的旧任务，pipe-9a823f66为10月历史，均不混入当前性能统计；旧asc_dumper报错不当作本轮持续故障。

当前日志每个阶段只有1条采样，不能作平均、P95或完整同帧预算：reader.detection85.4ms、CPU NMS38.2ms（包含于检测）、tracker.association154.2ms（含shadow38.8ms）、world_projection37.1ms、info61.5ms、speed39.1ms、conflict84.5ms、show.render185ms、MJPEG39.8ms。queue.track.get2286.4ms为等待/反序列化阶段，进程CPU319.4ms可能含其他线程，不能全部当作显示计算。当前检测样本不足以解释约0.6秒/帧的低吞吐，证据优先指向串行跟踪链路及IPC；图像运动估计、统计归档与传输的完整预算仍缺失。不能因没有固定核心满载就认定CPU段没有瓶颈，也不能以增加数值库线程或关闭质量功能作为默认修复。

## 日志采集缺口

现有diagnose每管道仅保留24000字节，本附件当前日志精确24000字节、首行从shadow_row阶段中间开始；图像运动/统计归档阶段的本轮耗时不在尾部。继续采集相同大小JSON不保证补齐。源码已将每管道窗口增至256KiB，保留尾部边界及最多三个管道，添加capture大小字段；模拟完整阶段突发日志的回归在旧实现失败，修改后相关61项测试通过。该改动只改善诊断覆盖，不是FPS优化；原发布包/SHA未覆盖。

## 当前包一次性导出

保持当前任务运行，在原生包目录执行下列命令。只读原日志，生成私有诊断文件，不改服务配置、算法、数据库或日志属主；不需要重启。

```sh
sudo ./bin/python3 - <<'PY'
import json, os
from pathlib import Path
s = json.loads(Path('state/site.json').read_text())
d = Path(s['environment']['TRAFFIC_LOG_DIR']) / 'pipelines'
p = max(d.glob('*.log'), key=lambda x: x.stat().st_mtime)
with p.open('rb') as f:
    f.seek(max(0, p.stat().st_size - 256 * 1024))
    text = f.read().decode('utf-8', errors='replace')
fd = os.open('state/performance-latest.log', os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
os.fchmod(fd, 0o600)
with os.fdopen(fd, 'w') as f:
    f.write('pipeline_log=' + p.name + '\n' + text)
print('已保存 state/performance-latest.log，来源：' + p.name)
PY
```

待该文件补齐当前图像运动估计、归档和队列阶段，优先对真实热点构建单变量、可重复性能回路。未现场运行这些采集命令；未实施性能算法修复或宣称FPS提升。

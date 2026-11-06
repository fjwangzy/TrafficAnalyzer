# Platform／检测器原生完整包 2026.11.03.2

目标为既有UOS Server20／aarch64／Ascend310P3。包包含当前完整Platform/检测管道源码、私有Python3.11.15、CANN9.0.0用户态库、FFmpeg和运行库。无需联网安装或手改源码，不依赖旧原生包。Console、数据库、Kafka、模型、视频/SRT和数据目录继续复用现场资源，无开机自启。

本版累计修正：OpenMP fork子进程CPU0绑定（原生入口内置OMP_PROC_BIND=false）；旧root日志/可写目录的提前权限检查；诊断窗口256KiB；轨迹坐标以同值Python标量存储，降低完整历史跨进程传输/GIL争用。原始轨迹点完整保留，不删尾迹、不跳帧提速、不改变模型/分辨率/stride/检测阈值/跟踪算法/质量门禁。

## 解压启动

将压缩包和同名.sha256放在同一目录。先在网页停止当前任务。旧包、旧state、Compose和数据目录保留，解压到独立的新目录；解压磁盘不能为noexec，建议预留25GiB。宿主仍需配套昇腾驱动/固件与设备权限。

```sh
sha256sum -c traffic-analyzer-native-2026.11.03.2.tar.gz.sha256
tar -xzf traffic-analyzer-native-2026.11.03.2.tar.gz
cd traffic-analyzer-native-2026.11.03.2
# 参数是原Docker部署根目录（含生产.env），不是旧native包目录。
sudo ./traffic start --deployment-root /data2/drone/traffic-analyzer-2026.10.19-intranet.1-linux-arm64
sudo ./traffic status
```

如果之前native.1正在运行，本版会根据/app与私有state确认归属、停止旧实例并自动切换；失败会尝试恢复此前应用/代理，并分别输出START_FAILED、RESTORE_SUCCEEDED或RESTORE_FAILED。不要同时用旧入口启动另一套Platform。旧Docker Platform容器须保留以导入现场配置并回退，运行镜像ID和是否源码挂载不作为安装前置。

私有配置自动从现场导入；state目录700、文件600。旧Docker日志一般归root，之后所有traffic命令统一sudo，避免混用账号。不会chmod777或递归chown数据库。配置、数据库实际目标/两个迁移head、厂商库、原始PT/OM哈希、真实三档NPU空图、Kafka认证及公布地址预检通过后才启动原生应用。普通启动不迁移；仅确定需要迁移并已备份、停止所有新旧平台后显式运行sudo ./traffic init-db，不能用它处理普通启动故障。

成功后浏览器仍使用原http://服务器IP:8009，原账号登录，从网页新建相同视频/SRT参数的任务。检测器以main_optimized.py原生三进程启动，不随平台启动自动创建任务。模型、视频、数据库和生产.env不重建、不迁移。Mac/MPS不变。

## 启停和诊断

```sh
sudo ./traffic stop
sudo ./traffic start
sudo ./traffic restart
sudo ./traffic check
sudo ./traffic diagnose
# 停止本包并恢复首次切换前的应用和Console代理：
sudo ./traffic rollback
```

日志继续位于原DATA_ROOT/logs/containers及pipelines目录，标准logging带时间/PID/Pipeline和异常栈，20MiB/6份轮转。监督器输出也只进入轮转日志，state/launcher.log用于启动器错误；诊断在state/diagnosis.json，自动脱敏，分享前复查，不要回传含生产凭据的site.json或整state。此版诊断每管道最多取256KiB，避免遗漏完整阶段周期。

Platform仅监听既有共享Docker bridge网关8000；Console继续通过该桥访问宿主；检测MJPEG只监听127.0.0.1，经平台鉴权代理。DB容器地址每次启动重新解析；实际库/schema必须匹配原生产设置。整个bridge网关若重建需先回退，再用新解压目录重导入；不能通过关闭防火墙/SELinux处理路由故障。

## 本次性能验收

新建任务前先停止旧任务；已有内存中的轨迹不会被配置项原地转换。本版修正需要使用本版源码重新创建任务。保持同一视频、模型、960/自适应设置和stride，预热后至少观察5分钟：FPS、reader.detection、tracker.kafka_archive、queue.detect.put/queue.track.get及show.render/MJPEG耗时。运行时仍应检查worker允许范围，不强改OS/cgroup/taskset限制或NPU内部绑核。

本机同ARM64运行库、合成250车×500点、真实进程队列对照：按线上标量字段构造的统计前台591–733ms降至177–245ms，队列往返725–905ms降至335–409ms，点值/点数一致。该结果仅证明对应代码路径，不代表现场FPS倍数；完整历史量、当前轨迹数和其他串行阶段仍影响吞吐。现场UOS/NPU、Kafka业务ACL、当前真实视频结果与FPS以本次实际复测为准；见VALIDATION.md。

本版完整包不包含旧安装状态、生产凭据、模型/视频、补丁应用入口。旧2026.11.03.1归档及SHA保持不变。

# 四进程与事件保真采样完整原生包 2026.11.03.3

适用既有UOS Server20、Linux aarch64、Ascend310P3。完整包自带当前Platform/管道源码、私有Python3.11.15、CANN9.0.0用户态库、FFmpeg及ARM64库；不依赖先安装旧native包、补丁或联网pip。宿主仍需配套驱动/固件、设备权限及可执行文件系统。Console、数据库、Kafka、生产连接、模型/视频/SRT和数据目录沿用现场；不注册开机自启。

## 本版变化

原生生产默认四进程：读取/检测、跟踪/在线业务、图像/证据、轨迹归档/Kafka。跟踪只发新增点和轻量事实；显示每车最多30个原始尾迹点，不反复传整条历史。第四进程写持久ACK、核对序号/点数/证据文件并等待双路EOF；任何故障不报成功，保留journal/incomplete。图像仍走共享内存，PG入库仍由Platform完成。

新Replay V2任务先完整计算，再按event-faithful/v2保点：同源时间和API毫秒时基的ENU误差≤0.2m、像素误差≤2px；移动/未知速度0.5s心跳、确认静止2s；停车起步边界、转向、TCC/执法/换道窗口默认前后5s密集保留。真实缺口不补点、不连线。均值/P85由完整序列冻结的精确摘要生成，不用稀疏点重算；回放API过滤内部频数。旧任务/旧档案不批量重写，本机Mac/MPS默认不变。

保留此前OpenMP fork绑核修正、root权限检查、256KiB诊断及Python标量优化。无模型/分辨率/stride/阈值调整，无新增依赖/DDL，普通启动不迁移。

## 解压启动

先在网页停止当前任务。包和同名.sha256放在同一目录，解压到独立新目录；旧部署和旧native包保留。建议预留至少25GiB解压空间，另外为工作中journal/完整片段预留容量，不能放在noexec文件系统。旧日志/资源由root创建，所有traffic命令统一sudo。

```sh
sha256sum -c traffic-analyzer-native-2026.11.03.3.tar.gz.sha256
tar -xzf traffic-analyzer-native-2026.11.03.3.tar.gz
cd traffic-analyzer-native-2026.11.03.3
# 此处是含原生产.env的Docker部署根，不是native.1/.2目录。
sudo ./traffic start --deployment-root /data2/drone/traffic-analyzer-2026.10.19-intranet.1-linux-arm64
sudo ./traffic status
```

入口导入原配置及资产路径，验证依赖/双迁移head、厂商库、模型PT/OM、NPU与连接后自动识别/停止旧native并切换。原Docker Platform容器保留用于配置导入及兼容回退，不要求镜像ID相同或必须源码挂载。成功为START_SUCCEEDED，浏览器仍是原http://服务器IP:8009；使用原账号新建相同参数任务。每个新任务应看到4个WORKER_START、ARCHIVER_READY protocol=1、MJPEG_READY；启动不会自动创建默认检测任务。

不要同时运行旧docker-compose/app-compose/host-platform/traffic入口拉起第二个Platform。除明确需要迁移且已备份/停止所有平台外，不执行init-db；源码依赖/迁移门禁不绕过。

## 启停、诊断与验收

```sh
sudo ./traffic stop
sudo ./traffic start
sudo ./traffic restart
sudo ./traffic check
sudo ./traffic diagnose
```

原DATA_ROOT/logs的containers/pipelines继续标准logging与20MiB×6轮转。新日志有egress.enqueue/journal/kafka_delivery/seal/drain、EGRESS_STATUS/COMPLETE、确认水位、队列深度和双路完成；不支持qsize的平台显示-1，不冒充空队列。state/diagnosis.json每管道取最多256KiB，state目录700、配置/诊断600；分享前检查脱敏，不回传site.json或完整state。

普通显示帧的载荷应不随完整历史增长。250车×500/5000点本机基准均约0.78MB，分别下降95.37%/99.54%，尾点与ID一致；本机合成不等于现场FPS。新建任务、保持原模型/帧步长/自适应设置，预热后至少5分钟观察FPS及检测、跟踪、显示和egress等待/写盘/发送耗时。真实UOS/NPU/ACL/性能仍需现场复测。

初始化失败会尝试恢复切换前状态，分别输出START_FAILED和RESTORE_SUCCEEDED/FAILED。中断留下switching时先诊断；在尚无v2新数据的条件下可sudo ./traffic rollback。不要通过chmod777、递归chown数据库或关闭防火墙/SELinux排查；内部MJPEG仍仅127.0.0.1，Console经原bridge访问宿主Platform。

## 数据版本与回退

首个v2任务接受数据后，TRAJECTORY_ARCHIVE_SPOOL_DIR下会有sampling-v2.active。之后入口拒绝恢复不识别v2摘要的旧消费者，即使依赖/数据库head相同；不能直接切回native.1/.2或旧Docker业务消费者。兼容版本之间可按原快照回退。生产消费异常“最新数据优先”规则不变。

如需关闭后续新任务的几何压缩：正常停止任务及平台，将私有state/site.json中environment.HISTORY_SAMPLING_ENABLED设为字符串false，保持600，再start并新建任务。仍使用四进程、完整事实和v2摘要，只输出全部几何点；不把旧任务改策略，也不退回旧的等距50点计算。需要改变0.2m/2px等参数时另做受控版本与验证，不手改受校验源码。

密集关键点若较大，轨迹points可使用可校验gzip-json/v1传输，平台有界还原为逻辑points后入库；不需要更改Kafka服务端大小配置。超过最终预算仍会明确失败并保留原始/待发数据，不通过删关键点“过门禁”。

## 构建及验证

```sh
python3 scripts/build_host_platform.py --native-release --version 2026.11.03.3 \
  --readme docs/NATIVE_DEPLOYMENT_2026.11.03.3.md \
  --validation-report docs/NATIVE_VALIDATION_2026.11.03.3.md
```

内外SHA、HOST_RELEASE.json和VALIDATION.md随包。模型/视频/生产凭据不包含在包内；旧.1/.2归档和SHA不覆盖。详细工程证据见FOUR_PROCESS_SAMPLING_20261103.md和旁置DELIVERY-native-2026.11.03.3.json。

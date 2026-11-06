# 2026.11.04.2 增量轨迹／固定Topic完整原生验收候选包

**现场已确认的入口修复：** 原.2包的init-kafka日志包装白名单遗漏，使用本版本前先按[NATIVE_INIT_KAFKA_FIX_20261104.md](NATIVE_INIT_KAFKA_FIX_20261104.md)应用5KB修复包；无需重复init-db。原完整包不覆盖。

适用既有UOS Server20/Linux aarch64/Ascend310P3。包内自带私有Python、CANN用户态运行库、当前应用源码及Console静态资源；Console、数据库、Kafka、模型、视频和现有私有连接继续沿用。不注册自启。

本候选的验收范围为现有生产ROAD_FEATURES_ENABLED=false配置；路网开启时的旧跨车排队归档推断尚未移植，不作为该路径的全功能等价交付。

本版新增数据库迁移和消息契约，**需要停写后显式初始化，不能作为不迁移的源码热更新**。canonical head为20261019_0021，Replay head为20261104_rv2_0007。新运行库基线保留原依赖字节，仅加入已验证的新迁移；普通start/check只校验，不执行DDL，也不创建Topic。

## 行为变化

- 确认离场后即发布片段，不再等待整场视频；已入库片段可在任务运行或中断时回放。短时遮挡仍按原跟踪器超时恢复。
- 轨迹结束片段先持久化，运行期后台以2秒源时间候选窗口核对外观与运动证据，竞争候选未结束时允许关联晚到。原片段不改ID、不删除。没有外观证据时不合并。
- 生产四进程巡航且ROAD_FEATURES_ENABLED=false时，持久ACK后的在线历史只保留128点；完整点与生命周期索引落盘。Mac默认三进程及仍依赖完整历史的路网/旧跟踪路径保持原行为。
- 统计按受影响五分钟窗口分页重建，从完整速度摘要读取均值/P85；关联后按轨迹组去重计数。EOF须等待数量、摘要哈希及窗口任务对账；手动停止保存manual_stop片段并保持任务中断状态。
- 持久事实收到Kafka确认后仍保留待确认文件，由Platform常驻恢复服务核对数据库提交回执。仅轨迹、关系和必要任务消息定向补偿；其他异常区间不自动补回。
- Topic固定为uav_statistics、uav_track_complete、uav_track_relations、uav_conflicts、uav_telemetry、uav_missions、uav_enforcement_clues、uav_system_metrics、uav_ingest_receipts。路口/相机/来源和任务身份属于消息属性。旧Topic及数据保留，新版不双订阅旧Topic。

## 首次切换

1. 网页正常停止旧任务，停止所有旧Platform实例；备份数据库和当前数据目录，保存旧版本及消费状态。旧包的中断原始归档保留，不自动补算成新任务。
2. 校验SHA并解压到独立新目录，保留旧包。部署根仍指向含原生产.env的Docker部署目录。
3. 在新目录显式执行迁移和Topic初始化。以下副本数1仅用于原Kafka策略已核实为单副本的现场；其他现场必须填写原核实策略，不能照抄降副本数。

```sh
sudo ./traffic init-db --deployment-root /原Docker部署根绝对路径
sudo ./traffic init-kafka --partitions 3 --replication-factor 1
sudo ./traffic start
sudo ./traffic check
```

新Topic的ACL必须由运维按随包app/deploy/intranet/TEST_SOURCE_TOPIC_ACL.json授权；工具不会自动改ACL。只读预检验证存在性、分区、副本及认证元数据；实际Topic写权限、消费者组权限和现场网络仍以真实任务验证。缺Topic或容量不足时会明确拒绝，不能用普通start代替初始化。

后续仍使用sudo ./traffic start/stop/restart/status/diagnose手动控制。正常停止允许最多120秒排空；超过预算保留失败材料，不伪装成功。日志仍在原DATA_ROOT/logs。

## 数据版本与验收边界

新固定Topic数据写入后会留下fixed-topics-v2.active标记；禁止回退到不识别本契约、迁移head或采样摘要的旧消费者。回退需兼容版本及经验证的备份方案，不能仅换回旧目录继续写。

本机工程验证覆盖真实四worker的自然EOF和手动停止、隔离Kafka→PG→运行中回放、窗口统计与哈希对账、900帧在线计算差分及10万结束轨迹的生命周期组件内存测试。合成CPU场景不代表UOS/NPU性能或精度；整管道长稳、现场入库P95/P99、ACL/断线场景及至少三组五分钟同源A/B仍待现场验收，未宣称30%吞吐目标已达成。

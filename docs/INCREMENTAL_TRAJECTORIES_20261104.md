# 2026-11-04 轨迹增量入库与固定 Topic：实现进度

状态：**核心后续源码及工程验证已完成；2026.11.04.2完整原生验收候选的归档状态以旁置DELIVERY为准；未部署生产，现场验收未完成。** 用户授权离场片段立即入库、短窗口关系关联、手动停止保存中断轨迹、轨迹定向补偿、固定业务 Topic；现场同负载吞吐提升目标为30%。不能用以下局部验证替代全部验收。

## 已实现的核心链路

- 结束片段单独持久化并生成稳定身份的轨迹消息；EOF仅发送任务清单，不重复发送全部轨迹。缓存冻结消息供重试，输入身份冲突在发送前拒绝。完整序列统计先冻结，再按既有event-faithful/v2精简几何。
- 固定九个业务Topic：uav_statistics、uav_track_complete、uav_track_relations、uav_conflicts、uav_telemetry、uav_missions、uav_enforcement_clues、uav_system_metrics、uav_ingest_receipts。路口和SourceProfile进入消息属性；按storage_profile选择适配器；任务ID作为分区key。显式初始化脚本为scripts/init_fixed_kafka_topics.py。
- 轨迹事实、inbox与入库回执同事务提交；Kafka ACK后待确认消息留在awaiting-receipt目录。Platform恢复服务定向重发缺少数据库回执的持久事实；用消息ID和哈希幂等。新契约的业务载荷有独立校验和。
- 支持超大轨迹分块、乱序暂存、逻辑校验和与完整组装后可见；重复分块不重复入库。轨迹点以1000点为批次插入。
- 新迁移20261104_rv2_0006增加回执、关系与分块暂存表。普通启动不执行迁移。任务清单到达后先finalizing，声明数量收齐后才能sealed。
- 运行中及中断任务有已入库轨迹即可被回放列表发现。前端每5秒刷新部分任务，区分完整/部分数据。源时间时基冻结，避免低FPS导致T+与墙钟漂移。
- 第四进程完整点数组、完成/丢弃身份与journal校验和索引移入本地磁盘索引；此SQLite仅为私有spool，不是业务数据库。清理发送水位和ByteTrack历史removed引用，投影previous映射仅保留当前帧。
- 四进程手动停止改为父进程请求reader发送manual_stop sentinel，再排空下游；超时仍保留失败材料。新增固定Topic数据标记和兼容回退版本声明。

## 首轮未完成项（历史状态，后续进度见下文）

1. 重识别关系目前只在任务清单阶段调用磁盘候选核对，且仅使用已有外观向量；尚未接入运行中的有界外观提取/候选水位/晚到关联调度。没有外观证据时不合并。
2. 聚合目前仍复用封存任务的全量重建路径；按受影响窗口增量调度、关联后车辆去重计数、最终清单哈希对账尚未实现完整。
3. 跟踪进程仍保留活跃车辆完整历史；第四进程已落盘，但长时间活跃车辆的等价增量状态/历史裁剪尚待逐帧差分验证。
4. Kafka启动前固定Topic存在性及分区/ACL检查尚未全面接入所有启动器。显式初始化脚本已提供；不能假定脚本存在就等于启动门禁完成。
5. 常驻恢复的跨进程竞争、终态隔离、进程退出后的完整故障矩阵，正常停止的真实四worker实跑，以及至少2小时或10万轨迹的整管道RSS验收尚未完成。
6. 尚未提供新完整离线包；现场UOS/310P3的入库P95/P99、至少三组五分钟A/B与吞吐提升30%均未验证。

## 已执行证据

- 后端/管道聚焦合并套件：607 passed、11 skipped、10 subtests，见本轮日志/tmp/trajectory-final-tests.log；后续新增分块及源时钟测试另行执行。最终重跑结果以/tmp/trajectory-final-tests2.log为准，不重复相加用例数量。
- 真实ORM事务测试覆盖轨迹先于任务、原子入库回执、重复身份与异内容拒绝；分块测试覆盖乱序、重复及完整前不可见。
- 根Compose派生的独立项目codex_trajectory_20261104、独立road9卷/15438端口：canonical与Replay双迁移从空库到head通过；真实PG在EOF前持久化、重复消息幂等、运行中列表与回放查询、事务回执通过。未迁移现有开发road9，也未访问生产。
- 前端284 passed；production build通过。
- 本机合成交接基准对比原2026.11.04.1包：250车×500点中位36.35→9.78ms，下降73.1%。完整输出在output/incremental-trajectory-20261104/transport/transport-benchmark.json。即时内存ACK，不含检测、在线业务、磁盘、网络，不作为端到端FPS结论。

## 隔离清理事故记录

第一次隔离PG验证清理误执行根Compose的down --volumes，而仅覆盖了数据库卷名。Docker删除了未挂载的traffic_survey_data、traffic_calibration_data、traffic_pipeline_output_data、traffic_pipeline_spool_data。无法据此确认其中原来是否有数据，未伪装为空卷或已恢复。

仍在运行的traffic_road9_data、traffic_kafka_data未删除；本机原生开发使用的.runtime/survey、.runtime/calibration及output/kafka-spool目录仍存在。此事实不证明被删Docker卷无业务内容。已向用户说明；没有通过创建同名空卷掩盖影响。

第二次隔离验证清理已改为不带--volumes的down，仅显式删除本次创建的codex_trajectory_20261104_pg卷。后续隔离必须覆盖根Compose全部显式命名卷，并只清理本次清单确认创建的资源。


## 后续进度：运行期闭环与候选包

- 运行期关系服务已接入第四进程：磁盘候选索引、每批32个外观描述、缓存可选外观模型、源时间水位、未结束竞争候选阻塞、双向唯一性门禁、持久关系outbox与一次发布。相同Mission的服务重建可继续候选任务；缺证据仍不合并。
- 新迁移`20261104_rv2_0007`新增轨迹组、片段窗口索引、带generation的脏窗口任务、关系应用状态及清单摘要字段。空库和向前升级均显式执行；旧初始迁移使用当前模型的列重入问题已在新迁移中兼容，不改写历史迁移。
- 入库事务登记脏窗口，独立平台任务按256轨迹分页、每批16窗口计算，只查询相关窗口，不在Kafka入库回调中全任务重扫。全序列摘要生成均值/P85；关联后轨迹组入口数及行为去重，原片段和原冲突ID不变。只在完整数量、源片段摘要哈希、关联及窗口任务收敛后sealed。
- 生产四进程巡航、路网关闭的路径在持久ACK后裁掉前缀，默认128点在线尾部，保留绝对序号；结束时P4完整还原再分类。在线车道仍依赖完整轨迹时保留原路径，未把裁剪强加到Mac三进程或路网开启路径。未确认包增加32个硬上限；GeoJSON完成要素改为落盘收集、逐条导出；帧的完成轨迹引用在发布后释放。
- 恢复服务已修复拒绝／未知回执误当成功的问题；隔离事实保留，未知状态不删；单坏文件不阻塞其他记录。发送器和恢复服务共用固定256片文件锁，减少跨进程竞争且不为每条轨迹新增锁文件。
- 固定Topic存在性/分区/副本的只读预检已接入发布器、消费者、恢复服务及原生预检；元数据查询先检查已存在Topic。新增显式`traffic init-kafka`和固定九Topic的ACL清单，副本数必须显式填写并保存为后续检查策略。实时与Replay共享业务订阅并按载荷属性路由；所有运行态要求回执/Replay迁移head，不以live模式跳过新增依赖。

### 本轮验证

- 后端/管道合并套件：663 passed、11 skipped、10 subtests passed；日志`/tmp/trajectory-continuation-final3.log`。最终补充门禁和空间要素测试后的结果以候选包DELIVERY记录为准，不把多轮重跑相加。
- 前端284 passed及production build通过。
- 实际图像跟踪、世界投影、状态、速度、方向和冲突节点900帧差分：逐帧业务字段及结束轨迹完全一致。本场景没有正例TCC，不据此声称新的正例精度验收。
- 2,000点在线传输回归：仅保留64点时，P4还原的全部像素、世界坐标和源时间序列无丢失。1,000空间要素回归验证GeoJSON落盘收集与流式输出。
- 10万结束轨迹生命周期组件：热身后RSS从36,847,616到35,717,120字节，变化-3.07%；约3.92秒。仅为组件负载，不是整管道两小时长稳或现场性能。结果`output/incremental-trajectory-20261104/lifecycle-100k/result.json`。
- 新安全隔离脚本`validate_incremental_replay.py`按随机project为根Compose全部声明卷命名，记录新建清单并按owner label清理；未再使用down --volumes。第4轮隔离实际四worker/Kafka/PG验证：EOF前可查轨迹和回放、自然结束后数量/哈希/窗口统计收敛、手动停止保存manual_stop片段并保持incomplete，均通过。证据`continuation-isolated-4/integration.json`。
- 候选包ARM64私有Python在断网、只读源码及受限CPU容器中完成四spawn/四fork、亲和范围、共享内存、FFmpeg/FFprobe和原生模块导入检查；另完成真实main_optimized四worker合成CPU自然EOF与SHM清理。不是UOS/Ascend实机。
- 小清河原生Mac/MPS真实素材100帧：55 PASS / 0 FAIL / 1 WARN，警告为前100帧方向统计为空；没有重跑mp4728全片，也没有新精度真值。

### 发布与仍需验收的事项

新ARM64运行库基线`traffic-analyzer-native-baseline:2026.11.04.2-arm64`复用原运行依赖，三份依赖声明逐字节一致，仅显式加入新迁移基线；构建不绕过ADR-041检查。候选包要求先停写、备份，再显式init-db与init-kafka；不自动迁移、不删除旧Topic、不批量重写旧数据，旧归档保持。

候选不等于生产验收：UOS/310P3、真实ACL/网络、入库P95/P99、三组五分钟同源A/B与30%FPS目标、整管道长稳及完整故障矩阵仍待验证。已生成的持久消息由恢复服务补偿；强杀后仅存在于增量journal、尚未生成消息的片段／候选，其完整自动重建链路尚未纳入本轮验收，原始journal及待确认数据保留，不能声称所有崩溃时点均已证明最终入库。


### 最终工程复验补充

最终合并回归666 passed、11 skipped、10 subtests passed（另有既有Starlette弃用警告）；前端284 passed/build通过。最后隔离联测`continuation-isolated-delivery`还验证了典型时段矩阵生成、脏窗口归零、封存和中断两个任务状态。关闭几何压缩及三进程Replay路径也保持完整序列和V2摘要，不再先精简50点再计算。

新候选包的最终应用源码已逐文件与工作树核对；ARM64私有运行库spawn/fork与实际四worker自然EOF再次通过。ADR-019 strict代码项通过，既有local_runtime_evidence外部门禁仍未解决，不记为审计全绿。上述结果不是UOS/NPU的现场性能验收。


### 候选归档完成

完整候选包为`dist/traffic-analyzer-native-2026.11.04.2.tar.gz`，4,688,004,442字节；SHA-256为`f817198ef5d15d3d4e8d985b0326d1819fb448358fa0ede59fb9d4f29453529f`。独立流式读取tar验证69,460个内部文件及外部哈希通过；没有解压覆盖现有部署，旧归档未覆盖。候选的完整工程与限制记录在`dist/DELIVERY-native-2026.11.04.2.json`。

本候选按现有生产路网关闭配置验收。旧全任务归档中的lane_verified跨车standing_queue推断尚未移植到新流式归档；路网开启的等价行为仍需专项处理与回归，不能把旧Archive单元测试通过当作新流式路径全部功能等价。


2026-11-04现场发现并修复init-kafka包装器白名单遗漏；60项聚焦回归及原.2 ARM64私有Python真实调用链通过。提供带原文件SHA校验、备份、清单同步和中断重跑的小修复包，原完整归档保留，未重做迁移或现场Kafka操作。详见[NATIVE_INIT_KAFKA_FIX_20261104.md](NATIVE_INIT_KAFKA_FIX_20261104.md)。

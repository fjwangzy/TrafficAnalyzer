# 2026.11.04.3 归档接收性能修复候选

适用既有 UOS Server20/aarch64/Ascend310P3 原生部署。完整包包含私有运行库、应用源码、Console资源与已修复的init-kafka日志入口；不含模型、视频或生产秘密，不覆盖旧包。

## 切换

1. 从网页正常停止当前任务，等待中断轨迹排空；保存当前数据、日志和旧包。
2. 校验旁置 SHA256，解压到独立目录。使用旧版本的 `sudo ./traffic stop` 停止旧 Platform。
3. 进入新目录执行：

```sh
sudo ./traffic start --deployment-root /原Docker部署根绝对路径
sudo ./traffic check
```

从已完成初始化的2026.11.04.2切换无需重复init-db/init-kafka。本版业务迁移、依赖与固定Topic基线未变：canonical 20261019_0021、Replay 20261104_rv2_0007。普通start/check不DDL、不建Topic；若旧环境尚未完成.2初始化，仍按.2文档显式初始化，不能跳过门禁。

新任务使用相同视频、遥测、模型、输入大小、stride和路网关闭配置做对照；测试串行运行，不同时跑两条重负载管道。后续手动start/stop，不注册自启。保留现场私有env、模型/视频、数据库及数据路径。

## 改动与验收

归档端每个活跃轨迹字段仅缓存最新128点，完整轨迹继续落盘；旧水位回查磁盘。增量包批量写入，保持持久ACK、身份/hash、事实与图像合流及双EOF。关联距离只批量计算原类别惩罚，不改门限、匹配顺序或业务频率。

新增日志阶段：egress.append_points、egress.restore_tails、egress.publish_segment、egress.relations_lock_wait、egress.ack_wait。关系锁计时围绕原首个写语句，不改变SQLite事务策略。

现场目标为三组同源、每组至少五分钟稳定处理吞吐≥3 FPS，归档队列不持续满载；另做两小时整管道内存与积压检查。组件结果和完整限制见随包VALIDATION.md及源码docs/FPS_RECEIVER_REGRESSION_20261104.md。本机结果不构成UOS/NPU或3 FPS现场验收。

每组建议运行至少六分钟后保留完整pipe日志；diagnose默认256KiB尾部可能不足五分钟，工具会拒绝把短捕获标成通过。使用随包工具核对三个不同任务的完整日志：

```sh
sudo ./bin/python3 checks/accept_pipeline_fps.py \
  /完整日志/pipe-任务1.log /完整日志/pipe-任务2.log /完整日志/pipe-任务3.log \
  --output /现场可写目录/fps-acceptance.json
```

默认要求每组覆盖≥300秒、整体及后半段≥3 FPS、后半段不低于前半段90%、满队列采样占比<10%。同一个任务的重复导出不算三组。工具只核对吞吐/队列，不代替配置一致性、端到端延迟、两小时内存或精度验收；旧.1只使用已有对照证据，不能在已写fixed/v2数据的生产环境启动旧消费者做A/B。

禁止直接退回不识别fixed-topics/v2、当前迁移或event-faithful/v2摘要的消费者；保留旧数据、失败journal与待确认包，回退须使用兼容版本。

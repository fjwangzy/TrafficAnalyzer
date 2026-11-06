# 2026.11.05.1 完整原生 ARM64 发布候选

适用既有UOS Server20/aarch64/Ascend310P3/CANN9.0.0。包含当前应用源码、Console构建资源、校验复用的私有Python/运行库；不含模型、视频、生产秘密。SQLite保留；此前讨论的去除SQLite或将归档移到Kafka消费端均未实施。

## 本版内容

在2026.11.04.3基础上包含当前工作区的尾迹冻结、frame_delta增量facts、批量图像轨迹变换、增量世界投影、冲突网格预筛及回归修正。轨迹SQLite页缓存默认16384KiB，可通过PIPELINE_EGRESS_SQLITE_CACHE_KIB配置（512..65536，2048恢复此前预算）。持久ACK、SQLite日志/同步/溢写策略、固定Topic和event-faithful/v2摘要保持。

新增可选PIPELINE_PERF_AUDIT=1分项诊断、EGRESS_STATUS.committed本地业务处理水位、修正后的FPS验收工具。本地水位不等于Kafka交付或PG入库回执。详细探针有额外开销，普通启动默认关闭。

## 安装与切换

1. 页面正常停止旧任务，保存当前数据、日志和旧版本。
2. 校验旁置SHA256，将新包解压到独立目录。用旧版本的`sudo ./traffic stop`停止旧Platform。
3. 新目录执行：

```sh
sudo ./traffic start --deployment-root /原部署根绝对路径
sudo ./traffic check
```

复用现场私有配置、模型、视频、数据库和数据目录；后续手动启停，不注册自启。已完成2026.11.04.2/.3初始化的环境无需重复init-db/init-kafka。本版依赖和迁移文件逐字节一致：canonical 20261019_0021、Replay V2 20261104_rv2_0007。普通start/check不DDL、不建Topic；此前未初始化的环境仍须显式完成门禁。

## 现场验证

启动日志须显示`ARCHIVER_READY ... sqlite_cache_kib=16384`。保持相同视频/遥测/模型/输入尺寸/stride/路网开关，串行测试。每组运行至少7分钟，保存完整pipeline日志，使用三个独立任务评估：

```sh
sudo ./bin/python3 checks/accept_pipeline_fps.py \
  /日志/pipe-任务1.log /日志/pipe-任务2.log /日志/pipe-任务3.log \
  --output /现场可写目录/fps-acceptance.json
```

工具要求每组≥300秒、平均及后半段≥3FPS、后半不低于前半90%、满队列采样<10%；缺少committed水位或未知队列深度不能冒充通过。另需核对数据回执、端到端延迟及两小时长稳。Mac上曾出现持续换页和低FPS，本版不宣称已解决现场吞吐问题。

## 兼容与回退

旧包和旧数据保留，不允许切回不支持fixed-topics/v2、当前迁移和v2摘要的消费者。frame_delta是新版私有journal内容，旧writer不支持；新任务产生的失败journal/待确认包应保留并由兼容工具处理，不交给旧writer强行重放。回退前停止写入并保存现场证据，不覆盖任何旧归档。

随包VALIDATION.md与ENGINEERING_CHECKS.json记录实际工程验证，HOST_RELEASE.json/APPLICATION_SHA256.json/CONSOLE_RELEASE.json/SHA256SUMS记录来源与完整性。现场UOS/NPU数值、≥3FPS和两小时长稳独立标记为not_evaluated。

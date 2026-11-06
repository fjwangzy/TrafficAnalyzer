# 2026.11.04.2 验收候选验证记录

这是新增迁移与固定Topic的完整原生候选，不覆盖原2026.11.04.1归档。运行依赖复用原ARM64私有运行库，迁移基线显式更新到Replay 20261104_rv2_0007；普通启动不迁移。

源码与隔离证据见docs/INCREMENTAL_TRAJECTORIES_20261104.md的后续进度及output/incremental-trajectory-20261104。实际四worker合成CPU输入已验证EOF前轨迹入库和回放、自然EOF数量/哈希/统计对账，以及手动停止保存manual_stop片段、任务不伪装自然完成。

900帧真实图像跟踪/世界投影/状态/速度/方向/冲突节点固定输入差分通过，在线历史裁剪前后逐帧业务值和结束轨迹记录一致；此场景不构成真实标注精度测量。2,000点传输测试证明保留64点尾部时完整归档无点损失；生产默认128点。

10万条结束轨迹的真实生命周期组件测试中，热身后RSS未随累计结束数量增长；不是整管道两小时长稳。运行期关联测试覆盖源时间水位、未结束竞争候选、唯一性/外观门禁、恢复和一次发布。窗口聚合覆盖分页、片段关联计数及全序列均值/P85；哈希不符不会sealed。

固定Topic只读预检及显式init-kafka入口已接入，ACL清单固定九个Topic。元数据检查不能代替生产实际写入/消费者组ACL验收。

本包的Linux ARM64私有运行库与归档校验结果以旁置DELIVERY文件为准；UOS/Ascend设备、现场网络/ACL、入库P95/P99、整管道长稳及30%FPS提升仍为not_evaluated。没有外部真值的IDF1/HOTA/正式ID switch、位置RMSE、速度MAE继续not_evaluated。

最终工程回归：后端/管道666 passed、11 skipped、10 subtests passed；前端284 passed/build。根Compose全随机独立命名资源的最后一轮Kafka/PG/四worker联测通过，典型时段矩阵与脏窗口归零确认通过。ARM64私有运行库和四worker断网CPU自然EOF复验通过。源树与候选包app文件逐字节核对通过；最终tar与内部清单结果见DELIVERY。

# 2026.11.04.3 验证记录

本候选修复.2磁盘接收路径的逐车逐字段SQL读取回归，保持当前业务、依赖、迁移及消息协议。最终工程证据见docs/FPS_RECEIVER_REGRESSION_20261104.md、output/fps-regression-20261104与dist/DELIVERY-native-2026.11.04.3.json。

最终合并回归697 passed、11 skipped、10 subtests passed（既有Starlette弃用警告1项）；前端284 passed/build。隔离根Compose派生PG/Kafka与真实四worker联测通过，包括EOF前轨迹入库、源时间/统计摘要、窗口收敛、自然结束及手动停止保存中断轨迹。各轮测试有交集，计数不相加。

新增回归覆盖128点缓存边界、旧帧回查、全部字段/空世界坐标、可变返回值隔离、同包多次追加、坏序号及SQL写失败原子回滚。类别惩罚与旧版成本矩阵逐元素相同，混合类别/低置信度/遮挡的真实跟踪序列一致。

性能基准比较实际.1/.2发布源码及修复版接收组件；Mac三组归一化组件降幅79.9%/82.6%/81.3%，ARM64私有运行库80.2%/79.6%/78.6%。长历史使用每车64点的回填轮次、每包最多1024总点；追加按源步数归一化，原始轮次数据同时保留。长回填轮次的追加本身变慢，不能声称所有写路径加速。近期尾部恢复均0条SQL，字段摘要一致。

候选私有ARM64运行库的四spawn/四fork、亲和范围、共享内存、原生扩展与FFmpeg/FFprobe检查通过；真实main_optimized四worker合成CPU视频自然EOF通过；强杀第四worker后任务失败、journal与未确认包保留、无伪成功及所属SHM清理通过。首次只读容器夹具因默认日志/输出目录不可写失败，改用/tmp工作目录与显式TRAFFIC_LOG_DIR后复跑通过，未改应用写目录语义。

小清河Mac/MPS真实素材100帧复跑55 PASS / 0 FAIL / 1 WARN，direction_stats为空，未达到历史56/0/0。10万结束轨迹生命周期组件RSS热身后-3.1%，不是整管道两小时验收。

UOS/Ascend310P3实机、同源三组五分钟≥3 FPS、两小时整管道长稳和现场P95/P99仍为not_evaluated。没有外部真值的IDF1/HOTA、正式ID switch、位置RMSE及速度MAE仍为not_evaluated。

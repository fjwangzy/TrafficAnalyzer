# 2026.11.04.1 前后端累计完整包验证

包含当前Platform/检测器源码与重新构建的Console资源。依赖及双迁移head按固定ARM64运行库基线检查，普通启动不DDL。版本证据记录于dist/DELIVERY-native-2026.11.04.1.json。

验证范围：前端单元测试及生产构建、Platform/原生控制器/管道回归，最终归档外部SHA与内部清单、离线私有运行库及真实四worker CPU自然EOF、隔离PG/Kafka/Console鉴权API/WebSocket/媒体代理。前端通过HTTP逐字节核对index及其引用的JS/CSS，确认现有Console容器使用本版资源。保留失败恢复快照测试和旧归档。

UOS/Ascend实机、内网网络及真实五分钟性能仍待现场；沿用event-faithful/v2，禁止直接降级到不识别摘要的消费者。合成测试不作为现场FPS或精度验收。

源码回归：前端284项；后端/管道594项及Mac显示传输10项，合计604项通过、11项跳过、10个subtests通过。最终包验证以旁置DELIVERY中的实测结果与日志SHA为准。

## 2026-11-04 现场功能回归反馈（待定位）

用户反馈最新生产包约2fps，冲突事件可生成、测绘标注可用，轨迹回放未查到入库轨迹。该反馈不等同于已确认数据库无轨迹；尚缺任务ID、自然EOF状态与现场消费日志。

源码核对：Replay V2完成片段先进入文件归档，完整journey在自然EOF封存时发布；正式回放列表仅返回sealed任务。运行中、手动停止或失败任务不能据回放列表为空判断入库故障。冲突事实可在running阶段独立入库。不得为排查放宽封存、身份或质量门禁。

本机执行 `.venv-mps/bin/python -m pytest test/test_mission_trajectory_archive.py platform/tests/test_trajectory_replay_inventory.py platform/tests/test_replay_v2_metric_store_contract.py -q`：23 passed；另执行 `.venv-mps/bin/python -m pytest platform/tests/test_replay_api.py test/test_mission_trajectory_archive.py -q`：18 passed（包含重复归档测试，不相加为独立用例数）。这些测试验证现有契约，不代表复现或解决现场故障。

现场下一步：确认任务是否自然结束；若已结束，在当前native包目录运行 `sudo ./traffic diagnose`，检查生成的 `state/diagnosis.json`，脱敏后提供目标任务相关日志。重点核对 `egress.seal`、`egress.drain`、`EGRESS_COMPLETE` 与Platform消费异常；EGRESS_COMPLETE本身也不证明PG消费事务已完成。保留现有归档、journal、Kafka spool及数据库数据，不自动补回消费策略跳过的区间。

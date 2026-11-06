# 2026.11.05.1 验证记录

本版保留SQLite，未实施此前暂停的去除SQLite/更换Kafka归档架构。当前源码相对2026.11.04.3的优化与诊断证据见FPS_OPTIMIZATION_VALIDATION_20261105.md、FPS_REGRESSION_AUDIT_20261105.md、FPS_PAGE_FLUCTUATION_20261105.md。

本版合并回归：742 passed、11 skipped、10 subtests passed；1项既有Starlette弃用警告。覆盖Platform、轨迹归档/增量facts、重识别、有界历史、跟踪/投影/冲突优化、发布与启动门禁。前端284项通过，生产构建通过；包内ARM64私有运行库的四spawn/四fork、共享内存和原生扩展导入检查通过；最终证据由随包ENGINEERING_CHECKS.json和旁置DELIVERY-native-2026.11.05.1.json记录。

依赖和迁移声明对照上一版清单未变；构建过程仍校验不可变运行镜像及运行库全部SHA256。现场UOS/310P3、≥3FPS、两小时长稳、外部真值精度均为not_evaluated。源码/组件结果不替代现场验收。

ADR-019严格本机审计：9项静态检查通过，local_runtime_evidence未通过。既有报告记录canonical head=20260723_0019，与当前20261019_0021不一致；没有改写历史报告、清空现有数据库或把未通过结果标为通过。此限制与当前发布包依赖/迁移基线逐字节校验分开记录。

最终隔离联测通过：空库拒启、显式init-db/双head与init-kafka、错误schema拒绝、私有libpq连接、原生Uvicorn、Console鉴权/API/cookie/媒体会话/WebSocket与静态资源、四worker自然EOF、Kafka→PG轨迹入库和完整序列均值/P85对账。1条完整轨迹300源点保留167点；supervisor正常退出及所属孤儿进程清理通过。

首次夹具因先预检后建Topic被正确拒绝；第二次夹具读取已退役sealed.json失败。已修复夹具为显式初始化固定Topic及读取增量immutable段，并增加条数/原始点/保留点/摘要对应校验，最终完整复跑通过，未放宽生产校验。隔离验证的命名卷/网络全部使用随机project专属名，未触碰现有开发数据。旧失败日志保留并记录SHA。

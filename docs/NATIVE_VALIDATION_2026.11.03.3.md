# 2026.11.03.3 四进程／事件保真v2验证

目标UOS Server20/aarch64/310P3。以完整序列为新业务基准，允许纠正旧“完成轨迹先等距抽稀”的历史偏差，旧数据不主动重算。所有本机测试与正式生产验收分开。

## 已完成的工程检查

- 原有Platform全套、协议/采样/归档/执行器/证据/轨迹/显示/原生入口回归：593 passed、11 skipped、10 subtests passed。命令见旁置DELIVERY及validation-fourprocess-tests日志，跳过项不算通过。
- 真实ARM64私有运行库、断网只读源、真实main_optimized.py四worker/合成CPU推理/自然EOF通过；不是NPU性能测试。
- 独立root Compose派生的PG/Kafka/Console临时project与卷：真实四进程、原生Uvicorn、Kafka至PostgreSQL收敛通过。停车起步300原始点→167保留点；数据库五分钟均值/P85与完整摘要一致，且明确区别于按稀疏点求出的均值。Fixture为已知检测/地理参考的合成契约输入，不宣称检测或真实定位精度。
- 强杀仅fixture拥有的第四worker：整个管道非零退出，journal、发送端未确认线包及incomplete保留，无EGRESS_COMPLETE，nonce前缀共享内存清理通过。单元覆盖队列满/ACK停滞/磁盘错误/seq缺口或身份冲突/证据hash错误/丢失图像EOF/禁止旧消费者降级。
- 时空误差检查覆盖同源float时间与API毫秒时间、直行/曲线/逐步转向、长停车/起步、未知速度、无ENU、质量和原始帧缺口。v2不会为无ENU观测冻结有效速度；时间戳/帧号不当作质量变化。关闭几何压缩仍保留v2全量摘要和全部点。旧档案拒绝清理，采样参数随Mission不可变。
- 250车×500点：显示载荷16813447→779067字节，减少95.37%；250车×5000点167598147→779067字节，减少99.54%。原ID和最后30个原始点保持；这只是相同运行库的合成基准，不外推现场FPS。
- 密集点gzip-json/v1往返、固定编码、长度/hash/点数/膨胀上限及逻辑点还原检查通过；摘要/P85精确频数和跨五分钟边界完整基准一致。

## 最终归档复验

最终tar.gz外部SHA、内部文件清单、重新解压后原生启动入口、4spawn/4fork亲和/共享内存/FFmpeg、真实四worker合成CPU/EOF和隔离Kafka/PG/Console链路复验，记录于DELIVERY-native-2026.11.03.3.json及validation-fourprocess-final-*日志。原.1/.2包保持不变，不包含现场.env、旧安装state或资源包。

全仓Ruff检查存在既有未触及文件的I001/E402等问题（HEAD校验可复现），本次修改文件的lint通过；不会把全仓lint声明为通过。ADR019既有local_runtime_evidence外部门禁未因本次代码验证消除。依赖/迁移基线保持，不新增DDL。

## 尚待现场验收

本版真实UOS/驱动/310P3三档、内网SASL/业务ACL、真实Console到宿主bridge与5分钟FPS/容量仍not_evaluated。相对原序列0.2m/2px不是外部真值RMSE；IDF1/HOTA、正式ID switch、位置RMSE、速度MAE等不新增通过。完整未完成任务数据保留用于诊断，不自动回补跳过的Kafka区间。

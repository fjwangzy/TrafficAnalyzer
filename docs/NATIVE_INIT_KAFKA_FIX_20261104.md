# 2026.11.04.2 init-kafka 日志入口修复

现场2026-11-04 18:04（北京时间）执行`traffic init-kafka`时，日志包装器提示`Expected platform/init-db/preflight/source-check and a command`。失败位于本地包装器参数检查，尚未启动Kafka初始化子程序。

根因：native_platform新增init-kafka调用，但deploy/intranet/run_logged.py固定白名单漏加该阶段。此前隔离验证直接执行初始化脚本，没有覆盖实际native.logged→run_logged→init_kafka链路，是发布验证遗漏。

修复只在原白名单增加init-kafka及对应错误提示；保留任意/路径阶段名拒绝、私有轮转日志、脱敏、信号转发和退出码语义。未改变数据库迁移、认证、模型、连接或Topic策略。

## 现场修复

下载`dist/traffic-analyzer-native-2026.11.04.2-init-kafka-fix.tar.gz`及同名.sha256，放在同一目录。此小包仅适用于原始完整2026.11.04.2。

```sh
sha256sum -c traffic-analyzer-native-2026.11.04.2-init-kafka-fix.tar.gz.sha256
tar -xzf traffic-analyzer-native-2026.11.04.2-init-kafka-fix.tar.gz
cd traffic-analyzer-native-2026.11.04.2-init-kafka-fix
sudo ./apply.sh /data2/drone/traffic-analyzer-native-2026.11.04.2 --check
sudo ./apply.sh /data2/drone/traffic-analyzer-native-2026.11.04.2
cd /data2/drone/traffic-analyzer-native-2026.11.04.2
sudo ./traffic init-kafka --partitions 3 --replication-factor 1
```

仅修复这次入口错误，无需重做init-db。使用目标私有Python，不依赖系统Python；锁定同一个state/control.lock，核对目标版本与原文件SHA，备份后原子更新run_logged.py及APPLICATION_SHA256.json/SHA256SUMS。原文件和恢复journal在state/patches/init-kafka-logged-stage-v1，重复执行幂等，中断可重跑。遇到未知原文件拒绝覆盖，不得删清单、手工改校验值或绕过版本门禁。

现有完整.2归档不覆盖；DELIVERY已追加已知问题及本修复引用。修复包SHA-256：2a2ff35a39f41e345c9f32528ac8c38f9a18d6e8bd2e701bfaa863d88d014fed。

## 验证

- 原命令形态本机复现同一报错；native.logged实际调用链回归先红后绿，覆盖原参数透传、子程序exit=0和exit=7。
- 修复安装器覆盖原文件校验、两份清单一致性、备份、幂等、未知源拒绝和中断重跑。
- 自动核对所有原生logged阶段均在真实包装器白名单内，继续拒绝任意/路径阶段名。
- 聚焦60 passed（test_init_kafka_logged_fix/native_platform/source_upgrade/compose_bootstrap/kafka_topic_preflight）。不是与此前666项重复相加。
- 原.2包ARM64私有Python、断网容器、只读原包，在临时目标应用修复；通过真实native.logged→修复包装器→原init_kafka.py --help，exit=0；未执行DB或Kafka写入。原.2包未修改。
- 实际现场Kafka权限及网络仍由修复后重跑init-kafka验证，本修复不声称已完成现场Kafka初始化。

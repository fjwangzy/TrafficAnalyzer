> 最新累计前后端完整包2026.11.04.1验证与启动说明见[NATIVE_VALIDATION_2026.11.04.1.md](NATIVE_VALIDATION_2026.11.04.1.md)，最终归档重新解压复验通过，完整证据见dist/DELIVERY-native-2026.11.04.1.json。

> 最新完整原生2026.11.03.3（四进程＋事件保真v2）最终解压复验见[NATIVE_VALIDATION_2026.11.03.3.md](NATIVE_VALIDATION_2026.11.03.3.md)与dist/DELIVERY-native-2026.11.03.3.json；本页保留首次原生交付记录，不代表现场NPU/FPS已验收。

# 原生全量包验证记录

版本：2026.11.03.1。目标：UOS Server20 / aarch64 / Ascend310P3。

## 本机完成的验证

- 76项聚焦回归通过：新旧宿主控制器、配置/模型清单、动态数据库地址、特殊字符密码、中文/空格路径、源码/镜像内置Console配置、重复启停、恢复顺序、重启后回退快照、旧/app归属与无关目录保护、PID复用、日志脱敏、Kafka公布地址可达性、管道EOF和执行器。证据：`dist/validation-native-tests-2026.11.03.1.log`。
- ARM64 Alpine隔离工具容器，无系统glibc/Python、断网、只读包、独立/tmp和共享内存：私有Python3.11.15、NumPy1.26.4、SciPy1.17.1、Torch2.2.2、OpenCV4.9、cython_bbox/lap、业务/检测完整导入、三个真实spawn进程、共享内存及FFmpeg/FFprobe通过。子解释器为包内加载器入口。证据：`dist/validation-native-runtime-2026.11.03.1.log`。
- 同样断网/只读环境，用真实PT权重和12帧合成视频、显式CPU诊断配置，运行真实main_optimized.py：reader+detection、tracker+stats、show三个worker正常退出，MJPEG_READY、共享内存与自然EOF通过，无泄漏警告。证据：`dist/validation-native-pipeline-2026.11.03.1.log`。此项没有使用Ascend，不代表生产检测设备改变或吞吐结论。
- 真实三档OM清单、OM文件及源PT哈希通过；无NPU设备时ASCEND_DEVICE_MISSING拒绝执行，不回退CPU。证据：`dist/validation-native-model-gate-2026.11.03.1.log`。这里预期出现1项设备失败、3项推理跳过，是负向门禁通过，不是NPU推理通过。
- 从根Compose+内网+PG覆盖派生独立project、无宿主端口、独立临时数据库/卷及Kafka：普通源码/数据库检查拒绝空库；显式init-db成功，canonical和Replay V2两个head通过；错schema拒绝；私有厂商libpq120007、数据库身份/权限和Kafka元数据公布端点检查通过。没有访问或修改本机road9/现有Kafka业务数据。
- 同一隔离project内，真实包内原生Uvicorn和监督进程、既有Console镜像：代理/ready、登录、Bearer鉴权API、HttpOnly Cookie媒体会话、HLS内容与未登录401、WebSocket握手通过；正常停止及带归属标识的脱离父进程worker清理通过。监督器中仅“查询保留Docker Platform是否运行”的调用使用固定stopped替身，工具环境没有Docker CLI/socket；不是现场一条命令切换验收。证据：`dist/validation-native-integration-2026.11.03.1.log`。所有验证服务/临时卷退出后清理。
- 新包完整文件清单、外部SHA256及最终归档解压复验交付记录：见旁置`DELIVERY-native-2026.11.03.1.json`和同名`.sha256`；归档仅包含代码/运行库/说明/空state目录，不带现场凭据、模型/视频、旧补丁入口或安装状态。

## 现场仍需执行

UOS宿主内核/驱动兼容性、真实三档NPU推理、Console容器到真实宿主bridge的防火墙/路由、现场Kafka SASL/业务ACL、网页创建真实视频/SRT任务、canonical消息落库及至少5分钟稳定吞吐均为 **not_evaluated**。工具容器共享的是本机Linux测试内核，不代表现场UOS或310P3，CPU诊断吞吐不得当作昇腾性能。

用户本次报告约1FPS，无本次现场日志或远程生产访问，根因未复现；本包没有关闭质量/认证/模型门禁或声称Docker是已确认原因。IDF1/HOTA、位置RMSE、速度MAE保持not_evaluated。

## 可复验入口

```sh
python3 -m pytest test/test_native_platform.py test/test_host_platform.py test/test_preflight_diagnostics.py test/test_runtime_logging.py test/test_main_optimized_eof.py platform/tests/test_pipeline_executor.py -q
python3 scripts/validate_native_release.py --package /absolute/path/to/extracted/native-package
```

第二项只用于构建电脑：需要已有ARM64数据库/Kafka/Console工具镜像，使用专属临时project；不在生产主机执行，也不向公网拉取镜像。首次现场启动及5分钟验收方法见README.md。

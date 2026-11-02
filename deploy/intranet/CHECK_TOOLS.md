# 离线检查工具与启动脚本

## Kafka一次离线采集（2026-10-19）

独立工具`diagnose_kafka.py`可放在发布目录外，在现场原部署目录执行
`python3 /工具目录/diagnose_kafka.py --deployment-root "$PWD"`，自动使用现有`app-compose`或`docker-compose`。
可附`--kafka-bin /Kafka/bin --client-properties /原成功配置/client.properties`做宿主Java CLI对照。
采集宿主/容器TCP、逐broker认证元数据、advertised地址、30/60秒检查、只读协调器查询、
kafka-python、路由/防火墙/Docker证据；生成私有报告目录，不输出密码，不加入组、提交或发布业务消息。
完整命令、权限与能力边界、每种结果的后续处理见[KAFKA_DIAGNOSIS.md](KAFKA_DIAGNOSIS.md)。

2026.10.19全量源码版工具路径为 `/app/deploy/intranet/`；旧镜像包工具路径为 `/app/deploy/`。源码 apply 后将下表的 `./docker-compose` 换成 `./app-compose` 执行应用检查，不用源码升级器执行数据库迁移。

从新发布包的解压目录执行。根`.env`已填入生产连接，权限600；intranet.3主配置为同机临时PG `road9:5432/ycx_prod.drone`，账号sysdba；HG另存`.env.hg`。
密码使用根Compose既有变量`ROAD9_PASSWORD`传入容器的`DB_PASSWORD`，不是本机road9库密码。
本包已累计所有修复，无需应用旧的hotfix/repair脚本。

| 用途 | 命令/工具 | 是否修改数据库 |
| --- | --- | --- |
| 校验归档内容 | `./docker-compose verify` | 否 |
| 离线导入镜像 | `./docker-compose load` | 否 |
| 准备资源和访问地址 | `./docker-compose prepare` | 否；创建输出目录、校验/导入模型并更新CORS来源 |
| 启动前完整预检 | `./docker-compose check` | 临时PG版先启动数据库，空目录会初始化扩展/schema；随后只读检查DB/Doris/Kafka及设备/模型 |
| 数据库/Doris/Kafka分项检查 | `./docker-compose run --rm --no-deps platform python3 /app/deploy/intranet/runtime_check.py --connections-only` | 只读检查，跳过NPU模型和资源测试 |
| 厂商驱动加载 | `./docker-compose run --rm --no-deps platform python3 /app/deploy/intranet/runtime_check.py --libraries-only` | 否 |
| DBA只读SQL | `deploy/intranet/db_readonly_checks.sql` | 否；在瀚高客户端手动执行 |
| 显式初始化 | `./docker-compose run --rm --no-deps init-db` | 是；按根.env目标迁移并幂等创建管理员/16源/7无人机 |
| 一键启动 | `./docker-compose up -d` | 临时PG版先启动数据库，预检/init-db成功后启动两应用服务 |
| 查看状态 | `./docker-compose ps` | 否 |
| 查看日志 | `./docker-compose logs --tail 100 platform init-db console2` | 否；日志按私有资料保管 |
| Topic/Group ACL清单 | `deploy/intranet/TEST_SOURCE_TOPIC_ACL.json` | 否 |
| 生成指定源ACL要求 | `./docker-compose run --rm --no-deps platform python3 /app/deploy/intranet/topic_acl.py --source-key SRC-E2BA6A8F6D0F` | 否；只生成清单，不授予权限 |
| 图像/视频资源 | `MODEL_SHA256SUMS`、`MODEL_ARCHIVE_SHA256SUMS`、`deploy/intranet/VIDEO_SHA256SUMS` | 否 |

`check/run`需要镜像已导入、设备挂载及资源目录可用。首次通常直接运行`./docker-compose up -d`；
排查时先`load`、`prepare`。分项诊断返回错误码/处理建议，连接检查不运行迁移。
`DB_TIMESCALE_REQUIRED=false`下允许普通PG表；`ROAD_FEATURES_ENABLED=false`仍暂停路网标注/匹配。
外部HG模式的库和schema由DBA预建授权，不自动安装扩展；临时PG模式空目录由数据库入口创建扩展/schema。两种模式均不复制旧库历史数据。

## 临时PostgreSQL完整包（intranet.3）

主`.env`使用同机road9:5432/ycx_prod.drone；先起PG并等待PostGIS+TimescaleDB健康，再预检/迁移/启动应用。
`DB_TIMESCALE_REQUIRED=true`，两扩展已在数据库镜像中准备，现场不用联网安装。
PG数据在DATA_ROOT/postgres；备份命令为 `sh deploy/intranet/backup-db.sh`，只读备份并生成SHA，失败清理临时文件。
HG原配置和拓扑在`.env.hg`、`docker-compose.hg.yaml`；迁移与回退边界详见HIGHGO_CUTOVER.md，不会自动同步或删库。

## 2026-10-18 实时指标只读诊断

在当前发布目录运行（将新增diagnose_live.py放入deploy/intranet，或用补充包同名工具路径）：

```sh
./docker-compose exec -T platform python3 - < deploy/intranet/diagnose_live.py
./docker-compose logs --tail 200 platform | sed -n '/Error processing Kafka message/p; /quarantined/p; /AuthorizationException/p'
```

工具只读查询最近运行任务的数据库样本和Kafka统计Topic最新记录；不加入业务消费组、不提交offset、不改数据库。
输出任务/SourceProfile/Pipeline身份、FPS/推理耗时/平均车速、地理参考原因与offset范围，不输出口令、Key或原始轨迹。
若Kafka已有FPS而数据库样本为空，继续检查写入/消费日志；若库中已有统计而页面没有，检查浏览器WebSocket与任务身份。
出现offset复用提示时先保留现有数据和原始错误，由明确的数据修复方案处理，工具不自动跳过消息。

## 2026-10-18 NPU与视频地址核验

生产画面应请求同源/api/v1/video/camera/{camera_id}，而不是浏览器localhost:8102；API里的内部video_stream_url与浏览器实际Network请求要区分。无需额外公开动态端口。
新增diagnose_live输出detector_configuration及实际统计的inference_context，配置值不代替运行结果。配合宿主npu-smi info和docker top确认NPU PID归属。
镜像默认入口source CANN环境，保留该入口；绕过入口的Python模块搜索结果不能代表正常检测进程。使用`./docker-compose run --rm --no-deps platform python3 -c 'import importlib.util; print(importlib.util.find_spec("acl"))'`可只读检查正常入口。

## 无日志的卡顿采样（2026-10-18.2）

将diagnose-live-2026.10.18.2.py复制到现有发布目录，检测运行时执行：

```sh
./docker-compose exec -T platform python3 - < diagnose-live-2026.10.18.2.py > live-diagnosis.json
```

检测器loopback MJPEG采样10秒，同时对比Kafka末尾offset推进，输出推理/管道耗时与统计年龄。只读、不保存JPEG、不提交offset、不重启；不同JPEG数为0/1不能单独证明管道死锁。源码修复未自动进入旧镜像，采样脚本可直接用于现有intranet.3。

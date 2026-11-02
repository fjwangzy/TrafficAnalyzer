# 临时数据库与后续 HG 切换

当前主`.env`指向同机Docker服务`road9:5432`，应用目标仍是`ycx_prod.drone`，账号sysdba。
本版内置PostgreSQL17、PostGIS与TimescaleDB；只承载无人机数据。Doris、Kafka、MineMap保持原配置。
数据库不映射宿主机端口，数据持久化于`DATA_ROOT/postgres`。不要删除该目录。

## 当前启动与备份

```sh
./docker-compose up -d
./docker-compose ps
sh deploy/intranet/backup-db.sh
```

入口先导入全部离线镜像、准备资源、启动数据库并等待两扩展健康，再运行预检和init-db，最后启动应用。
备份脚本使用pg_dump自定义格式，校验pg_restore可读取后才保留文件，输出文件及SHA权限600；失败清理临时文件。
本机已完成同版本PG17/相同扩展的空库完整恢复验证：先创建两扩展、调用timescaledb_pre_restore()，再pg_restore并调用timescaledb_post_restore()，核对业务表和超表。此结果不证明HG兼容。
这是单机数据库，不构成HA或正式RPO/RTO验收；请将校验通过的备份另存到受控位置。

## 后续切回 HG

HG原连接完整保存在`.env.hg`（600），三服务拓扑在`docker-compose.hg.yaml`。
这些文件只是保留目标配置，不会自动同步或迁移当前临时库中的数据。
切换前应停写、备份并核对HG的库/schema、角色权限、扩展与版本，再制定数据迁移和回退方案。

PostgreSQL17 + TimescaleDB 的整库dump不能盲目恢复到版本/扩展不同的HG。
应先确认目标兼容性；必要时由应用迁移创建表，再按已批准方案导入业务数据，核对行数、时间范围、ID和证据引用。
本版不连接HG执行这些步骤，也不删除旧库数据。

在现场确认迁移方案后，先将当前主`.env`中已经解析的PUBLIC_HOST/CORS_ORIGINS以及现场资源路径同步到`.env.hg`，
保留其中HG连接，不将主`.env`的DB_HOST=road9覆盖过去。可用以下命令只读核验目标连接：

```sh
docker compose --env-file .env.hg -f docker-compose.hg.yaml run --rm --no-deps platform python3 /app/deploy/runtime_check.py --connections-only
```

HG初始化及应用切换只能在目标检查、备份和数据对账完成后进行；切回HG后临时PG目录和备份继续保留以便回退。
主`.env`与`.env.hg`均含生产凭据，请私密保管。

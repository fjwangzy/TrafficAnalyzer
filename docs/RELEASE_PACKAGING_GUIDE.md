# 本地全量发布与源码更新打包指南

## 2026-10-20 单独宿主Platform排查包

仅为用户授权的原生对照：`python3 scripts/build_host_platform.py --version 2026.10.20.1`导出原ARM64镜像同版Python/CANN/私有动态库及当前源码。与app-package分开，不含模型/视频/私有env；Console与原数据库仍留Docker。UOS Server20系统Python3.12不改。见[宿主安装与切回操作](HOST_PLATFORM_RUNBOOK_20261020.md)，生产兼容性/NPU/吞吐仍需现场验证。

## 同基线直接复制（用户2026-10-19选择）

同一运行时镜像、依赖和数据库迁移均不变时，可以停应用后直接复制application源码目录；不要求执行升级器。现场布局以容器实际/app挂载为准：全量包使用application/app，曾执行源码apply时还应同步app/current对应版本。配套更新application/SHA256SUMS和发布根SHA256SUMS，否则下次./docker-compose的文件校验会拒绝。`.env`、模型、视频、数据目录保留。

本次可直接使用dist/traffic-analyzer-direct-copy-2026.10.19.1目录（或同名压缩文件），其中README给出复制和启停命令；没有安装/升级脚本。它只适配2026.10.19-intranet.1全量基线，依赖/迁移变化仍不能直接覆盖。下面prepare/apply为可选的自动校验和回退方式，不是用户必须使用的入口。

适用当前内网生产：Linux aarch64/ARM64、Ascend 310P3、CANN 9.0.0；同机 PostgreSQL/PostGIS/TimescaleDB，外部 Doris/Kafka/MineMap。在开发电脑的完整 TrafficAnalyzer 仓库打包，在生产机解压部署。macOS 开发仍使用原生 MPS，不运行生产 Platform 容器。

## 2026.10.19全量包出现静态文件403时

该原归档使用宿主静态文件；如果解压/复制收紧Linux文件权限，Nginx worker可能拒读。既有包在发布根目录运行`python3 traffic-analyzer-console-403-repair-2026.10.19.py`，先校验同名.sha256。修复文件见dist；只重建Console并更新清单，不需重新传全量包。新源码已改为容器内复制公开资源并设置755/644，避免依赖解压权限；不要对整个部署目录chmod777。详情见DEPLOYMENT_INTRANET.md。

## 2026.10.19检测器就绪修复源码版

`2026.10.19-intranet.2-app-source`适用于已部署intranet.1全量基线。修复日志突发吞掉MJPEG_READY、Linux fork共享内存重复清理，并累计Console403入口修复；只带源码，不带镜像或模型/视频。按第4节prepare/apply，运行时镜像仍填2026.10.19-intranet.1，不能误填源码版本.2。现场日志的跟踪关联慢另行诊断，不以延长超时或屏蔽警告代替修复。

## 1. 选哪一种包

| 变化 | 打包方式 | 现场操作 |
| --- | --- | --- |
| 首次部署，或 Python/系统依赖、数据库迁移、运行时镜像变化 | 全量包：build → app-package → package | 解压新目录，核对现场路径，`./docker-compose up -d`；显式 init-db 执行迁移 |
| 普通 Python、节点、前端或应用配置变化，依赖及迁移均不变 | 源码更新包：app-package | prepare → apply；只重建 Platform/Console，不迁移数据库 |
| 模型或视频变化 | 单独资源交付 | 不随应用包重复传输；模型须另做硬件兼容验证 |

全量包包含离线镜像、宿主只读应用源码、编译好的前端、配置模板、部署/备份工具与本指南。**模型权重、ONNX/OM、视频、遥测素材不在包内**；只携带资源清单与哈希。私有全量包包含根 `.env` 和保留的 `.env.hg`，按私有文件传输，不能提交 Git 或公开上传。

`source` 子命令生成的是源码准备快照，不能部署，也不是本指南的源码更新包；日常更新使用 `app-package`。

## 2. 本地准备（每次打包前）

在仓库根目录操作，Python 3.10+、Docker Desktop/Engine（支持 Linux ARM64）、Docker Compose >=2.24.4、Node/npm 可用。当前 Dockerfile 使用固定 digest 的 CANN/Node/Nginx/数据库基础镜像；首次构建需要联网。Docker 存储至少空闲 60 GiB，宿主也需留出镜像导出、压缩的临时空间，不靠删数据库卷腾空间。

```sh
cd /Users/yaoyao/ai/TrafficAnalyzer
python3 --version
docker info >/dev/null
docker compose version
node --version
npm --version
mkdir -p dist
```

第一次或前端 lock 文件变化后，在 `console2` 执行 `npm ci`。后续 app-package 会自动运行 `npm run build`，无需手工复制 dist。

打包的是**当前工作树**，包括尚未提交的业务改动。打包期间不要继续改源码，每次使用新版本号；已有同版本归档/构建记录时工具会拒绝覆盖。

私有配置文件已在本机 Git 忽略目录；不要 `cat` 到公开日志。当前同机 PG 参考 `deploy/intranet/release-2026.10.17-intranet.3.private.env`，HG 保留连接参考 `deploy/intranet/release-2026.10.17-intranet.2.private.env`。正式封包前核对实际现场参数，特别是：

- `COMPOSE_PROJECT_NAME`、`ASSET_ROOT`、`DATA_ROOT`；现有站点使用原值，避免误建第二套数据目录。
- 主配置 `DB_HOST=road9`、`DB_PORT=5432`、`DB_NAME=ycx_prod`、`DB_SCHEMA=drone`、`DB_TIMESCALE_REQUIRED=true`；不要填本机开发 road9 数据库。
- `ROAD_FEATURES_ENABLED=false`；生产内网 Doris、Kafka、MineMap及其凭据保持现场值，不能用开发公网值替换。
- `PUBLIC_HOST`/`CORS_ORIGINS` 可以沿用 `auto`，首次启动入口会写回实际浏览器来源；多网卡时明确设置生产访问地址。

## 3. 制作全量包（不含模型、视频）

以下版本号仅为示例，每次换新值。先完成测试（第 6 节），再打包。

```sh
VERSION=2026.10.19-intranet.1
PLATFORM_IMAGE="traffic-analyzer-platform:${VERSION}-arm64"
CONSOLE_IMAGE="traffic-analyzer-console:${VERSION}-arm64"

# 1. 构建四个 ARM64 镜像并验证驱动、应用导入及数据库扩展。
python3 scripts/build_intranet_release.py build \
  --version "$VERSION" --bundled-database

# 2. 以本次新镜像为依赖/迁移基线制作应用源码包。
python3 scripts/build_intranet_release.py app-package \
  --version "$VERSION" \
  --runtime-platform-image "$PLATFORM_IMAGE" \
  --runtime-console-image "$CONSOLE_IMAGE"

# 3. 将自己刚生成的源码包解压，供全量包校验并内嵌。
tar -xzf "dist/traffic-analyzer-${VERSION}-app-source.tar.gz" -C dist

# 4. 打包离线镜像、私有配置和宿主源码，不复制模型/视频。
python3 scripts/build_intranet_release.py package \
  --version "$VERSION" \
  --deployment-env deploy/intranet/release-2026.10.17-intranet.3.private.env \
  --highgo-env deploy/intranet/release-2026.10.17-intranet.2.private.env \
  --model-manifest dist/model-resources-v4/ascend/manifest.json \
  --app-source "dist/traffic-analyzer-${VERSION}-app-source"

# macOS 校验；Linux 使用 sha256sum -c。
(cd dist && shasum -a 256 -c "traffic-analyzer-${VERSION}-linux-arm64.tar.gz.sha256")
```

主要产物：

- `dist/traffic-analyzer-<版本>-linux-arm64.tar.gz`：交付生产的私有全量包，权限 600。
- 同名 `.sha256`：完整归档校验。
- `dist/traffic-analyzer-<版本>-app-source.tar.gz`：同基线源码包，可保留作基线参照。
- `dist/build-<版本>.json`：固定镜像引用、ID、驱动哈希及构建检查结果。

模型清单是构建电脑已有的文件；仅读取其元数据和哈希，不会把模型塞进应用包。已有生产 `ASSET_ROOT/weights` 满足清单时直接复用。若希望入口自动导入一个另外传输的模型包，可额外传 `--model-resource-archive /绝对路径/模型包.tar.gz`；该参数也只记录外部包哈希，不内嵌模型。没有模型资源时，启动会明确拒绝，不能跳过模型门禁。

### 生产机解压部署

已安装匹配的昇腾驱动、Docker 和 Compose，已有模型/视频目录，外部服务可达后：

```sh
VERSION=2026.10.19-intranet.1
sha256sum -c "traffic-analyzer-${VERSION}-linux-arm64.tar.gz.sha256"
tar -xzf "traffic-analyzer-${VERSION}-linux-arm64.tar.gz"
cd "traffic-analyzer-${VERSION}-linux-arm64"
chmod 600 .env .env.hg
# 升级既有现场时先核对 .env 的 project、ASSET_ROOT、DATA_ROOT 为原现场值。
./docker-compose up -d
./docker-compose ps
./docker-compose logs --tail 200
```

入口依次校验文件/ARM64镜像、离线导入、准备资源与访问来源、等待数据库、完整预检、一次性 init-db 迁移，然后启动应用。无需现场 build、pip install、npm 或联网拉镜像。首次即把 `application/app` 只读挂到 `/app`；Console 使用 `application/app/console`。应用生成配置另放可写目录，日志在 `DATA_ROOT/logs`。

已有站点升级全量基线会执行数据库迁移：先在原部署目录执行 `sh deploy/intranet/backup-db.sh`，确认备份可用并在维护窗口停止旧 Platform/Console；不要让旧新应用同时写同一库。保持原 Compose project 和持久化路径，旧包保留。**不要删除 DATA_ROOT/postgres，也不要使用 `down -v` 清数据。**迁移后的应用回滚必须评估旧代码兼容性，不以恢复旧包冒充数据库回退。详见 `docs/DEPLOYMENT_INTRANET.md` 和 `deploy/intranet/HIGHGO_CUTOVER.md`。

## 4. 后续只发源码更新包

先确定生产全量包的实际运行时镜像引用：查看该全量包的 `RELEASE.json`，使用其中 `images.platform.reference` 和 `images.console.reference`。不要随意用最新 tag；源码升级同时验证镜像 ID。构建电脑须保留这些镜像，换电脑时可从全量包的 `images/runtime.tar` 离线 `docker load`。

```sh
# 每次换新应用版本；运行时基线仍指向现场已部署的全量包。
VERSION=2026.10.20-app.1
RUNTIME_VERSION=2026.10.19-intranet.1
python3 scripts/build_intranet_release.py app-package \
  --version "$VERSION" \
  --runtime-platform-image "traffic-analyzer-platform:${RUNTIME_VERSION}-arm64" \
  --runtime-console-image "traffic-analyzer-console:${RUNTIME_VERSION}-arm64"
(cd dist && shasum -a 256 -c "traffic-analyzer-${VERSION}-app-source.tar.gz.sha256")
```

仅传输 `app-source.tar.gz` 和其 `.sha256`，不发镜像、私有配置、模型或视频。若报 `Migration file set changed` 或 `Runtime dependency/migration baseline changed`，回第 3 节出新全量基线，不改清单、不关闭门禁。

现场将源码包解压到**原部署目录之外的新目录**，不能覆盖 `application`、`app/current` 或现有只读发布目录：

```sh
VERSION=2026.10.20-app.1
sha256sum -c "traffic-analyzer-${VERSION}-app-source.tar.gz.sha256"
tar -xzf "traffic-analyzer-${VERSION}-app-source.tar.gz"
cd "traffic-analyzer-${VERSION}-app-source"
DEPLOY_ROOT=/data2/drone/traffic-analyzer-2026.10.19-intranet.1-linux-arm64
python3 upgrade_source.py --deployment-root "$DEPLOY_ROOT" prepare
python3 upgrade_source.py --deployment-root "$DEPLOY_ROOT" apply
```

`DEPLOY_ROOT` 换成实际全量包解压目录。prepare 校验文件、依赖/迁移基线、镜像 ID、导入和数据库当前 head，不停止服务；apply 重复校验，在维护窗口停两个应用、执行 NPU/连接预检、重建并等健康，失败恢复之前配置。数据库、模型、视频和私有 `.env` 保留；源码升级无 DDL。Platform 重启会中断当时检测任务，应在任务停妥后执行并检查恢复。

### 源码更新后的日常操作与回退

```sh
cd "$DEPLOY_ROOT"
./app-compose ps
./app-compose logs --tail 200
./app-compose up -d
./app-compose stop
# 回退到上一次应用配置；首次源码更新可回到全量包的 application 基线。
python3 app/upgrade_source.py --deployment-root "$PWD" rollback
```

首次全量部署用 `./docker-compose`；源码 apply 成功后，日常应用启停改用 `./app-compose`，旧入口仍指向全量包基线。源码版本保留在 `app/releases/<版本>`，指针在 `app/current`；不要手工改只读文件或删除正在使用的版本。更改生产连接仍在原全量部署根 `.env`。

## 5. 常见失败

| 提示/现象 | 处理 |
| --- | --- |
| 镜像不存在或 ID 不同 | 从对应全量包离线导入原镜像，不能重打相同 tag 代替 |
| 版本已存在 | 改新版本号，保留旧归档及记录 |
| 缺模型或模型 SHA 不同 | 核对 ASSET_ROOT 与独立模型清单，补齐匹配资源 |
| 数据库 head 与源码不匹配 | 确认使用正确库/schema及基线；迁移变化走全量包 init-db |
| 解压后页面资源权限失败 | 使用包内归一化 755 目录/644 静态文件；不要用私有 umask 二次复制改权限 |
| 网络、Kafka认证或 NPU 预检失败 | 查看具体诊断并修复环境，不跳过认证/模型预检 |
| 全量包很大 | CANN/PyTorch/数据库离线镜像占主要体积；后续 app-package 才是小包 |

## 6. 打包前验证与验收边界

发布入口相关改动至少执行：

```sh
python3 -m pytest test/test_intranet_release.py test/test_compose_bootstrap.py test/test_source_upgrade.py -q
python3 -m pytest platform/tests -q
(cd console2 && npm test && npm run build)
git diff --check
```

业务变更还需对应业务/管道回归，项目完整快速验证见根 AGENTS.md。发布完成后核对归档 SHA、内部 `SHA256SUMS`、`RELEASE.json`、模型/视频排除、私有 `.env` 600 权限；源码包不能含私有 `.env`。镜像构建/导入和本机隔离数据库验证不能代替现场内网、Kafka业务ACL、真实 NPU 推理/吞吐或正式精度验收。

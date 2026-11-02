# Platform 宿主原生排查包（2026-10-20）

## 2026-10-20 模型清单变量遗漏修复

首版安装器过滤ASCEND_*时误删ASCEND_MODEL_MANIFEST，PIPELINE_ASCEND_MANIFEST仍保留。用户现场switch-host报MODEL_PATH_CONFIG，并授权简单问题直接给修改命令，不要求补丁包。已安装现场在宿主包根目录将state/site.json的environment.ASCEND_MODEL_MANIFEST设为同对象PIPELINE_ASCEND_MANIFEST的现有值，权限保持600；然后重新switch-host，无需install/init-db，不跳过模型清单/PT/OM哈希与NPU门禁。不要回传含密码的site.json。

后续源码修正：安装时保留并翻译ASCEND_MODEL_MANIFEST；env_for为既有缺项状态从已翻译的PIPELINE_ASCEND_MANIFEST补齐，显式值保持。聚焦测试25 passed；ARM64私有原生Python使用真实三档OM清单及PT验证哈希通过，无设备环境在后续ASCEND_DEVICE_MISSING门禁停止，NPU推理仍未评估。原4.4GiB归档及SHA保留，不重新覆盖。


用户确认宿主为 **UOS Server 20、Python 3.12.12**。本包使用独立Python3.11，不向系统Python3.12安装依赖；私有ELF加载器和动态库随包提供。当前没有该UOS实机运行结果，不能将本机Linux ARM64验证当作现场通过。

适用已部署 `2026.10.19-intranet.1` ARM64 运行时基线（包括同基线 .2/.3/.4 源码更新）的 Linux aarch64 + Ascend 310P3 主机。Platform 和其 `main_optimized.py` 检测子进程原生运行；Console、现有 PostgreSQL、Kafka 等继续保持 Docker/原外部服务。Linux bridge 访问数据库，不开放数据库宿主端口、不重建数据库或清数据。生产连接继续复用现场私有配置，Mac 开发与 MPS 不改。

包包含当前完整 Platform/管道源码、原镜像同版 Python 3.11.15/CANN9.0.0 及私有 ARM64 动态库、FFmpeg。通过原生 ELF loader 使用包内库，无容器、chroot 或系统库覆盖，无现场联网 pip 安装，不要求宿主预装 Python3.11 或 CANN toolkit；仍需要匹配的宿主昇腾驱动/固件、设备访问权限、可执行的解压文件系统。运行库来自 Ubuntu22.04，实际宿主内核、驱动、libc/NSS兼容性以现场 prepare/check 为准；未通过不切换。包约需十余GiB解压空间。不要把不可信文件写入此运行库或源码。

## 安装和切换

先在网页停止检测、测绘等任务，选择维护窗口。以下命令需使用可以访问 Docker、昇腾设备和原数据目录的账号；通常使用 root。宿主 `/app` 必须未占用：历史源记录使用 `/app/test_videos`，入口只创建指向本包 app 的软链接，冲突会拒绝，不覆盖其他应用。模型和视频不随包重复传输，沿用现有挂载目录。

将 `.tar.gz` 与同名 `.sha256` 放一起，**解压到原部署目录之外的新目录**。原部署根目录不覆盖：

```sh
sha256sum -c traffic-analyzer-host-platform-2026.10.20.1.tar.gz.sha256
tar -xzf traffic-analyzer-host-platform-2026.10.20.1.tar.gz
cd traffic-analyzer-host-platform-2026.10.20.1
# 只把下面路径换为当前实际全量包部署根目录，里面有原 .env 和 docker-compose.yaml。
./host-platform install --deployment-root /data2/drone/traffic-analyzer-2026.10.19-intranet.1-linux-arm64
./host-platform prepare
./host-platform switch-host
./host-platform status
```

install 校验交付 SHA、现有镜像 ID 和当前 Compose/源码挂载，保存私有 `state/`（目录700，含密码的JSON600），生成可回退的原Compose快照和Console代理配置。不停止服务，不改原 `.env`。prepare 使用原生 Python 导入业务/检测源码并只读核验实际数据库、schema、两个迁移 head，不执行 DDL。

switch-host 再次 prepare，通过后停 Docker Platform；执行模型三档空图推理、厂商库、持久化目录、数据库版本/权限和 Kafka SASL 等现有完整预检；启动宿主 Platform，等待 `/ready`，然后只重建 Console 使之代理宿主网桥地址。启动失败会尝试恢复原 Platform/Console，须查看恢复结果。Doris/YCX既有预检的可选依赖警告政策不变。整个流程不停止数据库/Kafka，不更改其网络、卷或端口。

检测器的未鉴权内部MJPEG仅绑定127.0.0.1，浏览器继续经Platform鉴权媒体接口访问。宿主 Platform 仅监听该部署 Docker bridge 网关的8000，浏览器入口仍为原 `http://服务器IP:8009`。Console API/WebSocket/MJPEG/HLS经过原鉴权代理。宿主防火墙必须允许这个桥接网络的Console访问宿主8000；不要通过关闭防火墙或SELinux排查。若此链路受阻，保留故障证据并 rollback。数据库容器IP在install时采集，若数据库重建导致IP变化，入口拒绝陈旧地址；使用新解压目录重新install，不能擅改数据库目标。

安装不创建systemd自启，便于短期A/B。宿主重启后不会自动启动此排查版；排查期间不要再用旧 docker-compose/app-compose up 拉起第二个 Platform。原平台容器必须保留为 stopped，入口核对它的状态，防止双写。

## 日志、停启和切回

日志仍在原 `DATA_ROOT/logs`：`containers/platform.log`、`containers/preflight.log`、`containers/source-check.log`、`pipelines/<pipeline_id>.log`，沿用20MiB、6份轮转与异常栈。可直接tail；控制命令状态使用标准logging。开启相同视频和相同配置，比较同一阶段STAGE_WAIT/END、CPU亲和和队列反压，原生启动本身不保证FPS改善。

```sh
./host-platform stop
./host-platform start
./host-platform status
# 在没有任务运行时重新做完整只读/NPU预检：
./host-platform check
# 停止宿主Platform，恢复原Compose的Platform和Console：
./host-platform rollback
```

rollback复用安装时的原Compose快照、原镜像和原源码路径，数据/模型/视频/私有env不变，并清理本包自己创建的 `/app` 软链接。包目录与state保留以供检查。回退后继续用原部署目录入口管理服务。期间不要升级/移动原源码目录；也不要同时运行其他源码升级器。若恢复命令失败，查Docker日志，原Compose快照在本包state/docker-original.json（私有，不能公开）。

若prepare报告数据库迁移不匹配，先查是否部署了正确全量基线。仅在明确需要执行迁移并已备份时使用单独的 `./host-platform init-db`；它要求两种Platform都已停止。switch/start不会自动调用init-db，不通过改版本表或关闭门禁强行启动。

## 验证边界与构建

本包用原ARM64运行库进行路径迁移、业务/检测导入、Python子进程、FFmpeg、厂商库选择等本地检查；Mac上的Linux测试环境不能代替生产鲲鹏主机、NPU模型实推、内网Kafka ACL、宿主防火墙或整管道吞吐验收。现场验收结果初始为 `not_evaluated`，IDF1/HOTA、位置RMSE、速度MAE不在本次排查范围。

构建电脑命令（打包当前工作树，禁止覆盖同版本）：

```sh
python3 scripts/build_host_platform.py --version 2026.10.20.1
```

必须保留本包和state为私有文件；最初归档不带凭据，现场install后state含原生产连接。无需将state回传；回传日志前按现有脱敏要求处理。

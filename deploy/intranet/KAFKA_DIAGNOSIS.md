# Kafka离线一次采集（2026-10-19）

将本说明和`diagnose_kafka.py`一起带入内网。脚本独立于发布校验清单，放在发布目录之外即可，
不覆盖受SHA管理的源码。宿主机只需要Python 3.10+、已有Docker/Compose及当前离线镜像；不需要pip或联网。

## 一次执行

在**现场原部署目录**（含私有`.env`、`docker-compose.yaml`的目录）运行：

```sh
python3 /工具存放目录/diagnose_kafka.py --deployment-root "$PWD"
```

如果成功列Topic的Java CLI使用了配置文件，建议第一次就一起传入，避免再次切换网络：

```sh
python3 /工具存放目录/diagnose_kafka.py --deployment-root "$PWD" \
  --kafka-bin /实际路径/kafka/bin \
  --client-properties /实际路径/client.properties
```

`--kafka-bin`指向包含`kafka-broker-api-versions.sh`的目录；在PATH中则可省略。
`--client-properties`必须指向之前CLI成功时使用的原文件，不把密码写在命令行。
此可选项调用现有Java CLI，只保留退出码、API版本标记及异常类名，不保存原始输出或配置内容。
未提供此项会明确标记skipped；不会猜测认证信息。

脚本自动选择存在的`app-compose`，否则用原`docker-compose`。无需应用已成功启动；会创建
唯一命名的临时Platform工具容器，退出时只清理该工具容器。不会执行up/check/init-db、重启应用、
改防火墙、修改私有.env、提交offset、发消息、建Topic或加入业务组；仍会产生临时Docker容器/网络及既有入口的操作日志。

常见耗时约1至4分钟，超时较多或启用Java CLI对照时更久；各阶段显示进度。
宿主机防火墙读取可能需要root。用现场原有Docker执行权限运行；权限不足会保留退出码，
不会自动sudo或将“没有权限读取”当成“防火墙正常”。需要完整防火墙证据时，由现场管理员以有权限的账号运行同一条命令。

生成权限700的`kafka-diagnosis-时间-随机值/`目录，文件权限600：

- `SUMMARY.txt`：分支判断和下一步建议。
- `report.json`：完整结构化证据。将整个目录带回；报告含内网IP、路由、组名等内部信息。

诊断完成退出0只表示采集完成，**不等于Kafka健康**；容器检查未完成退出2，仍保留宿主机报告。
工具本身异常退出会仅显示类型，不输出可能包含连接串的原始异常。

## 自动检查范围

| 层级 | 证据 |
| --- | --- |
| 宿主机 | 配置broker和实际advertised地址的DNS/TCP、连接源IP、IP地址/路由/策略路由、IP forwarding/rp_filter |
| 防火墙 | FORWARD、DOCKER-USER、POSTROUTING规则；nft基础链策略及过滤/NAT表达式（不含注释或日志动作）、firewalld状态（权限/工具缺失独立记录） |
| Docker | 临时/既有Platform容器状态、镜像ID、网络模式、网络名、IPAM子网、masquerade选项；不导出完整inspect或完整Compose配置 |
| 应用配置 | 实际Settings中的bootstrap、协议、机制、凭据是否存在、消费者组；不输出账号、密码、哈希或长度 |
| Kafka | 每个bootstrap独立认证/元数据20秒；应用同款30秒检查；失败再做60秒检查；实际返回broker的TCP及新地址认证/元数据 |
| 消费者组 | 仅FindCoordinator查询；记录节点ID/异常类型，不JoinGroup、不消费、不提交 |
| 检测器客户端 | 使用已安装kafka-python的底层客户端请求元数据，不创建生产者、不发布消息 |
| 可选Java CLI | 在宿主机用原client.properties对相同地址运行broker-api-versions，结果与Python客户端并列保留 |

broker列表及FindCoordinator读取了aiokafka内部接口；版本不支持时记录异常，不能把接口提取失败当作网络失败。
TCP超时为3秒，DNS解析遵循系统resolver时限；容器检查整体由宿主机240秒上限保护。
这里只做少量连接和元数据请求，Kafka侧可能记录认证失败或连接日志。

## 现场分支处理清单

| 报告情况 | 现场下一步 |
| --- | --- |
| `HOST_OK_CONTAINER_FAILED` | 看host_network中的FORWARD/DOCKER-USER、NAT和转发开关；对照Docker IPAM与内网目标网段，检查重叠路由。与正常生产节点对比；由管理员修复准确规则，不清空防火墙。 |
| 宿主机和容器同一地址都失败 | 核对该broker服务监听、节点路由/ACL/白名单；CLI仅列Topic可能只访问了其他可用broker。 |
| bootstrap可用，advertised失败 | 将report中的实际host/port交Kafka管理员，核对advertised.listeners、DNS和每个broker的9093出口；仅更换bootstrap不能保证解决。 |
| TCP成功，Python认证/元数据失败 | 对照成功CLI的security.protocol、sasl.mechanism、用户名及密码。生产约定SASL_PLAINTEXT/PLAIN；若CLI用了SSL/SCRAM，交管理员确认监听器与应用支持范围，不擅自关闭认证。 |
| 单个broker失败，其他成功 | 查该broker的监听/认证/网络/负载。不能以删掉bootstrap中的该地址替代修复，因为metadata仍可能返回它。 |
| `LONGER_PROBE_PASSED` | 30秒失败而60秒成功，只证明本轮延长时间可通；检查部分broker超时、负载、链路延迟后再决定是否调整超时。 |
| Java成功而容器Python失败 | 先看宿主机/容器TCP差异；均成功再对照认证配置、Python库版本及broker认证日志。工具不会比较或导出凭据，不能仅凭此判定Python库有bug。 |
| `EXISTING_CONTAINER_CONFIG_DIFFERS` | 既有容器与当前部署的协议/机制/bootstrap不同。核对现场变更记录；确认后在维护窗口用当前入口重建，不在诊断阶段重启任务。 |
| `COORDINATOR_LOOKUP_FAILED` | 核对报告中的异常类型、组Describe权限、broker/协调器状态；认证和列Topic成功不代表组权限已足够。 |
| `DETECTOR_CLIENT_METADATA_FAILED` | aiokafka成功而kafka-python失败时，重点看库版本、协议兼容及检测器认证参数；不靠更换公网依赖试错。 |
| `METADATA_PASSED_NOW`但之前失败 | 可能是间歇网络或负载；在故障和正常节点各跑一份并对比。采集成功不证明历史故障消失，也不证明业务ACL。 |
| `CONTAINER_CHECK_INCOMPLETE` | 用当前入口`ps --all`核对容器状态，现场检查镜像是否已导入、NPU设备/素材/挂载是否可用、.env是否通过Settings校验。原始启动错误留在现场，分享前脱敏。 |

如需要独立复核某一个broker（替换实际路径/地址），可在宿主机执行：

```sh
/实际路径/kafka/bin/kafka-broker-api-versions.sh \
  --bootstrap-server 37.12.14.66:9093 \
  --command-config /实际路径/client.properties
ip route get 37.12.14.66
```

Topic/Group业务授权要求复用原发布目录`deploy/intranet/TEST_SOURCE_TOPIC_ACL.json`与`topic_acl.py`。
让Kafka管理员按实际业务Topic及`uav-platform-replay-v2`组核对授权和拒绝日志。
本工具不执行Produce/Fetch/JoinGroup/事务/提交，因而不能证明完整业务ACL；不通过发送业务测试消息试探权限。
它也不复验NPU、数据库迁移或Doris，仍需正常启动门禁与现场业务验收。

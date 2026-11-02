# 2026-10-17 Doris 路网与路况本机接入验证

本次按用户授权将公网连接写入 Git 忽略、权限600的 `platform/.env`，并实测后端、API和页面。
用户已确认使用带 `index` 的两张实际表名。未发布生产镜像/修复包；生产内网和昇腾不在本次验收结论内。

## 当前读写边界

- Doris `ycx_xc`：版本、路口、Link、Lane及月度典型路口/路段指标均只执行SELECT；业务值参数绑定，库名校验。
- 瀚高 `xinchan.ycx_drone`：生产无人机应用数据；运行时外部路网/路况不再访问road11/xianchang或依赖PostGIS。
- 本机 `road9.public`、Kafka和原生macOS/MPS保持；16个视频源、7台无人机仍可通过真实接口读取。
- 密码不进入Git、文档、镜像或测试输出；本机安装既有声明的PyMySQL依赖，未新增依赖种类。
- 生产 `ROAD_FEATURES_ENABLED=false` 继续生效；没有将本机接入当作生产功能重新启用。

## 实际表与口径

`dim_data_version` 的启用字段为 `is_enabled`；当前启用版本为 `20260501`。
路网使用 `dim_inter_info/dim_link_info/dim_lane_info`。附近查询使用Doris球面距离，WKT用已有Shapely解码。
官方函数说明：[ST_GeomFromText](https://doris.apache.org/docs/sql-manual/sql-functions/scalar-functions/spatial-functions/st-geometryfromtext/)。
坐标保持既有GCJ-02/ENU契约；Lane仍是候选，不因此升级为正式车道。

| 对象 | 实际表 | 展示字段与聚合 |
| --- | --- | --- |
| 路口 | `dws_tfc_inter_index_m_5mi` | 同版本、同月份、星期/时槽；方向月均延误指数最大值，速度为方向均值 |
| 路段 | `dws_tfc_link_index_m_5mi` | `delay_index_avg`、`stop_time_sec_avg`、`avg_nostop_speed_avg`；当前版本Link的终点路口关联 |

共同最新月份为 `202609`，不跨月混合。过滤删除态；当槽无指标仍保留当月范围并显示missing。
饱和度、服务水平及排队长度无来源时明确返回null；不会以延误指数冒充饱和度。
路口/路段均按延误指数<1.5畅通、1.5..2.0缓行、>2.0拥堵分级，页面同步标注月份、典型时段与延误指数排序。

## 真库与真实API结果

周五07:55（day=5,step=95）：

| 对象 | 总数 | 畅通 | 缓行 | 拥堵 | 缺指标 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 路口 | 8510 | 5388 | 1687 | 1419 | 16 |
| 路段 | 21070 | 15354 | 3341 | 2360 | 15 |

独立SQL复算一个路口的方向最大延误指数，与服务结果一致；路口ID、路段ID均无重复。
只读模型最近一轮冷查询 `16.013` 秒、内存缓存 `0.456` 秒；
HTTP含约15.2MB JSON的实际请求记录为周五07:55 `11.523` 秒、
周二10:00 `22.229` 秒，两次HTTP200。
越界星期/时槽返回422；缺失路口返回404 `DORIS_INTERSECTION_NOT_FOUND`，不写快照或伪造ID。

四个历史演示路口逐项核验：

| inter_id | Link数 | Lane数 | 结果 |
| --- | ---: | ---: | --- |
| `011wwe0z19700001` | 8 | 34 | 导入及附近查询通过 |
| `011wwe28dm500001` | 8 | 31 | 导入及附近查询通过 |
| `011wwe28dr400003` | — | — | 不存在于当前Doris版本，明确404 |
| `011wwe29k1q00001` | 8 | 25 | 导入及附近查询通过 |

保留既有本地地图及无人机绑定；没有自动把礼士路历史ID绑定到另一个Doris路口。

## 自动化与复验方式

```bash
RUN_PG_INTEGRATION=1 RUN_DORIS_INTEGRATION=1 .venv-mps/bin/python -m pytest platform/tests -q
.venv-mps/bin/python -m pytest test/test_preflight_diagnostics.py test/test_intranet_release.py test/test_highgo_hotfix.py test/test_compose_bootstrap.py test/test_road9_compose_runtime.py test/test_main_optimized_eof.py -q
cd console2 && npm test -- --run && npm run build
```

- Platform最终联合：399 passed、3 skipped、10 subtests passed；含公网Doris实测和本机PG集成。
- 3项跳过：缺保留SRT的发现测试1项；需要显式一次性隔离库的Mission清表型集成测试2项。
- 部署/预检/Compose/EOF聚焦：47 passed。
- Console2：25个文件266 passed，production build通过。
- `git diff --check`通过。
- 最终 `/ready`：replay_v2，数据库、Kafka、TimescaleDB、pipeline manager和trajectory replay全部healthy，0活动管道。

首次扩展PG回归误触了既有Mission夹具的整表清理路径，外键约束拒绝，未到commit且事务回滚。
已为这两项按原文件约定补上显式隔离库门禁，避免本机road9再次被该夹具清表；真实接口复核仍为16源/7无人机。
不清理业务记录以追求测试通过。

Doris专项回归覆盖参数绑定、空Link范围、版本启用、缺版本、不混月、缓存/stale隔离、
几何解析、只读限制、错误脱敏、404缺失ID、API的Doris数据与旧饱和度字段分离。
原始安全结果在 `.runtime/doris-validation.json`、`.runtime/doris-api-validation.json`。

## 页面验证和限制

真实本地页面可登录，显示8510个服务器路口、延误指数前三名16.13/8.46/7.74、
202609月份及道路版本，缺失饱和度/排队保留空值；Chrome常规桌面截图见
`../.runtime/doris-dashboard-desktop-20261017.png`，1440×900视口亦检查过，临时视口已恢复。
截图中的底图线为高德实时路况，左侧排名与底部典型时段来源为Doris；不混称两种图层。

内置浏览器切换全市Doris图层出现明显主线程停顿及空白/网格底图；Chrome基础地图和Doris排名正常，
但该轮自动化点击未成功切换Chrome典型图层，不能宣称全量Doris地图交互/视觉性能已验收。
约8510点+21070条几何、15.2MB响应仍有全城加载成本；仅延长该接口客户端超时到60秒，
未做矢量瓦片、视口分页、聚类或几何简化，也未改变源几何以掩盖性能问题。

没有重跑完整视频/昇腾推理、没有公网写入测试、没有内网生产部署；
本次不产生IDF1/HOTA、位置RMSE、速度MAE或生产容量结论。

# 2026-11-03 本地页面真实回归

执行时间：北京时间 22:31–22:36。当前工作树有既存未提交修改，本轮未改业务源码、配置、数据库结构或旧数据。浏览器为 Playwright headed Chromium，1600×1000，无接口 mock。

## 启动及结束状态

- 原生 macOS arm64 Platform 已运行，执行 `scripts/mac_local_platform.sh up` 确认可复用；后端 http://localhost:8000。
- `console2` 执行 `npm run dev -- --host 0.0.0.0`，前端 http://localhost:5173，保留运行。
- `/ready` 为 ready / replay_v2，database、Kafka、TimescaleDB、pipeline_manager、trajectory_replay 均 healthy；结束时活动管道 0。

## 实际执行结果

| 场景 | 结果与证据 |
|---|---|
| 登录 | 默认本机管理员登录成功；退出后访问 monitoring 被重定向到登录；错误密码被拒绝，正确密码可重新登录 |
| 工作台 | 成功显示地图及服务器只读态势，8290 个服务器路口、4 个项目；部分卡片明确为固定演示样例，不计真实检测成果 |
| 视频源 | 监测页实际加载16个源，切换小清河北路成功 |
| 页面启动真实检测 | 启动请求 POST /api/v1/missions 返回201；Mission MSN-034EB6C38E74，pipeline pipe-85006b3a，原生MPS、抽帧3、保持Mac默认三worker |
| 视频及实时数据 | 14:32:10Z完成MJPEG_READY，14:33:33Z采样LIVE 2.8 FPS、261辆、22.2km/h、193 TRACKS；截图稍后数据继续变化，证明非固定快照。浏览器视频img实际尺寸1280×720，WebSocket connected；遥测/统计/冲突GET均200 |
| 停止 | 页面点击停止，POST /api/v1/missions/MSN-034EB6C38E74/stop返回200，提示保留Mission；ready活动管道归零，所检查父/worker PID均已退出；存在下述停止日志问题 |
| 历史回放 | MSN-RV2-a863b59ca9f1在T+120秒显示111条可回放轨迹、19个流向、3条窗口冲突；2倍速播放时间推进至122秒，暂停时126秒；界面保留精度未评估及降级/截断提示 |
| 历史空态 | MSN-HIST-XQH-20260403-F1000返回200，实际journey_count=0、tracks=[]，页面正确显示空态，不计故障或轨迹正例 |
| 事件中心 | 列表150条；输入不存在事件关键词后显示空筛选结果；未执行技术确认、驳回或投递 |
| 测绘 | 列表14个任务；打开既有任务SVY-20261019-66074E的量算页，真实Frame #660底图、变换available、既有388m²对象可见；未新增量算或提交复核 |
| 执法线索 | 工作台和0条线索空态加载成功；未产生或投递线索 |
| 飞行任务/治理/系统 | 7架无人机、16个源、1个计划加载；路口项目4条、系统健康页可打开；系统页有下述React报错 |

## 保留问题

1. 页面停止能完成清理，但停止期间tracker记录WORKER_FAILED/SystemExit:143，父进程PIPELINE_EXIT returncode=143。该错误与本轮停止信号时间吻合；不能记为无错误的优雅退出。未修源码。
2. 无遥测的离线源重复请求telemetry返回404；启动小清河北路后该源遥测恢复200。切换页面时可见WebSocket closed before established告警，但运行时连接及数据已验证正常。
3. 系统与身份页出现React `Each child in a list should have a unique key prop`，指向DataTable传入tbody的列表项。没有白屏，但属于待修前端问题。
4. 地图库Canvas readback和YOLO half弃用告警存在，不作为业务测试失败或性能结论。

这是本机页面功能短时回归，整体结论为“主链路可用，带问题通过”，不是全量验收。真实检测约103秒后主动停止，未跑完整视频自然EOF、未证明归档完整封存或Kafka/数据库逐条对账；历史回放正例来自既有任务。未运行全量单元测试/构建，未新增四worker/v2采样、生产UOS/NPU或精度验收结论。IDF1/HOTA/位置RMSE/速度MAE继续not_evaluated，页面瞬时FPS不作吞吐基准。

## 证据

证据目录：`output/playwright/regression-20261103/`，含截图、页面快照、网络状态、console、最终ready及管道生命周期。重点截图：`05-live-xqh.png`、`07-history-120s.png`。浏览器原始trace位于`.playwright-cli/traces/trace-1793716295273.*`，包含本机鉴权会话，仅本地保留，不提交或对外分享。

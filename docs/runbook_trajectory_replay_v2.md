# 轨迹 Replay V2 shadow 验收手册

> 适用范围：`codex/trajectory-replay-v2` 开发隔离链路。本文不授权 canonical 改名、删除、覆盖或正式切换。

## 1. 隔离边界

- 主演示保持 Platform `8000`、Console `5173`、canonical `uav_*` 表/Topic。
- V2 使用 Platform `8200`、Console `5273`、视频端口 `18101+`、`uav_replay_v2_*` 表/Topic和消费者组 `uav-platform-replay-v2`。
- `/monitoring` 只验实时 BEV；`/gis` 只验 sealed Mission 回放。发现监控页请求 `replay-missions` 或 `replay` 即失败。
- 视频、权重、SRT/JSON 遥测直接引用 `/Users/yaoyao/ai/TrafficAnalyzer` 的绝对路径。不得复制到工作树；spool、输出和证据使用 `/private/tmp/traffic-analyzer-replay-v2-*`。
- V2 TCC 两图默认写 `/private/tmp/traffic-analyzer-replay-v2-survey`；live profile 仍使用原有工作树/runtime 配置，两者不得共用相对目录。

## 2. 启动

先确认 `5432`/`9092` 可用，且 `8200`/`5273`/`18101+` 未被占用。V2 Platform 使用主工作树现有原生 MPS 环境，但运行代码来自本工作树：

```bash
cd /Users/yaoyao/.codex/worktrees/611d/TrafficAnalyzer
APP_RUNTIME_PROFILE=replay_v2 \
PLATFORM_INSTANCE=replay_v2 \
MPS_VENV_DIR=/Users/yaoyao/ai/TrafficAnalyzer/.venv-mps \
scripts/mac_local_platform.sh up

cd /Users/yaoyao/.codex/worktrees/611d/TrafficAnalyzer/console2
VITE_PROXY_TARGET=http://127.0.0.1:8200 \
npm run dev -- --host 127.0.0.1 --port 5273
```

默认 live 启动命令和端口未改变。不要把 `APP_RUNTIME_PROFILE=replay_v2` 写入全局 shell 配置。

## 3. 启动探针

```bash
curl -fsS http://127.0.0.1:8000/ready
curl -fsS http://127.0.0.1:5173/
curl -fsS http://127.0.0.1:8200/ready
curl -fsS http://127.0.0.1:5273/
```

V2 日志必须显示只订阅
`^uav_replay_v2_(statistics|track_complete|conflicts|telemetry|mission)_.+$`。非认证 POST/PUT/PATCH/DELETE 应返回 405；认证登录仍可用。V2 不应启动 Mission scheduler、survey worker、告警同步或 canonical WebSocket 派发。

## 4. 数据与迁移核对

V2 Platform 只运行 `platform/alembic_replay_v2.ini`，版本表必须为
`uav_replay_v2_alembic_version`。当前 V2 head 是 `20260805_rv2_0003`，canonical head 保持
`20260728_0020`。

迁移前后至少记录：

1. `uav_alembic_version`；
2. canonical inbox、track event/point、telemetry、traffic metric、conflict 的精确行数；
3. canonical `information_schema.columns` 的稳定 checksum；
4. V2 hypertable 与 `policy_compression/policy_retention`；
5. intersection/link/lane/turn 真实 5 分钟聚合和独立典型矩阵均来自完整 sealed Mission；
6. Kafka canonical Topic offset 和 Topic 数量。

任何 canonical 版本、schema 或非实时增长之外的行数变化都阻断验收。V2 秒级 metric sample 的 shadow 策略固定为 7 天后压缩、90 天后保留清理。

## 5. 单 Mission 回放验收

1. 每次生成新的 `mission_id/run_id/pipeline_id/output/spool`。
2. 设置 `TRAJECTORY_STORAGE_PROFILE=replay_v2`、稳定 `SOURCE_PROFILE_ID`，并把
   `MISSION_TRAJECTORY_SPOOL_DIR` 指向新的 `/private/tmp/traffic-analyzer-replay-v2-*`。
3. 串行运行到自然 EOF；异常退出必须保留 incomplete spool，且默认 Mission 列表不可见。
4. 自然 EOF 后核对只发布一次 sealed Mission，最终 journey 数与 PG track event 数一致，点列索引、冻结速度、episodes/maneuvers 和 runtime segment lineage 完整。
5. Stats 不得携带完整轨迹尾迹；重复消费由 V2 inbox 幂等，数据库提交成功后才手动提交 offset。
6. 调用：

```text
GET /api/v1/trajectories/{intersection_id}/replay-missions
GET /api/v1/trajectories/{intersection_id}/replay?mission_id=...&cursor_sec=...&window_sec=...&page_after=...
```

7. `/gis` 默认最新 sealed Mission，T+0 至结束连续播放，支持 `0.5x/1x/2x/4x`；“全部 Mission”必须可稳定停留并禁用播放。回放查询固定使用 10 秒短窗；播放按 1 秒壁钟步进，上一请求未返回时不得推进，任意时刻最多保留一个回放请求。流向排名主标题必须显示“东进口 → 西出口”类物理方向，`straight/left_turn/right_turn/u_turn` 只能作为推断证据或筛选条件，不能替代物理流向。地图必须绘制 sample-and-hold 单点的当前端点，不能因仅有一个保留点而显示空底图。缺少世界坐标时显示像素平面，明确 quality gap 不连线，时间轴同时标注行为、gap 和冲突。
8. `/monitoring` 继续等待或显示实时 Pipeline 轨迹，不得出现 sealed Mission、历史 journey 或回放时钟。

## 6. 自动化门禁

```bash
python -m pytest test -q
PYTHONPATH=platform python -m pytest platform/tests -q
cd console2 && npm test && npm run build
cd .. && python test/test_pipeline_inter_xqh.py
python scripts/audit_adr019_retirement.py --scope local --strict
git diff --check
```

五个既有 SourceProfile 必须分别完成原生 MPS、自然 EOF、Kafka/PG 精确对账和浏览器回放。没有批准真值时 IDF1、HOTA、正式 ID switch、位置 RMSE、速度 MAE 和 ReID 准确率全部记录为 `not_evaluated`。

五源隔离运行器不调用 Mission 注册/停止控制面，直接引用主工作树素材，并在每源结束时执行 Kafka/V2 PG 对账：

```bash
/Users/yaoyao/ai/TrafficAnalyzer/.venv-mps/bin/python \
  scripts/run_replay_v2_acceptance.py \
  --output-dir /private/tmp/traffic-analyzer-replay-v2-five-source-$(date +%Y%m%d) \
  --frame-stride 14 --imgsz 640
```

运行器还必须报告 `canonical_topic_writes={}`；它只对已经存在的 canonical Topic 查询 offset，不能因门禁自身触发 Topic 自动创建。2026-08-05 基线证据为 `/private/tmp/traffic-analyzer-replay-v2-five-source-batched-20260805/summary.json`：5/5 sealed、6,539 journey、25 个 V2 Topic、预留 canonical Topic 为 0，canonical 六项行数为 `292244/19493/902896/102406/36245/103`。

XQH 全长复验位于 `/private/tmp/traffic-analyzer-replay-v2-xqh-full-20260805-v4`。原始 `summary.json`
保留运行器在聚合事务尚未完成且 turn 维度未降级时的失败；修复后不得覆盖原证据，使用
`postfix-reconciliation.json` 记录同一 sealed Mission 的最终通过结果。`isolation-after.json` 记录迁移、
canonical 行数、Topic offset/保留配置和四个服务探针；`api-acceptance.json` 记录 Mission 摘要与本机查询延迟；
`browser/gis-t500.png` 和 `browser/monitoring-realtime-empty.png` 分别证明研判回放和实时 BEV 空态边界。

## 7. 停止与切换门

```bash
cd /Users/yaoyao/.codex/worktrees/611d/TrafficAnalyzer
APP_RUNTIME_PROFILE=replay_v2 PLATFORM_INSTANCE=replay_v2 \
MPS_VENV_DIR=/Users/yaoyao/ai/TrafficAnalyzer/.venv-mps \
scripts/mac_local_platform.sh stop
```

全量门禁通过后仍停在 shadow。正式切换必须另行批准暂停旧写入、归档 canonical 事实、迁回正式命名并保留旧 Topic/offset/历史数据为只读证据；本手册不包含任何删除命令。

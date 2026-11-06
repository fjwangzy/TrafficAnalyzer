# AGENTS.md — Codex 长期协作规则

## 2026-11-03 四进程与历史数据版本

用户授权原生生产每管道四worker：reader/detector、tracker/在线分析、show/图像、egress/Kafka/归档。新增跨节点字段在FrameElement声明；模块内维护增量、持久ACK、显示快照、双EOF和失败清理，不在入口堆业务算法。仅新任务启用事件保真v2；完整计算后冻结均值/P85等统计并与回放几何分离，旧任务/档案不批量重写。当前内网路网开关、Mac/MPS默认、依赖/迁移和认证模型门禁保持。


## 2026-11-03 生产原生应用部署例外

按用户授权，内网Platform/检测器可使用完整原生ARM64包，Console/数据库/Kafka保持现有服务。使用deploy/native-platform/控制生命周期；检测仍以main_optimized.py为唯一生产入口，无Docker检测回退或系统Python依赖。首次配置导入与后续手动启停统一traffic入口；不得绕过模型、生产认证或ADR-041依赖/迁移基线。Mac/MPS开发态不改。详见NATIVE_DEPLOYMENT.md。


## 2026-10-19 最新数据优先降级约束

用户明确授权消费异常后以最新数据恢复功能：offset不作身份门禁，inbox保留原始运输位置并用消息ID及哈希去重。
失败记录不原位无限重试；受影响分区跳最新并提交，解码等无记录上下文的异常作用于已分配分区，
broker不可达时保留有界退避重连，重连后丢弃旧积压。日志必须记录失败位置与恢复offset。
跳过区间不自动补回；不可把异常消息绕过契约/身份校验广播为有效事实。详见API_CONTRACTS与恢复报告。

> 本文件是 Codex 在 TrafficAnalyzer 仓库中长期协作的工程规范。
> 根目录 `AGENTS.md` 是入口索引；本文件记录稳定开发规则、模块边界和验证要求。

## 基本原则

- 先读后写：修改代码前先阅读目标文件、直接依赖和相关契约文档。
- 保持节点式管道：视频分析能力优先落在 `nodes/` 节点中，不在 `main_optimized.py` 内堆业务逻辑。
- 以 `FrameElement` 为唯一帧级数据载体：新增跨节点字段必须在 `elements/FrameElement.py` 声明。
- 配置驱动：运行参数进入 `configs/app_config.yaml`，需要容器差异时通过环境变量或 Hydra override 注入。
- 不回退用户已有改动：工作树可能包含并行修改，除非用户明确要求，不还原不相关文件。
- 遵守 ADR-019：本机唯一数据库为 database=`road9` + TimescaleDB，UAV Topic、`msg_type`、WebSocket channel 和自建表使用 `uav_` 前缀；旧库与旧观测链路已退役，历史数据不迁移，不得恢复兼容或挂载旧存储。
- 遵守 ADR-020：Apple Silicon 开发态 Platform 必须原生运行于 macOS arm64，并以本地子进程直接使用 MPS；Docker Compose 仅用于生产发布，不得作为 Mac 开发启动入口，也不得静默回退 CPU。
- 遵守 ADR-025：成熟图像轨迹不受地理或路网质量门禁抑制；当前帧视频/SRT矩阵独立负责
  ENU/GCJ-02，Runtime Road Map Bundle 只影响 Lane ID、Link ID 与匹配质量。任何地图缺失、
  版本不兼容或匹配失败都不得结束、丢弃或拆分 `track_id`，也不得创建或覆盖世界坐标。

## 模块边界

| 模块 | 边界 |
|------|------|
| `elements/` | 共享数据模型，只被管道节点和入口引用 |
| `nodes/` | 视频检测、跟踪、态势、冲突和输出节点 |
| `utils_local/` | 几何、单应性、车道推断等纯工具 |
| `byte_tracker/` | ByteTrack 移植代码，参数优先从配置调整 |
| `platform/app/` | FastAPI 单体平台，不重新拆回微服务 |
| `platform/app/services/pipeline_executor.py` | Pipeline 本地子进程 `start/inspect/stop` 执行边界；Mac 开发与 Linux 生产通过配置选择设备 |
| `console2/` | 当前 React 前端，使用 canonical REST/WebSocket 契约 |
| `traffic-fly-console/` | 已退役子模块，仅保留历史审计，不进入 Compose、Nginx 或发布构建 |
| `docs/` | 架构、业务逻辑、API、数据库和测试报告，完成任务后同步更新 |

## TCC 闭环验证习惯

优先使用可重复的自动化验证：

```bash
python test/test_pipeline_inter_xqh.py
python -m pytest platform/tests -q
python -m pytest test/test_kafka_active_trajectories.py test/test_utils_local.py test/test_byte_tracker_core.py test/test_main_optimized_eof.py test/test_road9_compose_runtime.py test/test_telemetry_file_reader.py test/test_video_reader_frame_stride.py -q
cd console2 && npm test && npm run build
python scripts/audit_adr019_retirement.py --scope local --strict
```

当前 inter_xqh 端到端基线为 `56 PASS / 0 FAIL / 0 WARN`。如果测试资产或权重缺失，应记录缺失项，不能把未运行的验证当作通过；该基线也不能替代 ADR-019 的空白 `road9`、canonical 消息、本机运行态和旧资产隔离验收。

## 文档同步

涉及以下能力时必须同步对应文档：

- Kafka/WebSocket/API 契约：更新 `docs/API_CONTRACTS.md`。
- PostgreSQL/TimescaleDB schema、表、历史迁移或 Topic：更新 `docs/DATABASE_SCHEMA.md`。
- 管道节点、数据流或进程模型：更新 `docs/ARCHITECTURE.md` 和 `docs/BUSINESS_LOGIC.md`。
- 验证结果、TCC 交付状态：更新对应真实素材报告（当前 mp4728 为
  `docs/test_report_mp4728_20260728.md`）、`docs/test_report_inter_xqh.md` 和 `docs/TASKS.md`。

## 禁止事项

- 禁止新增绕过 `main_optimized.py` 的生产入口。
- 禁止在 ShowNode 中加入业务判定逻辑。
- 禁止将 `platform/` 重新拆为 gateway/services/shared 微服务结构。
- 禁止恢复无前缀 Topic/`msg_type`/WebSocket channel、旧数据库自动迁移或已退役观测依赖。
- 禁止使用 `python-jose`，平台鉴权使用 PyJWT。
- 禁止把旧的 0.9m~1.7m CPA 擦肩事件重新作为默认机非冲突业务口径。


## 2026-11-04 增量轨迹与固定Topic改造（工作中）

用户已授权离场片段入库、短窗口重识别关联、手动停止保存中断轨迹、轨迹及必要任务事实的定向补偿，以及按业务类型固定Kafka Topic。该授权更新此前按相机/SourceProfile分Topic及所有消息异常跳过不补的约束；其他历史区间仍不自动补回。实现、验证、未完成项及本机隔离清理事故见[INCREMENTAL_TRAJECTORIES_20261104.md](INCREMENTAL_TRAJECTORIES_20261104.md)。当前未完成整套验收，未发布新包。

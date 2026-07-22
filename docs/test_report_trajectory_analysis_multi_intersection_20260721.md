# 轨迹研判多路口验收报告（2026-07-21）

## 1. 验收结论

T-482 的数据链、分析读模型和 Console2 主交互已经实现。使用本机 canonical PostgreSQL
database=`road9` 对四个真实路口执行同一验证脚本，共读取 50,301 条完成事实；按
SourceProfile + Mission + Pipeline + Track ID 去重后为 28,487 条唯一轨迹。默认“最新可回放数据段
30 分钟”在四路口分别返回 24、18、50、14 条可渲染且发生移动的世界坐标轨迹；全历史模式均按
上限返回 50 条。流向排名优先完整或明确标注为推断的流向，地图不再一次性铺满全窗口轨迹；
YOLO 原始类别与业务车型分列参与筛选和研判。

筛选顺序固定为“来源/任务/时间窗口取候选 → lineage 去重 → 业务车型/YOLO/方向/质量过滤”，
避免旧版本或重复完成事实使原始分类数量虚增。浏览器实测 `INT_camera_1` 的 YOLO class 3 汇总与
筛选后 KPI 均为 4,800 条；选中流向后 KPI、时间轴、当前时间片和证据同步聚焦。

当前结论为应用层通过；生产镜像、外部秘密、TLS/SASL、HA、容量和保留策略仍受 ADR-019
外部门禁约束，不在本机验收范围内。

## 2. 实现范围

- 检测与完成轨迹消息保存 `yolo_class_id/name/model_id/class_mapping_version`；模型标识为权重
  文件名加 SHA-256 短摘要。
- Alembic `20260721_0014` 为 `uav_track_events` 增加 YOLO 和入口/出口类型化列及可信
  payload-only 回填；`20260721_0015` 增加来源窗口与 lineage 索引。本机 `road9` 已在该 head。
- `GET /api/v1/trajectories/{intersection_id}/analysis` 统一返回质量、时间桶、流向排名、业务/
  YOLO 分类、时间片轨迹和冲突；时间桶不超过 720。
- 冲突按可用的 SourceProfile、Mission、Pipeline 与 Track ID 归因，禁止裸 Track ID 关联。
- Console2 `/gis` 默认展示当前时间片、流向排名和证据下钻；地图最多显示 60 条当前片轨迹，
  渲染上限不覆盖窗口总量 KPI。

## 3. 真实路口结果

执行命令：

```bash
DB_HOST=127.0.0.1 DB_PORT=5432 DB_USER=traffic DB_NAME=road9 \
  .venv-mps/bin/python platform/scripts/verify_trajectory_analysis.py --intersection-limit 4 --period latest30m
DB_HOST=127.0.0.1 DB_PORT=5432 DB_USER=traffic DB_NAME=road9 \
  .venv-mps/bin/python platform/scripts/verify_trajectory_analysis.py --intersection-limit 4 --period all
```

| 路口 | 原始事实 / 全历史唯一轨迹 | 默认 30 分钟唯一轨迹 | 默认片可移动轨迹 | 位移中位/最大 | 路径中位/最大 | 默认分析耗时 | 最高有效流向 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `INT_mp4new_chonghua` | 24,734 / 12,513 | 1,086 | 24/24 | 5.26 / 23.22m | 5.34 / 27.55m | 402.5ms | 南进口 → 东出口，20 辆，4 个冲突 |
| `INT_mp4new_haiyou` | 13,298 / 6,477 | 1,229 | 18/18 | 0.12 / 3.45m | 0.24 / 5.05m | 371.0ms | 南进口 → 东出口，12 辆 |
| `INT_camera_1` | 8,111 / 7,436 | 6,630 | 50/50 | 0.55 / 1.09m | 0.82 / 1.42m | 1,314.5ms | 北进口 → 南出口，53 辆 |
| `INT_mp4new_lishi` | 4,158 / 2,061 | 743 | 14/14 | 0.75 / 6.14m | 0.84 / 6.14m | 207.7ms | 南进口 → 东出口，16 辆 |

默认窗口均为 180 个 10 秒时间桶。不可回放记录仍计入唯一轨迹总量，并通过质量字段公开，不在
地图生成伪轨迹；同一 lineage 重复完成事实通过 `duplicate_tracks_omitted` 公开，不进入占比与排名。

`EXPLAIN (ANALYZE, BUFFERS)` 对崇华路默认窗口的过滤 SQL 使用 `ended_at` 索引并执行增量排序。
四路口默认窗口分析均在本机应用层完成；`INT_camera_1` 候选量最大，耗时 1,314.5ms，其余三个
路口为 207.7–402.5ms。该结果只用于本机应用验收，不代替生产容量门禁。

## 4. YOLO 历史数据说明

四路口旧记录保留了原始 class ID（主要为 3、9，并含 0、4、5、8 等），但缺少当时模型名称
和权重身份。因此页面必须显示“名称未知”，本次迁移没有使用当前模型字典补齐。新检测链已经
由单元/消息契约测试证明会同步输出 ID、名称、模型摘要和映射版本；下一批真实新轨迹将具有完整
来源信息。

## 5. 自动化验证

- `python -m pytest platform/tests -q`：170 passed，5 skipped，10 subtests passed。
- `python -m pytest test_yolo_track_provenance.py test_kafka_active_trajectories.py -q`：6 passed。
- `cd console2 && npm test`：16 files、101 tests passed。
- `cd console2 && npm run build`：Vite production build passed。
- 四路口验证脚本：全历史与默认 30 分钟均为 4/4 passed；每个时间片非空、轨迹上限、可渲染性、
  移动性、唯一轨迹聚合和桶数断言通过。

## 6. 浏览器与视觉验收

- 在 Codex 应用内浏览器以同一 `1487 × 1058` 内容视口，将冻结视觉基线与真实页面并排比较；
  修复了右侧 23 条流向排名撑高整个工作区、导致地图和时间轴跌出首屏的问题。桌面地图/侧栏高度
  现在限制在 `560–640px`，窄屏侧栏固定为 420px 并移到地图下方。
- `900 × 989`、`1280 × 809`、`1440 × 989`、`1920 × 1169` 四档实测均无横向溢出；900px
  断点为单列，其他三档为地图+侧栏双列。
- 真实页面逐一切换崇华、海右、礼士和小清河北路四个路口，均返回非空当前时间片。YOLO class 3
  筛选分别得到 412、656、537、4,800 条去重轨迹；崇华流向聚焦后当前片仍有可回放轨迹。
- 回放速度 `2×` 写入 URL；流向、路口、时间窗口、当前时间片和代表轨迹均可通过查询参数复现。
- 最终页面保留真实数据质量提示：小清河路口当前片路径较短是数据事实；崇华当前片路径中位
  5.34m、最大 27.55m，可清晰看到运动折线，不以插值伪造轨迹。

## 7. 已知环境限制

本机 `.venv-mps` 的 PyTorch 2.2.2 报告 MPS build=true、available=false，因此官方
`scripts/mac_local_platform.sh up` 会按约束拒绝启动检测器。本次没有以 CPU 或 Docker 冒充 MPS
重跑 YOLO；Platform 使用本机 arm64 Python、真实 `road9` 和既有 canonical 数据完成 API 与页面
验证。该环境限制不影响消息/聚合/Console2 自动化结果，但在 MPS 恢复后应再采集一批新完成轨迹，
确认真实页面出现非空 YOLO 名称和模型标识。

## 8. 阶段收尾与下一轮准备

本阶段代码、迁移、读模型、Console2、四路口真实数据与视觉验收已收尾。后续“清理旧回放事实并用
当前检测链重跑八源”不与本阶段混跑，执行入口统一转到
[`runbook_trajectory_data_reset_and_replay.md`](runbook_trajectory_data_reset_and_replay.md)。

新增 `platform/scripts/inventory_trajectory_replay.py` 作为只读清理前盘点工具。2026-07-21 八源盘点为：
66,237 条统计、37,891 条完成轨迹、1,209,810 个轨迹点、95 个冲突、14,096 条遥测、40 个衍生
事件、132 个证据包；64,702 条关联 Inbox 明确保留，活动 Mission/Pipeline 为 0。清单保存于
`/private/tmp/TrafficAnalyzer-trajectory-replay-inventory-2026-07-21.json`。

本轮没有执行删除或重跑。当前 `.venv-mps` 仍为 `mps_built=true / mps_available=false`，因此下一轮
第一门禁是恢复原生 MPS；之后必须依次完成备份、dry-run 清单确认、显式删除授权、八源全新输出目录
重跑和 before/after 对账。

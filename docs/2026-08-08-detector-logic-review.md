# 检测器逻辑评审报告

- **日期**: 2026-08-08
- **评审范围**: `codex/2.0` vs `feature/influx` 中检测/跟踪相关改动
- **涉及文件**:
  - `nodes/DetectionTrackingNodes.py`
  - `nodes/DetectionNode.py`
  - `byte_tracker/byte_tracker_model.py`
  - `byte_tracker/utils/matching.py`
  - `utils_local/detection_geometry.py`
  - `utils_local/adaptive_imgsz.py`
- **评审方法**: 3 路 finder 并行扫描（逐行 diff / 删除行为审计 / 跨文件调用链追踪）+ 环境实测验证（MPS 推理、nms、fp16）

---

## 关键发现（按严重度排序）

### 🔴 F1（高）真实 class_id 取代"全部按 car=2"后，跨类惩罚对目标自身形成自惩罚

**位置**: `byte_tracker/byte_tracker_model.py:283-296`（`_association_distance`）

旧代码把一切可跟踪目标强制成 `class_id_value = 2`（注释"避免错误"），本次改为保留 YOLO 原始 class_id 并新增跨类惩罚。但旧路径 `DetectionTrackingNodes` **没有**传入 `class_group_resolver`，于是所有 `class_group = None`，`update_class` 的第一分支（`self.class_group is None`）**每帧无条件采纳检测类别**——class_name 随 YOLO 标签抖动逐帧翻转。

**后果**: visdrone 小目标（`car=3`/`van=4` 等视觉相似类别交替检出，恰是本配置 `confidence:0.05` 故意保留的低分候选）→ 同一目标 `tracked_cls_ids` 逐帧变化，`TrackerInfoUpdateNode` 每帧写入不同 `yolo_class_id` 与 `class_id_history`；同时 `_association_distance` 对该目标**下一帧的自身检测**加上 0.08 惩罚（`detection_classes != int(track.class_name)`），叠加 `fuse_score` 后 `fuse_cost` 逼近 `match_thresh=0.95` 上界 → 续接更容易丢失 → 重新初始化新 track_id → `CalcStatisticsNode`/Kafka 重复计数，类别统计抖动。

### 🔴 F2（高）`activate` 无条件 `is_activated=True`，单帧误检立即成为正式轨迹

**位置**: `byte_tracker/byte_tracker_model.py:129`

旧逻辑仅在 `frame_id == 1` 直接激活（后续帧的检测先进入 `unconfirmed`，需二次匹配才进入 `output_stracks`）；本次改为所有新轨迹立即激活。注释声明这是"Realtime policy"的有意变更，但副作用未被下游消化。

**后果**: 边缘目标 / 一帧虚警（`first_track_thresh:0.05` 会保留这类低分框）在其诞生帧就进入 `id_list/tracked_xyxy/tracked_cls_ids/tracked_conf`，被 `TrackerInfoUpdateNode` 建 TrackElement、`CalcStatisticsNode` 计数 → 幽灵车 / 车辆数逐帧抖动，且以 Lost 状态滞留 `track_buffer` 帧数。

### 🟠 F3（高）第二关联硬编码 `thresh=0.5` + 跨类/跨组惩罚拒掉同目标低分匹配

**位置**: `byte_tracker/byte_tracker_model.py:444-445`

Step-3 低分关联用硬编码 `0.5`（未用配置的 `match_thresh=0.95`），且 `_association_distance` 已把 0.08（跨类）/0.16（跨组）惩罚加进 `dists`。

**后果**: 同目标在低置信度续检时若类别/组标签在边界抖动（IoU dist 处于 0.42–0.5，加惩罚后 > 0.5），则**同目标不匹配** → track 转 Lost → 下一帧用新 ID 重新初始化 → 同一辆车被统计两次。三个 finder 独立收敛到该问题。

### 🟡 F4（中）scipy 回退与 `lap.lapjv(cost_limit)` 关联结果不一致

**位置**: `byte_tracker/utils/matching.py:49-56`

无 `lap`/`lapx` 时走 `linear_sum_assignment`：它先做矩形最小费用完全指派再筛掉超阈值对，而 `lapjv(extend_cost=True, cost_limit=thresh)` 用"哑列成本=thresh"把超阈值行直接置为未匹配。两者在存在 >thresh 配对的场景会产出**不同配对**（finder 已实证：3×3 矩阵 lapjv 匹配 2 对、scipy 匹配 3 对）。

**后果**: 仅由运行环境决定关联结果 → ID 抖动 / 幽灵续接。当前 dev 环境 `lap 0.9.4` 已装故休眠，但这是本次新增的潜伏不一致（`requirements.txt` 依赖 `lapx`，CI 的 `opencv-python-headless` 精简环境无 lap 时即触发）。

### 🟡 F5（中低）`apply_camera_warp` 把单帧 warp 施加给已丢失多帧的旧框

**位置**: `byte_tracker/byte_tracker_model.py:382-383`

`strack_pool` 含 `lost_stracks`（可丢失到 `max_time_lost`），却统一用当前帧的"上一帧→当前帧"单帧 warp 平移旧框后再做 KF 预测。

**后果**: 巡航路径（`GroundTrajectoryTrackerNode` 传 `camera_warp`）相机平移时，陈旧框被单帧位移后可能压到**另一辆车**的检测框 → 错误 `re_activate` → 两个目标身份合并 / 轨迹跳变。

### ⚪ F6（低）移除 `frame.copy()`，只读不变量依赖 ultralytics 不改写输入

**位置**: `nodes/DetectionTrackingNodes.py:86`

当前 ultralytics 8.4.102 的 letterbox/BGR2RGB 均为新建数组，安全；但同一 `frame` 后续被 `ShowNode` 原地绘制、被 `VideoSaverNode/FlaskServerVideoNode` 无副本共享。一旦升级或 MPS/half 预处理改变为原地写入，显示与保存帧将静默污染（通道错位/边缘条纹）且无异常。

### ⚪ F7（低）源时间戳回退/停滞时自适应 imgsz 瞬时退回 fallback

**位置**: `utils_local/adaptive_imgsz.py:44-52`

遥测缺失时用 `elapsed = now - last_valid` 判断保持窗口；若源时间戳乱序/停滞导致 `elapsed < 0`，则跳过保持分支直接返回 `fallback_imgsz`（如 1280→640），且 `_last_valid_timestamp_sec` 未回滚，回退可能持续到遥测恢复有序。

### ⚪ F8（低）`_get_results_dor_tracker` 成死代码且含潜在 TypeError

**位置**: `nodes/DetectionTrackingNodes.py:180`

`for result in results[0]` 对单个 `Results` 对象迭代（`Results` 不可迭代），一旦被调用即抛 `TypeError`；当前无调用者，属本次改动遗留的过期代码。

---

## 已实测排除的候选（透明记录）

| 候选 | 结论 | 证据 |
|---|---|---|
| `device:auto` 选中 MPS 后 `torchvision::nms` 未实现 → 崩溃 | ❌ 排除 | `.venv-mps`（torch 2.2.2 / torchvision 0.17.2）直接 `ops.nms` fp32/fp16 均正常返回 |
| `half=True` 在 MPS 上 fp16 不支持 → 崩溃 | ❌ 排除 | `yolo11s-visdrone.pt` 真实 `predict(device=mps, half=True)` 正常返回 0 boxes |
| `max_lost_sec` 配置后丢失轨迹永不回收 | ❌ 排除 | 现有两个 `update` 调用点自洽：`DetectionTrackingNodes` 未传 `max_lost_sec`（走帧超时）；`GroundTrajectoryTrackerNode` 同时传 `max_lost_sec` 与 `timestamp` |

> 提示：MPS 路径虽不崩溃，但 `predict` 已打印 `'half' is deprecated` 警告，建议改用 `quantize` 参数。

---

## Findings（结构化 JSON）

```json
[
  {
    "file": "byte_tracker/byte_tracker_model.py",
    "line": 283,
    "summary": "旧路径未配 class_group_resolver，update_class 因 class_group=None 每帧无条件采纳检测类别；真实 class_id 使小目标类别标签逐帧翻转，且 _association_distance 对目标自身的跨类续检加 0.08 惩罚",
    "failure_scenario": "visdrone 小目标在 car=3/van=4 间逐帧交替（confidence=0.05 保留的低分候选）→ tracked_cls_ids 逐帧变化，TrackerInfoUpdateNode 每帧改 yolo_class_id/class_id_history；自身检测被 +0.08 惩罚后叠加 fuse_score 贴近 match_thresh=0.95，续接丢失 → 新 track_id → CalcStatisticsNode/Kafka 重复计数与类别抖动"
  },
  {
    "file": "byte_tracker/byte_tracker_model.py",
    "line": 129,
    "summary": "activate 无条件 is_activated=True，移除 frame_id==1 确认闸门，单帧检测立即成为正式输出轨迹",
    "failure_scenario": "一帧边缘/虚警检测（first_track_thresh=0.05 保留的低分框）在诞生帧即进入 id_list/tracked_xyxy/tracked_cls_ids/tracked_conf → TrackerInfoUpdateNode 建 TrackElement、CalcStatisticsNode 计数 → 幽灵车、逐帧车辆数抖动"
  },
  {
    "file": "byte_tracker/byte_tracker_model.py",
    "line": 445,
    "summary": "第二关联硬编码 thresh=0.5 且不复用 match_thresh，跨类(0.08)/跨组(0.16)惩罚挤掉了同目标低分续检对",
    "failure_scenario": "同一车辆在类别边界抖动时以低分重新检出，IoU dist 0.42-0.5 + 惩罚后 > 0.5 → 同目标不匹配 → track Lost → 下一帧新 ID 重新初始化 → 同一车被统计两次"
  },
  {
    "file": "byte_tracker/utils/matching.py",
    "line": 50,
    "summary": "lap 缺失时的 scipy linear_sum_assignment 回退与 lap.lapjv(extend_cost, cost_limit) 产生不同关联配对（已实证），按环境改变跟踪结果",
    "failure_scenario": "无 lap/lapx 环境（如 CI 精简安装）下 3x3 代价矩阵 lapjv 匹配 2 对而 scipy 匹配 3 对 → ID 抖动 / 幽灵续接，行为仅由依赖是否安装决定"
  },
  {
    "file": "byte_tracker/byte_tracker_model.py",
    "line": 382,
    "summary": "apply_camera_warp 用当前单帧 warp 平移包含已丢失多帧的旧框，再做 KF 预测",
    "failure_scenario": "巡航路径相机平移时，丢失多帧的陈旧框被单帧位移后压到另一车辆检测框 → 错误 re_activate → 两车身份合并/轨迹跳变"
  },
  {
    "file": "nodes/DetectionTrackingNodes.py",
    "line": 86,
    "summary": "移除 frame.copy()，输入不被改写的假设仅由 ultralytics 内部新建数组保证",
    "failure_scenario": "ultralytics 升级或 MPS/half 预处理改为原地写入 ndarray 时，被 ShowNode 绘制、VideoSaver/Flask 共享的帧静默污染（通道错位/条纹）且无异常"
  },
  {
    "file": "utils_local/adaptive_imgsz.py",
    "line": 44,
    "summary": "遥测缺失时若源时间戳回退/停滞使 elapsed<0，跳过保持分支直接退回 fallback_imgsz 且不回滚 last_valid",
    "failure_scenario": "乱序/暂停后重放：1280→640 推理尺寸瞬时回退且持续，航拍小目标检测质量下降"
  },
  {
    "file": "nodes/DetectionTrackingNodes.py",
    "line": 180,
    "summary": "_get_results_dor_tracker 成为死代码且 for result in results[0] 对 Results 对象迭代会抛 TypeError",
    "failure_scenario": "任何未来调用该私有方法即 TypeError 崩溃；当前无调用者，属本次改动遗留的技术债"
  }
]
```

---

## 后续建议

- F1/F2/F3 是同一类回归（"保留真实 class_id" + 激活策略变更）的三个独立代码点，建议优先处理。
- 可将 F1–F3 合并为一个设计评审：类别感知关联 + 即时激活的权衡是否需要保留。

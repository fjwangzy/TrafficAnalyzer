# ByteTrack 卡尔曼滤波优化说明 — 技术交接

> 代码位置：`device_run_new/service_ultimate/yolo_inference_service/src/trace_track/`
> - 滤波器本体：`kalman_filter.{h,cpp}`
> - 单轨迹状态：`strack.{h,cpp}`
> - 调用编排：`byte_tracker.cpp`、`tracker_hub.cpp`、`track_thread.cpp`
>
> 优化前基线：`device_run_new/core/data_process/byte_track.py`（官方 ByteTrack 的工程内 Python 移植，状态量 `x, y, a, h`）
> 优化提交：`12e75ae3`「bytetrack中的卡尔曼滤波状态量优化」（2026-09-21）
> 模块短文档：`src/trace_track/README.md`

本文目标：让接手人完整掌握**优化后的卡尔曼滤波器**——状态量定义、噪声模型、每个接口的数学与实现、与 ByteTrack 主流程的集成方式、参数标定背景，以及排查与调参指引。

---

## 1. 背景：卡尔曼滤波在 ByteTrack 中做什么

ByteTrack 的核心是"轨迹（STrack）× 检测"的逐帧关联。每条轨迹内部维护一个 8 维卡尔曼滤波器，作用有三：

1. **平滑**：检测框逐帧抖动，滤波后的 `(cx, cy, w, h)` 更稳，输出轨迹平滑；
2. **外推（predict）**：关联发生在"预测框 vs 新检测框"之间——每帧先对所有轨迹做一次预测，预测框（`STrack::tlbr()`）参与 IoU 关联；
3. **补洞（re_activate）**：轨迹短暂丢失期间靠位置速度外推维持状态，重新匹配到检测时用 `update` 融合，避免轨迹状态跳变。

## 2. 优化内容一览：改了什么

提交 `12e75ae3` 对官方移植版做了三处配套修改，**三者必须作为一个整体理解，不可单独回退**：

| 项 | 官方 ByteTrack（优化前） | 优化后 |
|---|---|---|
| 状态量（8 维） | `(cx, cy, a, h)` + 速度，`a = w/h` 宽高比 | `(cx, cy, w, h)` + 速度，直接用宽 |
| 观测向量（4 维） | `(x, y, a, h)` | `(x, y, w, h)` |
| 第 3 维（尺寸维 1）噪声 std | 固定常数：initiate `1e-2` / predict `1e-2` / project `1e-1`（无量纲，不随目标尺度变化） | 锚定高度：`std_weight_position × h`（与 cx/cy/h 三维完全一致） |
| 第 7 维（尺寸速度维）噪声 std | 固定 `1e-5`（initiate/predict） | `std_weight_velocity × h`（与 vcx/vcy/vh 一致） |
| 丢失期间外推 | 仅置零 `mean[7]`（vh，h 的速度） | 同时置零 `mean[6]`（vw）与 `mean[7]`（vh），只按位置速度外推 |
| 编解码 | `tlwh_to_xyah` 含除法 `w/h`；`tlwh()` 含乘法 `a×h` 反算 | `tlwh_to_xywh` / `tlwh()` 仅中心↔左上角换算，无乘除耦合 |

## 3. 为什么要改：动机剖析

### 3.1 宽高比 `a` 是派生量，滤波它绕了弯

检测器输出的观测量本来就是 `w`（像素）。官方版把 `w` 拆成 `a = w/h` 与 `h` 两个状态分别滤波，输出时再 `w = a×h` 乘回来。这带来两个问题：

- `w` 的估计误差 = `a` 的误差 × `h` + `h` 的误差 × `a`，两个状态的噪声在输出端**乘性耦合**，`h` 大时同样大小的 `a` 误差对应几十像素的 `w` 误差；
- 观测 `a` 需要 `w/h` 除法，`h` 很小时数值放大不稳定。

直接滤波 `w` 后，观测矩阵仍是简单单位块（线性），`w` 的噪声直接以像素为量纲建模。

### 3.2 固定常数噪声不自适应，宽"涨不动"

官方版给 `a` 通道的噪声 std 是与目标尺度无关的固定常数（`1e-2 / 1e-5 / 1e-1`）。这些值是按 COCO 行人（宽高比变化小）调出来的经验值；在交通监控里，车辆从画面边缘入镜时宽度被裁剪，之后 `w` 要从入镜时的小值持续"长大"到真实值。固定小噪声意味着滤波器过度信任自己对 `a` 的预测，检测端持续给出更大的 `w` 时收敛缓慢——直观表现就是**检测框已经在变宽、跟踪框跟不上**。

### 3.3 噪声锚定高度 `h`（关键决策）

优化后的 `w` 通道噪声没有按 `w` 自身缩放，而是**统一锚定高度 `h`**。源码注释原话：

> 噪声统一锚定高度 h：宽若按自身缩放，入镜初期 w 小→噪声小→涨不动。

即：交通场景中目标入镜时（侧向切入），`w` 很小而 `h` 已接近真实值。若过程噪声 `∝ w`，`w` 小 → 允许的修正量小 → 框宽收敛更慢，形成正反馈式的"涨不动"。锚定较大且稳定的 `h` 后：

- `w` 通道从轨迹出生起就有足够的可修正余量（initiate 时 std = `2 × h/20`）；
- 噪声随目标实际尺度（以 h 为代理）自适应——远处小车噪声小、近处大车噪声大，与 `cx/cy/h` 三维的建模方式完全统一；
- 不需要引入新的超参（仍只用 `std_weight_position / std_weight_velocity` 两个官方权重）。

### 3.4 丢失期间不外推尺寸

丢失（Lost）期间没有观测，外推只会放大陈旧速度的误差。官方版在 `predict` 时把 `mean[7]`（其布局中的 vh）置零；本实现状态布局变为 `(…, w, h, vw, vh)` 后，相应地把 `mean[6]`（vw）、`mean[7]`（vh）**都**置零——丢失期间只按位置速度外推，尺寸冻结在最后估计值，等 `re_activate` 用真实观测校正（`strack.cpp` `STrack::predict` 与 `STrack::multi_predict` 两处，注释一致）。

## 4. 优化后的滤波器完整说明

### 4.1 状态、运动模型与常量

```text
状态  x = [cx, cy, w, h, vcx, vcy, vw, vh]ᵀ        （8 维，全像素量纲）
观测  z = [cx, cy, w, h]ᵀ                          （检测框 xywh）
运动  F = I₈，右上 4×4 块填 dt=1（匀速，帧间隔归一）
观测  H = [I₄ | 0₄ₓ₄]
噪声权重  std_weight_position = 1/20，std_weight_velocity = 1/160   （官方值，未改）
```

所有噪声 std 都是**当前高度估计 `h = mean(3)` 的函数**——目标越大，允许的位置/尺寸波动越大，天然自适应。

### 4.2 噪声表（唯一需要记的表）

| 时机 | 对角 std（按状态维度顺序） |
|---|---|
| `initiate`（初始化协方差） | `[2wp·h, 2wp·h, 2wp·h, 2wp·h, 10wv·h, 10wv·h, 10wv·h, 10wv·h]` |
| `predict`（过程噪声 Q） | `[wp·h, wp·h, wp·h, wp·h, wv·h, wv·h, wv·h, wv·h]` |
| `project`（观测噪声 R） | `[wp·h, wp·h, wp·h, wp·h]`（4 维） |

其中 `wp = 1/20`，`wv = 1/160`，`h` 取该时刻的 `mean(3)`。对照官方版：官方仅第 3、7 维（a、va）为固定常数 `1e-2/1e-5`、project 中 a 为 `1e-1`，其余与本表相同——**优化就是把这个"例外"消除**。

### 4.3 各接口的数学与实现

所有函数为 `const`、无内部可变状态（只有常量矩阵 `motion_mat_/update_mat_`），因此 `KalmanFilter` 天然线程安全、可全局共享（`STrack::shared_kalman` 静态实例即利用这一点）。

**`initiate(measurement)`** — 新轨迹初始化
`mean = [z, 0₄]`（速度置零），`cov = diag(表中 initiate std)²`。速度初始不确定度取 10 倍权重，表示"完全不知道初速"。

**`predict(mean, cov)`** — 预测步
`mean' = F·mean`（即位置 += 速度），`cov' = F·P·Fᵀ + Q(h)`。
实现为三段手写三重循环矩阵乘（`F` 是单位阵+角块，但代码按通用 8×8 乘编写，编译器可优化），全程无堆分配。

**`project(mean, cov)`** — 观测投影
`mean_p = H·mean`（取前 4 维），`S = H·P·Hᵀ + R(h)`（4×4）。中间量走 32 元素栈数组。

**`update(mean, cov, measurement)`** — 校正步
1. `project` 得 `(mean_p, S)`；
2. 增益 **K = P·Hᵀ·S⁻¹** 经 Cholesky 求解：`cho_solve(S, H·P)` 用 4×4 下三角分解（`cholesky_lower`）+ 前代/回代（`forward_sub/back_sub`）解出 `Kᵀ`，**取代通用矩阵求逆**（更快且数值更稳，SPD 专用）；
3. `mean' = mean + K·(z − mean_p)`；
4. `cov' = P − K·S·Kᵀ`（代码中先算 `KP = K·S` 再减 `KP·Kᵀ`，与官方 `np.dot(K, np.dot(S, K.T))` 同构）。
**失败防御**：Cholesky 分解失败（对角 ≤ 1e-12，即 S 非正定，通常由 NaN/Inf 污染引起）时**返回原 (mean, cov) 丢弃本次观测**，不抛异常不崩溃。注意此路径无显式日志——排查"轨迹不更新"时记得考虑它。

**`multi_predict(means, covs)`** — 批量预测
把 N 条轨迹的 `(8,)`/`(8,8)` gather 进 `(N,8)` / `(N,8,8)` xarray，逐行调用 `predict` 后写回。接口形态对齐 Python 的向量化 `multi_predict`（当前实现是逐行循环，收益在接口统一与调用侧一次打包；性能上每次 predict 无堆分配才是关键）。

**`gating_distance(mean, cov, measurements, only_position, metric)`** — 马氏距离
`maha`：对 `S` 做 Cholesky 后用前代解 `S^{-½}·d`，距离 = `‖S^{-½}d‖²`（等价 `dᵀS⁻¹d`，避免显式求逆）；`gaussian`：欧氏平方距离。
⚠️ 保留用于接口对齐，**当前关联路径未调用**（ByteTrack 关联用 IoU 距离，见 §5）。

### 4.4 实现层要点（相对 numpy 版）

- 全部热路径为**固定尺寸栈数组**（`float[16]/[32]`）+ 手写循环，零堆分配；xarray 仅作跨函数容器类型。与后处理模块同理，**不含 xtensor 表达式模板**，无 Debug 懒求值陷阱（服务构建仍统一强制 Release）。
- `cho_solve` 限定 `n ≤ 4`：观测维固定 4，超出直接返回 false 走防御路径。
- 单精度 float：与检测输出精度匹配，长轨迹协方差缓慢退化由 Q 持续注入对角项兜底；`track_buffer` 超时的轨迹直接移除，不会无限滤波。

## 5. 与 ByteTrack 主流程的集成（调用时序）

`ByteTracker::update(detections)`（`byte_tracker.cpp`）每帧执行，卡尔曼相关调用点：

```text
① 检测分桶：score > track_thresh(0.5) → 高分批；low_score(0.1) < score < track_thresh → 低分批
② STrack::multi_predict(tracked ∪ lost)          ← KF predict × N（丢失轨迹 vw/vh 置零后外推）
③ 第一轮：IoU 距离 + fuse_score → 匈牙利指派（match_thresh 0.8）
     匹配且 Tracked   → track->update(det)        ← KF update（例行校正）
     匹配但 Lost/丢失 → track->re_activate(det)   ← KF update（重关联，tracklet_len 清零）
④ 第二轮：未匹配 Tracked 轨迹 × 低分批（second_match_thresh 0.5）→ 同上 update/re_activate
     仍未匹配 → mark_lost
⑤ 未确认轨迹 × 高分剩余检测（unconfirmed_match_thresh 0.7）→ update；失败 → mark_removed
⑥ 新建：剩余高分检测且 score ≥ det_thresh(= track_thresh+0.1 = 0.6) → track->activate()
                                                  ← KF initiate（det_thresh 比官方提高，减少弱检测建轨）
⑦ Lost 超时：frame_id − end_frame > max_time_lost → mark_removed
⑧ 每帧末 remove_duplicate_stracks（IoU<0.15 去重，保留存活更久者）
输出：tracked_stracks_ 中 is_activated 的轨迹（框取自滤波状态 tlbr()）
```

关联代价 = `1 − IoU(预测框, 检测框)`，非 `mot20` 时再经 `fuse_score` 融合检测分数（`1 − IoU·score`）；匈牙利为 O(n³) Kuhn-Munkres 实现（`matching.cpp`，超阈代价屏蔽为大值后求解再过滤）。

### STrack 与坐标换算（`strack.cpp`）

- 轨迹激活前（`has_mean_=false`）`tlwh()` 直接返回检测框；激活后返回滤波状态 `(cx,cy,w,h)` 换算的左上角——**中心↔左上角是唯一换算，无宽高比反算**（这是优化点之一）。
- `activate / re_activate / update` 一律 `tlwh_to_xywh` 编码观测后进滤波器。
- 私有成员 `mean_/covariance_`（`xarray`）只经上述接口触碰。

### StreamTrackerHub 层的周边语义（`tracker_hub.cpp`）

- **每流独立 ByteTracker**（各自持一个 `KalmanFilter kalman_filter_` 成员）；`generation` 变化（上游环换代）→ 重建 tracker（epoch 隔离，轨迹 ID 重新计数）；
- `seq ≤ last_tracked_seq` 乱序帧短拷（不调 update，直接拷贝原始通道）；空框/全退化框（`x1≥x2 或 y1≥y2`）过滤后若为空 → 不调 `update` 只推进 `last_tracked_seq`；
- `tracking.enabled=false` → 双通道短拷（track_dets 与原始同语义、无 track_id）；
- 双通道输出：`dets` = 原始检测（track_id=-1），`track_dets` = 轨迹框 + track_id，两通道条数可不等。

## 6. 配置与业务标定

`services_config.yaml` → `yolo_inference_service.tracking`（当前部署值，经 `TrackingConfig` → `ByteTrackerArgs`）：

```yaml
tracking:
  enabled: true
  frame_rate: 8          # 实际帧率，参与 max_time_lost 换算
  track_thresh: 0.5      # 高分批阈值；det_thresh = track_thresh + 0.1 = 0.6（新建轨迹门槛）
  track_buffer: 150      # 见下
  match_thresh: 0.8      # 第一轮关联代价阈（1−IoU·score 上界）
  low_score: 0.1         # 低分批下限
  second_match_thresh: 0.5
  unconfirmed_match_thresh: 0.7
  mot20: false
```

**`track_buffer: 150` 的换算与背景**（YAML 内注释原文，重要的业务决策）：

- `max_time_lost = frame_rate / 30 × track_buffer = 8/30 × 150 = 40 帧`，按 8fps 即 **5 秒**；
- 注释原文：「ByteTrack 轨迹记忆(按 30fps 帧数标定,实际有效时长 = track_buffer/30 秒)。150 -> 5s: 车牌绑定到过线平均间隔 5~15s, 1s 记忆下检测闪断即换 ID, 是车牌/过车 track 失配(漂移)的主因」——即从默认 30（1 秒）加到 150（5 秒），是为了让轨迹跨越检测闪断、撑到车牌/过车绑定的平均间隔，直接服务车牌与过车统计的 ID 一致性。

## 7. 验证方法

1. **模块级冒烟**：trace_track 目录支持独立构建 `cmake -S . -B build -DYOLO_TRACE_TRACK_BUILD_SMOKE=ON`（见 `src/trace_track/README.md`；历史树构建产物在 `src/trace_track/build/yolo_trace_track_smoke`）。
2. **数值对齐**：与 `core/data_process/byte_track.py` 同输入序列对比轨迹框与 ID。⚠️ 注意 Python 基线仍是 `x,y,a,h` 状态——**滤波中间量（mean/cov）与 C++ 不再可比**，可比的是最终输出框（整数 tlbr）、ID 序列与匹配结果；框在检测噪声小、尺寸稳定时两者接近，入镜"宽度生长"场景会有可观察差异（这正是优化目的）。
3. **实机观测**：
   - 日志 `[ByteTrack] stream=... seq=... gen=...` 系列（`tracker_hub.cpp` 的 `log_and_check_track_seq`）：first / gen change / skip gap / reorder 四种事件可判断上游连续性与换代重建频率；
   - `TrackerHubStats`（经 `status` RPC 聚合）：`track_update_count / empty_boxed / out_of_order_skip / epoch_reset_count` 等；
   - 业务指标：车牌-过车绑定失配率（track_buffer 调整的直接观测对象）。

## 8. 调参指引（症状 → 参数）

| 症状 | 优先调 | 说明 |
|---|---|---|
| 入镜目标框宽跟不上检测（"涨不动"复发） | 不要动回旧版 | 先确认 `initiate/predict/project` 中 w 维噪声仍是 `×h` 锚定、状态仍是 `(cx,cy,w,h)`；若换模型后症状复发，可尝试增大 `std_weight_position`（构造函数内常量，1/20 → 1/15） |
| 轨迹框抖动大 | `std_weight_position` ↓ 或 `project` 观测噪声 ↑（即滤波更信自己） | 全局量，影响所有流 |
| 闪断后换 ID（复现失配） | `track_buffer` ↑（配合 frame_rate 换算） | 已从 30→150，再加大会增加 ID 被占用与轨迹重叠风险，观察 `remove_duplicate_stracks` 行为 |
| 弱检测建轨太多、短命轨迹碎片 | `track_thresh` ↑（det_thresh 随之 +0.1） | 注意同步影响三轮关联的分桶 |
| 丢失期间框尺寸漂移 | 检查 `STrack::predict / multi_predict` 的 vw/vh 置零 | 该逻辑是行为锚点，勿删 |
| 轨迹"冻住"不更新 | update 的 Cholesky 失败防御路径 | 检查上游检测是否 NaN/Inf（S 非正定触发静默丢弃观测） |

## 9. 交接注意事项（红线）

1. **状态量、噪声、编解码三者配套**：`kalman_filter.*` 的 `(x,y,w,h)` 观测与噪声表，和 `strack.*` 的 `tlwh_to_xywh/tlwh()` 是一次原子修改（提交 `12e75ae3`）。任何回退或再修改必须三处同步，否则滤波量纲错乱、轨迹发散。
2. `KalmanFilter` 按无状态设计：不要往里加可变成员（会破坏 `shared_kalman` 静态共享与多 worker 下的安全性）。需要新行为时优先改 STrack 层或传参。
3. `gating_distance` 当前未被主路径调用；若未来引入马氏距离门控（如 DeepSORT 式级联），可复用其 Cholesky 实现，注意 `only_position` 只取前 2 维。
4. 每帧对每条轨迹只调一次 `predict`（在 `update` 入口统一做）；`STrack::update/re_activate` 内部只做 `KF update`——不要在别处再触发 predict，会双重外推。
5. 帧率语义：F 的 dt 固定 1（按帧计数），上游实际 8fps 经抽样可能不均匀；`frame_rate` 只用于 `max_time_lost` 换算，不进滤波模型。若未来上游帧率大幅变化，重标定 `track_buffer` 而非动 F。

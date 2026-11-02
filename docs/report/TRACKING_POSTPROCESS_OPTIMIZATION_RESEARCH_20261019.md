# 追踪与检测后处理优化调研（2026-10-19）

本次阅读 `req/optimize.md/` 下两份技术交接及 `yolo_inference_service` 的相关 C++ 源码，并与 TrafficAnalyzer 当前工作树对照。仅完成方案研究，未修改运行代码、阈值、模型、部署配置或发布包，未运行真实视频/NPU 性能测试。

## 1. 结论与采用顺序

参考项目有两条不同的收益链：**XYWH 状态模型主要改善框尺寸响应与关联稳定性；score-first、融合解码和小矩阵专用实现主要减少计算与调度开销。** 二者应分别验证，不能把模型行为变化算作等价加速。

| 优化点 | 参考项目的实现与价值 | 当前项目适用性 | 建议 |
| --- | --- | --- | --- |
| `XYAH → XYWH` | 直接估计宽高，避免输出宽度由 `a×h` 重构 | 当前仍是 XYAH；入镜裁剪、转向、框宽快速变化值得验证 | 独立 A/B，优先于整套 C++ 替换，但不承诺 FPS 收益 |
| 尺寸噪声统一随 `h` 缩放 | 去除原 `a/va` 固定噪声，为裁剪入镜提供另一种响应模型 | 航拍旋转、宽扁车与小目标不一定适合全锚定高度 | 与 XYWH 配套比较，不把该噪声方案视为通用最优 |
| Lost 时同时清零 `vw/vh` | 避免无观测期间框尺寸持续漂移 | 当前只清零 XYAH 的 `vh`；换状态后必须同步 | 作为模型迁移原子改动，保留现有真实时间超时 |
| 固定尺寸数值内核 | 减少小矩阵求解、容器与库调度成本 | 当前已用 Cholesky，二维 shadow 已改两行前代；有部分能力 | 先测剩余热点，再批量化/专用化，不重复建设 |
| score-first DFL | 背景格不做四边 DFL，减少大量无效 softmax | 当前昇腾 OM 输出已解码框，CPU 无对应 DFL 阶段 | 学方法，不接入 RKNN 解码器 |
| 融合循环、减少中间数组 | 少做全网格张量物化、转置和拷贝 | 可以用于 CPU NMS 周边及跟踪批处理 | 在阶段耗时证实瓶颈后按热点实施 |
| NEON | 对连续小数组做 max 与加权累加 | 当前 NumPy/OpenCV 等已有 ARM 优化，IoU/匹配已有原生实现 | 属于最后一层优化，不能仅因 ARM 就整套重写 |
| 无状态阶段并行 + 按流重排 | 多帧解码并发，追踪按流顺序更新 | 当前三进程已隔离检测、分析和显示 | 多路扩展时参考，不直接照搬 6 worker/512 队列 |

当前约 1 FPS 的现场瓶颈仍缺应用 `.4` 后的新阶段日志。现有任务记录中的旧 shadow 求解和绘制热点已有针对性修复；合成 ByteTrack 对照约 33–43ms 不能证明现场耗时。先定位最新慢点，再选下面的优化路线。

## 2. ByteTrack：可借鉴的算法改进

### 2.1 直接估计宽高，减少宽高比重构耦合

参考实现状态为 `[cx, cy, w, h, vcx, vcy, vw, vh]`，原实现为 `[cx, cy, a, h, vcx, vcy, va, vh]`。宽度原本由 `a×h` 得到，两个估计量共同影响最终宽度；改成直接观测 `w`，便于表达框宽独立变化。适合重点观察画面边缘车辆逐步入镜、遮挡恢复和转向造成的包围框变化。

这不是仅删除一次乘除法的性能优化，也不能保证身份关联一定更好。XYAH 对近似固定宽高比的目标也有合理性。Ultralytics 官方同时提供 XYAH、XYWH 两种滤波器；其 XYWH 对横向维使用宽度、纵向维使用高度缩放噪声，与参考项目“所有维度锚定 h”不同。[官方实现](https://github.com/ultralytics/ultralytics/blob/main/ultralytics/trackers/utils/kalman_filter.py)

参考项目的 `h` 锚定是针对侧向裁剪的工程假设：入镜时宽度被截断，高度相对完整。航拍画面车辆姿态、长宽关系和遮挡方向多变，这一假设需要按目标尺度/姿态分层验证。噪声应区分过程噪声 Q、观测噪声 R 与初始协方差 P；增大 Q 与增大 R 对响应的影响不同，不能简化为“噪声越大越跟得上”。

### 2.2 Lost 时冻结尺寸均值，继续保留位置预测

参考项目在单条与批量预测两处同时清零 `vw/vh`，避免丢失时尺寸继续增长或收缩。不确定度仍通过预测传播，并非冻结协方差。对于无人机运动导致的实际缩放，冻结尺寸也可能降低重关联能力，因此需要短遮挡、快速相机运动和尺度变化样本共同验证。

参考项目 5 秒记忆来自车牌绑定业务，不适合直接复制。本项目继续使用 `max_lost_sec=2.0` 和 `max_frame_gap_sec=0.5`；也不能用 `track_buffer=150` 替换真实源时间语义。

### 2.3 迁移范围超过两个滤波文件

当前需联动的位置包括：

1. `byte_tracker/utils/kalman_filter.py`：状态定义、初始化、单条/批量预测、观测投影的噪声。
2. `byte_tracker/byte_tracker_model.py`：观测编码、`tlwh` 解码、activate/update/re_activate、单条/批量 Lost 尺寸处理、`apply_camera_warp` 中的状态重编码。
3. `byte_tracker/utils/matching.py`：shadow 门控及其他使用 `to_xyah()` 的接口，避免未来出现混合量纲。
4. `STrack.shared_kalman` 与 tracker 实例滤波器：必须选择同一种模型。
5. 跟踪与投影的接口回归：保持 `detected_*` 与 `tracked_*` 各自语义、稳定 ID、逐点源时间、ENU/GCJ-02 可空和完成事件规则。

当前相机 warp 重编码均值但未同步变换速度/协方差；若继续优化这部分，应作为单独算法问题验证，不能在状态替换时顺带改变并归因给 XYWH。

本项目正式关联继续使用相机补偿后的 IoU、置信度和类别软约束。参考项目也未调用 Mahalanobis 主关联门控；不能借本次迁移恢复本项目已退出生产的固定 dt 硬门控（ADR-026）。

### 2.4 时间模型仍有后续空间

两边当前 KF 的 F 均固定 `dt=1`。本项目传入的 timestamp 用于生命周期超时，并未进入 KF 转移矩阵。参考项目 `frame_rate` 同样只用于 lost 窗口换算。

若未来优化不均匀抽帧，应一起设计 F(dt)、Q(dt) 和速度单位，并明确使用源时间。不能只把 dt 改成秒而沿用现有噪声与速度状态。该项与 XYWH、C++ 加速分别做实验，避免无法判断收益来源。

## 3. DFL/NMS：真正的性能优化来自少算和少搬

### 3.1 先筛分数，再做昂贵解码

640 输入、三尺度 8400 个网格时，全网格路径对每格做 `4×16` DFL。参考实现先扫描类别最大分数及白名单，仅 K 个候选执行 DFL：

`全量 O(A×C + A×4×16) → 筛后 O(A×C + K×4×16)`

例如 K=100 时，DFL 处理网格数从 8400 降到 100；这只是该子步骤工作量变成 1/84，不是整帧加速 84 倍。低阈值、密集交通会增大 K，NMS 仍可能成为热点。

### 3.2 融合 DFL、框解码和候选输出

参考代码对过阈网格直接计算四边期望并生成 xyxy，省去全网格 dist、meshgrid、transpose、concat 等中间结果。逆 letterbox 原地执行；NMS 使用索引和 suppressed 位图，避免每轮反复构造候选数组。NMS 的最坏复杂度仍为平方级，没有因位图而变成线性算法。

NEON 只承担部分 max 归约和加权累加，exp 仍是标量。说明主要设计是减少工作量，SIMD 是后续补充。标量 exp 也不保证不同架构最终整数框逐位一致，归约顺序、浮点精度及边界取整仍需对照。

### 3.3 对当前 Ascend/MPS 的具体判断

`utils_local/ascend_detector.py:62` 限定单输出 `[1,4+classes,anchors]`，`predict()` 调用 Ultralytics NMS，然后逆 letterbox。CPU 接收到的前四维已经是框，不是 `[64,H,W]` 的 DFL logits；**将参考 RKNN 的九输出 DFL 解码器接进来会违反模型输出契约**。

因此当前可研究的是 `ascend.copy_output`、`ascend.cpu_nms`、候选整理和数据搬运，而不是补写 CPU DFL。Ultralytics 的 NMS 本身已包含置信度预筛，是否存在额外可省的工作，要以实际安装版本和阶段采样为准。[官方 NMS 源码](https://github.com/ultralytics/ultralytics/blob/main/ultralytics/utils/nms.py)

若重做 NMS，必须固定类别感知、阈值边界、同分顺序、坐标精度、max_det/max_nms 等实际语义。不能把参考项目在裁剪后做 NMS、整数输出等细节照搬成当前默认，也不能以跨类别粗去重或提高阈值换取表面加速。本项目 detector confidence=0.05，参考部署为 0.4，候选规模与小目标目标不同。

MPS 路径也应优先测量当前框架实现的阶段开销。为 score-first 而修改导出图、改用原始 DFL 输出属于模型契约及发布基线变更，不是源码等价优化。

## 4. 工程结构中值得保留的思路

- **无状态计算并行，有状态追踪串行。** 解码可处理多帧；同一流必须按序更新 tracker，不应让多个 worker 并发修改同一个 tracker。
- **身份与像素分离传递。** stream/seq/generation、源时间与 letterbox 随结果传递，防止跨流、跨代和坐标系错配。当前项目已有 Pipeline/帧号/源时间，应复用既有身份体系。
- **原始检测与追踪结果双通道。** 有助区分检测缺失、关联失败和显示问题。本项目已有 `detected_* / tracked_*`，可完善逐检测 lineage，无需引入第二套服务协议。
- **有界队列、反压和完整停机协议。** 并行之前先测队列等待、结果年龄、内存与重排等待。参考的 512 容量不能直接替换本项目默认 8；512 条结果在 80 条/秒出队的假设下可对应约 6.4 秒排队，容量不等于实时性。
- **实时与离线分别验证。** Kafka 异常后的“最新数据优先”授权不能自动扩展为视频帧或完成事实任意丢弃；新增采样/丢帧策略需要单独明确，保留已有自然 EOF 与持久化排空约束。

## 5. 对参考材料的核查与需要补齐的地方

以下为所提供源码的静态发现，不代表已复现实机故障。

| 材料说法或实现 | 源码核查 | 对方案的影响 |
| --- | --- | --- |
| KF 热路径“全部栈数组、零堆分配” | `predict/project/update/multi_predict` 仍有多处动态 `xt::xarray` 创建、复制；批量预测逐轨创建临时量 | 局部求解器使用栈数组成立，整个 KF 零分配不成立；可改固定尺寸类型/复用批量缓冲 |
| Cholesky 失败可防 NaN/Inf | 对角检查仅为 `sum <= 1e-12f`，NaN 不满足该条件，可能继续传播 | 增加 finite 检查、失败计数与可追踪原因，不能静默认为安全 |
| gating 失败防御 | 失败时返回初始化为全零的距离；主路径当前未使用 | 将来复用时可能把失败当成完美匹配，必须返回明确无效状态 |
| 空帧保留身份，利于重排 | 成立；但 `tracker_hub.cpp:190` 遇空框直接返回，不调用 tracker.update | 跟踪时间与预测只在非空检测帧推进；连续空帧会拉长真实记忆窗口，不能复制这一语义 |
| `track_buffer=150` 相当于 5 秒 | 按配置 8fps 换算成 40 次 tracker.update | 只有 update 真以 8Hz 连续执行才接近 5 秒；跳帧/空帧会破坏该解释 |
| “强制 Release” | CMake 仅在未指定构建类型时默认 Release | 显式 Debug 仍可构建；性能证据应记录实际编译选项 |
| 算法单测可运行 | 顶层/src 未挂 tests；测试引用缺失的 config/frame_meta；跟踪 README 的独立 CMake 入口在所给源码中也未见 | 先修构建与测试资产，再将其作为可复用基线；已有 build 产物不是当前源码通过的证据 |
| 类别扫描“内存连续” | NCHW 固定格点遍历类别，访问步长为 H×W | 并非逐类别连续读取；后续可试按空间块扫描/批量最大值，需实测缓存收益 |
| 同分排序 tie-break 对齐 | 比较器只有 score 的 `>`，使用非稳定 `std::sort` | 未定义相同 score 的稳定次序，重叠等分框可能影响 NMS 保留结果 |
| reg_max 换型说明 | 文档末尾写“reg_max≠4”，源码 `kRegMax=16`、box 通道=64 | 应修正为 reg_max≠16；不要混淆 4 条边与每边 16 bins |
| 8 路×10FPS 历史通过 | 交接材料给出历史提交口径，本次未复跑、未取得同条件原始压测证据 | 不能转换为 TrafficAnalyzer/Ascend 的吞吐承诺 |

xtensor 官方明确说明：表达式重复使用可能重复计算，可以通过物化、`xt::eval()` 或 immediate reduction 控制求值。因此应避免未控制的重复求值，而不是把所有表达式模板都当成慢路径。[表达式说明](https://xtensor.readthedocs.io/en/latest/expression.html)、[求值策略](https://xtensor.readthedocs.io/en/latest/operator.html#evaluation-strategy)

## 6. 建议的验证与落地路线

### 第一步：定位当前性能预算

记录当前实际版本、源、尺寸、stride、检测数/轨迹数、CPU quota/亲和、数值库线程设置。按阶段拆分推理、拷贝、NMS、相机运动估计、KF、shadow 门控、指派、世界投影/统计、绘制/编码和队列等待，报告稳定窗口 p50/p95 与端到端结果年龄。

已有日志中 `ascend.om_execute` 很快不能证明整个检测阶段快；网页 FPS 也不能直接代表某个跟踪内核耗时。三进程有重叠，需同时看最慢阶段吞吐与排队，不能把所有阶段时间简单相加推导实际 FPS。

### 第二步：先做行为尽量等价的性能改进

若剩余 KF 或 shadow 被确认占比高，可尝试批量协方差构建、小矩阵专用投影与求解、复用工作区、减少对象转换。当前 Cholesky 已有，不应再把“用 Cholesky 替代求逆”当作新增收益；官方 ByteTrack 基线也已如此实现。[官方滤波器](https://github.com/FoundationVision/ByteTrack/blob/main/yolox/tracker/kalman_filter.py)

F 的分块结构可用于简化预测，H 也只是前四维选择；可先在现有 NumPy 路径减少通用矩阵运算，再判断是否需要原生扩展。IOU、LAP/Scipy 指派已经是原生计算，C++ 包装并不会自动消除它们的复杂度。

等价优化使用同一检测序列比较数值容差、门限判定、匹配、ID、输出框和完成事实；对阈值附近的微差单独审计。每轮只变一个因素。

### 第三步：独立评估 XYWH

冻结模型输出、帧号、源时间和 camera_warp，把同一输入分别喂给现有 XYAH、参考 XYWH-h 噪声方案，必要时增加宽高分别缩放的 XYWH 对照。不更改生产阈值、2 秒 lost 窗口和 0.5 秒源时间断点。

覆盖小目标密集、边缘入镜、遮挡恢复、转向、停车与相机运动、短空检测、长时间无检测、不同 stride、乱序/重复时间以及自然 EOF。记录框宽跟随滞后、尺寸抖动、观测轨迹碎片/寿命、处理耗时等工程代理；框跟随检测的误差不等于真实定位误差。

重点验证图像 ID 不受 H/地图质量改变影响，世界点使用各自源帧 H，速度继续从可信 ENU 回归，TCC 质量门禁不泄漏，完成事件不重复。不能把 KF 的像素速度当成车辆米制速度。

依据 ADR-024，不新增人工轨迹标注工作包。没有外部批准真值时，IDF1/HOTA、正式 ID switch、位置 RMSE、速度 MAE 保持 `not_evaluated`；不以更平滑尾迹或更少 ID 宣称精度提高。

### 第四步：按证据决定原生化和多路并行

只有剩余热点值得优化时，才考虑小范围 C++/NEON 内核；新增原生扩展走依赖/镜像基线发布，遵守 ADR-041，不能混入同基线源码更新。保留 Mac 原生 MPS 默认值与 ARM64 Ascend 生产差异。

最终应交付“指定硬件、尺寸、候选规模与源条件下的阶段/端到端对照”，而不是把其他项目的 8 路压测或单内核倍数换算为本项目承诺。

## 7. 主要本地证据

- 参考交接：`req/optimize.md/bytetrack_kalman_filter_optimization.md`、`req/optimize.md/yolo_postprocess_optimization.md`。
- 参考跟踪：`req/optimize.md/yolo_inference_service/src/trace_track/{kalman_filter,strack,byte_tracker,tracker_hub}.cpp`。
- 参考后处理：`req/optimize.md/yolo_inference_service/src/postprocess/{dfl_decode,decode_outputs,postprocess_worker}.cpp`。
- 当前实现：`byte_tracker/utils/{kalman_filter,matching}.py`、`byte_tracker/byte_tracker_model.py`、`utils_local/ascend_detector.py`、`nodes/GroundTrajectoryTrackerNode.py`、`nodes/SpeedEstimationNode.py`。
- 约束与既有证据：`docs/DECISIONS.md` ADR-023/024/025/026/028/032/041、`docs/TASKS.md` 2026-10-19 性能记录。

以上本地行号/状态对应本次读取的当前工作树。参考文档所述历史提交未在独立原仓库核验；源码静态核查不替代编译、数值对照、真实视频或现场生产验证。

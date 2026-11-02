# yolo_inference_service 后处理（DFL + NMS）优化思路 — 技术交接

> 代码位置：`device_run_new/service_ultimate/yolo_inference_service/src/postprocess/`
> 数值基线（Python 参考实现）：`device_run_new/core/data_process/postprocess.py` 的 `decode_rknn_outputs`
> 关键提交：`acb7bc6f`「8 路 10 FPS极限测试通过」（2026-08-05，起于旧树 `service_new_new_new`，后随服务整体迁入 `service_ultimate`）
> 模块短文档：`src/postprocess/README.md`；旧实现方案底稿：`service_new_new_new/yolo_inference_service/plans/postprocess_dfl_nms_xtensor_plan.md`

本文目标：让接手人理解后处理**从 Python 基线到当前热路径的全部优化决策**（为什么改、改了什么、数值为何仍对齐）、掌握代码地图与失败语义，并能独立完成调参与二次开发。

---

## 1. 模块定位：后处理在流水线中的位置

```text
core rknn_engine（9 NPU worker）
  → InferOutputQueue（512，组件内）
      → PostprocessWorker × 6（竞争 pop_output(50ms)，多消费者安全）
          ① unpack_meta 解出 InferMeta（身份旁路）
          ② decode_rknn_outputs（本模块核心：DFL + conf 过滤 + 逆 letterbox + per-class NMS）
      → DetectionResultQueue（512，满则 push_blocking 阻塞）
  → ReorderThread（按 (stream_id, generation) 严格 seq+1 放出）
  → TrackThread（ByteTrack）→ PublishThread → 更新面 PUB
```

- **输入**：`InferOutput`（`user_meta` 字节 + `TensorData` 列表）。`user_meta` 由 `infer/meta_codec` 编解码，携带 `stream_id / seq / generation / letterbox / captured_at / stream_time_sec` 等身份键，全程 CPU 旁路，不进像素。
- **输出**：`FrameDetections`（`src/postprocess/types.h`）：身份键原样透传 + `vector<Detection>`。`Detection` 为**原图像素整数 xyxy** + `score` + `class_id`（`track_id` 此时恒为 -1，由下游 ByteTrack 填充），最终按 score 降序。
- **线程模型**：6 个 worker 线程竞争消费同一引擎输出队列；`DecodeConfig` 每 worker 一份只读拷贝。后处理不感知 Engine / NPU / 传输，只面向 `InferOutput` 编程。

## 2. 输入契约（模型输出张量）

RKNN 模型为 9 输出（RKNN 友好改造产物），顺序 `[box, cls, sum] × 3 尺度`：

| 张量 | 形状 | 说明 |
|---|---|---|
| box | `(1, 64, H, W)` | 4 边 × reg_max=16 的 DFL 分布 logits |
| cls | `(1, nc, H, W)` | 各类别分数（已过 sigmoid） |
| sum | — | **忽略不用**（两版实现一致） |

3 个尺度对应 grid `80×80 / 40×40 / 20×20`（imgsz=640，stride 8/16/32），共 8400 个 anchor 格子。**每个格子只有在 cls 最大类分过阈时才需要解码 box**——这是全部优化的出发点。

`decode_outputs.cpp` 在解码前做防御校验（任一不满足 → 该帧产出**空 dets 但保留身份键**，打 stderr 日志，不致命）：

- `tensors.size()` 为 0 / 非 3 的倍数；
- `TensorData::shape_matches_data()`（dims 与 data.size() 一致）；
- box/cls 均 4 维、`N=1`（NCHW）；box 通道数必须 64；box 与 cls 的 H、W 一致。

## 3. 优化历程：从 Python 基线到当前实现

### 3.1 阶段一：xtensor 全网格忠实移植（对齐 Python）

第一版按 Python `decode_rknn_outputs` 逐步镜像，全部用 xtensor 张量表达式：

`dfl()`（全网格 softmax+加权）→ `box_process()`（全网格 xyxy）→ `sp_flatten()`（转置+reshape）→ `filter_boxes()`（`xt::amax`/`xt::argmax` 过滤）→ `scale_boxes_to_orig()` → per-class `_nms`。

这一版的价值是**建立数值基线**：同输入下与 Python 输出一致（允许 float 微差，整数框对齐）。

### 3.2 阶段二：xtensor 懒求值的 Debug 性能陷阱

实测发现：Debug 构建下单帧后处理可达**数秒～十余秒、多核打满**（表现为"像死循环但不是"）。根因是 xtensor 表达式模板**懒求值**：`dfl()` 内的 `amax/exp/sum` 在被多处引用时反复重算。

两个对策，均已固化在代码里：

1. `dfl()` 参考实现内部改为**手写循环** softmax + 加权求和（不再用链式 xtensor 表达式）；
2. **构建强制 Release**：`src/CMakeLists.txt` 顶部 `if(NOT CMAKE_BUILD_TYPE) set(CMAKE_BUILD_TYPE Release ...)`，注释即此原因。

> 交接红线：**不要在后处理热路径引入 xtensor 链式表达式模板**；xtensor 目前只作容器类型与参考实现使用。

### 3.3 阶段三：score-first + 融合解码 + NEON 热路径（核心优化）

全网格实现即使 Release 后，仍要在 8400 个格子上无条件做 DFL（每个格子 4 边 × 16 logit 的 softmax 加权），而典型交通画面过 conf 阈的格子只有几十个。在 **8 路 × 10 FPS** 的极限压测目标驱动下，热路径整体重写为 `decode_branch_score_first()`（`dfl_decode.cpp`），把计算分配从"先解码再过滤"倒置为"**先过滤再解码**"。

## 4. 逐项优化详解（当前实现）

### 4.1 score-first：先扫 cls，过阈才做 DFL

`decode_branch_score_first()` 对每个尺度分支逐格处理：

1. 一趟循环扫 `nc` 个类别通道，求该格最大类分 `best_score` 与对应 `best_cls`（NCHW 布局，类通道步长 = `hw`）；
2. `best_score < conf_thres` → `continue`，**DFL 完全不执行**；
3. `obj_classes` 白名单非空且 `best_cls` 不在名单 → `continue`（白名单过滤内联进热路径，省掉 Python 版后置的 `np.isin` 掩码）。

效果：DFL 计算量从 O(8400 × 4 × 16) 降为 O(候选数 × 4 × 16)，背景格只付出一次 cls 扫描（且 cls 布局内存连续，缓存友好）。

### 4.2 融合 DFL + box 解码：不再物化任何中间张量

旧路径（及 Python）会物化 `(1,4,H,W)` 的 dist、xyxy 张量并做 transpose/reshape/concatenate。新路径对每个过阈格子**直接**：

```text
dist[side] = dfl_expect_reg16(gather 的 16 个 logit)      # side = lt,rb 共 4 边
x1 = (x + 0.5 - dist[0]) * stride_w      # grid 坐标 → letterbox 像素
y1 = (y + 0.5 - dist[1]) * stride_h
x2 = (x + 0.5 + dist[2]) * stride_w
y2 = (y + 0.5 + dist[3]) * stride_h
```

`stride_w = imgsz / grid_w`（8/16/32）。`box_process` 中的 meshgrid/concat/广播乘全部消失。

### 4.3 gather + NEON：dfl_expect_reg16 的实现与数值取舍

- `gather_reg16()`：NCHW 下同侧 16 个 logit 沿通道分布（步长 `hw`），先 gather 到 `alignas(16)` 的**连续栈缓冲**，才能用 NEON 一次加载。
- `dfl_expect_reg16()`（`__ARM_NEON` 分支）：
  - NEON `vmaxq` 树形归约求 16 logit 最大值（softmax 数值稳定减 max）；
  - **`std::exp` 刻意走标量循环**——代码注释原话："exp 走标量以保持与 Python 数值对齐；NEON 负责 max / 加权累加"。NEON exp 估计指令（`vexpq_f32`）与 libm `exp` 存在 ULP 级差异，会破坏与 Python 基线"整数框对齐"的验收标准，故性能上只吃 max 归约与加权累加两段；
  - 加权累加 `e[m] × m` 用 `vmlaq_f32`（4 组 float32x4 FMA）+ 水平相加，最后除 softmax 分母。
- 无 NEON 平台（x86 开发机）编译期回退纯标量分支，行为一致。

### 4.4 参考路径的同步优化

保留的全网格参考函数（供数值对齐与测试）也做了去表达式化：`filter_boxes()` 由 `xt::amax + xt::argmax` 两次张量表达式改为**一趟手写循环**同时求 best score 与 best class（与热路径的 cls 扫描同构）。

### 4.5 候选结构与 per-class NMS

- 候选框用紧凑结构体 `DecodedBox { x1,y1,x2,y2,score,class_id }`（AoS 布局，NMS 访问局部性好），先经 `scale_decoded_box_to_orig()` **原地**做逆 letterbox：`(v - pad) / scale`，并 clamp 到 `[0, src_w/src_h]`（与 Python `_scale_boxes_to_orig` 等价，含 Python 的 `LetterBoxParams` 单一 ratio 语义）。
- `decode_outputs.cpp` 内 `nms_decoded()`：按 `std::set<int>` 的 unique class 分桶 → 索引掩码 → 贪心 NMS。相对 Python `_nms` 的改进：用 `suppressed` 位图 + 保留 order 数组，免去每轮重建 order 的数组拷贝。IoU 公式含 `+1e-5` 宽高下限，与 Python 逐字对齐。
- 最终 `Detection` 坐标取 int，整帧按 score 降序 sort——与 Python 返回结构一一对应。

### 4.6 多 worker 并行

6 个 `PostprocessWorker` 竞争 `engine->pop_output(50ms)`（`BoundedQueue` 多消费者安全）。后处理单帧耗时可变（候选数波动），多消费者天然削峰；与 9 个 NPU worker 的产出节奏匹配。采用 `pop_output` 轮询而非回调，原因见架构文档 §5.4（回调须在 start 前设置且在 worker 线程内执行，与多线程竞争消费结构不符）。

## 5. 代码地图

| 文件 | 职责 | 关键函数 |
|---|---|---|
| `types.h` | `Detection / FrameDetections / DecodeConfig` | — |
| `dfl_decode.{h,cpp}` | 解码内核：NEON 热路径 + 全网格参考实现 + 逆 letterbox | `decode_branch_score_first` / `dfl_expect_reg16` / `gather_reg16` / `dfl` / `box_process` / `sp_flatten` / `filter_boxes` / `scale_boxes_to_orig` / `scale_decoded_box_to_orig` |
| `decode_outputs.{h,cpp}` | 编排：张量契约校验 → 逐分支解码 → scale → per-class NMS | `decode_rknn_outputs` / `nms_decoded` |
| `nms.{h,cpp}` | 通用单类贪心 NMS（xtensor 入参版，参考路径配套） | `nms_xyxy` |
| `postprocess_worker.{h,cpp}` | 线程壳：pop → unpack_meta → decode → push | `runLoop` |
| `detection_queue.h` | `DetectionResultQueue = UnorderedInferQueue<FrameDetections>` | — |

配置结构在 `src/app/service_config.{h,cpp}` 的 `PostprocessConfig`（postprocess 目录下不再有独立 config.cpp）。

## 6. 数据流与失败语义（重要）

`PostprocessWorker::runLoop` 的每帧处理与降级行为：

| 情形 | 行为 | 下游影响 |
|---|---|---|
| `pop_output` 超时 | 返回 nullopt，循环继续（50ms 轮询 stop_flag） | 无 |
| `unpack_meta` 失败 | `meta_fail_` 计数，**丢帧不产出**（无身份键无法入队） | reorder 等该 seq 超时（gap 2s 跳帧） |
| `ok=false` 空 envelope（推理失败） | tensors 保持空 → decode 产出**空 dets 帧但保留身份键** | reorder 正常按 seq 放出空帧，不悬挂（"缺帧跳过"旧语义） |
| 张量契约非法 / decode 抛异常 | catch `std::exception`，清空 dets 保留身份键，stderr 日志 | 同上，空帧 |
| 正常 | `decode_count_` / `empty_count_` 计数 → `push_blocking` 入 DetectionResultQueue(512) | 队列满阻塞，阻塞计数触发 SampleBackoff 降抽样（架构文档 §8） |

停机：`stop()` 置位 stop_flag 后 join，退出时打印 `decoded=/empty=` 汇总。

## 7. 配置

`services_config.yaml` → `yolo_inference_service.postprocess`（当前部署值）：

```yaml
postprocess:
  enabled: true            # D3 决议：仅接受 true，否则启动致命
  worker_count: 6
  conf_thres: 0.4
  iou_thres: 0.7
  imgsz: 640               # 校验用：与 engine input_geometry() 不一致时 WARN，以模型为准
  obj_classes: []          # 空 = 不过滤；非空 = 类别白名单（内联进 score-first）
  detection_queue_capacity: 512
```

注意：`DecodeConfig`（`types.h`）的代码缺省值 `conf 0.25 / iou 0.45 / imgsz 640` 是**对齐 Python 参考的缺省**；实际部署值以 YAML 为准（0.4 / 0.7），不要直接改代码缺省来调参。

## 8. 构建与性能约束

- 模块随服务统一构建：`cmake -S . -B build && cmake --build build -j`（`src/CMakeLists.txt`，无独立 postprocess 库目标）。
- **强制 Release**（`src/CMakeLists.txt` 顶部）：Debug 下 xtensor 表达式模板懒求值可使后处理退化到秒级/帧。任何本地 Debug 调试请只跑参考路径，性能结论一律以 Release 为准。
- xtensor/xtl 依赖：优先复用旧树构建缓存（`service_new_new_new/yolo_inference_service/build/_deps/`），否则 FetchContent（xtl 0.7.7 + xtensor 0.25.0）。不引入 OpenCV/Eigen（旧方案强制意见 2）。
- 后处理禁止下沉进推理 worker（旧方案强制意见 3）：`InferWorker` 只产出张量，DFL/NMS 只在 postprocess 消费——保持 NPU 线程不被 CPU 后处理阻塞。

## 9. 验证方法与现状

1. **Python 数值对齐**（最高优先级验收）：用同一组 tensors + LetterboxMeta 分别喂 `decode_rknn_outputs`（Python）与 C++ `decode_rknn_outputs`，断言框/分/类一致（允许 float 微差、整数框逐位对齐）。任何改动解码顺序/数值路径（如把 exp 换成 NEON 估计）都必须重跑此项。
2. **算法单测**：`tests/test_yolo_front_back.cpp` 覆盖 DFL 均匀 logits → 期望 7.5、per-class NMS 抑制边界、decode 编排的异常回退与类别过滤、mock 引擎端到端数值闭环。
   ⚠️ **现状缺口**：该测试当前**未接入构建**（顶层/`src` 的 CMakeLists 均无 `add_subdirectory(tests)`），且其 include 的 `src/postprocess/config.h`、`frame_meta.h` 为旧结构路径、现已不存在。README 中 `./build/tests/test_yolo_front_back` 的说法已过时。接手后第一件事建议：按现行结构修复该测试（`DecodeConfig` 改由 `service_config` 提供）并重新挂进 CMake。
3. **性能验收**：8 路 × 10 FPS 压测（历史通过口径，commit `acb7bc6f`）。观察指标：postprocess worker 的 `decoded/empty` 计数（`status` RPC 聚合）、DetectionResultQueue 是否触发 SampleBackoff。

## 10. 交接注意事项与后续方向

- **数值对齐是刻意取舍**：exp 标量化、`+1e-5`、score 降序 tie-break 等细节均为对齐 Python 而设。要进一步提速可改 NEON exp / 查表 softmax，但会引入 ULP 偏差，需重新对齐并评估整数框翻转率。
- 热路径若需支持非 64 通道 box（换 reg_max≠4 的模型），`kBoxChannels` 校验与 `kRegMax=16`、NEON 的 4×float32x4 结构都要联动改——目前按 reg_max=16 写死。
- 多尺度分支数写死为 3 的倍数约定；若换单输出模型（Ultralytics 格式），走的是另一条 Python 路径 `decode_yolo_output`，C++ 侧未实现，不要混用。
- 全网格参考函数（`dfl/box_process/sp_flatten/filter_boxes/nms_xyxy`）只为测试与对齐保留，**不要在服务热路径调用**（性能与 Debug 陷阱双重原因）。
- 后续可考虑：per-class NMS 前先做一次跨类别的粗去重（当前实现完全对齐 Python，跨类重叠框会保留，与基线行为一致，改动前先确认下游可接受）。

# 旧版 yolo_inference_service 功能总结（重构底稿）

> 目的：重构 `service_ultimate/yolo_inference_service` 前，对旧实现
> （`device_run_new/service_new_new_new/yolo_inference_service`，C++17 单进程，约 9.6K 行 C++ + Python 客户端）
> 做代码级盘点。**所有内容以代码为准**。引用格式：旧服务内相对路径 + 行号。
> 本文档核心回答两个问题：**该服务需要什么输入，产出什么输出**（§2 / §3），其余章节为支撑细节。

---

## 1. 服务定位与模块地图

一句话职责：**消费上游 `rtsp_receive_service` 的 NV12 抽样帧（三平面取数）→ RGA3 前处理写入本服务 RGB888 DMA-BUF 环 → RKNN NPU 多核推理 → DFL/NMS 后处理 → 按 (stream_id, generation) seq 重排 → ByteTrack 追踪 → ZMQ 双平面（控制面 ROUTER / 更新面 PUB）对外发布满载检测结果**。

```text
src/
  main.cpp                    全流水线编排：6 份配置 + 6 条队列 + 各阶段线程装配与倒序关停
  preprocess/                 上游接入 + RGA 前处理 + 本地 RGB 环
    ├─ upstream_ingress.*       三平面客户端周期刷新 / 事件→按流排队 / 重连
    ├─ rga3_preprocess.*        RGA3 NV12→RGB888 letterbox，dst 槽 handle 缓存
    ├─ local_rgb_ring.*         core RingBuffer 适配层（FixedSlot+DmaBuf+RejectWrite）
    └─ preprocess_pipeline.*    RGA 线程 + publish 后薄回调钩子
  inference/                  NPU 推理
    ├─ input_source.*           publish 回调 → pin 槽 → try_push meta/admit
    ├─ infer_worker.*           pop meta → rknn run → release → push raw
    ├─ rknn_runner.*            RKNN ctx（thread_local）/ INT8 去量化
    └─ sample_backoff.*         队列压力 → SQLite 全流 sample_interval_ms 递增
  postprocess/                DFL 解码 + NMS（xtensor + NEON 热路径，多 worker）
  reorder/                    AdmitQueue + ReorderBuffer 严格 seq+1 放出 / gap 超时跳帧
  trace_track/                StreamTrackerHub（每流 ByteTracker）+ 装配双通道输出
  comm_server/                对外：PublishThread(PUB) + ControlServer(ROUTER) + ResultStore + wire_pack
  py_client/                  Python 下游 SDK（YoloInferenceClient + InferenceUpdateSubscriber）
```

核心数据流（身份旁路 `stream_id/seq/generation/letterbox` 由 CPU 全程携带，不写入像素）：

```text
rtsp_receive_service 三平面
  → ingress: FrameUpdate(stream_id,seq,gen,buffer_index,w,h,stride…)
  → data_plane read_frame(seq) → SCM_RIGHTS NV12 fd（用后异步 release）
  → RGA3: NV12 → RGB888 letterbox 640×640 → LocalRgbRing 槽 publish
  → InferInputSource: acquire → InferMetaQueue + AdmitQueue
  → InferWorker×9 (NPU core 0/1/2 ×3): mmap 槽 → rknn_run → INT8 去量化 TensorData → UnorderedInferQueue
  → PostprocessWorker×6: DFL + conf 过滤 + 坐标还原原图 + per-class NMS → DetectionResultQueue
  → ReorderThread: admit/ingest 按 (stream_id,generation) 严格 seq+1 放出 → OrderedResultQueue
  → TrackThread: ByteTrack（每流独立）→ dets(原始) + track_dets(带 track_id) → TrackedResultQueue
  → PublishThread: ResultStore.put + is_latest → msgpack InferenceUpdate → ZMQ PUB
```

与上游依赖关系：CMake 直接 `add_subdirectory` 上游 `rtsp_receive_service/src/c_client`（`drn_c_client`，preprocess/CMakeLists.txt:13-16）；环本体复用 `core_module/c_cpp_module/ring_buffer`。

---

## 2. 服务需要什么输入（Input）

### 2.1 上游帧输入：rtsp_receive_service 三平面（主要输入）

| 平面 | 端点（部署值） | 用途 |
|------|----------------|------|
| 控制面 ROUTER | `ipc:///tmp/drn-rtsp-receive.sock`（`upstream.control_endpoint` 必填） | `health()` 发现 update/data 端点并校验 `data_plane` 声明含 `dma_buf`；周期 `list_streams()` 刷新流目录（默认 5s，`ingress.stream_refresh_interval_sec`） |
| 更新面 PUB | health 自动发现（`upstream.update_endpoint` 空时） | 订 `FrameUpdate` 轻事件（recv 超时 200ms），驱动取帧 |
| 数据面 UDS | health 自动发现（`upstream.data_endpoint` 空时） | `read_frame(stream_id, seq)` 精确取帧 → SCM_RIGHTS 收 NV12 DMA-BUF fd；empty/无 fd 时按 `fallback_read_latest=true` 回退 `read_latest`；用完经异步 release 队列归还槽引用（全部数据面收发集中在 ingress 单线程） |

输入事件 `FrameUpdate` 字段（上游契约）：`stream_id, seq(≥1), generation, buffer_index, width, height, stride_y, stride_uv, captured_at, stream_time_sec`。

ingress 输入过滤与容错（upstream_ingress.cpp:351-591）：

- `subscribe_stream_ids` 白名单（空 = 订全部流）。
- 流目录过滤：descriptor `enabled=false / fault=true` 的事件直接丢。
- **generation 校验**：事件 generation 与目录不符 → 先 refresh 目录再校验，仍不符丢弃并计数；数据面返回的 `handle.generation` 与事件不符同样丢弃并触发 refresh。
- **重连**：传输类错误（broken pipe / peer closed / connection refused 等，刻意排除 EAGAIN 超时）→ 丢队列 + flush release + 整链重建，退避 1s（`reconnect_backoff_sec`）。
- **stale 强制重连**：目录里有活流出帧但本服务 10s（`stale_reconnect_sec`）无成功入队 → 重连（防 RTSP 重启后 ZMQ IPC SUB 幽灵连接只跑 VPU、NPU 空闲）。
- 每流待处理队列上限 `max_queue_per_stream=4`，满丢最旧。

### 2.2 模型与类别表文件

| 输入 | 部署值 | 要求 |
|------|--------|------|
| RKNN 模型（`infer.model_path`） | `config_files/traffic_edge_box_label_tiny_inference.rknn` | 单输入 640×640×3（NHWC UINT8，RGB888）；输出 INT8 非对称量化；输出张量数须为 3 的倍数（每尺度 3 张量：box(64ch DFL)+cls+1 个未用张量）；动态 shape 模型自动 `rknn_set_input_shapes(batch=1)`，静态模型跳过（调用会毁 ctx，rknn_runner.cpp:204-255） |
| 类别名表（`tracking.names_path`） | `config_files/traffic_edge_box_label_tiny_inference.yaml` | Ultralytics `names` map（id→name）；空 = 输出 `cls{id}`；**全仓唯一类别表入口**，index_calcu 过车落库/灯色解析也读此处 |

### 2.3 共享 SQLite（`infer.stream_db_path`）

`sqlite/traffic_data.sqlite`：本服务**只写不读**——队列压力时 `UPDATE stream_configs SET sample_interval_ms = sample_interval_ms + 25`（全行、仅 `>0` 行，sample_backoff.cpp / §5 背压），依赖 rtsp_receive_service 的 SQLite 热更新感知生效；两次成功写库间冷却 60s。

### 2.4 YAML 配置

单一 `config_files/services_config.yaml` 的 `yolo_inference_service` 顶层节点（节点/文件缺失**不致命**，用默认值继续跑——与 rtsp 严格校验相反，见 §9）。部署值汇总：

```yaml
yolo_inference_service:
  log_level: INFO
  log_path: <logs/yolo_inference_service>          # 声明了但当前未接 spdlog
  upstream:    { control_endpoint: ipc:///tmp/drn-rtsp-receive.sock,
                 update_endpoint: "", data_endpoint: "",       # 空 = health 发现
                 subscribe_stream_ids: [] }                      # 空 = 全部流
  ingress:     { max_queue_per_stream: 4, update_timeout_ms: 200,
                 fallback_read_latest: true, stream_refresh_interval_sec: 5.0,
                 reconnect_backoff_sec: 1.0, stale_reconnect_sec: 10.0 }
  local_ring:  { capacity: 16, drop_when_busy: true }
  infer:       { enabled: true,
                 model_path: <…tiny_inference.rknn>,
                 core_masks: ["0","1","2"], instances_per_core: 3,   # 9 workers
                 meta_queue_capacity: 512, unordered_queue_capacity: 512,
                 sample_backoff_ms: 25, sample_backoff_cooldown_ms: 60000,
                 stream_db_path: <sqlite/traffic_data.sqlite> }
  postprocess: { enabled: true, worker_count: 6, conf_thres: 0.4, iou_thres: 0.7,
                 imgsz: 640, obj_classes: [], detection_queue_capacity: 512 }
  reorder:     { enabled: true, gap_timeout_sec: 2.0, max_waiting_per_stream: 64,
                 poll_timeout_ms: 50, admit_queue_capacity: 512,
                 ordered_queue_capacity: 512, sample_backoff_on_ordered_block: true }
  tracking:    { enabled: true, frame_rate: 8, track_thresh: 0.5, track_buffer: 30,
                 match_thresh: 0.8, edge_margin_ratio: 0.01, low_score: 0.1,
                 second_match_thresh: 0.5, unconfirmed_match_thresh: 0.7,
                 mot20: false, tracked_queue_capacity: 512, poll_timeout_ms: 50,
                 sample_backoff_on_tracked_block: true, names_path: <…tiny_inference.yaml> }
  transport:   { endpoint: ipc:///tmp/drn-yolo-inference.sock,        # 控制面 bind
                 update_endpoint: ipc:///tmp/drn-yolo-inference-updates.sock,  # PUB bind
                 update_hwm: 1024 }
  results:     { history_size: 32 }                # 进程内 ResultStore 每流历史
  publish:     { poll_timeout_ms: 50 }
```

校验（comm_server/config.cpp:32-55）：两个对外端点须为 `ipc:///` 且互不相同、与已知外部端点错开；其余节点仅做下限夹取。

### 2.5 运行环境依赖

RGA3（librga im2d，**仅 RGA3**，禁 imfill/RGA2 路径）、RKNN runtime（RK3588 三核 NPU，`rknn_set_core_mask` 显式绑核）、core_module RingBuffer、cppzmq / msgpack-cxx / yaml-cpp / xtensor(+xtl)。构建强制 Release（Debug 下 xtensor 表达式模板后处理可达数秒/帧，CMakeLists.txt:10-12）。

---

## 3. 服务输出什么（Output）

### 3.1 更新面 ZMQ PUB —— 主数据路径（`transport.update_endpoint`）

- Wire 帧：`[topic = UTF-8(stream_id) + '\0'] [msgpack(payload, use_bin_type)]`，两帧 multipart；topic 尾 NUL 防前缀误匹配。
- 发送策略：`SNDHWM=1024` + **非阻塞**；失败计 `publish_drop` 继续下一帧，**不反压不重试**；慢订阅者丢事件是设计行为。
- 仅 `comm_server/PublishThread` 持有 PUB socket；流水线各阶段禁止对外发布。

事件 `InferenceUpdate`（wire_pack.cpp:126-146）：

```jsonc
{
  "is_latest": true,          // 该流当前 latest 是否指向本帧（ResultStore 计算）
  "inferred_at": 1757…,       // 发布时刻（秒，墙钟）
  "result": {                 // 满载一帧结果，9 键
    "stream_id": "1",
    "generation": 3,           // 环代次（必写）
    "source_epoch": "3",       // = to_string(generation)，兼容旧下游（必写）
    "seq": 1024,               // 上游抽样 seq（重排后仍用此键）
    "width": 1920, "height": 1080,   // 原图像素（letterbox.src_w/h）
    "letterbox": { "scale": 0.33, "pad_x": 0, "pad_y": 174,
                   "dst_w": 640, "dst_h": 640, "new_w": 640, "new_h": 576 },
    "untracked_detections": [ /* 推理全量原始框，永不出现 track_id 键 */ ],
    "detections": [ /* 追踪通道；条目 track_id>=1 时才写该键 */ ]
  }
}
```

检测条目（两通道同构，置信度键锁定 `score`）：

```json
{ "box": [x1, y1, x2, y2],      // 原图像素 xyxy 整数
  "score": 0.92, "class_id": 0, "class_name": "car",
  "track_id": 5 }                 // 仅 detections 且 track_id>=1 时写入
```

- `untracked_detections`（进程内 `dets`）= 后处理原始框（无 track_id）；`detections`（进程内 `track_dets`）= ByteTrack 在线轨迹框。**两通道条数不必相等**（追踪通道是轨迹集合，非逐原始框打标）。
- `captured_at / stream_time_sec` 首版未透传（可缺省）。

### 3.2 控制面 ZMQ ROUTER —— 探活与诊断（`transport.endpoint`）

- 信封：请求 `{request_id, operation, payload}`（msgpack map）；应答 `{request_id, ok, error(nil|str), payload}`（control_server.cpp:45-67）。bind 前 unlink 残留 IPC 文件，linger=0。
- **不是正常取数通道**；下游主路径 = health 取 `update_endpoint` → SUB 直连。

| operation | 参数 | 成功 payload |
|---|---|---|
| `health` | - | `{update_endpoint, known_streams[], result_stream_count}` |
| `status` | - | `{update_endpoint, publish_ok, publish_drop, emit_count, publish_pack_fail, result_store_stream_count}`（+ 可注入 extra） |
| `get_latest` | `{stream_id}` | `{result}`（同 3.1 的 result map）；无结果回 `not_found` |
| `list_latest` | - | `{results: [result…]}`（所有有结果流的最新一条） |

`get_latest/list_latest` 由进程内 `ResultStore`（每流有界历史 32 条）供数，定位为**过渡补洞 / deprecated**。

### 3.3 副作用输出：SQLite 降抽样反馈

队列压力触发 `sample_interval_ms += 25`（§2.3 / §5），经 rtsp 热更新收敛上游帧率——这是本服务对共享库的唯一写路径。

### 3.4 既定下游消费者（重构必须保持的契约面）

- `index_calcu_service`（`src/da/input_thread.py`）：`YoloInferenceClient.subscribe_updates()` 订满载事件 → 过车 / 灯态 / 维度统计落库；读同一 names 表。
- `fastapi_backend_service`（`src/core/preview_adapter.py`，`service_inference_endpoint` 配置）：取检测结果做前端预览框渲染。
- 通用 Python SDK：旧服务自带 `src/py_client/`（`YoloInferenceClient` 控制面 DEALER + `InferenceUpdateSubscriber` SUB，endpoint 经 health 发现、回落默认 `ipc:///tmp/drn-yolo-inference-updates.sock`）。

### 3.5 明确不输出

- **无**对外像素 / 结果 DMA-BUF 或结果数据面（与上游 rtsp 三平面不同，本服务只有两平面）；载荷不含像素与 RTSP 凭证。
- PUB 失败不抛穿主循环、不回滚 ByteTrack 状态、不当帧重试。
- 不写任何业务统计表（过车/灯态归 index_calcu，职责边界见 code_guidelines 准则 2）。

---

## 4. 流水线各阶段行为（输入如何变成输出）

### 4.1 RGA 前处理与本地环（preprocess）

- Letterbox（rga3_preprocess.cpp:85-115）：`scale = min(640/w, 640/h)`；`new_w/h` 偶数对齐并夹 [2,640]；`pad = round((640−new)/2 − 0.1)`（对齐 Ultralytics）；垫色 114。
- 源 NV12：每帧 import（4-arg `importbuffer_fd` 显式传宽高/格式，避免 RGA 自动探测 VPU tiled 修饰符出错），用后 release；dst：每槽 import 一次缓存 handle。几何变小时对槽再 `memset(114)` 防旧内容露边。
- 输出写入 **LocalRgbRing**：core `RingBuffer`（FixedSlot + DmaBuf + RejectWrite），capacity 16，槽 640×640×3 ≈ 1.17 MiB；目标槽被推理持有（全忙）→ 丢帧（`drop_when_busy`）。侧表存 LetterboxMeta + 上游身份，seq 哨兵保护；`publish_commit` 成功后在同 RGA 线程薄回调 `on_frame_published`（preprocess 不拥有下游队列）。

### 4.2 推理（inference）

- `InferInputSource::on_frame_published`（input_source.cpp:35-106）：`acquire(seq_local)` pin 槽 → `InferMeta{dma_fd, slot_index, 上游身份, letterbox}` `try_push` meta 队列（满 → release + 丢帧 + 触发 backoff）→ 同步 `try_push` `AdmitEvent` 进 reorder admit 队列（元数据先行，结果未到由 reorder 兜底）→ release 本侧引用（worker 自持 pin）。
- `InferWorker` ×9（core_masks 0/1/2 × instances_per_core 3）：竞争 pop meta → mmap 槽 fd（PROT_READ）→ `rknn_inputs_set`（驱动拷贝后立即 munmap）→ `rknn_run` → `rknn_outputs_get` → INT8 仿射去量化为 `TensorData{data, index, dims}` → **先 release 槽再** push raw 队列。每个 worker 线程 `thread_local` 独立 RKNN ctx + 显式绑核；推理失败仍 release 并**推送空 tensors envelope**（下游按缺帧跳过，不悬挂重排）。

### 4.3 后处理（postprocess）

`decode_rknn_outputs`（decode_outputs.cpp:85-197）：每尺度取第 0/1 张量（box 64ch DFL + cls，NCHW N=1）；`decode_branch_score_first` 融合 DFL 解码（热路径 NEON）；conf 阈值 0.4 过滤 + `obj_classes` 白名单；letterbox 逆变换还原到**原图像素坐标**；per-class NMS（IoU 0.7）；输出按 score 降序的 `FrameDetections`（含身份旁路键）。张量数非 3 的倍数 / shape 不匹配 → 该帧空结果（不致命）。

### 4.4 重排（reorder）

- 双输入：`AdmitQueue`（帧已被接受的元数据）+ `DetectionResultQueue`（乱序结果）；ingest 前反复排空 admit 防 orphan。
- 状态按 `(stream_id, generation)` 隔离；generation 切换丢旧 epoch 全部状态。期望序 `expected = last_released + 1`，**严格连续才 flush**；`waiting` 每路上限 64，满且到达序恰为 expected 时逐出最旧非 expected，否则拒收。
- `gap_scan`：队头缺结果等待超 2s（`gap_timeout_sec`）→ `result_missing` 跳过该 seq，或已有更晚结果时 `min_diff_jump` 跳到距 expected 最近的已到结果并清理更旧的 admitted/waiting（跳帧计数）。
- 流移除（上游目录 removed / stream_gone）→ `forget_stream` 清状态；停机抽干。
- `PassthroughThread`（reorder 关闭直通）已实现但 **main.cpp 未使用**（无条件建 ReorderThread，`reorder.enabled` 实际不生效，§9）。

### 4.5 ByteTrack 追踪（trace_track）

- `StreamTrackerHub`：每流一个 `ByteTracker`；generation 变化重建轨迹（epoch 隔离）；`seq <= last_tracked_seq` 的乱序帧**不喂 tracker**，直接短拷原始框输出。
- 贴边过滤：box 距原图边缘 < `edge_margin_ratio(0.01)×宽/高` 的检测不入 tracker（防画面边缘半目标污染轨迹）；过滤后空 boxed → 短路同上。
- 输出装配（assemble_frame）：`dets` = 原始框去 track_id；`track_dets` = tracker 在线轨迹框（Kalman 后 tlbr 取整 + track_id）；两通道都 enrich `class_name`（names 表缺失回 `cls{id}`）。
- 追踪关闭（`tracking.enabled=false`）时 track_dets 与原始同语义、无 track_id。

### 4.6 发布（comm_server）

`PublishThread`：pop tracked → `ResultStore.put`（进程内每流 32 条历史，供 get_latest 与 `is_latest` 计算）→ msgpack 组包 → PUB（`publish(topic, payload)` 非阻塞）。组包失败计 `publish_pack_fail` 跳过该帧。`ControlServer` 单线程 poll(100ms) 处理 ROUTER 请求。

---

## 5. 队列、线程与背压（有界 + latest-wins + 降抽样）

| 队列（容量，部署值） | 生产者 → 消费者 | 满时行为 |
|---|---|---|
| ingress 每流 deque（4） | ingress → RGA 线程 | 丢最旧 |
| LocalRgbRing（16 槽，RejectWrite） | RGA → 推理 | 目标槽被持有即丢帧 |
| InferMetaQueue（512） | input_source → 9 infer worker | try_push 拒收丢帧 + **backoff** |
| UnorderedInferQueue（512） | infer worker → 6 postprocess | push_blocking 阻塞 + **backoff** |
| DetectionResultQueue（512） | postprocess → reorder | push_blocking（不触发 backoff） |
| AdmitQueue（512） | input_source → reorder | try_push 拒收（后续 orphan 丢弃） |
| OrderedResultQueue（512） | reorder → track | push_blocking + backoff（可配） |
| TrackedResultQueue（512） | track → publish | push_blocking + backoff（可配） |

**SampleBackoff 全流降抽样**：触发点 `meta_queue_full / raw_queue_block / ordered_queue_block / tracked_queue_block` → SQLite 全行 `sample_interval_ms += 25`，冷却 60s（冷却期内只计数不写库）。这是准则 7「过载以降抽样消化」的落地。

线程清单：ingress×1、RGA×1、infer×9、postprocess×6、reorder×1、track×1、publish×1、control×1，加主线程（100ms 轮询 stop 标志）。

---

## 6. 进程生命周期（main.cpp）

- 启动：6 份独立配置加载（preprocess / infer / postprocess / reorder / tracking / comm_server）→ 构造全部队列与 ResultStore → 可选 SampleBackoff → `PreprocessPipeline.start()`（创建 LocalRgbRing，**必须先于** InferInputSource 构造）→ `set_on_frame_published` → 建 9 个 infer worker（`infer.enabled=false` 或 core_masks 空时兜底单 worker core "0"——注意 `enabled=false` 并不会完全不推）→ 6 个 postprocess worker → reorder → track → `PublishThread.bind` / `ControlServer.bind`（失败直接退出）→ `set_on_stream_removed`（流移除时联动 forget reorder/track/result_store）→ start。
- 关停：SIGINT/SIGTERM → 原子 stop 标志 → **先 stop 全部队列**（唤醒 push_blocking/pop 防 join 死锁）→ 倒序 join（ctrl → pub → track → reorder → post → infer → preprocess）→ stderr 打印退出统计（pre_rga_fail / ingress_miss / ingress_reconnect / meta_accept/reject / post_decode/empty / reorder_released / track_assembled / pub_ok/drop/emit，main.cpp:236-261）。各阶段线程停机前均有抽干逻辑。

---

## 7. 契约锁定点（重构不可破坏，除非与下游协商）

1. 更新面 wire：topic = `stream_id + '\0'` 两帧 multipart；msgpack `use_bin_type`；事件三键 `is_latest / inferred_at / result`。
2. `result` 九键固定；`generation` 与 `source_epoch`（字符串化）**都必写**；`seq` 对外沿用上游抽样 seq；`width/height` 为原图（非 640）。
3. 置信度键锁定 `score`；`box` 为原图像素整数 xyxy；`class_name` 缺失回退 `cls{id}`。
4. 双通道语义：`untracked_detections` 永不出现 `track_id` 键；`detections` 仅 `track_id>=1` 写入，关闭追踪时省略；两通道条数不必相等。
5. PUB 满即丢（SNDHWM + NOBLOCK）、只计 `publish_drop`，不反压、不重试、不回滚追踪状态；慢订阅者丢事件合法。
6. 下游主取数路径 = **只订更新面**；`get_latest/list_latest` 仅为补洞（保留但定位 deprecated）。
7. 输入侧：像素只经数据面 DMA-BUF fd；`release` 槽引用协议与上游数据面一致（同连接同流单帧持有、断连统一释放）。
8. 身份旁路（stream_id/seq/generation/letterbox）全程 CPU 携带，不写入 DMA-BUF 像素。

---

## 8. 测试面

`tests/test_e2e.py`（需 rtsp_receive_service 已启动 + build 产物）：拉起二进制 → py_client 订阅更新面，断言 (1) 能收 `InferenceUpdate`；(2) 每流同时含 `dets` 与 `track_dets` 双通道；(3) 每流 seq 严格 +1 递增（验证重排有效性）。`tests/quick_test.py` 为快速冒烟。旧服务无独立 systemd 单元（systemd/ 目录为空，进程裸跑 + stderr 日志落 `log/`）。

---

## 9. 已知问题与重构注意清单（旧 README/plans vs 实现的偏差）

**协议/行为层面**
1. 配置加载**宽松**：YAML 文件或节点缺失 → 默认值继续跑（各 config.cpp 只 stderr 提示）；与 rtsp「严格校验致命」不一致；`log_level/log_path` 读了但**全服务用 fprintf(stderr)**，无命名 logger / 滚动日志（违准则 3 的落地标准）。
2. `reorder.enabled=false` **不生效**：main.cpp 无条件构造 ReorderThread；PassthroughThread 是死代码。
3. `infer.enabled=false` 不完全不推理：core_masks 为空时仍兜底建单 worker（main.cpp:130-138）。
4. `postprocess.enabled=false` 时无人消费 raw_queue → 推理结果堆满 512 后阻塞 worker 并持续触发 backoff（组合配置陷阱）。
5. 模型每尺度第 3 个输出张量（`3i+2`）未被使用（decode 只取 box/cls）；换模型须重新核对张量布局。
6. 推理输入非零拷贝：每帧 mmap → `rknn_inputs_set` 由驱动拷贝后 munmap（rknn_runner.cpp:54-84）；未用 rknn tensor import DMA-BUF 直通路径。
7. `captured_at / stream_time_sec` 未透传到输出（README 承诺"有则透传"，实现未做）。
8. `LocalRgbRing::release` 内置 clamp(0) 容忍二次释放（input_source 与 infer_worker 都会 release 同一槽，靠该防护无害）——重构应收敛为单一释放责任点。

**结构/工程层面**
9. 无 flock 单例、无 sd_notify、无 systemd 单元；多实例会抢 bind IPC 文件（bind 前 unlink 残留会顶掉旧实例）。
10. CMake 直接依赖上游 `rtsp_receive_service/src/c_client` 源码目录（跨服务内部模块引用，违准则 2/9 的边界）；`service_ultimate/core_module/c_cpp_module/three_plane` 已下沉通用传输层，重构应改接该组件。
11. 环本体已在 core_module（FixedSlot+DmaBuf+RejectWrite 适配），`local_rgb_ring` 是薄适配层（侧表 + seq 哨兵），可随服务迁移。
12. py_client 与 rtsp py_client 风格一致但独立成包；重构时按准则下沉为官方 SDK 并保持 wire 契约（或同步升级 index_calcu / fastapi）。
13. 配置迁 `service_ultimate/config_files/services_config.yaml`；DB 指向 `service_ultimate/sqlite/traffic_data.sqlite`（与 fastapi / rtsp 同库，准则 5/6）。
14. 退出统计只打 stderr；阶段计数器（backoff applied/skipped/fail、ingress miss 等）未纳入控制面 `status`（extra_status 钩子已预留未接）。

**重构落位建议（对齐 service_ultimate 准则）**
- 命名 logger / 单例锁 / sd_notify / 信号驱动关停顺序对齐 rtsp 重构后的进程壳规范（准则 10）。
- 「输入 = 三平面客户端 + 模型 + names + SQLite 写 + YAML；输出 = PUB 满载事件 + ROUTER 探活 + 降抽样反馈」的边界保持不变；内部各阶段队列与 backoff 语义（§5）建议原样保留。

---

## 10. 旧服务文档索引

- 服务内 plans：`c_client_rga_preprocess_plan.md`（前处理/上游接入）、`inference_from_preprocess_plan.md`（环→推理衔接）、`postprocess_dfl_nms_xtensor_plan.md`（DFL/NMS）、`reorder_plan.md`（重排缓冲）、`bytetrack_xtensor_plan.md`（追踪）、`inference_result_publish_plan.md` + `comm_server_plan.md`（对外两平面）。
- 各模块 `src/*/README.md`；服务根 `README.md`（功能与对外契约，与本文档一致处可直接复用）。
- 相关：`service_ultimate/rtsp_receive_service/plans/legacy_rtsp_receive_logic_summary.md`（上游契约权威盘点）、`service_ultimate/code_guidelines.md`。

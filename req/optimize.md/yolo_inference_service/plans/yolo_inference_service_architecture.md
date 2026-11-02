# yolo_inference_service 架构设计（service_ultimate 封板版）

> 本文以 [`legacy_yolo_inference_logic_summary.md`](legacy_yolo_inference_logic_summary.md)（下称「旧版总结」）为底稿，
> 在**保持对外契约（旧版总结 §7 锁定点，除 D5 明确决议的破坏性变更外）不变**的前提下，把服务迁移到
> `service_ultimate` 并改为装配 `core_module` 基础组件。设计准则来源：
> [`service_ultimate/code_guidelines.md`](../../code_guidelines.md)（下称「准则 N」）；
> 组件语义来源：[`core_module/c_cpp_module/three_plane/README.md`](../../core_module/c_cpp_module/three_plane/README.md)、
> [`core_module/plans/rknn_engine_plan.md`](../../core_module/plans/rknn_engine_plan.md)（其阶段 2 即本文）；
> 组件实现现状以 `core_module/c_cpp_module/rknn_engine/{include,src}` 实测代码为准（§2.1）。
> 参照范本：[`rtsp_receive_service/plans/rtsp_receive_service_architecture.md`](../../rtsp_receive_service/plans/rtsp_receive_service_architecture.md)。
> **决策点 D1–D6 已全部定稿**（§12），本文各处直接按决议后的目标态表述。

---

## 0. 结论速览

| 维度 | 旧版（service_new_new_new） | 新版（本文） |
|---|---|---|
| 推理 | 服务内 `src/inference`（rknn_runner thread_local ctx + 9 worker + 两条队列 + 双 release 靠 clamp 容忍 + mmap 驱动拷贝输入） | **整段删除**，替换为 `core_module/c_cpp_module/rknn_engine`（`IInferenceEngine` 注入；零拷贝 import 主路径、「凡进入 submit 的任务恰好一次 release」、背压事件回调） |
| 上游接入 | CMake `add_subdirectory` 旧树 `rtsp_receive_service/src/c_client`（跨树跨服务源码引用） | c_client **下沉** `core_module/c_cpp_module/three_plane_client`（D1 已定稿，本重构前置阶段产出），服务只链接组件 |
| 对外两平面 | 服务内 `comm_server`（control_server ROUTER + publisher PUB + wire_pack 信封） | 传输层**复用** `core_module/c_cpp_module/three_plane`（ControlPlaneServer + UpdatePublisher）；服务侧只写 RPC 领域打包、InferenceUpdate 打包 |
| 控制面操作 | 4 个（health / status / get_latest / list_latest） | **2 个**（health / status）；`get_latest / list_latest` 删除（D5 已定稿），index_calcu 补洞经其既有配置 `fallback_poll_sec=0` 禁用，随其后续大改造彻底移除 |
| 进程内结果历史 | ResultStore 每流 32 条历史（服务 get_latest / is_latest） | 精简为 `latest_tracker`（每流最新 seq，仅支撑 `is_latest` 计算）；`results.history_size` 配置键删除 |
| 本地 RGB 环 | core `RingBuffer` + `local_rgb_ring` 薄适配（几何写死 640×640×3） | 同构保留；槽几何改查 `engine->input_geometry()`（rknn_engine 强制意见 7） |
| Python 下游 SDK | 服务自带 `src/py_client` | 已下沉 `core_module/py_module/yolo_client`（官方 SDK 单点，本服务不再携带；D5 随之修剪 `get_latest/list_latest` 方法） |
| 配置 | 6 份独立加载、宽松校验（缺失用默认值）；`services_config.yaml` 当前**无** `yolo_inference_service` 节点 | 单份 `service_config` 严格校验（D2 已定稿，对齐 rtsp）；补齐 `services_config.yaml` 节点 |
| 日志 | 全程 `fprintf(stderr)`，`log_level/log_path` 读了不接 | `init_loggers` 命名 logger 先于一切模块；three_plane / rknn_engine 的 `LogFn` 桥接到命名 logger |
| 进程壳 | 裸跑、无 flock、无 sd_notify、无 systemd 单元 | 对齐 rtsp 壳：flock 单例、sd_notify、信号驱动倒序关停、systemd 单元 + manage.sh |
| enabled 开关 | `reorder.enabled` 不生效（死代码）、`infer.enabled=false` 仍兜底建单 worker、`postprocess.enabled=false` 堆队列陷阱 | 语义收敛（D3 已定稿）：infer/postprocess 仅接受 true 否则致命；reorder/tracking 的 passthrough 真正接通 |
| 统计 | 退出时 stderr 打印；`status` 的 extra 钩子未接 | `EngineStats` + 各阶段计数聚合进控制面 `status`（只增字段） |
| `captured_at / stream_time_sec` | 未透传（旧 README 承诺未做） | 经 `user_meta` 旁路透传，`result` 只增字段（D4 已定稿） |

**不变的东西（下游零感知，旧版总结 §7 全条保留，除 D5 删两操作外）**：更新面 wire（topic = `stream_id + '\0'` 两帧 multipart、msgpack `use_bin_type`、事件三键 `is_latest / inferred_at / result`）；`result` 九键与 `generation` + `source_epoch` 双写；置信度键 `score`、原图像素整数 xyxy、`class_name` 缺失回退 `cls{id}`；双通道语义（`untracked_detections` 永无 `track_id`）；PUB 满即丢不反压；`health / status` 信封与 payload 键；下游主取数路径 = 只订更新面。

---

## 1. 服务定位与边界

一句话职责：**消费上游 `rtsp_receive_service` 三平面的 NV12 抽样帧 → RGA3 letterbox 前处理写入本服务 RGB888 DMA-BUF 环 → core rknn_engine 多核 NPU 推理 → DFL/NMS 后处理 → 按 (stream_id, generation) seq 重排 → ByteTrack 追踪 → 经 core three_plane 双平面（控制面 ROUTER / 更新面 PUB）对外发布满载检测结果**。

| 负责 | 不负责 |
|---|---|
| 上游三平面消费（事件订阅、按 seq 取 fd、release 归还） | 拉流与解码（rtsp_receive_service） |
| RGA letterbox 前处理、本地 RGB 环生命周期 | 推理编排与 NPU 实例管理（core rknn_engine） |
| DFL/NMS 后处理、重排、ByteTrack 追踪、结果发布 | 两平面传输机制（core three_plane） |
| 队列压力 → SQLite 全流降抽样反馈（SampleBackoff 写库） | 任何业务统计落库（过车/灯态归 index_calcu / light_state_detect，准则 2） |
| | 结果数据面 / 对外像素输出（本服务只有两平面，明确不做） |

既定消费者（契约面）：

- `index_calcu_service`（`src/da/input_thread.py`）：主路径 `subscribe_updates()` 订满载事件——保持；其周期性 `list_latest` 补洞（默认启用）随 D5 移除，靠其既有配置 `fallback_poll_sec: 0` 禁用（该服务后续将大改造，届时彻底删掉调用）。
- `fastapi_backend_service`（`src/core/preview_adapter.py`）：`subscribe_updates()` 订事件做预览框渲染——不受 D5 影响。
- 通用 SDK：`core_module/py_module/yolo_client`（`YoloInferenceClient` 控制面 + `InferenceUpdateSubscriber` SUB，endpoint 经 health 发现）。

---

## 2. core_module 组件适配总表

| core_module 组件 | 本服务用法 | 替代 / 对应的旧实现 |
|---|---|---|
| `c_cpp_module/three_plane` → `ControlPlaneServer` | 控制面 ROUTER bind，main 线程 `poll_once(100ms)`；Handler = 服务侧 `control_ops`（2 个 RPC 领域打包） | `comm_server/control_server`（信封 / unlink / linger / 错误码全部由组件承担） |
| `c_cpp_module/three_plane` → `UpdatePublisher` | 更新面 PUB bind + `set_sndhwm(update_hwm)`；publish 线程直接调用（内部三级丢弃、绝不阻塞） | `comm_server/publisher`（SNDHWM + NOBLOCK + publish_drop 计数语义一致） |
| `c_cpp_module/three_plane` → `protocol.h` | 控制面信封解析 / topic 组帧（组件内部使用） | `wire_pack` 的信封部分（领域 map 打包仍留服务） |
| `c_cpp_module/rknn_engine` → `IInferenceEngine` / `Engine` | 全部 NPU 推理：`submit(InferJob)` / `pop_output()` / `set_backpressure_handler` / `stats()`；真实现 `make_rknn_engine()` 一次注入（组件补齐后，§2.1） | `inference/{rknn_runner, infer_worker, infer_meta_queue, unordered_infer_queue}` 整段；`input_source` 的队列与 release 部分改薄 |
| `c_cpp_module/rknn_engine` → `make_mock_backend_factory` / 自写 FakeEngine | 无 NPU 环境跑全部服务单测（§11） | 无 |
| `c_cpp_module/ring_buffer` | `LocalRgbRing` 底座（FixedSlot + DmaBuf + RejectWrite） | 同（环本体已在 core，适配层随服务迁入） |
| `py_module/yolo_client` | 下游官方 SDK 单点（D5：随服务删除两操作同步修剪方法） | 旧 `src/py_client`（删除，index_calcu / fastapi 的 import 路径已指向 core） |
| **（本次新增下沉）** `c_cpp_module/three_plane_client` | 上游三平面 C++ 消费（ControlClient / UpdateSubscriber / DataPlaneClient） | 跨树引用 `service_new_new_new/rtsp_receive_service/src/c_client`（消除，D1 已定稿） |

> `three_plane_client` 是本重构的前置产出（§13 P0）：从旧 `c_client` 原样迁入 core（wire 字节级不变）。
> 信号灯 / 车牌服务（rknn_engine 计划阶段 3 消费者）同样要消费 rtsp 帧，属准则 9 的「多服务共用机制」；
> three_plane README 预告的「C++ 客户端 SDK 下沉为后续工作」在此时机落地。

### 2.1 rknn_engine 组件现状与缺口（按实测代码盘点，2026-09）

| 项 | 状态 | 说明 |
|---|---|---|
| `include/` 9 个头文件 | ✅ 已完成 | engine / i_inference_engine / i_infer_backend / infer_job / bounded_queue / log / mock_backend / rknn_backend（仅声明）/ tensor_convert |
| `src/engine.cpp` | ✅ 已完成 | 编排 / probe 几何 / submit 拒收就地 release / 背压事件 / 停机抽干 / 统计，语义见 §5.3 |
| `src/mock_backend.cpp` | ✅ 已完成 | `make_mock_backend_factory`（假张量几何 / 延迟 / 周期性失败可编排） |
| `include/tensor_convert.h` | ✅ 已完成 | INT8 仿射去量化 + FP16→float32 纯函数（真后端复用） |
| `src/rknn_backend.cpp` | ❌ **缺失** | 真 NPU 后端（rknn_api 封装：ctx / 绑核 / 零拷贝 import / 动态 shape / 输出转换）与 `make_rknn_engine` 便捷入口仅有头文件声明，**符号不存在** |
| `CMakeLists.txt` | ❌ 缺失 | `drn_core_rknn_engine` 静态库目标未建 |
| `tests/test_rknn_engine.cpp` | ❌ 缺失 | rknn_engine 计划 §6 的 7 组单测未落 |
| `README.md` | ❌ 缺失 | — |

**对服务接入的三点直接影响**（服务代码已按此设计，不受缺口阻塞）：

1. `make_rknn_engine` 当前不可链接 → 服务装配经由 `Engine(EngineConfig, BackendFactory)` 直构；开发期注入 `make_mock_backend_factory`（或服务自写 FakeEngine），真后端落地后切换为 `make_rknn_engine` 一行改动（§13 P2/P3 分工）。
2. **Engine 构造 probe 失败不抛异常**（factory 返回 null 时直接返回，geometry 无效、零 worker）→ 服务装配必须自查 `input_geometry().valid()` 并在 `start()` 后核对 `stats().workers.size() == len(core_masks)×instances_per_core`，不满足即致命（§6.1 第 5 步）。
3. **submit 拒收（队列满 / 任务无效）由组件就地 release**（engine.cpp 拒收路径）→ 服务侧 `submit` 返回 false 后**不得**再 release（会双重归还），只做计数与丢帧日志（§5.1 / §5.3）。

---

## 3. 目录与模块地图

```text
service_ultimate/yolo_inference_service/
├── plans/
│   ├── legacy_yolo_inference_logic_summary.md       旧版逻辑盘点（底稿）
│   └── yolo_inference_service_architecture.md       本文
├── src/
│   ├── CMakeLists.txt          链接 drn_core_three_plane + drn_core_rknn_engine（+ three_plane_client）
│   │                           + core ring_buffer；librga / xtensor / spdlog / sqlite3 / yaml-cpp /
│   │                           cppzmq / msgpack-cxx / libsystemd（可选，HAS_SYSTEMD，对齐 rtsp）
│   ├── main.cpp                进程壳入口：--config → ServiceApp::run()
│   ├── app/                    装配与生命周期（对齐 rtsp 壳）
│   │   ├── service_config.{h,cpp}    YAML 单份加载 + 严格校验（D2）
│   │   ├── logger.h                  init_loggers / LOG* 宏（命名 logger 表见 §6）
│   │   └── service_app.{h,cpp}       启动顺序、serve_loop、倒序关停、flock、信号、sd_notify
│   ├── upstream/               上游三平面接入（旧 preprocess/upstream_ingress 迁入）
│   │   └── ingress.{h,cpp}           单线程：SUB 事件 → 过滤/generation 校验 → 按流排队；
│   │                                 数据面 read_frame / fallback read_latest；异步 release 队列；
│   │                                 重连（传输类错误退避 1s）+ stale 强制重连（10s 无入队）
│   ├── preprocess/             RGA 前处理 + 本地 RGB 环（旧 preprocess/{rga3_preprocess,local_rgb_ring} 迁入）
│   │   ├── rga3_preprocess.{h,cpp}   RGA3 NV12→RGB888 letterbox（垫色 114、4-arg importbuffer_fd、
│   │                                 dst 槽 handle 缓存、几何变小时 memset）
│   │   └── local_rgb_ring.{h,cpp}    core RingBuffer 薄适配（侧表 + seq 嗅兵；槽几何 =
│   │                                 engine->input_geometry()，容量 capacity）
│   ├── infer/                  rknn_engine 服务侧薄层（旧 src/inference 删除后的衔接层）
│   │   ├── engine_ingest.{h,cpp}    on_frame_published → ring.acquire → 组 InferJob → submit；
│   │                                拒收只计数（release 由组件负责，见 §2.1）；admit 事件同步
│   │                                try_push 进 reorder
│   │   └── meta_codec.{h,cpp}       InferMeta ↔ InferJob::user_meta 编解码（身份旁路，含 D4 字段）
│   ├── postprocess/            原样迁入（decode_outputs / dfl_decode / nms / worker）
│   │                                 worker 改为直接 engine->pop_output(50ms)（原 raw 队列由
│   │                                 Engine 内 InferOutputQueue 承担，容量对齐 512）
│   ├── reorder/                原样迁入（admit_queue / reorder_buffer / reorder_thread）；
│   │                                 PassthroughThread 接通（D3，reorder.enabled 真正生效）
│   ├── trace_track/            原样迁入（byte_tracker / kalman / matching / strack / tracker_hub / thread）
│   ├── comm/                   对外两平面服务侧薄层（传输在 core three_plane）
│   │   ├── control_ops.{h,cpp}      2 个 RPC（health / status）→ 领域对象打包 + status 统计聚合
│   │   ├── wire_pack.{h,cpp}        InferenceUpdate / 检测条目 msgpack（契约锁定，§9）
│   │   ├── latest_tracker.{h,cpp}   每流最新 seq（is_latest 计算；D5 后不再保留历史服务 RPC）
│   │   └── publish_thread.{h,cpp}   pop tracked → latest_tracker 更新 → wire_pack → UpdatePublisher.publish
│   └── backpressure/
│       └── sample_backoff.{h,cpp}   SQLite 全流 sample_interval_ms += 25、60s 冷却（服务保留）
├── systemd/
│   ├── device-run-yolo-inference.service     Type=notify（对齐 rtsp 单元风格）
│   └── manage.sh
└── tests/
    ├── test_unit.cpp          FakeEngine 全流水线 + wire 契约快照 + 背压触发（无设备）
    └── test_e2e.py            py_client 订阅断言（迁旧 e2e：双通道 + 每流 seq 严格 +1）
```

依赖方向（只允许向下；服务对推理只依赖 `drn::core::rknn::IInferenceEngine` 接口 + 工厂）：

```text
app ──▶ comm ──▶ trace_track ──▶ reorder ──▶ postprocess ──▶ infer ──▶ preprocess ──▶ upstream
 │        │            ▲                        │              │           │
 │        │            └───── AdmitQueue ◀──────┼──────────────┘           │
 │        └──▶ core three_plane（传输）          └──▶ core rknn_engine（IInferenceEngine）
 └──▶ core ring_buffer（经 preprocess/local_rgb_ring 适配）                 └──▶ core three_plane_client（D1）
```

图中虚补一条边：`infer` 的 engine_ingest 向 `reorder` 的 AdmitQueue 生产事件（类型依赖
infer → reorder，与 postprocess → infer 的 InferOutput 消费方向相反，属流水线的元数据先行通道）。

`postprocess` 只见 `InferOutput`（`user_meta` + `TensorData`），不感知 Engine / 后端；`upstream` 不知道
RGA 与推理（只投递 NV12 fd + 身份）；`comm` 不进入流水线内部（只读 latest_tracker 与统计快照）。

---

## 4. 线程模型

| 线程 | 数量 | 职责 | 阻塞点 / 节拍 |
|---|---|---|---|
| main（reactor） | 1 | `ControlPlaneServer::poll_once(100ms)`；兼作 stop_flag 轮询 | ZMQ poll 100ms |
| ingress | 1 | 上游 SUB recv（超时 200ms）→ 过滤校验 → 按流排队；数据面 read_frame；release 队列 flush；目录周期刷新（5s） | recv / send 超时 |
| RGA 前处理 | 1 | pop 每流队列最旧待处理 → RGA letterbox → LocalRgbRing publish → `on_frame_published` 薄回调 | 队列 pop |
| engine worker | len(core_masks)×instances_per_core（部署 9） | Engine 内部：pop job → NPU 推理 → release → push 输出 | 组件内（§5.3） |
| postprocess | 6 | `engine->pop_output(50ms)` → DFL/NMS → DetectionResultQueue | pop_output 50ms |
| reorder | 1 | admit/ingest 双输入 → 严格 seq+1 放出 → OrderedResultQueue | poll 50ms |
| track | 1 | StreamTrackerHub（每流 ByteTracker）→ TrackedResultQueue | poll 50ms |
| publish | 1 | pop tracked → latest_tracker → wire_pack → `UpdatePublisher.publish`（非阻塞） | poll 50ms |
| ZMQ IO | 1 | context IO | — |

与旧版线程清单一致（ingress×1、RGA×1、infer×9、post×6、reorder×1、track×1、publish×1、control 并入
main reactor）；差异仅是 control 不再单列线程、9 个 infer worker 交由 Engine 托管。

跨线程共享状态与保护方式：

| 状态 | 保护 |
|---|---|
| LocalRgbRing（槽 / refcount / latest_seq） | core RingBuffer 自身原语（acquire/release/publish） |
| 上游流目录快照 | ingress 单线程持有；`on_stream_removed` 回调投递无锁队列给 app 联动清理 |
| latest_tracker（每流最新 seq） | 内部 mutex（publish 线程写、control 读快照） |
| 各阶段计数器 | 原子；`status` 聚合拷贝 |
| Engine 状态 | 组件内（stats() 线程安全） |

---

## 5. 核心数据流与推理衔接（重构核心）

### 5.1 全链数据流

```text
rtsp_receive_service 三平面（core three_plane_client 消费）
  → ingress：FrameUpdate(stream_id, seq, gen, buffer_index, w, h, stride…)
     过滤（subscribe 白名单 / 目录 enabled / generation 校验）→ 每流 deque(4，满丢最旧)
  → data_plane read_frame(seq) → SCM_RIGHTS NV12 fd（empty 回退 read_latest；用后异步 release）
  → RGA3：NV12 → RGB888 letterbox → LocalRgbRing 槽 publish_commit（RejectWrite 忙即丢）
  → engine_ingest：acquire(seq) → InferJob{slot_fd, size, offset=0, release, user_meta} → engine.submit()
     ├─ submit 拒收（队列满）：组件就地 release（不变量：凡进入 submit 的任务恰好一次 release，
     │   engine.cpp 拒收路径）+ 组件发 kJobQueueFull 事件；服务只计数 + 丢帧日志，不二次 release；
     │   拒收时**不投 AdmitEvent**（无结果却先登记 admit 会变 orphan，与旧「meta 满不发 admit」一致）
     └─ submit 成功 → 同步 try_push AdmitEvent 进 reorder admit 队列（元数据先行，结果未到由
         reorder 兜底；admit 满拒收 → 后续结果按 orphan 丢弃，沿旧语义）
  → Engine（core rknn_engine）×9 worker：零拷贝 import / mmap 回退 → rknn_run → INT8 去量化
     float32 TensorData → job.release()（恰好一次，先于交付）→ InferOutputQueue
  → postprocess×6：engine->pop_output → 解 user_meta → DFL + conf 过滤 + 逆 letterbox + per-class NMS
     → DetectionResultQueue
  → reorder：admit / ingest 按 (stream_id, generation) 严格 seq+1 放出；gap 超时跳帧 → OrderedResultQueue
  → track：每流 ByteTracker（generation 切换重建；乱序帧短拷）→ dets + track_dets → TrackedResultQueue
  → publish：latest_tracker 更新（is_latest）→ wire_pack InferenceUpdate → UpdatePublisher.publish(stream_id)
```

身份旁路（stream_id / seq / generation / letterbox / captured_at / stream_time_sec）由 CPU 全程携带，
打包进 `InferJob::user_meta` 随任务往返，组件不解析、不写入像素（rknn_engine 强制意见 8）。

### 5.2 InferMeta ↔ user_meta（`infer/meta_codec`）

旧 `InferMeta` 的服务侧字段编码为紧凑字节（msgpack 或定长 POD，实现自选，对组件不透明）：

```text
InferMeta {
  uint32_t slot_index;        // LocalRgbRing 槽（诊断用）
  string  stream_id;
  uint64_t seq;               // 上游抽样 seq（对外沿用）
  uint64_t generation;        // 上游环代次（epoch 隔离键）
  LetterboxMeta { scale, pad_x, pad_y, dst_w, dst_h, new_w, new_h };
  int src_w, src_h;           // 原图像素
  double captured_at;         // D4：透传（上游 FrameUpdate 带入）
  double stream_time_sec;     // D4：同上
}
```

### 5.3 与旧推理实现的语义对照（逐条对齐，保证行为不变；右列按 engine.cpp 实测语义）

| 旧 `src/inference` 行为 | 新落位（组件实测语义） | 备注 |
|---|---|---|
| publish 回调 → pin 槽 → `try_push` meta 队列（满 → release + 丢帧 + backoff） | `engine_ingest` 同逻辑；队列即 Engine InferJobQueue（512，`BoundedQueue::try_push` 满不 move 元素） | 拒收点的 release 与背压事件均由组件发出（§2.1 第 3 条） |
| input_source 与 worker **双 release** 同一槽（clamp(0) 容忍，旧已知问题 8） | 组件单边保证「凡进入 submit 的任务恰好一次 release」：拒收就地 release（engine.cpp submit）、成功 / 失败 / 停机抽干路径在交付前 release（engine.cpp run_loop） | 责任单一化；服务侧唯一约束 = submit 后不再触碰缓冲、拒收后不二次 release |
| worker：pop → mmap → `rknn_inputs_set` → run → INT8 去量化 → **先 release 再 push** | Engine worker：零拷贝 import（主）/ mmap 回退（显式，`tensor_convert.h` 数值转换）→ run → release → push；失败推 `ok=false` 空 envelope（不悬挂重排） | 输入路径升级（旧已知问题 6）；停机抽干路径跳过推理执行、只归还缓冲（engine.cpp draining 分支） |
| 9 worker = core_masks 0/1/2 × 3，thread_local ctx + 显式绑核 | Engine `worker_count = len(core_masks) × instances_per_core`，每 worker 独立 ctx + 绑核（失败降级 AUTO 记日志 + stats）；worker 后端创建失败该 worker 不上线（Error 日志），服务以 `stats().workers.size()` 核对 | 编排公式不变；core_masks 为空组件兜底 `["0"]`（服务严格校验不依赖该兜底） |
| 动态 shape 模型 `rknn_set_input_shapes(batch=1)`，静态跳过 | RknnBackend 职责（**待实现**，§2.1 缺口） | 语义不变 |
| raw 队列满 → worker 阻塞 + backoff | Engine InferOutputQueue（512）`push_blocking` 阻塞 + kOutputQueueBlock 事件（engine.cpp run_loop 第 4 步） | 语义不变 |
| 槽几何写死 640×640×3 | `engine->input_geometry()`（构造期 probe 后端查询）据此建 LocalRgbRing；**probe 失败不抛异常，服务必须自查 `valid()`**（§6.1） | 换模型无须改码（强制意见 7） |
| `sample_backoff`（SQLite 写库） | **留在服务** `backpressure/sample_backoff`；触发点 = 组件背压事件 + 服务侧队列阻塞点 | 写库行为不变（§8） |

### 5.4 输出消费模式

采用 `pop_output` 模式（对齐旧「6 个 postprocess worker 竞争 pop raw 队列」结构）：
每个 postprocess worker 线程独立 `engine->pop_output(50ms)`（`BoundedQueue::pop` 多消费者竞争安全），
超时返回 nullopt 即轮询 stop 标志。不使用 `set_output_callback`（须在 start() 前设置、且在 worker
线程内执行，与多线程后处理竞争消费的结构不符）。

---

## 6. 进程生命周期（`app/service_app`，对齐 rtsp 壳）

### 6.1 启动顺序（按依赖正序，任一步失败即致命退出）

1. `load_config(--config)`：读 `services_config.yaml` 顶层键 `yolo_inference_service`（当前缺失，随本重构补齐，§7），严格校验（D2：缺键 / 未知键 / 两 endpoint 非 `ipc:///` / 互相重复 / 与已知外部端点冲突 / `infer.enabled != true` / `postprocess.enabled != true` / `core_masks` 为空均致命）。
2. `init_loggers(log_path, log_level)`：**先于一切模块**；此后禁止 `fprintf(stderr)`（修正旧已知问题 1）。命名 logger：`ingress / preprocess / infer / postprocess / reorder / track / comm / app`；three_plane 与 rknn_engine 的 `LogFn` 桥接到 `comm` / `infer`。
3. `flock(lock_file, LOCK_EX|LOCK_NB)` 单例；失败 ERROR + `EX_UNAVAILABLE` 退出（修正旧已知问题 9）。
4. 信号：SIGINT / SIGTERM → 原子 stop_flag；SIGPIPE 忽略。
5. 装配（顺序即依赖）：
   `zmq_ctx` → `SampleBackoff`（按配置可选）→ **构造 Engine**（真后端落地前：`Engine(cfg, make_mock_backend_factory(...))`；落地后：`make_rknn_engine(cfg)`。模型文件不可加载在组件内表现为 probe 失败不抛异常）→ **自查 `input_geometry().valid()`，无效即致命退出**（防 0 尺寸建环，§2.1 第 2 条）→ `LocalRgbRing`（几何 = `input_geometry()`，DMA-BUF 分配 / 建环失败即致命；必须先于 engine_ingest 构造）→ `engine_ingest`（挂 LocalRgbRing 的 `on_frame_published`）→ `engine.set_backpressure_handler(→ SampleBackoff，停机期见 §8)` → postprocess×6 / reorder / track 装配 → `latest_tracker` → `UpdatePublisher`（**先 `bind`（失败致命）再 `set_sndhwm(update_hwm)`**——组件 `bind()` 内部先置默认 sndhwm=1000 再 bind，先调 `set_sndhwm` 会被覆盖；bind 后、订阅者连入前设置即对全部管道生效）→ `PublishThread.start` → `ControlPlaneServer.bind`（失败致命，`set_sndtimeo(send_timeout_ms)`）→ `engine.start()` → **核对 `stats().workers.size() == len(core_masks)×instances_per_core`，不足即致命**（防后端工厂静默降编排）→ `ingress.start`（上游连接失败**不致命**：退避重连循环，目录为空照常 serve；engine 先于 ingress 启动，杜绝「帧已到、worker 未起」窗口）。
6. `sd_notify("READY=1")` → `serve_loop()`：`while(!stop) control.poll_once(100ms)`；Handler 抛非 ControlError 异常 → ERROR + `invalid_request` 应答，循环不中断。
7. `on_stream_removed` 联动：上游目录流移除 → 依次 `reorder.forget_stream / tracker_hub.forget_stream / latest_tracker.forget_stream`（旧语义保留）。

### 6.2 关停顺序（依赖逆序，准则 10）

```text
stop_flag=1
→ Ingress.stop()             停上游订阅与数据面收发，flush release 队列（fd 全部归还上游）
→ ControlPlaneServer.close() 停止接受新 RPC（linger=0 + unlink）
→ 关闭服务侧四条流水线队列（Admit / Detection / Ordered / Tracked）
                             唤醒其中阻塞的 push/pop——必须先于任何 join（防死锁：若先停 publish，
                             track 仍可能在满队列上 push_blocking 永久阻塞，join 悬挂）。沿旧 main.cpp
                             「先 stop 全部队列 → 倒序 join」经验；迁入的队列类型保留 close() 唤醒语义
                             （对齐 rknn BoundedQueue：关闭后 push 一律失败、pop 排空至空）
→ 倒序 join：PublishThread → Track → Reorder → postprocess workers
                             各线程收到 stop + 队列关闭后退出；停机丢弃尾部在途结果是设计内行为（旧版一致）
→ engine.stop()              组件实测语义：先 close 输出队列（解开 worker 阻塞 push）再 close 任务队列；
                             worker 抽干剩余任务时跳过推理执行、只归还缓冲（release 不丢、禁止丢 pin），
                             剩余 envelope 因输出队列已关被丢弃（停机设计行为）；逐 worker join。
                             此后 RGA 线程若仍 submit，组件走拒收路径就地 release，无泄漏
→ RGA / LocalRgbRing 停      RGA 线程排干每流 deque 后 join；环销毁
→ UpdatePublisher.close()    linger=0 + unlink
→ SampleBackoff / latest_tracker reset → flock 解锁 → spdlog::shutdown()
```

析构幂等；SIGTERM 后 `TimeoutStopSec=30` 内必须退出；退出统计改记 INFO 汇总一条（不再裸 stderr，旧已知问题 14 的落盘半边）。

### 6.3 systemd

`systemd/device-run-yolo-inference.service`：`Type=notify`、`NotifyAccess=main`、`Restart=on-failure`、
`RestartSec=3`、`TimeoutStartSec=60`、`TimeoutStopSec=30`、`LimitNOFILE=65536`、`WorkingDirectory=@PROJECT_ROOT@`、
ExecStart 指向 `service_ultimate/yolo_inference_service/build/yolo_inference_service --config …/services_config.yaml`。
`manage.sh` 渲染 `@PROJECT_ROOT@` 后 enable 不 start（与 rtsp 单元同风格）。构建强制 Release 不变
（Debug 下 xtensor 表达式模板后处理可达数秒/帧，沿旧顶层 CMake 约束）。

---

## 7. 配置（`services_config.yaml` → 键 `yolo_inference_service`，准则 5）

节点当前缺失，随本重构补齐；键集合 = 旧部署值（旧版总结 §2.4）+ 壳新增键 − D5 删除键，全键必填、未知键拒绝（D2）：

```yaml
yolo_inference_service:
  log_level: INFO                          # TRACE|DEBUG|INFO|WARNING|ERROR|CRITICAL（新增：真正接入）
  log_path: device_run_new/service_ultimate/logs/yolo_inference_service
  server:
    lock_file: /tmp/drn-yolo-inference.lock          # 新增：flock 单例
  upstream:                                # 上游 rtsp_receive_service 三平面
    control_endpoint: ipc:///tmp/drn-rtsp-receive.sock
    update_endpoint: ""                    # 空 = health 自动发现（保持）
    data_endpoint: ""                      # 空 = health 自动发现（保持）
    subscribe_stream_ids: []               # 空 = 订全部流
  ingress:
    max_queue_per_stream: 4
    update_timeout_ms: 200
    fallback_read_latest: true
    stream_refresh_interval_sec: 5.0
    reconnect_backoff_sec: 1.0
    stale_reconnect_sec: 10.0
  local_ring:
    capacity: 16                           # 槽几何不再配置：查 engine->input_geometry()
    drop_when_busy: true
  infer:                                   # → core rknn_engine EngineConfig
    enabled: true                          # D3：仅接受 true，false 致命
    model_path: config_files/traffic_edge_box_label_tiny_inference.rknn
    core_masks: ["0", "1", "2"]            # D6：维持满核 9 worker（三推理服务均满核，见 §12）
    instances_per_core: 3
    job_queue_capacity: 512                # 旧 meta_queue_capacity
    output_queue_capacity: 512             # 旧 unordered_queue_capacity
    dmabuf_zero_copy: true                 # 新增：可强制 mmap 回退（诊断用）
    stream_db_path: device_run_new/service_ultimate/sqlite/traffic_data.sqlite
    sample_backoff_ms: 25
    sample_backoff_cooldown_ms: 60000
  postprocess:
    enabled: true                          # D3：仅接受 true（消除组合陷阱，旧已知问题 4）
    worker_count: 6
    conf_thres: 0.4
    iou_thres: 0.7
    imgsz: 640                             # 保留校验用：与 input_geometry() 不一致时 WARN（模型为准）
    obj_classes: []
    detection_queue_capacity: 512
  reorder:
    enabled: true                          # D3：真正生效（false = PassthroughThread 直通）
    gap_timeout_sec: 2.0
    max_waiting_per_stream: 64
    poll_timeout_ms: 50
    admit_queue_capacity: 512
    ordered_queue_capacity: 512
    sample_backoff_on_ordered_block: true
  tracking:
    enabled: true                          # 保持语义：false = track_dets 与原始同语义、无 track_id
    frame_rate: 8
    track_thresh: 0.5
    track_buffer: 30
    match_thresh: 0.8
    edge_margin_ratio: 0.01
    low_score: 0.1
    second_match_thresh: 0.5
    unconfirmed_match_thresh: 0.7
    mot20: false
    tracked_queue_capacity: 512
    poll_timeout_ms: 50
    sample_backoff_on_tracked_block: true
    names_path: config_files/traffic_edge_box_label_tiny_inference.yaml   # 全仓唯一类别表入口
  transport:
    endpoint: ipc:///tmp/drn-yolo-inference.sock            # 控制面（= fastapi.service_inference_endpoint）
    update_endpoint: ipc:///tmp/drn-yolo-inference-updates.sock
    recv_timeout_ms: 100
    send_timeout_ms: 100
  publish:
    poll_timeout_ms: 50
    update_hwm: 1024                       # UpdatePublisher.set_sndhwm
```

相对旧版的键变化：`local_ring` 删除几何键（改查 `input_geometry()`）；`infer` 队列键改名对齐
EngineConfig（`meta_queue_capacity → job_queue_capacity`、`unordered_queue_capacity → output_queue_capacity`）
并新增 `dmabuf_zero_copy`；**`results.history_size` 删除**（D5：结果历史与 get_latest/list_latest 一并移除）；
新增壳键（`log_level/log_path/server.lock_file/transport.*_timeout_ms`）。
校验规则保持旧 comm_server/config 的端点约束（两对外端点须 `ipc:///` 且互不相同、与已知外部端点错开）。

---

## 8. 背压与降抽样（SampleBackoff，服务保留）

触发点映射（全部落到同一个 `SampleBackoff` 实例，行为 = SQLite 全行 `sample_interval_ms += 25`、
仅 `>0` 行、两次成功写库间冷却 60s——不变）：

| 旧触发点 | 新触发点（按 engine.cpp 实测） |
|---|---|
| `meta_queue_full`（ingest try_push 拒收） | **组件单一来源**：`Engine::submit` 拒收路径发 `kJobQueueFull` 事件（engine.cpp：计数 + fire_backpressure）；服务 ingest 只计数与日志，不再自行触发（避免双计） |
| `raw_queue_block`（worker push 阻塞） | **组件单一来源**：`kOutputQueueBlock` 事件（worker push_blocking 经历满队列等待时） |
| `ordered_queue_block` / `tracked_queue_block` | 不变：reorder / track 线程在 push_blocking 前直接调用（可配开关保留） |

写库经 rtsp_receive_service 的 SQLite 热更新感知收敛上游帧率——本服务对共享库的唯一写路径，不变。

两点实现约束：

- **事件在触发线程内同步执行**：kJobQueueFull 在 RGA 线程（submit 调用方）、kOutputQueueBlock 在 engine worker 线程回调——与旧版触发点线程一致；SampleBackoff 有 60s 冷却 + 单条 UPDATE，不构成对触发线程的阻塞风险（沿旧行为）。
- **停机期静默**：stop_flag 置位后背压处理器直接返回不再写库——engine.stop() 关闭任务队列后，RGA 线程残留的 submit 会走拒收路径发 kJobQueueFull，若不屏蔽会在关停时写一次无意义的 SQLite。

---

## 9. 对外契约（对应旧版总结 §7；除标明外全部锁定不变）

1. 更新面 wire：topic = `stream_id + '\0'` 两帧 multipart；payload msgpack `use_bin_type`；事件三键 `is_latest / inferred_at / result`。（`UpdatePublisher` 组件的 topic 组帧已验证与现网字节级一致。）
2. `result` 九键固定；`generation` 与 `source_epoch`（字符串化）**都必写**；`seq` 沿用上游抽样 seq；`width/height` 为原图（非 640）。D4 已定稿：`result` 只增 `captured_at / stream_time_sec` 两键（可缺省），不改动既有键。
3. 检测条目：置信度键锁定 `score`；`box` 原图像素整数 xyxy；`class_name` 缺失回退 `cls{id}`。
4. 双通道：`untracked_detections` 永不出现 `track_id` 键；`detections` 仅 `track_id>=1` 写入、追踪关闭时省略；两通道条数不必相等。
5. PUB 满即丢、只计数不反压不重试、不回滚 ByteTrack 状态（`UpdatePublisher` 三级丢弃语义与旧 SNDHWM+NOBLOCK 等价）。
6. 控制面信封：请求 `{request_id, operation, payload}` / 应答 `{request_id, ok, error, payload}`（组件承担）。**操作表收敛为 2 个（D5 已定稿，破坏性变更）**：`health`（payload `{update_endpoint, known_streams[], result_stream_count}` 原样）与 `status`（payload `{update_endpoint, publish_ok, publish_drop, emit_count, publish_pack_fail, result_store_stream_count, …新增只增}`；`result_store_stream_count` 键名保留、语义 = latest_tracker 中有结果流数）。`status` 新增键只增：engine（submit_ok/reject、infer_ok/fail、infer_us_ewma/max、input_path、import_fallback_count、degraded_auto_core、workers 在线数）+ 阶段计数（pre_rga_fail / ingress_miss / ingress_reconnect / post_decode/empty / reorder_released / track_assembled）——补齐旧已知问题 14。`get_latest / list_latest` **删除**，同步动作：`core_module/py_module/yolo_client` 删除 `get_latest / list_latest / _list_latest_raw` 方法（`client.py / async_client.py`）；index_calcu 补洞经其既有配置 `fallback_poll_sec: 0` 禁用（该服务后续大改造时彻底移除调用，不在本重构范围）。
7. 输入侧：像素只经数据面 DMA-BUF fd；release 槽引用协议与上游一致（同连接同流单帧持有、断连统一释放）。
8. 身份旁路全程 CPU 携带，不写入 DMA-BUF 像素。

---

## 10. 各阶段迁入要点（保持算法行为不变）

### 10.1 上游接入（`upstream/ingress`）

旧 `preprocess/upstream_ingress` 原样迁入，仅替换底层客户端类型为 `core three_plane_client`：

- health 发现 update/data 端点 + 校验 `data_plane` 声明含 `dma_buf`（新 rtsp 服务 health 返回 `data_endpoint / data_plane:"dma_buf_nv12"`，兼容）。
- 事件过滤链不变：subscribe 白名单 → 目录 `enabled/fault` 过滤 → generation 双重校验（事件 vs 目录、`handle.generation` vs 事件，不符丢 + refresh）。
- 重连不变：传输类错误（排除 EAGAIN 超时）→ 丢队列 + flush release + 整链重建、退避 1s；stale 10s 无入队强制重连。
- 全部数据面收发集中在 ingress 单线程；用后 release 走异步队列（data plane fd 与 LocalRgbRing 无关，直接归还上游）。

### 10.2 RGA 前处理与本地环（`preprocess/`）

- `rga3_preprocess` 原样迁入：`scale = min(dst_w/src_w, dst_h/src_h)`，`dst_w/h = input_geometry().width/height`（不再写死 640）；`new_w/h` 偶数对齐夹 [2,dst]；`pad = round((dst−new)/2 − 0.1)`；垫色 114；源 NV12 每帧 4-arg `importbuffer_fd` 用后 release；dst 槽 import 一次缓存 handle；几何变小对槽 memset(114)。
- `local_rgb_ring` 原样迁入（旧已知问题 11：薄适配层）：core `RingBuffer`（FixedSlot + DmaBuf + RejectWrite），`capacity` 配置，`slot_size = input_geometry().size`；侧表存 LetterboxMeta + 上游身份 + seq 哨兵；目标槽被推理持有 → 丢帧（`drop_when_busy`）；`publish_commit` 成功后同 RGA 线程薄回调 `on_frame_published`。

### 10.3 后处理（`postprocess/`）

原样迁入（xtensor + NEON 热路径）：每尺度取第 0/1 张量（box 64ch DFL + cls）；DFL 解码；conf 过滤 +
`obj_classes` 白名单；letterbox 逆变换还原原图坐标；per-class NMS；score 降序输出。输入改从
`InferOutput` 解包（`ok=false` → 空结果直接进 reorder 通道，保持「缺帧跳过」语义）；张量数非 3 的倍数 /
shape 不匹配 → 该帧空结果不致命（旧已知问题 5 的防御保留，日志 WARN）。

### 10.4 重排（`reorder/`）

原样迁入：双输入（AdmitQueue + DetectionResultQueue）；ingest 前排空 admit 防 orphan；(stream_id,
generation) 隔离；换代丢旧 epoch；严格 seq+1 才 flush；waiting 每路上限 64 满逐出策略；gap_scan 2s
超时 `result_missing` / `min_diff_jump` 跳帧；流移除 `forget_stream`；停机抽干。
**PassthroughThread 接入 main 装配**（D3）：`reorder.enabled=false` 时直通（修正旧已知问题 2）。

### 10.5 追踪（`trace_track/`）

原样迁入：每流 ByteTracker；generation 变化重建；`seq <= last_tracked_seq` 乱序帧短拷；贴边过滤
（`edge_margin_ratio×宽/高`）；`dets / track_dets` 双通道装配 + `class_name` enrich（names 表缺失回
`cls{id}`）；追踪关闭时 track_dets 与原始同语义。

### 10.6 发布（`comm/`）

- `publish_thread`：pop tracked → `latest_tracker.put(stream_id, seq)`（返回 is_latest）→ `wire_pack` → `UpdatePublisher.publish(stream_id, bytes)`；组包失败计 `publish_pack_fail` 跳过。
- `latest_tracker`（替代旧 ResultStore，D5）：`map<stream_id, seq>` + mutex，put 时比较该流当前最新是否本帧得出 `is_latest`，forget_stream 联动清理；**不再保留 32 条历史、不再服务任何 RPC 取数**。
- `wire_pack`：InferenceUpdate msgpack 打包原样迁入（§9 契约锁定；D4 只增键）。
- `control_ops`：Handler 签名 `std::vector<uint8_t>(const tp::ControlRequest&)`；未知操作抛 `ControlError(invalid_operation)`（`get_latest / list_latest` 随之返回该错误——SDK 已同步修剪，不会有人调用）；`status` 聚合 §9.6 新增键。

---

## 11. 测试与验收

### 11.1 单元 / 进程内测试（无设备，`tests/test_unit.cpp`）

核心策略：服务面向 `IInferenceEngine` 编程，注入 **FakeEngine**（或 `Engine + make_mock_backend_factory`
——后者当前即组件唯一可用后端，§2.1）即可在 x86 无 NPU 环境跑通全流水线：

| 测试 | 验证点 | 关键断言 |
|---|---|---|
| mock 引擎全流水线 | ingest→post→reorder→track→publish→SUB | mock 后端产出合法 3 尺度张量（缩小特征图，`MockPlan.fill` 填充）+ user_meta 往返；进程内 SUB 收到 InferenceUpdate；双通道齐备 |
| wire 契约快照 | §9 锁定 | 固定检测结果 → msgpack 字节与旧版产出快照一致（topic、九键、score/box/class_name、双通道、D4 新键可缺省）；health / status payload 键快照 |
| seq 重排 | reorder | 乱序投递 InferOutput → 订阅面每流 seq 严格 +1；gap 超时跳帧 |
| release 恰好一次 | ingest/Engine 边界（按组件实测不变量） | **凡进入 submit 的任务恰好一次 release（含拒收路径，组件负责）**；服务侧对拒收不产生第二次 release（计数断言：`stats().release_calls == submit_ok + submit_reject`，服务任务恒为有效任务——fd≥0 且带 release；组件对无效任务路径 release 但不计入 release_calls）；停机关停后 release_calls 与已提交数守恒 |
| 背压 → SampleBackoff | §8 | mock 后端高延迟填满 job 队列 → kJobQueueFull 事件（组件单一来源）→ SQLite 临时库 `sample_interval_ms` 全行 +25；冷却期内只计数；ordered/tracked 阻塞点服务侧直调路径同测 |
| passthrough 开关 | D3 | `reorder.enabled=false` 直通（无严格序断言改为到达序）；`tracking.enabled=false` 无 track_id |
| D5 操作表 | 控制面 | `get_latest / list_latest` 返回 `invalid_operation`；health / status 正常 |
| meta_codec | user_meta 往返 | 编解码字段零丢失（含 D4 新字段） |
| 配置校验 | D2 | 缺键 / 未知键 / endpoint 冲突 / `infer.enabled=false` / `postprocess.enabled=false` / `core_masks` 空均致命 |
| 装配防御 | §2.1 第 2 条 | FakeEngine 返回无效 geometry → 启动致命；worker 数不足 → 启动致命 |
| 关停 | 准则 10 | SIGTERM → §6.2 顺序执行、全线程 join 无死锁、两 socket unlink、lock 释放 |

### 11.2 实机 e2e（RK3588，需上游 rtsp_receive_service、rknn_backend 补齐（§13 P2）与真模型）

| 测试 | 验证点 | 关键断言 |
|---|---|---|
| `test_e2e.py`（迁旧） | 端到端 | py_client（core yolo_client，修剪后版本）订更新面：能收 InferenceUpdate；每流双通道；**每流 seq 严格 +1** |
| 零拷贝路径 | rknn_engine 阶段 2 验收 | `stats().input_path == zero_copy` 且 `import_fallback_count == 0`；否则回退路径功能等价 + 原因记录 |
| 性能不回退 | rknn_engine 阶段 2 验收 | 同流同模型下 NPU 利用率与端到端帧率不低于旧版（9 worker 满核编排不变，D6） |
| 背压实机 | 降抽样收敛 | 人为调小队列容量制造压力 → SQLite `sample_interval_ms` 递增 → 上游帧率收敛、压力解除后稳定 |
| 上游重连 | ingress | 重启 rtsp 服务：退避重连恢复产帧；目录流删除 → `forget_stream` 生效、无残留流继续发布 |
| 契约交叉 | 下游零感知 | fastapi preview_adapter（subscribe_updates）对新服务正常工作；index_calcu 以 `fallback_poll_sec=0` 配置运行主路径正常（补洞已禁用） |

### 11.3 P0 组件交叉验证（three_plane_client 下沉）

旧 `c_client` 的既有测试随迁；并以新 `service_ultimate/rtsp_receive_service` 为对端跑通：health /
list_streams、FrameUpdate 订阅（10 字段 + topic 过滤）、read_frame / read_latest（SCM_RIGHTS fd + 元数据）、
release 精确匹配、read_frame → empty——对齐 three_plane README 已验证的 py_client 交叉矩阵。

---

## 12. 决策点决议（已定稿）

| 编号 | 决议 | 落地说明 |
|---|---|---|
| **D1** | **A**：上游 C++ 客户端下沉 `core_module/c_cpp_module/three_plane_client` | 本重构 P0 产出；wire 字节级不变、对上游服务零感知；信号灯 / 车牌服务直接复用 |
| **D2** | **A**：配置严格校验（对齐 rtsp，缺键 / 未知键致命） | 节点本次才补进 `services_config.yaml`，不存在存量部署被新校验打断的问题 |
| **D3** | **A**：`infer / postprocess.enabled` 仅接受 true（否则致命）；`reorder / tracking` 的 passthrough 真正接通 | 消除旧已知问题 2/3/4 的组合陷阱；`reorder.enabled=false` 走 PassthroughThread 直通 |
| **D4** | **A**：`captured_at / stream_time_sec` 本次补上（result 只增两键，可缺省） | 身份旁路字段已在 user_meta 通道上；不破坏 §9 既有键 |
| **D5** | **B**：`get_latest / list_latest` **删除**，控制面收敛为 health / status | 同步动作（§9.6 / §10.6）：yolo_client SDK 删除两方法；index_calcu 补洞经既有配置 `fallback_poll_sec: 0` 禁用，其后续大改造时彻底移除调用；ResultStore 精简为 latest_tracker（is_latest 计算），`results.history_size` 配置键删除 |
| **D6** | **A**：维持 `["0","1","2"]×3 = 9 worker` 满核部署 | 整机核策略定为**三推理服务均使用全部 3 核、不做人工切片**：车牌与信号灯服务运算量极小，核空闲时推理即可（其 core_masks 同样覆盖三核，如 `"0_1_2"`）。本决议取代 rknn_engine 计划 §3.2「显式错开」的示例部署；调整只动各服务 YAML，不改码 |

---

## 13. 迁移路线

| 阶段 | 内容 | 完成判据 |
|---|---|---|
| **P0 客户端下沉** | 旧 `c_client` 迁 `core_module/c_cpp_module/three_plane_client`（wire 不变；`drn_core_three_plane_client` 静态库 + 单测） | §11.3 对新 rtsp 服务交叉验证全过；旧树不再被本服务 CMake 引用 |
| **P1 进程壳 + 两平面** | `app/`（严格配置、logger、flock、信号、sd_notify、倒序关停）+ `comm/` 接 three_plane（health/status，latest_tracker 空转）+ `services_config.yaml` 节点 + systemd 单元 | health/status 应答；SIGTERM 干净退出、两 socket unlink；`status` 含基本计数 |
| **P2 rknn_engine 组件补齐**（可与 P1 并行） | 补 `src/rknn_backend.cpp`（rknn_api 封装：ctx / 绑核 / 零拷贝 import / 动态 shape / INT8·FP16 输出转换，复用 `tensor_convert.h`）+ `make_rknn_engine` + `CMakeLists.txt`（`drn_core_rknn_engine`）+ `tests/test_rknn_engine.cpp`（rknn_engine 计划 §6 的 7 组单测，mock 覆盖）+ `README.md` | 组件单测全绿（编排数 / release 恰好一次 / 空 envelope / 队列语义 / 停机抽干 / stats 自洽 / 按模型类型选路）；RK3588 实机真模型零拷贝 import 冒烟（rknn_engine 计划阶段 1 验收补账） |
| **P3 上游 + 前处理 + 引擎接入** | `upstream/ingress`（three_plane_client）+ `preprocess/`（RGA + LocalRgbRing 查 `input_geometry()`）+ `infer/`（engine_ingest / meta_codec）+ Engine 注入（mock 先行；P2 完成后切 `make_rknn_engine`） | §11.1 前六行单测过（mock 引擎全流水线 / 契约快照 / seq 重排 / release 不变量 / 背压 / passthrough）；实机真模型端到端出张量 |
| **P4 后处理 / 重排 / 追踪 / 发布 + D5 契约同步** | `postprocess/ reorder/ trace_track/` 原样迁入（worker 改 pop_output；PassthroughThread 接通）+ `wire_pack` + `publish_thread`；同步修剪 `core_module/py_module/yolo_client`（删 get_latest/list_latest）并置 index_calcu `fallback_poll_sec=0` | wire 契约快照测试过（含 D5 操作表断言）；实机 e2e（seq 严格 +1、双通道）；fastapi / index_calcu 交叉验证过 |
| **P5 背压 / 统计 / 封板** | SampleBackoff 触发点映射（组件事件单一来源）+ `status` 聚合 EngineStats 与阶段计数 + e2e 全矩阵 + 性能对比 | §11.2 全过（含 NPU 利用率与帧率不低于旧版）；旧服务标记弃用 |

代码复用来源：`upstream_ingress / rga3_preprocess / local_rgb_ring / decode_outputs / dfl_decode / nms /
reorder_* / byte_tracker 全家 / wire_pack / sample_backoff` 以旧实现为底稿迁入并按 §3 重组；
`src/inference`（rknn_runner / infer_worker / 两条队列）**不迁**（由 rknn_engine 替代）；
`comm_server` 传输层（control_server / publisher 信封）**不迁**（由 three_plane 替代）；
`comm_server/result_store` **不迁**（D5：由 latest_tracker 精简替代）；`src/py_client` **不迁**
（已下沉 core yolo_client）。

---

## 14. 与既有计划的关系

- 本文 = `core_module/plans/rknn_engine_plan.md` 阶段 2（yolo_inference_service 重构接入）的落地设计；其阶段 1（组件落地）**未全部完成**（§2.1：Engine / mock / 纯函数转换已完成，真后端 / 构建 / 单测 / README 缺失），由本文 §13 P2 补齐；阶段 3（信号灯 / 车牌接入）不在本文范围，但其核分配策略已被 D6 决议更新为「三服务满核、不做人工切片」。
- 上游契约以 `rtsp_receive_service/plans/rtsp_receive_service_architecture.md` 已封板实现为准（本服务是其既定 C++ 消费者，经 D1 组件对接，不感知其内部）。
- 旧服务内 plans（旧版总结 §10 索引）在迁移各阶段作算法底稿；迁移完成后随旧树归档。

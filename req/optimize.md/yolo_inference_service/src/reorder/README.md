# reorder — 按流 seq 严格 +1 重排序

实现方案见 [`plans/reorder_plan.md`](../../plans/reorder_plan.md)。

对齐 Python：`service_new_new/yolo_inference_service_new_new/src/reorder/`。

## 模块

| 文件 | 职责 |
|------|------|
| `admit_queue.h` | 非阻塞 `try_push` / `try_pop` |
| `reorder_buffer.*` | 状态机：admit / ingest / flush / gap_scan |
| `reorder_thread.*` | 主循环 + Passthrough |
| `ordered_queue.h` | `OrderedResultQueue` |
| `config.*` | YAML `yolo_inference_service.reorder` |

## 构建

```bash
cmake -S . -B build -DYOLO_REORDER_BUILD_SMOKE=ON
cmake --build build -j
./build/yolo_reorder_smoke
```

## 配置示例

```yaml
yolo_inference_service:
  reorder:
    enabled: true
    gap_timeout_sec: 1.0
    max_waiting_per_stream: 32
    poll_timeout_ms: 50
    admit_queue_capacity: 256
    ordered_queue_capacity: 64
    sample_backoff_on_ordered_block: true
```

## 接线要点

- `InferInputSource`：meta `try_push` 成功后 `AdmitQueue.try_push(upstream_seq)`。
- `InferWorker`：推理失败仍 push 空 tensors 的 `InferRawResult`。
- 下游 ByteTrack：对 `OrderedResultQueue` **按 `stream_id` 分路**。

# postprocess — DFL + NMS（xtensor）+ PostprocessWorker

实现方案见 [`plans/postprocess_dfl_nms_xtensor_plan.md`](../../plans/postprocess_dfl_nms_xtensor_plan.md)。

对齐 Python：[`device_run_new/core/data_process/postprocess.py`](../../../../core/data_process/postprocess.py) 的 `decode_rknn_outputs`。

## 模块

| 文件 | 职责 |
|------|------|
| `dfl_decode.*` | DFL / box_process / filter / letterbox 还原 |
| `nms.*` | 单类贪心 NMS（xyxy） |
| `decode_outputs.*` | 9 输出 → `FrameDetections` |
| `postprocess_worker.*` | `UnorderedInferQueue` → `DetectionResultQueue` |
| `config.*` | YAML `yolo_inference_service.postprocess` |

## 构建

```bash
cmake -S . -B build -DYOLO_POSTPROCESS_BUILD_SMOKE=ON
cmake --build build -j
```

依赖：`yolo_inference`、`yaml-cpp`、`xtensor`（+ `xtl`；无系统包时 FetchContent）。

## 配置示例

```yaml
yolo_inference_service:
  postprocess:
    enabled: true
    conf_thres: 0.25
    iou_thres: 0.45
    imgsz: 640
    obj_classes: []          # 空=不过滤
    detection_queue_capacity: 16
```

## 输入契约

`InferRawResult.tensors` 须为 3 的倍数，顺序 `[box,cls,sum]×尺度`；每项 `TensorData::dims` 有效且与 `data.size()` 一致。

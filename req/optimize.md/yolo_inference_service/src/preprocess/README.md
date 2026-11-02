# preprocess — c_client 接收 + RGA3 letterbox + LocalRgbRing

实现方案见 [`plans/c_client_rga_preprocess_plan.md`](../../plans/c_client_rga_preprocess_plan.md)。

## 模块

| 文件 | 职责 |
|------|------|
| `upstream_ingress.*` | ControlClient + FrameUpdateSubscriber + DataPlaneClient → `UpstreamFrame` 队列 |
| `rga3_preprocess.*` | 仅 RGA3：NV12→RGB888 letterbox 写中心；mmap 垫色 114 |
| `local_rgb_ring.*` | DMA32 RGB888 640×640 环；`acquire`/`release` |
| `preprocess_pipeline.*` | Ingress + 单 RGA 线程编排 |

## 构建

```bash
cmake -S . -B build -DYOLO_PREPROCESS_BUILD_SMOKE=ON
cmake --build build -j
```

依赖：`drn_c_client`、`librga`、`yaml-cpp`；板端需 `/dev/dma_heap/system-uncached-dma32`（或 `system-dma32`）。

## 配置

`config_files/services_config.yaml` 键 `yolo_inference_service`（见仓库统一配置）。

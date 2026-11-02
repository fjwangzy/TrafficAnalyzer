# yolo_inference_service（service_ultimate 重构中）

旧实现盘点见 [`plans/legacy_yolo_inference_logic_summary.md`](./plans/legacy_yolo_inference_logic_summary.md)；
推理底座方案见 [`../core_module/plans/rknn_engine_plan.md`](../core_module/plans/rknn_engine_plan.md)。

## 当前范围（已迁入）

```text
上游 NV12 fd（接入层组装 UpstreamFrame）
   → src/preprocess：submit_frame 有界队列 → RGA3 letterbox → LocalRgbRing publish
   → core_module/c_cpp_module/rknn_engine：submit(dma_fd + release + 身份旁路)
       → N worker（core_masks × instances_per_core）零拷贝推理 → InferOutput
   → src/postprocess：user_meta 解包 → score-first DFL → per-class NMS → FrameDetections
```

- **前端 `src/preprocess/`**：RGA3 前处理（NV12→RGB888 letterbox、槽 handle
  缓存、几何变小重垫色）+ 本地 DMA-BUF 环（core RingBuffer 适配，seq 哨兵
  侧表）+ 入口有界队列与 publish 薄回调。算法与旧服务逐行对齐。
- **后端 `src/postprocess/`**：DFL 解码（score-first + NEON 融合期望）、
  per-class NMS、letterbox 坐标还原、张量布局校验与异常回退；输入改为
  rknn_engine 的 `TensorData` + `frame_meta` 身份旁路。xtensor 全网格参考
  实现未随迁（服务路径未使用，环境亦无 xtensor）。
- **推理主体**：`core_module/c_cpp_module/rknn_engine`（多 NPU 核 × 每核多
  RKNN 实例、DMA-BUF 零拷贝主路径 / mmap 回退、INT8 去量化 / FP16 转换、
  release 恰好一次、背压事件）。见该目录 README。

## 待迁（后续计划）

upstream 三平面接入（c_client）、SampleBackoff 降抽样写库、reorder /
trace_track / comm_server 发布、全流水线 main 与 systemd 单元。

## 构建与测试

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
./build/tests/test_yolo_front_back     # 前后端算法 + mock 引擎链路单测
# rknn_engine 组件单测在其目录内：core_module/c_cpp_module/rknn_engine/build/tests/
```

依赖：yaml-cpp、librga（前处理编译期）、core_module（ring_buffer /
rknn_engine）；单测纯 CPU，无须 NPU / RGA 运行时。

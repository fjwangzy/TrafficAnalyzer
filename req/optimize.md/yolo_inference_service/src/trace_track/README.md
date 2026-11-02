# ByteTrack（xtensor）— `src/trace_track`

按流维护 `ByteTracker`，对重排序放出的有序帧做多目标追踪与双通道装配。

## 边界

- **入**：`OrderedResultQueue` / `OrderedFrameDetections`（`track_dets` 入站为空）
- **出**：`TrackedResultQueue`（同结构；`dets`=全量原始 `track_id=-1`，`track_dets`=轨迹或短路拷贝）
- **线程**：仅 `TrackThread` 调用 `update` / `assemble_frame`
- 计划：`plans/bytetrack_xtensor_plan.md`

## 构建

```bash
cd src/trace_track
cmake -S . -B build -DYOLO_TRACE_TRACK_BUILD_SMOKE=ON
cmake --build build -j
./build/yolo_trace_track_smoke
```

## 配置

YAML 节点 `yolo_inference_service.tracking`（见计划 §4）。

## Hub 要点

- 空框 / 全退化框过滤：**不**调用 `ByteTracker::update`，只推进 `last_tracked_seq`
- `generation` 切换重建 tracker
- `enabled=false` 仍走双通道形状与 `class_name` enrich

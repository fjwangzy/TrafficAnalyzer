# mp4729 垂直俯拍视频 3 秒效果测试（2026-07-30）

> 修订说明：以下三秒烟测产生于 SourceGeoRegistration 运行时门禁移除之前，保留为历史渲染证据；
> 缺少该记录不再关闭 geo/TCC，当前能力只由同步遥测和当前帧世界矩阵决定。

## 结论

- 状态：`local_smoke_passed_with_warning / production_accuracy_not_evaluated`。
- `mp4729` 三个源均为 3840×2160、29.97 FPS 的 4K HEVC 横向编码，内容是垂直俯拍道路，不需要旋转画布。
- 3/5/7 m/s 三个源各截取开头 3.003 秒，通过原生 arm64 Python + MPS 的 `hover_cruise_v1` 生产链路运行到自然 EOF；三份渲染结果均为 23 帧、3840×2160、3.070 秒并可完整解码。
- 三份 DJI Cloud OSD 导出都包含录制前后数据。测试按 MP4 `creation_time` 对齐，分别使用 73.779、17.884、99.111 秒偏移；每个样本 23/23 个处理帧均命中遥测。
- 同步高度约 171.4–171.5 m，当前自适应尺寸策略在三个样本中均选择 `high / imgsz=1280`。
- 画面中的检测框、类别标签和候选像素尾迹可见，未发生旋转、拉伸、黑帧或保存中断。密集车流区域的文字标签有重叠，属于当前 4K 全量标注布局的可读性限制。
- 当时短样本显示黄色虚线候选和 `NO STATS-TCC`，属于旧 SGR 门禁下的历史结果；当前实现不得因
  SGR 或地图缺失关闭 geo/TCC。无外部真值时仍不得据此声称 IDF1/HOTA、ID switch、位置 RMSE、
  速度 MAE 或生产精度。

## 运行口径

| 项目 | 值 |
|---|---|
| Python | `/Users/yaoyao/ai/TrafficAnalyzer/.venv-mps/bin/python`，arm64，3.11.15 |
| PyTorch / 设备 | 2.2.2 / MPS available |
| 跟踪档案 | `hover_cruise_v1` |
| 源抽样 | `frame_stride=4`，约 7.493 Hz |
| 检测尺寸 | 自适应 `high / 1280` |
| Kafka / Platform / road9 | 本次短样本关闭，不写业务数据 |
| 输出帧率 | 7.4925 FPS，用于保持约 3 秒可播放时长 |

## 逐源结果

| 源 | 遥测记录 | 时间偏移 | 遥测覆盖 | 输出 | 结果 |
|---|---:|---:|---:|---|---|
| 3 m/s | 422 | 73.779 s | 23/23 | 23 帧，3.070 s，18,393,007 B | PASS，1 次共享内存清理告警 |
| 5 m/s | 302 | 17.884 s | 23/23 | 23 帧，3.070 s，19,757,099 B | PASS，无共享内存清理告警 |
| 7 m/s | 286 | 99.111 s | 23/23 | 23 帧，3.070 s，19,668,896 B | PASS，4 次共享内存清理告警 |

三个主进程均返回 0，VideoReader 到达 EOF，VideoSaver 完成释放。3 m/s 与 7 m/s 的日志出现 Python `multiprocessing.resource_tracker` 对已注销共享内存名再次 `remove` 的 `KeyError`；未造成帧缺失、视频损坏或非零退出，但后续长回放前应单独消除该清理噪声。

## 证据

- 根目录：`/private/tmp/TrafficAnalyzer-mp4729-3sec-20260730/`
- 输入短片：`clips/`
- 生产 ShowNode 渲染视频：`rendered/3ms/`、`rendered/5ms/`、`rendered/7ms/`
- 2.5 秒可见帧：各输出目录的 `t2.5.jpg`
- 完整运行日志：`logs/3ms.log`、`logs/5ms.log`、`logs/7ms.log`

本报告只覆盖三个 3 秒工程烟测，不替代三源完整自然 EOF 回归、Kafka/road9 对账、浏览器验收或外部真值精度评估。

## Console 加载状态

- 完整原始 3 m/s 视频及对应 OSD 已注册为 `SRC-MP4729-JS-0729-3MS`。
- 归属无人机：`UAV-MP4728-JS`（“回放无人机 · 经十路巡航”）。
- 该新源设为无人机默认源；已有 mp4728 3/5/7 m/s 源均保留。
- `roadless_trajectory` 只表示道路能力缺失；当前实现中 SGR 不存在，geo/TCC 由逐帧遥测和世界矩阵独立决定。

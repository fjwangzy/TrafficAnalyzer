# CMakeLists.txt — yolo_inference_service（service_ultimate 封板版）
#
# 完整流水线：upstream 三平面接入 → RGA3 前处理 → core rknn_engine 推理
# → DFL/NMS → 重排 → ByteTrack → three_plane 双平面发布。
# 构建脚本在 src/CMakeLists.txt（对齐 rtsp_receive_service 布局）。

cmake_minimum_required(VERSION 3.14)
project(yolo_inference_service LANGUAGES CXX)

add_subdirectory(src)

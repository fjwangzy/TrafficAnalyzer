/**
 * @file infer/types.h
 * @brief 推理衔接层共享类型：TensorData 别名 + InferRawResult。
 *
 * 旧 src/inference 已由 core_module rknn_engine 替代；本文件只保留
 * 后处理需要的「原始推理结果 + 身份旁路」视图，TensorData 直接别名
 * 组件类型（data/index/dims 布局一致，decode_outputs 无须改动）。
 */

#ifndef YOLO_INFER_TYPES_H_
#define YOLO_INFER_TYPES_H_

#include <cstdint>
#include <string>
#include <vector>

#include "i_inference_engine.h"

#include "../preprocess/types.h"

namespace yolo {
namespace inference {

/** 组件 TensorData 别名（float32 连续 + 完整形状）。 */
using TensorData = drn::core::rknn::TensorData;

/**
 * @brief 后处理输入视图（从 InferOutput + user_meta 组装）。
 *
 * ok=false 的空 envelope 组装为空 tensors，decode 产出空 dets，
 * 身份键保留——重排按缺帧跳过，不悬挂。
 */
struct InferRawResult {
    std::string stream_id;               /**< 上游流标识（重排主键） */
    uint64_t seq = 0;                    /**< 上游帧序（重排主键） */
    uint64_t generation = 0;             /**< 代次 */
    preprocess::LetterboxMeta letterbox; /**< letterbox 参数（坐标还原） */
    std::vector<TensorData> tensors;     /**< 模型原始输出（float32） */
    int worker_id = -1;
    int core_mask = -1;
    double captured_at = 0.0;            /**< D4：上游采集时刻透传 */
    double stream_time_sec = 0.0;        /**< D4：上游流时间轴秒 */
    bool has_stream_time = false;
};

}  // namespace inference
}  // namespace yolo

#endif  /* YOLO_INFER_TYPES_H_ */

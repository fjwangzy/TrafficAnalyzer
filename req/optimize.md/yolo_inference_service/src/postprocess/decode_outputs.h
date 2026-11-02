/**
 * @file decode_outputs.h
 * @brief 9 输出 RKNN raw → 原图坐标检测框（对齐 decode_rknn_outputs）。
 */

#ifndef YOLO_POSTPROCESS_DECODE_OUTPUTS_H_
#define YOLO_POSTPROCESS_DECODE_OUTPUTS_H_

#include "../infer/types.h"
#include "types.h"

namespace yolo {
namespace postprocess {

/**
 * @brief 将 InferRawResult 解码为 FrameDetections。
 *
 * 要求 tensors 为 9 路（或 3 的倍数）且顺序为
 * `[box,cls,sum] × branch`；dims 必须有效。
 * 非法输入时返回空 dets，但保留身份键。
 */
FrameDetections decode_rknn_outputs(const inference::InferRawResult& raw,
                                    const DecodeConfig& cfg);

}  // namespace postprocess
}  // namespace yolo

#endif  /* YOLO_POSTPROCESS_DECODE_OUTPUTS_H_ */

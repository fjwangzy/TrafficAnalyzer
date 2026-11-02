/**
 * @file detection_queue.h
 * @brief 检测结果队列：复用 UnorderedInferQueue 模板。
 */

#ifndef YOLO_POSTPROCESS_DETECTION_QUEUE_H_
#define YOLO_POSTPROCESS_DETECTION_QUEUE_H_

#include "../infer/unordered_infer_queue.h"
#include "types.h"

namespace yolo {
namespace postprocess {

/** 进程内检测结果队列（满则阻塞；供重排/追踪另案消费）。 */
using DetectionResultQueue =
    inference::UnorderedInferQueue<FrameDetections>;

}  // namespace postprocess
}  // namespace yolo

#endif  /* YOLO_POSTPROCESS_DETECTION_QUEUE_H_ */

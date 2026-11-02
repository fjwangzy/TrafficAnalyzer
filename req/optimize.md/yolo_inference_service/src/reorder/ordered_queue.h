/**
 * @file ordered_queue.h
 * @brief 有序结果队列：复用 UnorderedInferQueue 模板（push_blocking）。
 */

#ifndef YOLO_REORDER_ORDERED_QUEUE_H_
#define YOLO_REORDER_ORDERED_QUEUE_H_

#include "../infer/unordered_infer_queue.h"
#include "types.h"

namespace yolo {
namespace reorder {

using OrderedResultQueue =
    inference::UnorderedInferQueue<OrderedFrameDetections>;

}  // namespace reorder
}  // namespace yolo

#endif  /* YOLO_REORDER_ORDERED_QUEUE_H_ */

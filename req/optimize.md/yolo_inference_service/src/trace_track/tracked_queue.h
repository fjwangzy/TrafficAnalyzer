/**
 * @file tracked_queue.h
 * @brief TrackedResultQueue：复用 UnorderedInferQueue（push_blocking）。
 */

#ifndef YOLO_TRACE_TRACK_TRACKED_QUEUE_H_
#define YOLO_TRACE_TRACK_TRACKED_QUEUE_H_

#include "../infer/unordered_infer_queue.h"
#include "../reorder/types.h"

namespace yolo {
namespace trace_track {

using TrackedResultQueue =
    inference::UnorderedInferQueue<reorder::OrderedFrameDetections>;

}  // namespace trace_track
}  // namespace yolo

#endif  /* YOLO_TRACE_TRACK_TRACKED_QUEUE_H_ */

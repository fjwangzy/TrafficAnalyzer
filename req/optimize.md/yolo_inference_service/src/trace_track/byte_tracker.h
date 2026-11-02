/**
 * @file byte_tracker.h
 * @brief ByteTracker / ByteTrackerArgs（对齐 byte_track.py）。
 */

#ifndef YOLO_TRACE_TRACK_BYTE_TRACKER_H_
#define YOLO_TRACE_TRACK_BYTE_TRACKER_H_

#include <vector>

#include "kalman_filter.h"
#include "strack.h"

namespace yolo {
namespace trace_track {

struct ByteTrackerArgs {
    float track_thresh = 0.5f;
    int track_buffer = 30;
    float match_thresh = 0.8f;
    bool mot20 = false;
    int frame_rate = 30;
    float low_score = 0.1f;
    float second_match_thresh = 0.5f;
    float unconfirmed_match_thresh = 0.7f;
};

/**
 * @brief 检测输入一行：x1,y1,x2,y2,score,class_id。
 */
struct DetRow {
    float x1 = 0.f;
    float y1 = 0.f;
    float x2 = 0.f;
    float y2 = 0.f;
    float score = 0.f;
    int class_id = -1;
};

class ByteTracker {
public:
    explicit ByteTracker(ByteTrackerArgs args = {});

    /**
     * @brief 对一帧检测执行关联与状态更新。
     * @return 当前 is_activated 的 tracked 列表。
     */
    std::vector<STrackPtr> update(const std::vector<DetRow>& detections);

    int frame_id() const { return frame_id_; }

private:
    int next_track_id();

    int frame_id_ = 0;
    std::vector<STrackPtr> tracked_stracks_;
    std::vector<STrackPtr> lost_stracks_;
    std::vector<STrackPtr> removed_stracks_;
    ByteTrackerArgs args_;
    float det_thresh_ = 0.6f;
    int buffer_size_ = 30;
    int max_time_lost_ = 30;
    KalmanFilter kalman_filter_;
    int track_id_counter_ = 0;

    static constexpr int kRemovedBuffer = 1000;
};

}  // namespace trace_track
}  // namespace yolo

#endif  /* YOLO_TRACE_TRACK_BYTE_TRACKER_H_ */

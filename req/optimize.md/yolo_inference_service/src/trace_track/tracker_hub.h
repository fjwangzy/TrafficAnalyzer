/**
 * @file tracker_hub.h
 * @brief StreamTrackerHub：按流 ByteTracker + 双通道装配。
 */

#ifndef YOLO_TRACE_TRACK_TRACKER_HUB_H_
#define YOLO_TRACE_TRACK_TRACKER_HUB_H_

#include <cstdint>
#include <memory>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include "../reorder/types.h"
#include "byte_tracker.h"
#include "../app/service_config.h"

namespace yolo {
namespace trace_track {

struct TrackerHubStats {
    bool tracking_enabled = true;
    std::size_t tracker_stream_count = 0;
    uint64_t track_assemble_count = 0;
    uint64_t track_update_count = 0;
    uint64_t track_empty_boxed_count = 0;
    uint64_t track_out_of_order_skip = 0;
    uint64_t track_epoch_reset_count = 0;
    uint64_t track_forget_count = 0;
};

class StreamTrackerHub {
public:
    explicit StreamTrackerHub(
        TrackingConfig config,
        std::unordered_map<int, std::string> class_names = {});

    /** 双通道装配：dets=raw(track_id=-1)；track_dets=轨迹或短路拷贝。 */
    reorder::OrderedFrameDetections assemble_frame(
        reorder::OrderedFrameDetections ordered);

    void forget_stream(const std::string& stream_id);
    void forget_all();

    TrackerHubStats stats() const;

private:
    struct TrackerState {
        std::unique_ptr<ByteTracker> tracker;
        uint64_t generation = 0;
        uint64_t last_tracked_seq = 0;
    };

    std::vector<postprocess::Detection> apply_tracking(
        const std::string& stream_id, uint64_t generation, uint64_t seq,
        const std::vector<postprocess::Detection>& raw);

    void enrich_class_names(std::vector<postprocess::Detection>& dets) const;
    void log_and_check_track_seq(const std::string& stream_id,
                                 uint64_t generation, uint64_t seq);

    TrackerState& create_tracker(const std::string& stream_id,
                                 uint64_t generation);
    void rebuild_tracker(const std::string& stream_id, uint64_t new_generation);

    std::vector<postprocess::Detection> tracker_update(
        TrackerState& state, const std::vector<postprocess::Detection>& boxed);

    ByteTrackerArgs make_args() const;

    TrackingConfig config_;
    std::unordered_map<int, std::string> class_names_;
    std::unordered_map<std::string, TrackerState> trackers_;
    std::unordered_map<std::string, uint64_t> generations_;
    std::unordered_map<std::string, std::pair<uint64_t, uint64_t>>
        last_recv_frames_;  // generation, seq

    uint64_t update_count_ = 0;
    uint64_t empty_boxed_count_ = 0;
    uint64_t out_of_order_skip_ = 0;
    uint64_t epoch_reset_count_ = 0;
    uint64_t forget_count_ = 0;
    uint64_t assemble_count_ = 0;
};

postprocess::Detection copy_without_track_id(
    const postprocess::Detection& det);

}  // namespace trace_track
}  // namespace yolo

#endif  /* YOLO_TRACE_TRACK_TRACKER_HUB_H_ */

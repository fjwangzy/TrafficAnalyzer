/**
 * @file latest_tracker.cpp
 * @brief LatestTracker 实现。
 */

#include "latest_tracker.h"

namespace yolo {
namespace comm {

bool LatestTracker::put(const reorder::OrderedFrameDetections& frame) {
    std::lock_guard<std::mutex> lk(mu_);
    ++put_count_;
    auto& latest = streams_[frame.stream_id];
    const bool is_latest =
        frame.generation > latest.generation ||
        (frame.generation == latest.generation && frame.seq >= latest.seq);
    if (is_latest) {
        latest.generation = frame.generation;
        latest.seq = frame.seq;
    }
    return is_latest;
}

void LatestTracker::forget_stream(const std::string& stream_id) {
    std::lock_guard<std::mutex> lk(mu_);
    streams_.erase(stream_id);
}

void LatestTracker::forget_all() {
    std::lock_guard<std::mutex> lk(mu_);
    streams_.clear();
}

size_t LatestTracker::stream_count() const {
    std::lock_guard<std::mutex> lk(mu_);
    return streams_.size();
}

std::vector<std::string> LatestTracker::known_streams() const {
    std::lock_guard<std::mutex> lk(mu_);
    std::vector<std::string> out;
    out.reserve(streams_.size());
    for (const auto& kv : streams_) out.push_back(kv.first);
    return out;
}

uint64_t LatestTracker::put_count() const {
    std::lock_guard<std::mutex> lk(mu_);
    return put_count_;
}

}  // namespace comm
}  // namespace yolo

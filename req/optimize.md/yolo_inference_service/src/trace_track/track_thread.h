/**
 * @file track_thread.h
 * @brief TrackThread：Ordered → Hub.assemble → Tracked。
 */

#ifndef YOLO_TRACE_TRACK_TRACK_THREAD_H_
#define YOLO_TRACE_TRACK_TRACK_THREAD_H_

#include <atomic>
#include <cstdint>
#include <memory>
#include <string>
#include <thread>

#include "../backpressure/sample_backoff.h"
#include "../reorder/ordered_queue.h"
#include "../app/service_config.h"
#include "tracker_hub.h"
#include "tracked_queue.h"

namespace yolo {
namespace trace_track {

class TrackThread {
public:
    TrackThread(reorder::OrderedResultQueue& ordered_queue,
                TrackedResultQueue& tracked_queue, TrackingConfig cfg,
                inference::SampleBackoff* backoff = nullptr);

    ~TrackThread();

    TrackThread(const TrackThread&) = delete;
    TrackThread& operator=(const TrackThread&) = delete;

    void start();
    void stop();

    bool running() const {
        return running_.load(std::memory_order_acquire);
    }

    StreamTrackerHub& hub() { return *hub_; }
    const StreamTrackerHub& hub() const { return *hub_; }

    uint64_t assembled_count() const {
        return assembled_count_.load(std::memory_order_relaxed);
    }

    void forget_stream(const std::string& stream_id) {
        hub_->forget_stream(stream_id);
    }

private:
    void runLoop();

    reorder::OrderedResultQueue& ordered_queue_;
    TrackedResultQueue& tracked_queue_;
    TrackingConfig cfg_;
    inference::SampleBackoff* backoff_;
    std::unique_ptr<StreamTrackerHub> hub_;

    std::atomic<bool> stop_flag_{false};
    std::atomic<bool> running_{false};
    std::thread thread_;
    std::atomic<uint64_t> assembled_count_{0};
};

}  // namespace trace_track
}  // namespace yolo

#endif  /* YOLO_TRACE_TRACK_TRACK_THREAD_H_ */

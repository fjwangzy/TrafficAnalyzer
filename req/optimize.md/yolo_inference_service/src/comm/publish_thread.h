/**
 * @file publish_thread.h
 * @brief PublishThread：Tracked -> LatestTracker -> wire_pack -> UpdatePublisher。
 *
 * 传输在 core three_plane（UpdatePublisher：三级丢弃、绝不阻塞）；
 * 本线程只做组装与统计。PUB socket 唯一持有者是 UpdatePublisher。
 */

#ifndef YOLO_COMM_PUBLISH_THREAD_H_
#define YOLO_COMM_PUBLISH_THREAD_H_

#include <atomic>
#include <cstdint>
#include <thread>

#include "update_publisher.h"

#include "../app/service_config.h"
#include "../trace_track/tracked_queue.h"
#include "latest_tracker.h"

namespace yolo {
namespace comm {

struct PublishThreadStats {
    uint64_t publish_ok = 0;
    uint64_t publish_drop = 0;
    uint64_t emit_count = 0;
    uint64_t publish_pack_fail = 0;
};

class PublishThread {
public:
    PublishThread(trace_track::TrackedResultQueue& tracked_queue,
                  LatestTracker& tracker, drn::core::tp::UpdatePublisher& pub,
                  int poll_timeout_ms)
        : tracked_queue_(tracked_queue)
        , tracker_(tracker)
        , pub_(pub)
        , poll_timeout_ms_(poll_timeout_ms) {}

    ~PublishThread() { stop(); }

    PublishThread(const PublishThread&) = delete;
    PublishThread& operator=(const PublishThread&) = delete;

    void start();
    void stop();

    bool running() const {
        return running_.load(std::memory_order_acquire);
    }

    PublishThreadStats stats() const {
        PublishThreadStats s;
        s.publish_ok = publish_ok_.load(std::memory_order_relaxed);
        s.publish_drop = publish_drop_.load(std::memory_order_relaxed);
        s.emit_count = emit_count_.load(std::memory_order_relaxed);
        s.publish_pack_fail =
            publish_pack_fail_.load(std::memory_order_relaxed);
        return s;
    }

    void forget_stream(const std::string& stream_id) {
        tracker_.forget_stream(stream_id);
    }

private:
    void runLoop();

    trace_track::TrackedResultQueue& tracked_queue_;
    LatestTracker& tracker_;
    drn::core::tp::UpdatePublisher& pub_;
    int poll_timeout_ms_;

    std::atomic<bool> stop_flag_{false};
    std::atomic<bool> running_{false};
    std::thread thread_;

    std::atomic<uint64_t> publish_ok_{0};
    std::atomic<uint64_t> publish_drop_{0};
    std::atomic<uint64_t> emit_count_{0};
    std::atomic<uint64_t> publish_pack_fail_{0};
};

}  // namespace comm
}  // namespace yolo

#endif  /* YOLO_COMM_PUBLISH_THREAD_H_ */

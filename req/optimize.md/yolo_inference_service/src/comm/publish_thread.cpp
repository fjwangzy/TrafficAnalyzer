/**
 * @file publish_thread.cpp
 * @brief PublishThread 实现：pop -> tracker.put(is_latest) -> pack -> publish。
 */

#include "publish_thread.h"

#include <chrono>
#include <cstdio>
#include <utility>

#include "wire_pack.h"

namespace yolo {
namespace comm {

void PublishThread::start() {
    if (running_.load(std::memory_order_acquire)) return;
    stop_flag_.store(false, std::memory_order_release);
    thread_ = std::thread([this] { runLoop(); });
    running_.store(true, std::memory_order_release);
}

void PublishThread::stop() {
    stop_flag_.store(true, std::memory_order_release);
    if (thread_.joinable()) thread_.join();
    running_.store(false, std::memory_order_release);
}

void PublishThread::runLoop() {
    while (!stop_flag_.load(std::memory_order_acquire)) {
        auto frame = tracked_queue_.pop(
            std::chrono::milliseconds(poll_timeout_ms_));
        if (!frame) continue;

        const bool is_latest = tracker_.put(*frame);

        std::vector<uint8_t> bytes;
        if (!comm_server::pack_inference_update(
                is_latest, static_cast<double>(::time(nullptr)), *frame,
                &bytes)) {
            ++publish_pack_fail_;
            continue;
        }

        ++emit_count_;
        if (pub_.publish(frame->stream_id, bytes)) {
            ++publish_ok_;
        } else {
            // 满即丢是设计内行为（慢订阅者丢事件合法）
            ++publish_drop_;
        }
    }
}

}  // namespace comm
}  // namespace yolo

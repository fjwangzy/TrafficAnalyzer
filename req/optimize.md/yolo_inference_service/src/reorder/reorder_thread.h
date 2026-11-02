/**
 * @file reorder_thread.h
 * @brief ReorderThread：抽干 Admit + ingest Detection + gap_scan → Ordered。
 */

#ifndef YOLO_REORDER_THREAD_H_
#define YOLO_REORDER_THREAD_H_

#include <atomic>
#include <cstdint>
#include <memory>
#include <string>
#include <thread>

#include "../backpressure/sample_backoff.h"
#include "../postprocess/detection_queue.h"
#include "admit_queue.h"
#include "../app/service_config.h"
#include "ordered_queue.h"
#include "reorder_buffer.h"

namespace yolo {
namespace reorder {

class ReorderThread {
public:
    ReorderThread(AdmitQueue& admit_queue,
                  postprocess::DetectionResultQueue& det_queue,
                  OrderedResultQueue& ordered_queue,
                  ReorderConfig cfg,
                  inference::SampleBackoff* backoff = nullptr);

    ~ReorderThread();

    ReorderThread(const ReorderThread&) = delete;
    ReorderThread& operator=(const ReorderThread&) = delete;

    void start();
    void stop();

    bool running() const {
        return running_.load(std::memory_order_acquire);
    }

    ReorderBuffer& buffer() { return *buffer_; }
    const ReorderBuffer& buffer() const { return *buffer_; }

    uint64_t released_count() const {
        return released_count_.load(std::memory_order_relaxed);
    }

    /** @brief 流下架 API（开放依赖触发源）。 */
    int forget_stream(const std::string& stream_id) {
        return buffer_->forget_stream(stream_id);
    }

private:
    void runLoop();
    void drain_admits();
    void push_released(std::vector<OrderedFrameDetections>&& frames);

    AdmitQueue& admit_queue_;
    postprocess::DetectionResultQueue& det_queue_;
    OrderedResultQueue& ordered_queue_;
    ReorderConfig cfg_;
    inference::SampleBackoff* backoff_;
    std::unique_ptr<ReorderBuffer> buffer_;

    std::atomic<bool> stop_flag_{false};
    std::atomic<bool> running_{false};
    std::thread thread_;
    std::atomic<uint64_t> released_count_{0};
};

/**
 * @brief 调试 Passthrough：Detection → Ordered（不做重排）。
 * reorder.enabled=false 时由组装层选用。
 */
class PassthroughThread {
public:
    PassthroughThread(postprocess::DetectionResultQueue& det_queue,
                      OrderedResultQueue& ordered_queue,
                      int poll_timeout_ms = 50);
    ~PassthroughThread();

    void start();
    void stop();

private:
    void runLoop();

    postprocess::DetectionResultQueue& det_queue_;
    OrderedResultQueue& ordered_queue_;
    int poll_timeout_ms_;
    std::atomic<bool> stop_flag_{false};
    std::atomic<bool> running_{false};
    std::thread thread_;
};

}  // namespace reorder
}  // namespace yolo

#endif  /* YOLO_REORDER_THREAD_H_ */

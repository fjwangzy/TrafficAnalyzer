/**
 * @file reorder_thread.cpp
 * @brief ReorderThread / PassthroughThread 实现。
 */

#include "reorder_thread.h"

#include <cstdio>

namespace yolo {
namespace reorder {

ReorderThread::ReorderThread(AdmitQueue& admit_queue,
                             postprocess::DetectionResultQueue& det_queue,
                             OrderedResultQueue& ordered_queue,
                             ReorderConfig cfg,
                             inference::SampleBackoff* backoff)
    : admit_queue_(admit_queue)
    , det_queue_(det_queue)
    , ordered_queue_(ordered_queue)
    , cfg_(std::move(cfg))
    , backoff_(backoff)
    , buffer_(std::make_unique<ReorderBuffer>(
          cfg_.gap_timeout_sec, cfg_.max_waiting_per_stream)) {}

ReorderThread::~ReorderThread() { stop(); }

void ReorderThread::start() {
    if (running_.load(std::memory_order_acquire)) return;
    stop_flag_.store(false, std::memory_order_release);
    thread_ = std::thread([this] { runLoop(); });
    running_.store(true, std::memory_order_release);
    std::fprintf(stderr, "[reorder thread] started\n");
}

void ReorderThread::stop() {
    stop_flag_.store(true, std::memory_order_release);
    if (thread_.joinable()) thread_.join();
    running_.store(false, std::memory_order_release);
}

void ReorderThread::drain_admits() {
    while (auto ev = admit_queue_.try_pop()) {
        buffer_->admit(ev->stream_id, ev->generation, ev->seq);
    }
}

void ReorderThread::push_released(
    std::vector<OrderedFrameDetections>&& frames) {
    for (auto& f : frames) {
        ordered_queue_.push_blocking(std::move(f));
        ++released_count_;
        if (cfg_.sample_backoff_on_ordered_block && backoff_ &&
            ordered_queue_.block_count() > 0) {
            backoff_->try_apply_backoff("ordered_queue_block");
        }
    }
}

void ReorderThread::runLoop() {
    while (!stop_flag_.load(std::memory_order_acquire)) {
        drain_admits();

        auto det = det_queue_.pop(
            std::chrono::milliseconds(cfg_.poll_timeout_ms));
        if (det.has_value()) {
            // 关键：ingest 前再次排空 admit_queue，
            // 避免检测结果因产生速度 > admit 排空速度而"orphan"
            drain_admits();
            auto released = buffer_->ingest(std::move(*det));
            push_released(std::move(released));
        } else if (det_queue_.stopped()) {
            break;
        }

        drain_admits();
        auto gap = buffer_->gap_scan();
        push_released(std::move(gap.second));
    }

    // 停机抽干
    drain_admits();
    while (auto det = det_queue_.pop(std::chrono::milliseconds(0))) {
        auto released = buffer_->ingest(std::move(*det));
        push_released(std::move(released));
    }
    auto gap = buffer_->gap_scan();
    push_released(std::move(gap.second));

    std::fprintf(stderr,
                 "[reorder thread] stopped: released=%llu stats={%s}\n",
                 static_cast<unsigned long long>(released_count_.load()),
                 buffer_->stats_summary().c_str());
}

// ---- Passthrough ----

PassthroughThread::PassthroughThread(
    postprocess::DetectionResultQueue& det_queue,
    OrderedResultQueue& ordered_queue,
    int poll_timeout_ms)
    : det_queue_(det_queue)
    , ordered_queue_(ordered_queue)
    , poll_timeout_ms_(poll_timeout_ms > 0 ? poll_timeout_ms : 50) {}

PassthroughThread::~PassthroughThread() { stop(); }

void PassthroughThread::start() {
    if (running_.load(std::memory_order_acquire)) return;
    stop_flag_.store(false, std::memory_order_release);
    std::fprintf(stderr,
                 "[reorder passthrough] WARNING: reorder disabled — "
                 "Detection→Ordered without buffering (out-of-order risk)\n");
    thread_ = std::thread([this] { runLoop(); });
    running_.store(true, std::memory_order_release);
}

void PassthroughThread::stop() {
    stop_flag_.store(true, std::memory_order_release);
    if (thread_.joinable()) thread_.join();
    running_.store(false, std::memory_order_release);
}

void PassthroughThread::runLoop() {
    while (!stop_flag_.load(std::memory_order_acquire)) {
        auto det = det_queue_.pop(
            std::chrono::milliseconds(poll_timeout_ms_));
        if (!det.has_value()) {
            if (det_queue_.stopped()) break;
            continue;
        }
        OrderedFrameDetections out;
        out.stream_id = std::move(det->stream_id);
        out.seq = det->seq;
        out.generation = det->generation;
        out.letterbox = std::move(det->letterbox);
        out.dets = std::move(det->dets);
        out.worker_id = det->worker_id;
        out.core_mask = det->core_mask;
        ordered_queue_.push_blocking(std::move(out));
    }
}

}  // namespace reorder
}  // namespace yolo

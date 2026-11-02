/**
 * @file track_thread.cpp
 * @brief TrackThread 主循环与停机抽干。
 */

#include "track_thread.h"

#include <cstdio>

namespace yolo {
namespace trace_track {

TrackThread::TrackThread(reorder::OrderedResultQueue& ordered_queue,
                         TrackedResultQueue& tracked_queue, TrackingConfig cfg,
                         inference::SampleBackoff* backoff)
    : ordered_queue_(ordered_queue)
    , tracked_queue_(tracked_queue)
    , cfg_(std::move(cfg))
    , backoff_(backoff) {
    auto names = yolo::app::load_class_names(cfg_.names_path);
    hub_ = std::make_unique<StreamTrackerHub>(cfg_, std::move(names));
}

TrackThread::~TrackThread() { stop(); }

void TrackThread::start() {
    if (running_.load(std::memory_order_acquire)) return;
    stop_flag_.store(false, std::memory_order_release);
    thread_ = std::thread([this] { runLoop(); });
    running_.store(true, std::memory_order_release);
    std::fprintf(stderr, "[track thread] started\n");
}

void TrackThread::stop() {
    stop_flag_.store(true, std::memory_order_release);
    if (thread_.joinable()) thread_.join();
    running_.store(false, std::memory_order_release);
}

void TrackThread::runLoop() {
    while (!stop_flag_.load(std::memory_order_acquire)) {
        auto ordered = ordered_queue_.pop(
            std::chrono::milliseconds(cfg_.poll_timeout_ms));
        if (!ordered.has_value()) {
            if (ordered_queue_.stopped()) break;
            continue;
        }
        auto assembled = hub_->assemble_frame(std::move(*ordered));
        tracked_queue_.push_blocking(std::move(assembled));
        ++assembled_count_;
        if (cfg_.sample_backoff_on_tracked_block && backoff_ &&
            tracked_queue_.block_count() > 0) {
            backoff_->try_apply_backoff("tracked_queue_block");
        }
    }

    // 停机抽干
    while (auto ordered =
               ordered_queue_.pop(std::chrono::milliseconds(0))) {
        auto assembled = hub_->assemble_frame(std::move(*ordered));
        tracked_queue_.push_blocking(std::move(assembled));
        ++assembled_count_;
    }
    hub_->forget_all();

    auto st = hub_->stats();
    std::fprintf(stderr,
                 "[track thread] stopped: assembled=%llu update=%llu "
                 "empty_boxed=%llu ooo=%llu epoch_reset=%llu\n",
                 static_cast<unsigned long long>(assembled_count_.load()),
                 static_cast<unsigned long long>(st.track_update_count),
                 static_cast<unsigned long long>(st.track_empty_boxed_count),
                 static_cast<unsigned long long>(st.track_out_of_order_skip),
                 static_cast<unsigned long long>(st.track_epoch_reset_count));
}

}  // namespace trace_track
}  // namespace yolo

/**
 * @file postprocess_worker.cpp
 * @brief PostprocessWorker 实现：pop_output -> 解 meta -> decode -> push。
 */

#include "postprocess_worker.h"

#include "decode_outputs.h"

#include <cstdio>
#include <utility>

namespace yolo {
namespace postprocess {

PostprocessWorker::~PostprocessWorker() {
    stop();
}

void PostprocessWorker::start() {
    if (running_.load(std::memory_order_acquire)) return;
    stop_flag_.store(false, std::memory_order_release);
    thread_ = std::thread([this] { runLoop(); });
    running_.store(true, std::memory_order_release);
}

void PostprocessWorker::stop() {
    stop_flag_.store(true, std::memory_order_release);
    if (thread_.joinable()) thread_.join();
    running_.store(false, std::memory_order_release);
}

void PostprocessWorker::runLoop() {
    while (!stop_flag_.load(std::memory_order_acquire)) {
        auto out = engine_.pop_output(std::chrono::milliseconds(50));
        if (!out.has_value()) continue;  // 超时轮询 stop；关闭且抽干亦退出

        yolo::infer::InferMeta meta;
        if (!yolo::infer::unpack_meta(out->user_meta, &meta)) {
            ++meta_fail_;
            std::fprintf(stderr,
                         "[postprocess %d] user_meta unpack failed "
                         "(worker=%d ok=%d)\n",
                         id_, out->worker_id,
                         static_cast<int>(out->ok));
            continue;
        }

        inference::InferRawResult raw;
        raw.stream_id = std::move(meta.stream_id);
        raw.seq = meta.seq;
        raw.generation = meta.generation;
        raw.letterbox = std::move(meta.letterbox);
        raw.captured_at = meta.captured_at;
        raw.stream_time_sec = meta.stream_time_sec;
        raw.has_stream_time = meta.has_stream_time;
        raw.worker_id = out->worker_id;
        raw.core_mask = out->core_mask;
        if (out->ok) raw.tensors = std::move(out->tensors);
        // ok=false：tensors 保持空 -> decode 产出空 dets（缺帧跳过）

        FrameDetections frame = decode_rknn_outputs(raw, cfg_);
        if (frame.dets.empty()) {
            ++empty_count_;
        } else {
            ++decode_count_;
        }
        det_queue_.push_blocking(std::move(frame));
    }

    std::fprintf(stderr,
                 "[postprocess worker %d] stopped: decoded=%llu empty=%llu\n",
                 id_,
                 static_cast<unsigned long long>(decode_count_.load()),
                 static_cast<unsigned long long>(empty_count_.load()));
}

}  // namespace postprocess
}  // namespace yolo

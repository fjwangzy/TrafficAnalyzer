/**
 * @file engine_ingest.cpp
 * @brief EngineIngest 实现：acquire -> InferJob -> submit -> admit。
 */

#include "engine_ingest.h"

#include <cstdio>
#include <utility>

#include "meta_codec.h"

namespace yolo {
namespace infer {

void EngineIngest::on_frame_published(uint64_t seq_local, double captured_at,
                                      double stream_time_sec,
                                      bool has_stream_time) {
    auto frame = ring_.acquire(seq_local);
    if (!frame.has_value()) {
        ++acquire_miss_;
        return;
    }

    InferMeta meta;
    meta.slot_index = static_cast<uint32_t>(frame->slot_index);
    meta.stream_id = frame->upstream_stream_id;
    meta.seq = frame->upstream_seq;
    meta.generation = frame->upstream_generation;
    meta.letterbox = frame->letterbox;
    meta.captured_at = captured_at;
    meta.stream_time_sec = stream_time_sec;
    meta.has_stream_time = has_stream_time;

    drn::core::rknn::InferJob job;
    job.dma_fd = frame->dma_fd;
    job.size = static_cast<uint32_t>(frame->slot_size);
    job.offset = 0;
    // release 恰好一次由组件保证（含拒收路径）；closure 捕获槽下标，
    // refcount 持有期间侧表 seq 稳定，slot -> seq 换算安全。
    const int slot_index = frame->slot_index;
    job.release = [this, slot_index] { ring_.release(slot_index); };
    job.user_meta = pack_meta(meta);

    if (!engine_.submit(std::move(job))) {
        // 组件已就地 release 并发 kJobQueueFull；这里只计数。
        ++rejected_;
        std::fprintf(stderr,
                     "[engine_ingest] job queue full: rejected stream=%s "
                     "seq=%llu accepted=%llu rejected=%llu\n",
                     meta.stream_id.c_str(),
                     static_cast<unsigned long long>(meta.seq),
                     static_cast<unsigned long long>(accepted_.load()),
                     static_cast<unsigned long long>(rejected_.load()));
        return;
    }
    ++accepted_;

    // 元数据先行：detection 未到由 reorder pre-ingest drain 兜底；
    // admit 满拒收 -> 后续结果按 orphan 丢弃（旧语义）。
    if (admit_queue_) {
        reorder::AdmitEvent ev;
        ev.stream_id = meta.stream_id;
        ev.generation = meta.generation;
        ev.seq = meta.seq;
        if (!admit_queue_->try_push(std::move(ev))) {
            ++admit_reject_;
        }
    }
}

}  // namespace infer
}  // namespace yolo

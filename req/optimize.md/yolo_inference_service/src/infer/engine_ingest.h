/**
 * @file engine_ingest.h
 * @brief 环 -> core rknn_engine 衔接：publish 回调 -> acquire -> submit。
 *
 * 旧 InferInputSource 的队列与 release 责任已收敛进组件（rknn_engine
 * 强制意见 6）：凡进入 submit 的任务恰好一次 release（含拒收路径，
 * engine.cpp），本类拒收后只计数，不二次 release。
 */

#ifndef YOLO_INFER_ENGINE_INGEST_H_
#define YOLO_INFER_ENGINE_INGEST_H_

#include <atomic>
#include <cstdint>

#include "i_inference_engine.h"

#include "../preprocess/local_rgb_ring.h"
#include "../reorder/admit_queue.h"

namespace yolo {
namespace infer {

class EngineIngest {
public:
    EngineIngest(preprocess::LocalRgbRing& ring,
                 drn::core::rknn::IInferenceEngine& engine,
                 reorder::AdmitQueue* admit_queue)
        : ring_(ring)
        , engine_(engine)
        , admit_queue_(admit_queue) {}

    /** @brief RGA 线程 publish 成功后的薄回调（seq_local = 刚发布的环序）。 */
    void on_frame_published(uint64_t seq_local, double captured_at,
                            double stream_time_sec, bool has_stream_time);

    uint64_t accepted_count() const {
        return accepted_.load(std::memory_order_relaxed);
    }
    uint64_t rejected_count() const {
        return rejected_.load(std::memory_order_relaxed);
    }
    uint64_t acquire_miss_count() const {
        return acquire_miss_.load(std::memory_order_relaxed);
    }
    uint64_t admit_reject_count() const {
        return admit_reject_.load(std::memory_order_relaxed);
    }

private:
    preprocess::LocalRgbRing& ring_;
    drn::core::rknn::IInferenceEngine& engine_;
    reorder::AdmitQueue* admit_queue_;

    std::atomic<uint64_t> accepted_{0};
    std::atomic<uint64_t> rejected_{0};
    std::atomic<uint64_t> acquire_miss_{0};
    std::atomic<uint64_t> admit_reject_{0};
};

}  // namespace infer
}  // namespace yolo

#endif  /* YOLO_INFER_ENGINE_INGEST_H_ */

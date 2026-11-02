/**
 * @file postprocess_worker.h
 * @brief 从 core rknn_engine pop_output -> DFL/NMS -> DetectionResultQueue。
 *
 * 旧 raw 队列由组件 InferOutputQueue 承担；多 worker 竞争 pop_output
 * （BoundedQueue 多消费者安全）。ok=false 空 envelope 产出空 dets 帧
 * （身份键保留），重排按缺帧跳过——旧语义。
 */

#ifndef YOLO_POSTPROCESS_WORKER_H_
#define YOLO_POSTPROCESS_WORKER_H_

#include <atomic>
#include <chrono>
#include <cstdint>
#include <thread>

#include "i_inference_engine.h"

#include "../infer/meta_codec.h"
#include "../infer/types.h"
#include "detection_queue.h"
#include "types.h"

namespace yolo {
namespace postprocess {

class PostprocessWorker {
public:
    PostprocessWorker(int id,
                      drn::core::rknn::IInferenceEngine& engine,
                      DetectionResultQueue& det_queue,
                      DecodeConfig cfg)
        : id_(id)
        , engine_(engine)
        , det_queue_(det_queue)
        , cfg_(std::move(cfg)) {}

    ~PostprocessWorker();

    PostprocessWorker(const PostprocessWorker&) = delete;
    PostprocessWorker& operator=(const PostprocessWorker&) = delete;

    void start();
    void stop();

    bool running() const {
        return running_.load(std::memory_order_acquire);
    }

    uint64_t decode_count() const {
        return decode_count_.load(std::memory_order_relaxed);
    }

    uint64_t empty_count() const {
        return empty_count_.load(std::memory_order_relaxed);
    }

    uint64_t meta_fail_count() const {
        return meta_fail_.load(std::memory_order_relaxed);
    }

private:
    void runLoop();

    int id_;
    drn::core::rknn::IInferenceEngine& engine_;
    DetectionResultQueue& det_queue_;
    DecodeConfig cfg_;

    std::atomic<bool> stop_flag_{false};
    std::atomic<bool> running_{false};
    std::thread thread_;

    std::atomic<uint64_t> decode_count_{0};
    std::atomic<uint64_t> empty_count_{0};
    std::atomic<uint64_t> meta_fail_{0};
};

}  // namespace postprocess
}  // namespace yolo

#endif  /* YOLO_POSTPROCESS_WORKER_H_ */

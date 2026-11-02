/**
 * @file admit_queue.h
 * @brief 有界非阻塞 AdmitQueue：仅 try_push / try_pop（RGA 线程禁阻塞）。
 */

#ifndef YOLO_REORDER_ADMIT_QUEUE_H_
#define YOLO_REORDER_ADMIT_QUEUE_H_

#include <atomic>
#include <cstddef>
#include <mutex>
#include <optional>
#include <queue>

#include "types.h"

namespace yolo {
namespace reorder {

class AdmitQueue {
public:
    explicit AdmitQueue(size_t capacity = 256)
        : capacity_(capacity > 0 ? capacity : 1) {}

    AdmitQueue(const AdmitQueue&) = delete;
    AdmitQueue& operator=(const AdmitQueue&) = delete;

    /** @brief 非阻塞入队；满则拒收并计 reject。 */
    bool try_push(AdmitEvent item) {
        std::lock_guard<std::mutex> lk(mu_);
        if (q_.size() >= capacity_) {
            ++reject_count_;
            return false;
        }
        q_.push(std::move(item));
        return true;
    }

    /** @brief 非阻塞出队；空则 nullopt。 */
    std::optional<AdmitEvent> try_pop() {
        std::lock_guard<std::mutex> lk(mu_);
        if (q_.empty()) return std::nullopt;
        AdmitEvent item = std::move(q_.front());
        q_.pop();
        return item;
    }

    size_t size() const {
        std::lock_guard<std::mutex> lk(mu_);
        return q_.size();
    }

    size_t capacity() const { return capacity_; }

    uint64_t reject_count() const {
        return reject_count_.load(std::memory_order_relaxed);
    }

private:
    size_t capacity_;
    mutable std::mutex mu_;
    std::queue<AdmitEvent> q_;
    std::atomic<uint64_t> reject_count_{0};
};

}  // namespace reorder
}  // namespace yolo

#endif  /* YOLO_REORDER_ADMIT_QUEUE_H_ */

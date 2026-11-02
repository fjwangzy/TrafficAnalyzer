/**
 * @file unordered_infer_queue.h
 * @brief 有界阻塞队列：worker push raw（满则阻塞）+ 后处理 pop。
 *
 * 语义（plan §2.2 / §9.2.3）：
 *   - push_blocking()：队列满时阻塞调用线程（不丢已推理结果）。
 *   - pop()：队列空时阻塞等待。
 *   - 单队列混流；元素含 identity sidecar 供重排。
 *   - 多生产（InferWorker）/ 多消费（PostprocessWorker）安全。
 *   - release 先于 push_blocking，避免 raw 满拖死 LocalRgbRing。
 *
 * 线程安全：内部使用 std::mutex + std::condition_variable。
 */

#ifndef YOLO_INFERENCE_UNORDERED_INFER_QUEUE_H_
#define YOLO_INFERENCE_UNORDERED_INFER_QUEUE_H_

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstddef>
#include <mutex>
#include <optional>
#include <queue>

namespace yolo {
namespace inference {

/**
 * @brief 有界 raw 输出队列（多生产 / 多消费）。
 *
 * @tparam T 元素类型（实际为 InferRawResult / FrameDetections）。
 */
template <typename T>
class UnorderedInferQueue {
public:
    /**
     * @brief 构造指定容量的队列。
     * @param capacity 最大容量；必须 >= 1。
     */
    explicit UnorderedInferQueue(size_t capacity = 16)
        : capacity_(capacity > 0 ? capacity : 1) {}

    UnorderedInferQueue(const UnorderedInferQueue&) = delete;
    UnorderedInferQueue& operator=(const UnorderedInferQueue&) = delete;

    /**
     * @brief 阻塞入队（满则阻塞调用线程；不丢已推理结果）。
     *
     * @param item 入队元素（移动语义）。
     */
    void push_blocking(T item) {
        std::unique_lock<std::mutex> lk(mu_);
        // 阻塞直到队列有空间或 stop（predicate 避免停机后永久 wait）
        while (q_.size() >= capacity_ &&
               !stopped_.load(std::memory_order_acquire)) {
            ++block_count_;
            cv_pop_.notify_one();
            cv_push_.wait(lk, [this] {
                return q_.size() < capacity_ ||
                       stopped_.load(std::memory_order_acquire);
            });
        }
        if (stopped_.load(std::memory_order_acquire)) {
            return;  // 停止期间丢弃（调用方正在拆流水线）
        }
        q_.push(std::move(item));
        // 多后处理 worker：唤醒所有等待消费者，避免仅一个线程被叫醒
        cv_pop_.notify_all();
    }

    /**
     * @brief 限时出队（消费者）。
     *
     * @param timeout 最长等待；到期仍空则返回 nullopt（含 timeout=0 的抽干场景）。
     * @return 出队元素；超时或 stop() 后返回 nullopt。
     */
    std::optional<T> pop(std::chrono::milliseconds timeout =
                             std::chrono::milliseconds(100)) {
        std::unique_lock<std::mutex> lk(mu_);
        // 必须在超时后返回，否则 pop(0) 抽干会在空队列上忙等死循环，
        // 进而令 PublishThread/TrackThread/ReorderThread 的 stop()+join 永久卡住。
        if (!cv_pop_.wait_for(lk, timeout, [this] {
                return !q_.empty() ||
                       stopped_.load(std::memory_order_acquire);
            })) {
            return std::nullopt;  // 超时
        }
        if (q_.empty()) {
            return std::nullopt;  // stop 或竞态清空
        }

        T item = std::move(q_.front());
        q_.pop();
        // 通知一个阻塞的生产者（如果有）
        cv_push_.notify_one();
        return item;
    }

    /**
     * @brief 优雅停止：唤醒所有阻塞线程。
     */
    void stop() {
        stopped_.store(true, std::memory_order_release);
        cv_push_.notify_all();
        cv_pop_.notify_all();
    }

    /** @brief 当前队列大小（近似值）。 */
    size_t size() const {
        std::lock_guard<std::mutex> lk(mu_);
        return q_.size();
    }

    /** @brief 队列容量。 */
    size_t capacity() const { return capacity_; }

    /**
     * @brief 队列是否已满（快照；近似值）。
     *
     * 供 backoff 观测：进入 push_blocking 的阻塞是否持续。
     */
    bool full() const {
        std::lock_guard<std::mutex> lk(mu_);
        return q_.size() >= capacity_;
    }

    /** @brief 累计阻塞次数（近似观测）。 */
    uint64_t block_count() const {
        return block_count_.load(std::memory_order_relaxed);
    }

    /** @brief 是否已停止。 */
    bool stopped() const {
        return stopped_.load(std::memory_order_acquire);
    }

private:
    size_t capacity_;
    mutable std::mutex mu_;
    std::queue<T> q_;
    std::condition_variable cv_push_;  /**< 生产者等待空间 */
    std::condition_variable cv_pop_;   /**< 消费者等待数据 */
    std::atomic<bool> stopped_{false};
    std::atomic<uint64_t> block_count_{0};
};

}  // namespace inference
}  // namespace yolo

#endif  /* YOLO_INFERENCE_UNORDERED_INFER_QUEUE_H_ */

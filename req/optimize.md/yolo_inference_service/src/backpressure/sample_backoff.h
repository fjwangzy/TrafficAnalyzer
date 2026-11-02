/**
 * @file sample_backoff.h
 * @brief 队列满时全流降抽样：SQLite stream_configs 全行 += sample_backoff_ms。
 *
 * 语义（plan §2.5 / §9.2.4）：
 *   - 触发：InferMetaQueue 拒收（try_push=false）或 UnorderedInferQueue 阻塞。
 *   - 动作：打开共享 SQLite，全流 sample_interval_ms += sample_backoff_ms。
 *   - 冷却：两次成功写库之间须 >= sample_backoff_cooldown_ms（默认 5000ms）。
 *   - 冷却期内再次触发只计指标，不写库。
 *   - 生效：依赖 rtsp_receive_service sqlite 热更新感知变更。
 *
 * 线程安全：内部使用 std::mutex 保护 SQLite 写 + 时间戳。
 */

#ifndef YOLO_INFERENCE_SAMPLE_BACKOFF_H_
#define YOLO_INFERENCE_SAMPLE_BACKOFF_H_

#include <atomic>
#include <chrono>
#include <cstdint>
#include <mutex>
#include <string>

namespace yolo {
namespace inference {

/**
 * @brief 全流降抽样管理器。
 *
 * 用法：
 *   1. 构造时传入 db_path、sample_backoff_ms、sample_backoff_cooldown_ms。
 *   2. 触发条件满足时调用 try_apply_backoff()。
 *   3. 内部自处理冷却逻辑与 SQLite 写入。
 */
class SampleBackoff {
public:
    /**
     * @brief 构造降抽样管理器。
     *
     * @param db_path  SQLite 业务库路径（与 rtsp 共用，含 stream_configs 表）。
     * @param backoff_ms 每次满队列事件对 sample_interval_ms 的增量。
     * @param cooldown_ms 两次成功写入的最小间隔（毫秒）。
     */
    SampleBackoff(const std::string& db_path,
                  int backoff_ms = 25,
                  int cooldown_ms = 5000);

    SampleBackoff(const SampleBackoff&) = delete;
    SampleBackoff& operator=(const SampleBackoff&) = delete;

    /**
     * @brief 尝试触发降抽样。
     *
     * 受冷却约束：冷却期内调用只累计 skipped_count_，不写库。
     *
     * @param reason 触发原因（如 "meta_queue_full", "raw_queue_block"），用于日志。
     * @return true  成功写库（冷却过后）。
     * @return false 冷却期内跳过，或写入失败。
     */
    bool try_apply_backoff(const char* reason);

    /** @brief 累计成功写库次数。 */
    uint64_t applied_count() const {
        return applied_count_.load(std::memory_order_relaxed);
    }

    /** @brief 冷却期内累计跳过次数。 */
    uint64_t skipped_count() const {
        return skipped_count_.load(std::memory_order_relaxed);
    }

    /** @brief 累计 SQLite 写失败次数。 */
    uint64_t fail_count() const {
        return fail_count_.load(std::memory_order_relaxed);
    }

private:
    /**
     * @brief 执行 SQLite 写入：UPDATE stream_configs SET
     *        sample_interval_ms = sample_interval_ms + :inc WHERE sample_interval_ms > 0。
     *
     * @return 更新行数；负值表示错误。
     */
    int apply_sqlite_increment();

    std::string db_path_;
    int backoff_ms_;
    int cooldown_ms_;

    std::mutex mu_;
    std::chrono::steady_clock::time_point last_applied_;

    std::atomic<uint64_t> applied_count_{0};
    std::atomic<uint64_t> skipped_count_{0};
    std::atomic<uint64_t> fail_count_{0};
};

}  // namespace inference
}  // namespace yolo

#endif  /* YOLO_INFERENCE_SAMPLE_BACKOFF_H_ */

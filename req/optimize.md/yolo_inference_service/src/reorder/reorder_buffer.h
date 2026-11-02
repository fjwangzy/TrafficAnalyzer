/**
 * @file reorder_buffer.h
 * @brief 重排序核心状态机（对齐 Python ReorderBuffer；无线程/无锁）。
 */

#ifndef YOLO_REORDER_BUFFER_H_
#define YOLO_REORDER_BUFFER_H_

#include <cstdint>
#include <functional>
#include <optional>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include "../postprocess/types.h"
#include "types.h"

namespace yolo {
namespace reorder {

class ReorderBuffer {
public:
    /** 单调时钟：返回秒（double）。单测可注入。 */
    using Clock = std::function<double()>;

    explicit ReorderBuffer(double gap_timeout_sec = 1.0,
                           int max_waiting_per_stream = 32,
                           Clock clock = nullptr);

    ReorderBuffer(const ReorderBuffer&) = delete;
    ReorderBuffer& operator=(const ReorderBuffer&) = delete;

    void admit(const std::string& stream_id, uint64_t generation, uint64_t seq);

    std::vector<OrderedFrameDetections> ingest(
        postprocess::FrameDetections result);

    /**
     * @brief 超时扫描。
     * @return (skipped 诊断列表, 额外放出的有序帧)
     */
    std::pair<std::vector<GapSkipInfo>, std::vector<OrderedFrameDetections>>
    gap_scan();

    /** @brief 清空某流全部代次；返回丢弃条数。 */
    int forget_stream(const std::string& stream_id);

    /** @brief 汇总指标（简化版；供日志）。 */
    std::string stats_summary() const;

    uint64_t epoch_reset_drop_count() const { return epoch_reset_drop_count_; }
    uint64_t forget_stream_drop_count() const {
        return forget_stream_drop_count_;
    }

private:
    StreamEpochState& ensure_epoch(const std::string& stream_id,
                                   uint64_t generation);
    int drop_epochs(const std::string& stream_id,
                    std::optional<uint64_t> keep_generation);

    std::optional<uint64_t> expected_seq(const StreamEpochState& state) const;
    std::vector<OrderedFrameDetections> flush(StreamEpochState& state);
    bool accept_waiting(StreamEpochState& state, uint64_t seq,
                        postprocess::FrameDetections result);
    void refresh_wait_timer(StreamEpochState& state);

    static OrderedFrameDetections to_ordered(
        postprocess::FrameDetections&& unordered);
    static bool admitted_contains(const StreamEpochState& state, uint64_t seq);
    static void admitted_remove(StreamEpochState& state, uint64_t seq);

    using StateKey = std::pair<std::string, uint64_t>;
    struct StateKeyHash {
        size_t operator()(const StateKey& k) const {
            return std::hash<std::string>{}(k.first) ^
                   (std::hash<uint64_t>{}(k.second) << 1);
        }
    };

    std::unordered_map<StateKey, StreamEpochState, StateKeyHash> states_;
    std::unordered_map<std::string, uint64_t> active_generation_;
    double gap_timeout_;
    int max_waiting_;
    Clock clock_;
    uint64_t forget_stream_drop_count_ = 0;
    uint64_t epoch_reset_drop_count_ = 0;
};

}  // namespace reorder
}  // namespace yolo

#endif  /* YOLO_REORDER_BUFFER_H_ */

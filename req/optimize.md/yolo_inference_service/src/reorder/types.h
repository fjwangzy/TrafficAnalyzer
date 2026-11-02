/**
 * @file types.h
 * @brief 重排序共享类型：AdmitEvent / OrderedFrameDetections / StreamEpochState。
 *
 * 对应计划：plans/reorder_plan.md §3
 */

#ifndef YOLO_REORDER_TYPES_H_
#define YOLO_REORDER_TYPES_H_

#include <cstdint>
#include <deque>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

#include "../postprocess/types.h"

namespace yolo {
namespace reorder {

/** 接纳事件：InferMetaQueue 成功入队后登记（seq = upstream_seq）。 */
struct AdmitEvent {
    std::string stream_id;
    uint64_t generation = 0;
    uint64_t seq = 0;  /**< upstream_seq；禁止 seq_local */
};

/**
 * @brief 有序放出结果（ByteTrack 前；track_dets 恒空）。
 */
struct OrderedFrameDetections {
    std::string stream_id;
    uint64_t seq = 0;
    uint64_t generation = 0;
    preprocess::LetterboxMeta letterbox;
    std::vector<postprocess::Detection> dets;       /**< 可 empty */
    std::vector<postprocess::Detection> track_dets; /**< 占位，恒空 */
    int worker_id = -1;
    int core_mask = -1;
    double captured_at = 0.0;        /**< D4：上游采集时刻透传 */
    double stream_time_sec = 0.0;
    bool has_stream_time = false;
};

/** gap_scan 诊断项。 */
struct GapSkipInfo {
    std::string stream_id;
    uint64_t generation = 0;
    uint64_t seq = 0;
    uint64_t expected = 0;
    uint64_t skip_frames = 0;
    uint64_t stale_cleared = 0;
    double waited_sec = 0.0;
    std::string reason;  /**< result_missing / min_diff_jump */
};

/**
 * @brief 单流单代次重排序状态（对齐 Python _StreamEpochState）。
 */
struct StreamEpochState {
    std::string stream_id;
    uint64_t generation = 0;

    std::deque<uint64_t> admitted;
    std::unordered_map<uint64_t, postprocess::FrameDetections> waiting;

    std::optional<uint64_t> last_released_seq;
    std::optional<uint64_t> last_admitted_seq;
    std::optional<double> head_wait_started_at;
    std::optional<uint64_t> head_wait_seq;

    uint64_t gap_skip_count = 0;
    uint64_t gap_jump_count = 0;
    uint64_t gap_skip_frames = 0;
    uint64_t gap_jump_frames = 0;
    uint64_t admit_count = 0;
    uint64_t ingest_count = 0;
    uint64_t released_count = 0;
    uint64_t admit_gap_count = 0;
    uint64_t admit_gap_frames = 0;
    uint64_t orphan_drop_count = 0;
    uint64_t dup_count = 0;
    uint64_t waiting_full_hit_count = 0;
    uint64_t waiting_full_evict_count = 0;
    uint64_t waiting_full_reject_count = 0;
    uint64_t epoch_reset_drop_count = 0;
    uint64_t forget_stream_drop_count = 0;
};

}  // namespace reorder
}  // namespace yolo

#endif  /* YOLO_REORDER_TYPES_H_ */

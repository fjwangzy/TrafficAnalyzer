/**
 * @file latest_tracker.h
 * @brief 每流最新 (generation, seq) 追踪：is_latest 计算 + 目录（D5）。
 *
 * 旧 ResultStore 的 32 条历史与 get_latest/list_latest 已随 D5 删除；
 * 本类只保留 is_latest 计算所需的最小状态（publish 单线程写、控制面读）。
 */

#ifndef YOLO_COMM_LATEST_TRACKER_H_
#define YOLO_COMM_LATEST_TRACKER_H_

#include <cstdint>
#include <mutex>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include "../reorder/types.h"

namespace yolo {
namespace comm {

class LatestTracker {
public:
    /**
     * @brief 登记一帧并返回它是否为该流当前最新（is_latest）。
     *
     * 单 publish 线程按到达序调用；重排保证 seq 单调，重复 / 回退帧
     * 返回 false（不回退水位）。
     */
    bool put(const reorder::OrderedFrameDetections& frame);

    void forget_stream(const std::string& stream_id);
    void forget_all();

    size_t stream_count() const;
    std::vector<std::string> known_streams() const;
    uint64_t put_count() const;

private:
    struct Latest {
        uint64_t generation = 0;
        uint64_t seq = 0;
    };

    mutable std::mutex mu_;
    std::unordered_map<std::string, Latest> streams_;
    uint64_t put_count_ = 0;
};

}  // namespace comm
}  // namespace yolo

#endif  /* YOLO_COMM_LATEST_TRACKER_H_ */

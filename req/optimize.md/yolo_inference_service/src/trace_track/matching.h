/**
 * @file matching.h
 * @brief IoU 代价、fuse_score、Hungarian + linear_assignment。
 */

#ifndef YOLO_TRACE_TRACK_MATCHING_H_
#define YOLO_TRACE_TRACK_MATCHING_H_

#include <utility>
#include <vector>

#include <xtensor/xarray.hpp>

#include "strack.h"

namespace yolo {
namespace trace_track {

/** MxN IoU 矩阵（空输入返回 zeros）。 */
xt::xarray<float> ious(const xt::xarray<float>& atlbrs,
                       const xt::xarray<float>& btlbrs);

/** cost = 1 - IoU；atracks/btracks 为 STrack 列表。 */
xt::xarray<float> iou_distance(const std::vector<STrackPtr>& atracks,
                               const std::vector<STrackPtr>& btracks);

xt::xarray<float> fuse_score(const xt::xarray<float>& cost_matrix,
                             const std::vector<STrackPtr>& detections);

struct AssignmentResult {
    std::vector<std::pair<int, int>> matches;
    std::vector<int> unmatched_a;
    std::vector<int> unmatched_b;
};

/**
 * @brief Hungarian + 阈值过滤（对齐 Python linear_assignment）。
 *
 * 超 thresh 代价先屏蔽为大值再求解，再过滤 cost > thresh 的匹配。
 */
AssignmentResult linear_assignment(const xt::xarray<float>& cost_matrix,
                                   float thresh);

}  // namespace trace_track
}  // namespace yolo

#endif  /* YOLO_TRACE_TRACK_MATCHING_H_ */

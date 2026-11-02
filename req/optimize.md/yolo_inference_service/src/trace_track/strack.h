/**
 * @file strack.h
 * @brief STrack / TrackState / 轨迹集合工具。
 */

#ifndef YOLO_TRACE_TRACK_STRACK_H_
#define YOLO_TRACE_TRACK_STRACK_H_

#include <array>
#include <memory>
#include <vector>

#include "kalman_filter.h"

#include <xtensor/xbuilder.hpp>

namespace yolo {
namespace trace_track {

enum class TrackState : int {
    New = 0,
    Tracked = 1,
    Lost = 2,
    Removed = 3,
};

class STrack {
public:
    static KalmanFilter shared_kalman;

    STrack(const std::array<float, 4>& tlwh, float score, int cls_id = -1);

    void predict();
    static void multi_predict(std::vector<std::shared_ptr<STrack>>& stracks);

    void activate(KalmanFilter* kalman_filter, int frame_id, int track_id);
    void re_activate(const STrack& new_track, int frame_id, bool new_id = false,
                     int track_id = 0);
    void update(const STrack& new_track, int frame_id);

    void mark_lost() { state = TrackState::Lost; }
    void mark_removed() { state = TrackState::Removed; }

    std::array<float, 4> tlwh() const;
    std::array<float, 4> tlbr() const;

    static std::array<float, 4> tlwh_to_xywh(const std::array<float, 4>& tlwh);
    static std::array<float, 4> tlbr_to_tlwh(const std::array<float, 4>& tlbr);
    static std::array<float, 4> tlwh_to_tlbr(const std::array<float, 4>& tlwh);

    int track_id = 0;
    bool is_activated = false;
    TrackState state = TrackState::New;
    float score = 0.f;
    int start_frame = 0;
    int frame_id = 0;
    int tracklet_len = 0;
    int cls_id = -1;

    int end_frame() const { return frame_id; }

private:
    std::array<float, 4> _tlwh{};
    KalmanFilter* kalman_filter_ = nullptr;
    bool has_mean_ = false;
    KalmanMean mean_ = xt::zeros<float>({8});
    KalmanCov covariance_ = xt::zeros<float>({8, 8});
};

using STrackPtr = std::shared_ptr<STrack>;

std::vector<STrackPtr> joint_stracks(const std::vector<STrackPtr>& a,
                                     const std::vector<STrackPtr>& b);
std::vector<STrackPtr> sub_stracks(const std::vector<STrackPtr>& a,
                                   const std::vector<STrackPtr>& b);
std::pair<std::vector<STrackPtr>, std::vector<STrackPtr>>
remove_duplicate_stracks(const std::vector<STrackPtr>& a,
                         const std::vector<STrackPtr>& b);

}  // namespace trace_track
}  // namespace yolo

#endif  /* YOLO_TRACE_TRACK_STRACK_H_ */

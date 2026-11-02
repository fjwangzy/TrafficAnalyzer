/**
 * @file strack.cpp
 * @brief STrack 与轨迹集合工具。
 */

#include "strack.h"

#include "matching.h"

#include <unordered_map>
#include <unordered_set>

#include <xtensor/xbuilder.hpp>

namespace yolo {
namespace trace_track {

KalmanFilter STrack::shared_kalman;

STrack::STrack(const std::array<float, 4>& tlwh, float score, int cls_id)
    : score(score), cls_id(cls_id), _tlwh(tlwh) {}

void STrack::predict() {
    if (!has_mean_ || kalman_filter_ == nullptr) return;
    KalmanMean mean_state = mean_;
    if (state != TrackState::Tracked) {
        // 丢失期间不外推尺寸（宽/高速度置零），只按位置速度外推。
        mean_state(6) = 0.f;
        mean_state(7) = 0.f;
    }
    auto out = kalman_filter_->predict(mean_state, covariance_);
    mean_ = out.first;
    covariance_ = out.second;
}

void STrack::multi_predict(std::vector<STrackPtr>& stracks) {
    if (stracks.empty()) return;
    const auto n = stracks.size();
    xt::xarray<float> means = xt::zeros<float>({n, static_cast<std::size_t>(8)});
    xt::xarray<float> covs =
        xt::zeros<float>({n, static_cast<std::size_t>(8), static_cast<std::size_t>(8)});
    for (std::size_t i = 0; i < n; ++i) {
        auto& st = *stracks[i];
        if (!st.has_mean_) continue;
        for (int j = 0; j < 8; ++j) means(i, j) = st.mean_(j);
        if (st.state != TrackState::Tracked) {
            // 丢失期间不外推尺寸（宽/高速度置零），只按位置速度外推。
            means(i, 6) = 0.f;
            means(i, 7) = 0.f;
        }
        for (int r = 0; r < 8; ++r)
            for (int c = 0; c < 8; ++c) covs(i, r, c) = st.covariance_(r, c);
    }
    shared_kalman.multi_predict(means, covs);
    for (std::size_t i = 0; i < n; ++i) {
        auto& st = *stracks[i];
        if (!st.has_mean_) continue;
        for (int j = 0; j < 8; ++j) st.mean_(j) = means(i, j);
        for (int r = 0; r < 8; ++r)
            for (int c = 0; c < 8; ++c) st.covariance_(r, c) = covs(i, r, c);
    }
}

void STrack::activate(KalmanFilter* kalman_filter, int frame_id, int track_id) {
    kalman_filter_ = kalman_filter;
    this->track_id = track_id;
    auto xywh = tlwh_to_xywh(_tlwh);
    KalmanMeas m = xt::zeros<float>({4});
    for (int i = 0; i < 4; ++i) m(i) = xywh[static_cast<std::size_t>(i)];
    auto init = kalman_filter_->initiate(m);
    mean_ = init.first;
    covariance_ = init.second;
    has_mean_ = true;
    tracklet_len = 0;
    state = TrackState::Tracked;
    if (frame_id == 1) {
        is_activated = true;
    }
    this->frame_id = frame_id;
    start_frame = frame_id;
}

void STrack::re_activate(const STrack& new_track, int frame_id, bool new_id,
                         int track_id) {
    auto xywh = tlwh_to_xywh(new_track.tlwh());
    KalmanMeas m = xt::zeros<float>({4});
    for (int i = 0; i < 4; ++i) m(i) = xywh[static_cast<std::size_t>(i)];
    auto out = kalman_filter_->update(mean_, covariance_, m);
    mean_ = out.first;
    covariance_ = out.second;
    tracklet_len = 0;
    state = TrackState::Tracked;
    is_activated = true;
    this->frame_id = frame_id;
    if (new_id) this->track_id = track_id;
    score = new_track.score;
    cls_id = new_track.cls_id;
}

void STrack::update(const STrack& new_track, int frame_id) {
    this->frame_id = frame_id;
    tracklet_len += 1;
    auto xywh = tlwh_to_xywh(new_track.tlwh());
    KalmanMeas m = xt::zeros<float>({4});
    for (int i = 0; i < 4; ++i) m(i) = xywh[static_cast<std::size_t>(i)];
    auto out = kalman_filter_->update(mean_, covariance_, m);
    mean_ = out.first;
    covariance_ = out.second;
    state = TrackState::Tracked;
    is_activated = true;
    score = new_track.score;
    cls_id = new_track.cls_id;
}

std::array<float, 4> STrack::tlwh() const {
    if (!has_mean_) return _tlwh;
    // 状态即 (cx, cy, w, h)：中心换回左上角即可，无宽高比反算。
    std::array<float, 4> ret = {mean_(0), mean_(1), mean_(2), mean_(3)};
    ret[0] -= ret[2] / 2.f;
    ret[1] -= ret[3] / 2.f;
    return ret;
}

std::array<float, 4> STrack::tlbr() const {
    return tlwh_to_tlbr(tlwh());
}

std::array<float, 4> STrack::tlwh_to_xywh(const std::array<float, 4>& tlwh) {
    std::array<float, 4> ret = tlwh;
    ret[0] += ret[2] / 2.f;
    ret[1] += ret[3] / 2.f;
    return ret;
}

std::array<float, 4> STrack::tlbr_to_tlwh(const std::array<float, 4>& tlbr) {
    std::array<float, 4> ret = tlbr;
    ret[2] -= ret[0];
    ret[3] -= ret[1];
    return ret;
}

std::array<float, 4> STrack::tlwh_to_tlbr(const std::array<float, 4>& tlwh) {
    std::array<float, 4> ret = tlwh;
    ret[2] += ret[0];
    ret[3] += ret[1];
    return ret;
}

std::vector<STrackPtr> joint_stracks(const std::vector<STrackPtr>& a,
                                     const std::vector<STrackPtr>& b) {
    std::unordered_map<int, int> exists;
    std::vector<STrackPtr> res;
    for (const auto& t : a) {
        exists[t->track_id] = 1;
        res.push_back(t);
    }
    for (const auto& t : b) {
        if (!exists.count(t->track_id)) {
            exists[t->track_id] = 1;
            res.push_back(t);
        }
    }
    return res;
}

std::vector<STrackPtr> sub_stracks(const std::vector<STrackPtr>& a,
                                   const std::vector<STrackPtr>& b) {
    std::unordered_map<int, STrackPtr> stracks;
    for (const auto& t : a) stracks[t->track_id] = t;
    for (const auto& t : b) stracks.erase(t->track_id);
    std::vector<STrackPtr> out;
    out.reserve(stracks.size());
    for (auto& kv : stracks) out.push_back(kv.second);
    return out;
}

std::pair<std::vector<STrackPtr>, std::vector<STrackPtr>>
remove_duplicate_stracks(const std::vector<STrackPtr>& a,
                         const std::vector<STrackPtr>& b) {
    auto pdist = iou_distance(a, b);
    std::unordered_set<int> dupa;
    std::unordered_set<int> dupb;
    if (pdist.size() > 0) {
        for (std::size_t p = 0; p < pdist.shape(0); ++p) {
            for (std::size_t q = 0; q < pdist.shape(1); ++q) {
                if (pdist(p, q) < 0.15f) {
                    int timep = a[p]->frame_id - a[p]->start_frame;
                    int timeq = b[q]->frame_id - b[q]->start_frame;
                    if (timep > timeq) {
                        dupb.insert(static_cast<int>(q));
                    } else {
                        dupa.insert(static_cast<int>(p));
                    }
                }
            }
        }
    }
    std::vector<STrackPtr> resa;
    std::vector<STrackPtr> resb;
    for (std::size_t i = 0; i < a.size(); ++i) {
        if (!dupa.count(static_cast<int>(i))) resa.push_back(a[i]);
    }
    for (std::size_t i = 0; i < b.size(); ++i) {
        if (!dupb.count(static_cast<int>(i))) resb.push_back(b[i]);
    }
    return {resa, resb};
}

}  // namespace trace_track
}  // namespace yolo

/**
 * @file byte_tracker.cpp
 * @brief ByteTracker::update 两轮关联 + 未确认 + 新建 + Lost 超时。
 */

#include "byte_tracker.h"

#include "matching.h"

#include <array>
#include <memory>

namespace yolo {
namespace trace_track {

ByteTracker::ByteTracker(ByteTrackerArgs args) : args_(std::move(args)) {
    det_thresh_ = args_.track_thresh + 0.1f;
    buffer_size_ =
        static_cast<int>(args_.frame_rate / 30.0 * args_.track_buffer);
    max_time_lost_ = buffer_size_;
}

int ByteTracker::next_track_id() {
    ++track_id_counter_;
    return track_id_counter_;
}

std::vector<STrackPtr> ByteTracker::update(
    const std::vector<DetRow>& detections) {
    ++frame_id_;
    std::vector<STrackPtr> activated_stracks;
    std::vector<STrackPtr> refind_stracks;
    std::vector<STrackPtr> lost_stracks;
    std::vector<STrackPtr> removed_stracks;

    std::vector<STrackPtr> detections_list;
    std::vector<STrackPtr> detections_second;

    for (const auto& d : detections) {
        if (d.score > args_.track_thresh) {
            std::array<float, 4> tlbr = {d.x1, d.y1, d.x2, d.y2};
            detections_list.push_back(std::make_shared<STrack>(
                STrack::tlbr_to_tlwh(tlbr), d.score, d.class_id));
        } else if (d.score > args_.low_score && d.score < args_.track_thresh) {
            std::array<float, 4> tlbr = {d.x1, d.y1, d.x2, d.y2};
            detections_second.push_back(std::make_shared<STrack>(
                STrack::tlbr_to_tlwh(tlbr), d.score, d.class_id));
        }
    }

    std::vector<STrackPtr> unconfirmed;
    std::vector<STrackPtr> tracked_stracks;
    for (auto& track : tracked_stracks_) {
        if (!track->is_activated) {
            unconfirmed.push_back(track);
        } else {
            tracked_stracks.push_back(track);
        }
    }

    // Step 2: 第一轮
    auto strack_pool = joint_stracks(tracked_stracks, lost_stracks_);
    STrack::multi_predict(strack_pool);
    auto dists = iou_distance(strack_pool, detections_list);
    if (!args_.mot20) {
        dists = fuse_score(dists, detections_list);
    }
    auto assign1 = linear_assignment(dists, args_.match_thresh);
    for (const auto& m : assign1.matches) {
        auto& track = strack_pool[static_cast<std::size_t>(m.first)];
        auto& det = detections_list[static_cast<std::size_t>(m.second)];
        if (track->state == TrackState::Tracked) {
            track->update(*det, frame_id_);
            activated_stracks.push_back(track);
        } else {
            track->re_activate(*det, frame_id_, false);
            refind_stracks.push_back(track);
        }
    }

    // Step 3: 第二轮
    std::vector<STrackPtr> r_tracked_stracks;
    for (int i : assign1.unmatched_a) {
        if (strack_pool[static_cast<std::size_t>(i)]->state ==
            TrackState::Tracked) {
            r_tracked_stracks.push_back(strack_pool[static_cast<std::size_t>(i)]);
        }
    }
    auto dists2 = iou_distance(r_tracked_stracks, detections_second);
    auto assign2 = linear_assignment(dists2, args_.second_match_thresh);
    for (const auto& m : assign2.matches) {
        auto& track = r_tracked_stracks[static_cast<std::size_t>(m.first)];
        auto& det = detections_second[static_cast<std::size_t>(m.second)];
        if (track->state == TrackState::Tracked) {
            track->update(*det, frame_id_);
            activated_stracks.push_back(track);
        } else {
            track->re_activate(*det, frame_id_, false);
            refind_stracks.push_back(track);
        }
    }
    for (int it : assign2.unmatched_a) {
        auto& track = r_tracked_stracks[static_cast<std::size_t>(it)];
        if (track->state != TrackState::Lost) {
            track->mark_lost();
            lost_stracks.push_back(track);
        }
    }

    // 未确认
    std::vector<STrackPtr> detections_remain;
    for (int i : assign1.unmatched_b) {
        detections_remain.push_back(
            detections_list[static_cast<std::size_t>(i)]);
    }
    auto dists3 = iou_distance(unconfirmed, detections_remain);
    if (!args_.mot20) {
        dists3 = fuse_score(dists3, detections_remain);
    }
    auto assign3 =
        linear_assignment(dists3, args_.unconfirmed_match_thresh);
    for (const auto& m : assign3.matches) {
        unconfirmed[static_cast<std::size_t>(m.first)]->update(
            *detections_remain[static_cast<std::size_t>(m.second)], frame_id_);
        activated_stracks.push_back(
            unconfirmed[static_cast<std::size_t>(m.first)]);
    }
    for (int it : assign3.unmatched_a) {
        auto& track = unconfirmed[static_cast<std::size_t>(it)];
        track->mark_removed();
        removed_stracks.push_back(track);
    }

    // Step 4: 新建
    for (int inew : assign3.unmatched_b) {
        auto& track = detections_remain[static_cast<std::size_t>(inew)];
        if (track->score < det_thresh_) continue;
        track->activate(&kalman_filter_, frame_id_, next_track_id());
        activated_stracks.push_back(track);
    }

    // Step 5: Lost 超时
    for (auto& track : lost_stracks_) {
        if (frame_id_ - track->end_frame() > max_time_lost_) {
            track->mark_removed();
            removed_stracks.push_back(track);
        }
    }

    std::vector<STrackPtr> tracked_kept;
    for (auto& t : tracked_stracks_) {
        if (t->state == TrackState::Tracked) tracked_kept.push_back(t);
    }
    tracked_stracks_ = joint_stracks(tracked_kept, activated_stracks);
    tracked_stracks_ = joint_stracks(tracked_stracks_, refind_stracks);
    lost_stracks_ = sub_stracks(lost_stracks_, tracked_stracks_);
    lost_stracks_.insert(lost_stracks_.end(), lost_stracks.begin(),
                         lost_stracks.end());
    // 先对「旧」removed 做 sub，再 extend 本帧 removed（对齐 Python）
    lost_stracks_ = sub_stracks(lost_stracks_, removed_stracks_);
    removed_stracks_.insert(removed_stracks_.end(), removed_stracks.begin(),
                            removed_stracks.end());
    if (static_cast<int>(removed_stracks_.size()) > kRemovedBuffer) {
        removed_stracks_ = std::vector<STrackPtr>(
            removed_stracks_.end() - kRemovedBuffer, removed_stracks_.end());
    }
    auto dedup = remove_duplicate_stracks(tracked_stracks_, lost_stracks_);
    tracked_stracks_ = std::move(dedup.first);
    lost_stracks_ = std::move(dedup.second);

    std::vector<STrackPtr> output;
    for (auto& t : tracked_stracks_) {
        if (t->is_activated) output.push_back(t);
    }
    return output;
}

}  // namespace trace_track
}  // namespace yolo

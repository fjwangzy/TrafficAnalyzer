/**
 * @file tracker_hub.cpp
 * @brief StreamTrackerHub 装配与 generation / 空 boxed 语义。
 */

#include "tracker_hub.h"

#include <cmath>
#include <cstdio>

namespace yolo {
namespace trace_track {

postprocess::Detection copy_without_track_id(
    const postprocess::Detection& det) {
    postprocess::Detection out = det;
    out.track_id = -1;
    return out;
}

StreamTrackerHub::StreamTrackerHub(
    TrackingConfig config, std::unordered_map<int, std::string> class_names)
    : config_(std::move(config)), class_names_(std::move(class_names)) {}

ByteTrackerArgs StreamTrackerHub::make_args() const {
    ByteTrackerArgs a;
    a.track_thresh = config_.track_thresh;
    a.track_buffer = config_.track_buffer;
    a.match_thresh = config_.match_thresh;
    a.mot20 = config_.mot20;
    a.frame_rate = config_.frame_rate;
    a.low_score = config_.low_score;
    a.second_match_thresh = config_.second_match_thresh;
    a.unconfirmed_match_thresh = config_.unconfirmed_match_thresh;
    return a;
}

void StreamTrackerHub::enrich_class_names(
    std::vector<postprocess::Detection>& dets) const {
    for (auto& d : dets) {
        auto it = class_names_.find(d.class_id);
        if (it != class_names_.end()) {
            d.class_name = it->second;
        } else {
            d.class_name = "cls" + std::to_string(d.class_id);
        }
    }
}

void StreamTrackerHub::log_and_check_track_seq(const std::string& stream_id,
                                               uint64_t generation,
                                               uint64_t seq) {
    auto it = last_recv_frames_.find(stream_id);
    if (it == last_recv_frames_.end()) {
        std::fprintf(stderr,
                     "[ByteTrack] stream=%s seq=%llu gen=%llu (first)\n",
                     stream_id.c_str(),
                     static_cast<unsigned long long>(seq),
                     static_cast<unsigned long long>(generation));
    } else {
        const auto prev_gen = it->second.first;
        const auto prev_seq = it->second.second;
        if (prev_gen != generation) {
            std::fprintf(stderr,
                         "[ByteTrack] stream=%s seq=%llu gen=%llu "
                         "(gen change prev_gen=%llu prev_seq=%llu)\n",
                         stream_id.c_str(),
                         static_cast<unsigned long long>(seq),
                         static_cast<unsigned long long>(generation),
                         static_cast<unsigned long long>(prev_gen),
                         static_cast<unsigned long long>(prev_seq));
        } else if (seq > prev_seq + 1) {
            std::fprintf(stderr,
                         "[ByteTrack] stream=%s seq=%llu gen=%llu skip gap=%llu "
                         "(prev_seq=%llu)\n",
                         stream_id.c_str(),
                         static_cast<unsigned long long>(seq),
                         static_cast<unsigned long long>(generation),
                         static_cast<unsigned long long>(seq - prev_seq - 1),
                         static_cast<unsigned long long>(prev_seq));
        } else if (seq < prev_seq) {
            std::fprintf(stderr,
                         "[ByteTrack] stream=%s seq=%llu gen=%llu reorder "
                         "(prev_seq=%llu)\n",
                         stream_id.c_str(),
                         static_cast<unsigned long long>(seq),
                         static_cast<unsigned long long>(generation),
                         static_cast<unsigned long long>(prev_seq));
        }
    }
    last_recv_frames_[stream_id] = {generation, seq};
}

StreamTrackerHub::TrackerState& StreamTrackerHub::create_tracker(
    const std::string& stream_id, uint64_t generation) {
    TrackerState state;
    state.tracker = std::make_unique<ByteTracker>(make_args());
    state.generation = generation;
    state.last_tracked_seq = 0;
    auto [it, _] = trackers_.emplace(stream_id, std::move(state));
    return it->second;
}

void StreamTrackerHub::rebuild_tracker(const std::string& stream_id,
                                       uint64_t /*new_generation*/) {
    trackers_.erase(stream_id);
    ++epoch_reset_count_;
}

std::vector<postprocess::Detection> StreamTrackerHub::tracker_update(
    TrackerState& state, const std::vector<postprocess::Detection>& boxed) {
    if (!state.tracker) {
        std::vector<postprocess::Detection> out;
        out.reserve(boxed.size());
        for (const auto& d : boxed) out.push_back(copy_without_track_id(d));
        return out;
    }
    std::vector<DetRow> rows;
    rows.reserve(boxed.size());
    for (const auto& d : boxed) {
        DetRow r;
        r.x1 = static_cast<float>(d.x1);
        r.y1 = static_cast<float>(d.y1);
        r.x2 = static_cast<float>(d.x2);
        r.y2 = static_cast<float>(d.y2);
        r.score = d.score;
        r.class_id = d.class_id;
        rows.push_back(r);
    }
    auto online = state.tracker->update(rows);
    std::vector<postprocess::Detection> out;
    out.reserve(online.size());
    for (const auto& t : online) {
        auto tlbr = t->tlbr();
        postprocess::Detection d;
        d.x1 = static_cast<int>(tlbr[0]);
        d.y1 = static_cast<int>(tlbr[1]);
        d.x2 = static_cast<int>(tlbr[2]);
        d.y2 = static_cast<int>(tlbr[3]);
        d.score = t->score;
        d.class_id = t->cls_id;
        d.track_id = t->track_id;
        out.push_back(d);
    }
    return out;
}

std::vector<postprocess::Detection> StreamTrackerHub::apply_tracking(
    const std::string& stream_id, uint64_t generation, uint64_t seq,
    const std::vector<postprocess::Detection>& raw) {
    if (!config_.enabled) {
        std::vector<postprocess::Detection> out;
        out.reserve(raw.size());
        for (const auto& d : raw) out.push_back(copy_without_track_id(d));
        return out;
    }

    log_and_check_track_seq(stream_id, generation, seq);

    auto gen_it = generations_.find(stream_id);
    if (gen_it == generations_.end() || gen_it->second != generation) {
        rebuild_tracker(stream_id, generation);
        generations_[stream_id] = generation;
    }

    auto it = trackers_.find(stream_id);
    TrackerState* state = nullptr;
    if (it == trackers_.end()) {
        state = &create_tracker(stream_id, generation);
    } else {
        state = &it->second;
    }

    if (seq <= state->last_tracked_seq) {
        ++out_of_order_skip_;
        std::vector<postprocess::Detection> out;
        out.reserve(raw.size());
        for (const auto& d : raw) out.push_back(copy_without_track_id(d));
        return out;
    }

    std::vector<postprocess::Detection> boxed;
    for (const auto& d : raw) {
        // 退化框（零/负宽高）面积非正，IoU 关联无意义，直接过滤。
        if (d.x1 < d.x2 && d.y1 < d.y2) {
            boxed.push_back(d);
        }
    }

    if (boxed.empty()) {
        ++empty_boxed_count_;
        state->last_tracked_seq = seq;
        std::vector<postprocess::Detection> out;
        out.reserve(raw.size());
        for (const auto& d : raw) out.push_back(copy_without_track_id(d));
        return out;
    }

    auto tracked_list = tracker_update(*state, boxed);
    state->last_tracked_seq = seq;
    ++update_count_;
    return tracked_list;
}

reorder::OrderedFrameDetections StreamTrackerHub::assemble_frame(
    reorder::OrderedFrameDetections ordered) {
    std::vector<postprocess::Detection> raw;
    raw.reserve(ordered.dets.size());
    for (const auto& d : ordered.dets) {
        raw.push_back(copy_without_track_id(d));
    }

    auto tracked = apply_tracking(ordered.stream_id, ordered.generation,
                                  ordered.seq, raw);

    enrich_class_names(raw);
    enrich_class_names(tracked);

    ordered.dets = std::move(raw);
    ordered.track_dets = std::move(tracked);
    ++assemble_count_;
    return ordered;
}

void StreamTrackerHub::forget_stream(const std::string& stream_id) {
    trackers_.erase(stream_id);
    generations_.erase(stream_id);
    last_recv_frames_.erase(stream_id);
    ++forget_count_;
}

void StreamTrackerHub::forget_all() {
    trackers_.clear();
    generations_.clear();
    last_recv_frames_.clear();
}

TrackerHubStats StreamTrackerHub::stats() const {
    TrackerHubStats s;
    s.tracking_enabled = config_.enabled;
    s.tracker_stream_count = trackers_.size();
    s.track_assemble_count = assemble_count_;
    s.track_update_count = update_count_;
    s.track_empty_boxed_count = empty_boxed_count_;
    s.track_out_of_order_skip = out_of_order_skip_;
    s.track_epoch_reset_count = epoch_reset_count_;
    s.track_forget_count = forget_count_;
    return s;
}

}  // namespace trace_track
}  // namespace yolo

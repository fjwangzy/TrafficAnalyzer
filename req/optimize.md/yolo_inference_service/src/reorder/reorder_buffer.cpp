/**
 * @file reorder_buffer.cpp
 * @brief ReorderBuffer：admit / ingest / flush / gap_scan（对齐 Python buffer.py）。
 */

#include "reorder_buffer.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>

namespace yolo {
namespace reorder {
namespace {

double default_clock() {
    using clock = std::chrono::steady_clock;
    const auto now = clock::now().time_since_epoch();
    return std::chrono::duration<double>(now).count();
}

}  // namespace

ReorderBuffer::ReorderBuffer(double gap_timeout_sec, int max_waiting_per_stream,
                             Clock clock)
    : gap_timeout_(gap_timeout_sec > 0.0 ? gap_timeout_sec : 1.0)
    , max_waiting_(max_waiting_per_stream > 0 ? max_waiting_per_stream : 1)
    , clock_(clock ? std::move(clock) : Clock(default_clock)) {}

bool ReorderBuffer::admitted_contains(const StreamEpochState& state,
                                      uint64_t seq) {
    return std::find(state.admitted.begin(), state.admitted.end(), seq) !=
           state.admitted.end();
}

void ReorderBuffer::admitted_remove(StreamEpochState& state, uint64_t seq) {
    auto it = std::find(state.admitted.begin(), state.admitted.end(), seq);
    if (it != state.admitted.end()) {
        state.admitted.erase(it);
    }
}

OrderedFrameDetections ReorderBuffer::to_ordered(
    postprocess::FrameDetections&& unordered) {
    OrderedFrameDetections out;
    out.stream_id = std::move(unordered.stream_id);
    out.seq = unordered.seq;
    out.generation = unordered.generation;
    out.letterbox = std::move(unordered.letterbox);
    out.captured_at = unordered.captured_at;
    out.stream_time_sec = unordered.stream_time_sec;
    out.has_stream_time = unordered.has_stream_time;
    out.dets = std::move(unordered.dets);
    out.track_dets.clear();
    out.worker_id = unordered.worker_id;
    out.core_mask = unordered.core_mask;
    return out;
}

std::optional<uint64_t> ReorderBuffer::expected_seq(
    const StreamEpochState& state) const {
    if (state.last_released_seq.has_value()) {
        return *state.last_released_seq + 1;
    }
    if (!state.admitted.empty()) {
        return state.admitted.front();
    }
    return std::nullopt;
}

int ReorderBuffer::drop_epochs(const std::string& stream_id,
                               std::optional<uint64_t> keep_generation) {
    std::vector<StateKey> old_keys;
    for (const auto& kv : states_) {
        if (kv.first.first != stream_id) continue;
        if (keep_generation.has_value() &&
            kv.first.second == *keep_generation) {
            continue;
        }
        old_keys.push_back(kv.first);
    }
    int total = 0;
    for (const auto& key : old_keys) {
        auto it = states_.find(key);
        if (it == states_.end()) continue;
        const int dropped = static_cast<int>(it->second.waiting.size() +
                                             it->second.admitted.size());
        total += dropped;
        epoch_reset_drop_count_ += static_cast<uint64_t>(dropped);
        std::fprintf(stderr,
                     "[reorder] epoch reset stream=%s old_gen=%llu dropped=%d\n",
                     stream_id.c_str(),
                     static_cast<unsigned long long>(key.second), dropped);
        states_.erase(it);
    }
    return total;
}

StreamEpochState& ReorderBuffer::ensure_epoch(const std::string& stream_id,
                                              uint64_t generation) {
    const StateKey key{stream_id, generation};
    auto it = states_.find(key);
    auto active_it = active_generation_.find(stream_id);

    if (it != states_.end() && active_it != active_generation_.end() &&
        active_it->second == generation) {
        return it->second;
    }

    if (active_it != active_generation_.end() &&
        active_it->second != generation) {
        drop_epochs(stream_id, generation);
    }

    it = states_.find(key);
    if (it == states_.end()) {
        StreamEpochState st;
        st.stream_id = stream_id;
        st.generation = generation;
        it = states_.emplace(key, std::move(st)).first;
    }
    active_generation_[stream_id] = generation;
    return it->second;
}

void ReorderBuffer::refresh_wait_timer(StreamEpochState& state) {
    auto expected = expected_seq(state);
    if (!expected.has_value() ||
        state.waiting.find(*expected) != state.waiting.end()) {
        state.head_wait_started_at = std::nullopt;
        state.head_wait_seq = std::nullopt;
        return;
    }
    if (!state.head_wait_seq.has_value() || *state.head_wait_seq != *expected) {
        state.head_wait_seq = *expected;
        state.head_wait_started_at = clock_();
    }
}

bool ReorderBuffer::accept_waiting(StreamEpochState& state, uint64_t seq,
                                   postprocess::FrameDetections result) {
    if (static_cast<int>(state.waiting.size()) < max_waiting_) {
        state.waiting[seq] = std::move(result);
        if (static_cast<int>(state.waiting.size()) == max_waiting_) {
            ++state.waiting_full_hit_count;
        }
        return true;
    }

    ++state.waiting_full_hit_count;
    auto expected = expected_seq(state);
    if (expected.has_value() && seq == *expected) {
        std::optional<uint64_t> oldest;
        for (const auto& kv : state.waiting) {
            if (kv.first == *expected) continue;
            if (!oldest.has_value() || kv.first < *oldest) {
                oldest = kv.first;
            }
        }
        if (oldest.has_value()) {
            state.waiting.erase(*oldest);
            ++state.waiting_full_evict_count;
            state.waiting[seq] = std::move(result);
            std::fprintf(stderr,
                         "[reorder] waiting full evict stream=%s seq=%llu "
                         "evicted=%llu cap=%d\n",
                         state.stream_id.c_str(),
                         static_cast<unsigned long long>(seq),
                         static_cast<unsigned long long>(*oldest), max_waiting_);
            return true;
        }
    }

    ++state.waiting_full_reject_count;
    std::fprintf(stderr,
                 "[reorder] waiting full reject stream=%s seq=%llu cap=%d\n",
                 state.stream_id.c_str(),
                 static_cast<unsigned long long>(seq), max_waiting_);
    return false;
}

std::vector<OrderedFrameDetections> ReorderBuffer::flush(StreamEpochState& state) {
    std::vector<OrderedFrameDetections> released;
    while (true) {
        auto expected = expected_seq(state);
        if (!expected.has_value()) break;
        if (state.waiting.find(*expected) == state.waiting.end()) break;
        if (!admitted_contains(state, *expected)) break;

        admitted_remove(state, *expected);
        auto unordered = std::move(state.waiting[*expected]);
        state.waiting.erase(*expected);
        state.last_released_seq = *expected;
        ++state.released_count;
        released.push_back(to_ordered(std::move(unordered)));
    }
    refresh_wait_timer(state);
    return released;
}

void ReorderBuffer::admit(const std::string& stream_id, uint64_t generation,
                          uint64_t seq) {
    auto& state = ensure_epoch(stream_id, generation);

    if (state.last_released_seq.has_value() &&
        seq <= *state.last_released_seq) {
        return;
    }
    if (admitted_contains(state, seq)) return;

    if (state.last_admitted_seq.has_value() &&
        seq > *state.last_admitted_seq + 1) {
        const uint64_t gap = seq - *state.last_admitted_seq - 1;
        ++state.admit_gap_count;
        state.admit_gap_frames += gap;
        std::fprintf(stderr,
                     "[reorder] admit seq gap stream=%s gen=%llu prev=%llu "
                     "seq=%llu gap_frames=%llu\n",
                     stream_id.c_str(),
                     static_cast<unsigned long long>(generation),
                     static_cast<unsigned long long>(*state.last_admitted_seq),
                     static_cast<unsigned long long>(seq),
                     static_cast<unsigned long long>(gap));
    }

    state.admitted.push_back(seq);
    std::sort(state.admitted.begin(), state.admitted.end());
    ++state.admit_count;
    state.last_admitted_seq = seq;
    refresh_wait_timer(state);
}

std::vector<OrderedFrameDetections> ReorderBuffer::ingest(
    postprocess::FrameDetections result) {
    const std::string stream_id = result.stream_id;
    const uint64_t generation = result.generation;
    const uint64_t seq = result.seq;

    auto& state = ensure_epoch(stream_id, generation);

    if (state.last_released_seq.has_value() &&
        seq <= *state.last_released_seq) {
        ++state.dup_count;
        return {};
    }

    if (!admitted_contains(state, seq)) {
        ++state.orphan_drop_count;
        std::fprintf(stderr,
                     "[reorder] orphan stream=%s gen=%llu seq=%llu "
                     "reason=not_admitted\n",
                     stream_id.c_str(),
                     static_cast<unsigned long long>(generation),
                     static_cast<unsigned long long>(seq));
        return {};
    }

    if (state.waiting.find(seq) != state.waiting.end()) {
        ++state.dup_count;
        return {};
    }

    if (!accept_waiting(state, seq, std::move(result))) {
        return {};
    }

    ++state.ingest_count;
    return flush(state);
}

std::pair<std::vector<GapSkipInfo>, std::vector<OrderedFrameDetections>>
ReorderBuffer::gap_scan() {
    std::vector<GapSkipInfo> skipped;
    std::vector<OrderedFrameDetections> released;
    const double now = clock_();

    // 拷贝 key 列表，避免遍历中修改 map
    std::vector<StateKey> keys;
    keys.reserve(states_.size());
    for (const auto& kv : states_) keys.push_back(kv.first);

    for (const auto& key : keys) {
        auto it = states_.find(key);
        if (it == states_.end()) continue;
        auto& state = it->second;

        if (state.admitted.empty() && state.waiting.empty()) continue;

        auto expected = expected_seq(state);
        if (!expected.has_value()) continue;

        if (state.waiting.find(*expected) != state.waiting.end() &&
            admitted_contains(state, *expected)) {
            auto more = flush(state);
            released.insert(released.end(), more.begin(), more.end());
            continue;
        }

        if (!state.head_wait_started_at.has_value() ||
            !state.head_wait_seq.has_value() ||
            *state.head_wait_seq != *expected) {
            state.head_wait_seq = *expected;
            state.head_wait_started_at = now;
            continue;
        }

        const double waited = now - *state.head_wait_started_at;
        if (waited < gap_timeout_) continue;

        std::vector<uint64_t> candidates;
        for (const auto& kv : state.waiting) {
            if (!admitted_contains(state, kv.first)) continue;
            if (state.last_released_seq.has_value() &&
                kv.first <= *state.last_released_seq) {
                continue;
            }
            candidates.push_back(kv.first);
        }

        if (candidates.empty()) {
            if (admitted_contains(state, *expected)) {
                admitted_remove(state, *expected);
            }
            state.last_released_seq = *expected;
            ++state.gap_skip_count;
            ++state.gap_skip_frames;

            GapSkipInfo info;
            info.stream_id = state.stream_id;
            info.generation = state.generation;
            info.seq = *expected;
            info.expected = *expected;
            info.skip_frames = 1;
            info.waited_sec = waited;
            info.reason = "result_missing";
            skipped.push_back(info);

            std::fprintf(stderr,
                         "[reorder] gap skip stream=%s seq=%llu waited=%.2fs "
                         "reason=result_missing\n",
                         state.stream_id.c_str(),
                         static_cast<unsigned long long>(*expected), waited);

            auto more = flush(state);
            released.insert(released.end(), more.begin(), more.end());
            continue;
        }

        uint64_t best = candidates[0];
        for (uint64_t s : candidates) {
            const uint64_t d_best =
                best > *expected ? best - *expected : *expected - best;
            const uint64_t d_s =
                s > *expected ? s - *expected : *expected - s;
            if (d_s < d_best || (d_s == d_best && s < best)) {
                best = s;
            }
        }

        auto unordered = std::move(state.waiting[best]);
        state.waiting.erase(best);
        if (admitted_contains(state, best)) {
            admitted_remove(state, best);
        }

        std::vector<uint64_t> stale_admitted;
        for (uint64_t s : state.admitted) {
            if (s < best) stale_admitted.push_back(s);
        }
        for (uint64_t s : stale_admitted) {
            admitted_remove(state, s);
            ++state.gap_skip_count;
            ++state.gap_skip_frames;
        }

        std::vector<uint64_t> stale_waiting;
        for (const auto& kv : state.waiting) {
            if (kv.first < best) stale_waiting.push_back(kv.first);
        }
        for (uint64_t s : stale_waiting) {
            state.waiting.erase(s);
            ++state.gap_skip_count;
            ++state.gap_skip_frames;
        }

        const uint64_t jump_frames =
            best > *expected ? best - *expected : 0;
        state.gap_jump_frames += jump_frames;
        state.last_released_seq = best;
        ++state.released_count;
        ++state.gap_jump_count;
        released.push_back(to_ordered(std::move(unordered)));

        GapSkipInfo info;
        info.stream_id = state.stream_id;
        info.generation = state.generation;
        info.seq = best;
        info.expected = *expected;
        info.skip_frames = jump_frames;
        info.stale_cleared = stale_admitted.size() + stale_waiting.size();
        info.waited_sec = waited;
        info.reason = "min_diff_jump";
        skipped.push_back(info);

        std::fprintf(stderr,
                     "[reorder] gap jump stream=%s expected=%llu released=%llu "
                     "skip_frames=%llu waited=%.2fs\n",
                     state.stream_id.c_str(),
                     static_cast<unsigned long long>(*expected),
                     static_cast<unsigned long long>(best),
                     static_cast<unsigned long long>(jump_frames), waited);

        auto more = flush(state);
        released.insert(released.end(), more.begin(), more.end());
    }

    return {skipped, released};
}

int ReorderBuffer::forget_stream(const std::string& stream_id) {
    const int total = drop_epochs(stream_id, std::nullopt);
    active_generation_.erase(stream_id);
    forget_stream_drop_count_ += static_cast<uint64_t>(total);
    if (total > 0) {
        std::fprintf(stderr,
                     "[reorder] stream forgotten stream=%s dropped=%d\n",
                     stream_id.c_str(), total);
    }
    return total;
}

std::string ReorderBuffer::stats_summary() const {
    uint64_t admit = 0, ingest = 0, released = 0, orphan = 0, dup = 0;
    uint64_t gap_skip = 0, gap_jump = 0;
    for (const auto& kv : states_) {
        const auto& s = kv.second;
        admit += s.admit_count;
        ingest += s.ingest_count;
        released += s.released_count;
        orphan += s.orphan_drop_count;
        dup += s.dup_count;
        gap_skip += s.gap_skip_count;
        gap_jump += s.gap_jump_count;
    }
    char buf[256];
    std::snprintf(buf, sizeof(buf),
                  "streams=%zu admit=%llu ingest=%llu released=%llu "
                  "orphan=%llu dup=%llu gap_skip=%llu gap_jump=%llu "
                  "epoch_drop=%llu forget_drop=%llu",
                  states_.size(),
                  static_cast<unsigned long long>(admit),
                  static_cast<unsigned long long>(ingest),
                  static_cast<unsigned long long>(released),
                  static_cast<unsigned long long>(orphan),
                  static_cast<unsigned long long>(dup),
                  static_cast<unsigned long long>(gap_skip),
                  static_cast<unsigned long long>(gap_jump),
                  static_cast<unsigned long long>(epoch_reset_drop_count_),
                  static_cast<unsigned long long>(forget_stream_drop_count_));
    return std::string(buf);
}

}  // namespace reorder
}  // namespace yolo

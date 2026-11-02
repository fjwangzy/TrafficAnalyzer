/**
 * @file upstream_ingress.cpp
 * @brief UpstreamIngress 实现：周期 list_streams + 三平面自动重连。
 */

#include "ingress.h"

#include "control_client.h"
#include "data_plane_client.h"
#include "update_subscriber.h"

#include <cctype>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <utility>

namespace yolo {
namespace preprocess {
namespace {

bool contains_ci(const std::string& hay, const char* needle) {
    if (!needle || !*needle) return false;
    const std::string h = hay;
    const std::string n = needle;
    auto lower = [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    };
    std::string hl;
    std::string nl;
    hl.resize(h.size());
    nl.resize(n.size());
    for (size_t i = 0; i < h.size(); ++i) hl[i] = lower(static_cast<unsigned char>(h[i]));
    for (size_t i = 0; i < n.size(); ++i) nl[i] = lower(static_cast<unsigned char>(n[i]));
    return hl.find(nl) != std::string::npos;
}

}  // namespace

UpstreamIngress::UpstreamIngress(PreprocessServiceConfig cfg)
    : cfg_(std::move(cfg)) {}

UpstreamIngress::~UpstreamIngress() {
    stop();
}

void UpstreamIngress::set_on_stream_removed(StreamRemovedCallback cb) {
    std::lock_guard<std::mutex> lk(cb_mu_);
    on_stream_removed_ = std::move(cb);
}

void UpstreamIngress::start() {
    connect_upstream();
    refresh_descriptors();
    note_ingress_ok();
    last_refresh_ = SteadyClock::now();

    std::fprintf(stderr,
                 "[UpstreamIngress] start update=%s data=%s streams=%zu "
                 "refresh=%.1fs stale=%.1fs backoff=%.1fs\n",
                 bound_update_endpoint_.c_str(), bound_data_endpoint_.c_str(),
                 descriptors_.size(),
                 cfg_.ingress.stream_refresh_interval_sec,
                 cfg_.ingress.stale_reconnect_sec,
                 cfg_.ingress.reconnect_backoff_sec);

    stop_.store(false, std::memory_order_release);
    thr_ = std::thread([this] { ingress_loop(); });
}

void UpstreamIngress::stop() {
    stop_.store(true, std::memory_order_release);
    q_cv_.notify_all();
    if (thr_.joinable()) thr_.join();
    drain_queues();
    try {
        flush_releases();
    } catch (const std::exception& e) {
        // 随后的 socket close 会让服务端统一释放该连接剩余 held 槽。
        std::fprintf(stderr,
                     "[UpstreamIngress] final release flush failed: %s\n",
                     e.what());
    }
    disconnect_upstream();
}

void UpstreamIngress::connect_upstream() {
    control_ = std::make_unique<drn::c_client::ControlClient>(
        cfg_.upstream.control_endpoint);

    auto health = control_->health();
    if (health.data_plane.find("dma_buf") == std::string::npos) {
        throw std::runtime_error(
            "upstream health.data_plane does not declare dma_buf: " +
            health.data_plane);
    }

    std::string update_ep = cfg_.upstream.update_endpoint;
    if (update_ep.empty()) update_ep = health.update_endpoint;
    if (update_ep.empty()) {
        throw std::runtime_error("no update_endpoint");
    }

    std::string data_ep = cfg_.upstream.data_endpoint;
    if (data_ep.empty()) data_ep = health.data_endpoint;
    if (data_ep.empty()) {
        throw std::runtime_error(
            "no data_endpoint (upstream DataPlane not ready)");
    }

    bound_update_endpoint_ = update_ep;
    bound_data_endpoint_ = data_ep;

    // 订全部；过滤在 enqueue 侧用 subscribe 列表
    sub_ = std::make_unique<drn::c_client::FrameUpdateSubscriber>(update_ep);
    data_ = std::make_unique<drn::c_client::DataPlaneClient>(data_ep);
}

void UpstreamIngress::disconnect_upstream() {
    sub_.reset();
    data_.reset();
    control_.reset();
    bound_update_endpoint_.clear();
    bound_data_endpoint_.clear();
}

bool UpstreamIngress::reconnect(const char* reason) {
    std::fprintf(stderr, "[UpstreamIngress] reconnect reason=%s\n", reason);
    // 先销毁排队帧并在旧连接上释放其槽引用，再断开数据面。
    // 若旧连接已坏，socket close 仍会让服务端统一释放该连接 held 槽。
    drain_queues();
    try {
        flush_releases();
    } catch (const std::exception& e) {
        std::fprintf(stderr,
                     "[UpstreamIngress] release before reconnect failed: %s\n",
                     e.what());
    }
    disconnect_upstream();
    {
        // 旧连接对应的 release 不得带到新连接；服务端断连时已清理 held。
        std::lock_guard<std::mutex> lk(release_mu_);
        pending_releases_.clear();
    }
    try {
        connect_upstream();
        auto diff = refresh_descriptors();
        apply_directory_diff(diff);
        note_ingress_ok();
        last_refresh_ = SteadyClock::now();
        reconnect_count_.fetch_add(1, std::memory_order_relaxed);
        std::fprintf(stderr,
                     "[UpstreamIngress] reconnect ok update=%s data=%s "
                     "streams=%zu count=%llu\n",
                     bound_update_endpoint_.c_str(),
                     bound_data_endpoint_.c_str(), descriptors_.size(),
                     static_cast<unsigned long long>(
                         reconnect_count_.load(std::memory_order_relaxed)));
        return true;
    } catch (const std::exception& e) {
        std::fprintf(stderr, "[UpstreamIngress] reconnect failed: %s\n",
                     e.what());
        disconnect_upstream();
        return false;
    }
}

UpstreamIngress::DirectoryDiff UpstreamIngress::refresh_descriptors() {
    DirectoryDiff diff;
    if (!control_) return diff;

    auto list = control_->list_streams();
    std::unordered_map<std::string, StreamCache> next;
    next.reserve(list.size());

    for (const auto& d : list) {
        StreamCache c;
        c.generation = d.generation;
        c.is_enabled = d.is_enabled;
        c.fault = d.fault;
        c.capacity = d.capacity;
        c.latest_seq = d.latest_seq;
        next[d.stream_id] = c;
        if (d.is_enabled && !d.fault && d.latest_seq >= 1) {
            diff.any_live_publisher = true;
        }
    }

    std::vector<std::string> removed;
    std::vector<std::string> generation_changed;
    std::vector<std::string> added;

    {
        std::lock_guard<std::mutex> lk(desc_mu_);
        for (const auto& kv : descriptors_) {
            if (next.find(kv.first) == next.end()) {
                removed.push_back(kv.first);
            }
        }
        for (const auto& kv : next) {
            auto it = descriptors_.find(kv.first);
            if (it == descriptors_.end()) {
                added.push_back(kv.first);
            } else if (it->second.generation != kv.second.generation) {
                generation_changed.push_back(kv.first);
            }
        }
        descriptors_ = std::move(next);
    }

    diff.added = std::move(added);
    diff.removed = std::move(removed);
    diff.generation_changed = std::move(generation_changed);
    return diff;
}

void UpstreamIngress::apply_directory_diff(const DirectoryDiff& diff) {
    for (const auto& sid : diff.added) {
        std::fprintf(stderr, "[UpstreamIngress] stream added: id=%s\n",
                     sid.c_str());
    }
    for (const auto& sid : diff.generation_changed) {
        std::fprintf(stderr,
                     "[UpstreamIngress] stream generation changed: id=%s\n",
                     sid.c_str());
        purge_stream_queue(sid);
    }
    for (const auto& sid : diff.removed) {
        std::fprintf(stderr, "[UpstreamIngress] stream removed: id=%s\n",
                     sid.c_str());
        purge_stream_queue(sid);
        StreamRemovedCallback cb;
        {
            std::lock_guard<std::mutex> lk(cb_mu_);
            cb = on_stream_removed_;
        }
        if (cb) {
            try {
                cb(sid);
            } catch (const std::exception& e) {
                std::fprintf(stderr,
                             "[UpstreamIngress] on_stream_removed failed "
                             "stream_id=%s: %s\n",
                             sid.c_str(), e.what());
            }
        }
    }
}

void UpstreamIngress::drain_queues() {
    std::lock_guard<std::mutex> lk(q_mu_);
    for (auto& kv : queues_) {
        kv.second.clear();  // UpstreamFrame 析构 close fd
    }
    queues_.clear();
}

void UpstreamIngress::purge_stream_queue(const std::string& stream_id) {
    std::lock_guard<std::mutex> lk(q_mu_);
    auto it = queues_.find(stream_id);
    if (it == queues_.end()) return;
    it->second.clear();
    queues_.erase(it);
}

void UpstreamIngress::enqueue(UpstreamFrame&& frame) {
    const std::string sid = frame.stream_id;
    std::lock_guard<std::mutex> lk(q_mu_);
    auto& q = queues_[sid];
    while (static_cast<int>(q.size()) >= cfg_.ingress.max_queue_per_stream) {
        q.pop_front();  // 丢最旧
    }
    q.push_back(std::move(frame));
    q_cv_.notify_one();
}

void UpstreamIngress::enqueue_release(std::string stream_id, uint64_t seq) {
    if (stream_id.empty() || seq == 0) return;
    std::lock_guard<std::mutex> lk(release_mu_);
    pending_releases_.emplace_back(std::move(stream_id), seq);
}

void UpstreamIngress::flush_releases() {
    if (!data_) return;

    std::deque<std::pair<std::string, uint64_t>> pending;
    {
        std::lock_guard<std::mutex> lk(release_mu_);
        pending.swap(pending_releases_);
    }
    for (const auto& item : pending) {
        data_->release_frame(item.first, item.second);
    }
}

std::optional<UpstreamFrame> UpstreamIngress::pop(int timeout_ms) {
    std::unique_lock<std::mutex> lk(q_mu_);
    auto has_any = [this] {
        for (auto& kv : queues_) {
            if (!kv.second.empty()) return true;
        }
        return false;
    };

    if (timeout_ms < 0) timeout_ms = 0;
    if (!has_any()) {
        if (timeout_ms == 0) return std::nullopt;
        q_cv_.wait_for(lk, std::chrono::milliseconds(timeout_ms),
                       [&] { return stop_.load() || has_any(); });
    }
    if (!has_any()) return std::nullopt;

    for (auto& kv : queues_) {
        if (kv.second.empty()) continue;
        UpstreamFrame f = std::move(kv.second.front());
        kv.second.pop_front();
        return f;
    }
    return std::nullopt;
}

void UpstreamIngress::sleep_interruptible(double sec) {
    if (sec <= 0.0) return;
    const auto deadline =
        SteadyClock::now() +
        std::chrono::duration_cast<SteadyClock::duration>(
            std::chrono::duration<double>(sec));
    while (!stop_.load(std::memory_order_acquire) &&
           SteadyClock::now() < deadline) {
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
}

bool UpstreamIngress::is_transport_error(const std::exception& e) const {
    const std::string msg = e.what();
    // 不含 EAGAIN / timed out：避免读帧超时被当成断线反复重连
    return contains_ci(msg, "Broken pipe") ||
           contains_ci(msg, "peer closed") ||
           contains_ci(msg, "not connected") ||
           contains_ci(msg, "Connection reset") ||
           contains_ci(msg, "Connection refused") ||
           contains_ci(msg, "No such file") ||
           contains_ci(msg, "connect ");
}

void UpstreamIngress::note_ingress_ok() {
    last_ingress_ok_ = SteadyClock::now();
}

void UpstreamIngress::ingress_loop() {
    while (!stop_.load(std::memory_order_acquire)) {
        if (!sub_ || !data_ || !control_) {
            if (!reconnect("missing_handles")) {
                sleep_interruptible(cfg_.ingress.reconnect_backoff_sec);
            }
            continue;
        }

        try {
            // RGA 线程完成 DMA-BUF 读取后把 release 投递回来；所有数据面
            // 收发仍集中在 ingress 单线程，避免同一 SOCK_SEQPACKET 并发读写。
            flush_releases();
        } catch (const std::exception& e) {
            std::fprintf(stderr,
                         "[UpstreamIngress] release upstream slot failed: %s\n",
                         e.what());
            if (!reconnect("release_slot")) {
                sleep_interruptible(cfg_.ingress.reconnect_backoff_sec);
            }
            continue;
        }

        std::optional<drn::c_client::FrameUpdate> ev;
        try {
            ev = sub_->receive(cfg_.ingress.update_timeout_ms);
        } catch (const std::exception& e) {
            std::fprintf(stderr,
                         "[UpstreamIngress] update plane error: %s\n",
                         e.what());
            if (is_transport_error(e)) {
                if (!reconnect("update_plane")) {
                    sleep_interruptible(cfg_.ingress.reconnect_backoff_sec);
                }
            }
            continue;
        }

        if (ev) {
            if (ev->seq < 1 || ev->stream_id.empty()) {
                // fall through to refresh/stale checks
            } else {
                bool wanted = true;
                if (!cfg_.upstream.subscribe_stream_ids.empty()) {
                    wanted = false;
                    for (const auto& id : cfg_.upstream.subscribe_stream_ids) {
                        if (id == ev->stream_id) {
                            wanted = true;
                            break;
                        }
                    }
                }

                if (wanted) {
                    bool drop = false;
                    bool need_refresh = false;
                    {
                        std::lock_guard<std::mutex> lk(desc_mu_);
                        auto it = descriptors_.find(ev->stream_id);
                        if (it != descriptors_.end()) {
                            if (!it->second.is_enabled || it->second.fault) {
                                drop = true;
                            } else if (it->second.generation != 0 &&
                                       ev->generation != it->second.generation) {
                                need_refresh = true;
                            }
                        }
                    }

                    if (!drop) {
                        if (need_refresh) {
                            try {
                                auto diff = refresh_descriptors();
                                apply_directory_diff(diff);
                            } catch (const std::exception& e) {
                                std::fprintf(stderr,
                                             "[UpstreamIngress] refresh on "
                                             "generation mismatch failed: %s\n",
                                             e.what());
                                if (is_transport_error(e)) {
                                    if (!reconnect("refresh_gen_mismatch")) {
                                        sleep_interruptible(
                                            cfg_.ingress.reconnect_backoff_sec);
                                    }
                                    continue;
                                }
                            }
                            std::lock_guard<std::mutex> lk(desc_mu_);
                            auto it = descriptors_.find(ev->stream_id);
                            if (it == descriptors_.end() ||
                                it->second.generation != ev->generation) {
                                gen_mismatch_.fetch_add(
                                    1, std::memory_order_relaxed);
                                drop = true;
                            }
                        }
                    }

                    if (!drop && data_) {
                        drn::c_client::FrameHandle handle;
                        try {
                            handle = data_->read_frame(ev->stream_id, ev->seq);
                            if (handle.empty || !handle.has_fd()) {
                                if (cfg_.ingress.fallback_read_latest) {
                                    handle = data_->read_latest(ev->stream_id);
                                }
                            }
                        } catch (const drn::c_client::ControlError& e) {
                            std::fprintf(stderr,
                                         "[UpstreamIngress] data plane "
                                         "ControlError %s: %s\n",
                                         e.code().c_str(), e.what());
                            data_miss_.fetch_add(1, std::memory_order_relaxed);
                            if (e.code() == "stream_gone") {
                                purge_stream_queue(ev->stream_id);
                            }
                            handle = {};
                        } catch (const std::exception& e) {
                            std::fprintf(stderr,
                                         "[UpstreamIngress] data plane error: "
                                         "%s\n",
                                         e.what());
                            data_miss_.fetch_add(1, std::memory_order_relaxed);
                            if (is_transport_error(e)) {
                                if (!reconnect("data_plane")) {
                                    sleep_interruptible(
                                        cfg_.ingress.reconnect_backoff_sec);
                                }
                                continue;
                            }
                            handle = {};
                        }

                        if (!handle.empty && handle.has_fd()) {
                            if (handle.generation != 0 &&
                                handle.generation != ev->generation) {
                                const uint64_t stale_seq = handle.seq;
                                handle.close();
                                enqueue_release(ev->stream_id, stale_seq);
                                gen_mismatch_.fetch_add(
                                    1, std::memory_order_relaxed);
                                try {
                                    auto diff = refresh_descriptors();
                                    apply_directory_diff(diff);
                                } catch (...) {
                                }
                            } else {
                                UpstreamFrame frame;
                                frame.stream_id = ev->stream_id;
                                frame.seq =
                                    handle.seq != 0 ? handle.seq : ev->seq;
                                frame.generation = handle.generation != 0
                                                       ? handle.generation
                                                       : ev->generation;
                                frame.buffer_index = ev->buffer_index;
                                frame.width =
                                    ev->width > 0 ? ev->width : handle.width;
                                frame.height =
                                    ev->height > 0 ? ev->height : handle.height;
                                frame.stride_y = ev->stride_y > 0
                                                     ? ev->stride_y
                                                     : handle.stride_y;
                                frame.stride_uv = ev->stride_uv > 0
                                                      ? ev->stride_uv
                                                      : handle.stride_uv;
                                frame.captured_at = ev->captured_at;
                                if (ev->stream_time_sec.has_value()) {
                                    frame.stream_time_sec =
                                        *ev->stream_time_sec;
                                    frame.has_stream_time = true;
                                }
                                frame.nv12_fd = handle.dma_fd;
                                const std::string release_sid = frame.stream_id;
                                const uint64_t release_seq = frame.seq;
                                frame.release_upstream =
                                    [this, release_sid, release_seq] {
                                        enqueue_release(release_sid,
                                                        release_seq);
                                    };
                                handle.dma_fd = -1;

                                enqueue(std::move(frame));
                                note_ingress_ok();
                            }
                        } else {
                            data_miss_.fetch_add(1, std::memory_order_relaxed);
                        }
                    }
                }
            }
        }

        const auto now = SteadyClock::now();
        const double refresh_sec = cfg_.ingress.stream_refresh_interval_sec;
        const auto refresh_due =
            std::chrono::duration<double>(now - last_refresh_).count() >=
            refresh_sec;
        if (!refresh_due) continue;

        last_refresh_ = now;
        DirectoryDiff diff;
        try {
            // 先 health：控制面不通或端点变更 → 整链重连
            auto health = control_->health();
            std::string want_update = cfg_.upstream.update_endpoint;
            if (want_update.empty()) want_update = health.update_endpoint;
            std::string want_data = cfg_.upstream.data_endpoint;
            if (want_data.empty()) want_data = health.data_endpoint;
            if ((!want_update.empty() &&
                 want_update != bound_update_endpoint_) ||
                (!want_data.empty() && want_data != bound_data_endpoint_)) {
                if (!reconnect("endpoint_changed")) {
                    sleep_interruptible(cfg_.ingress.reconnect_backoff_sec);
                }
                continue;
            }

            diff = refresh_descriptors();
            apply_directory_diff(diff);
        } catch (const std::exception& e) {
            std::fprintf(stderr,
                         "[UpstreamIngress] stream directory refresh failed: "
                         "%s\n",
                         e.what());
            if (!reconnect("refresh_failed")) {
                sleep_interruptible(cfg_.ingress.reconnect_backoff_sec);
            }
            continue;
        }

        if (cfg_.ingress.stale_reconnect_sec > 0.0 &&
            diff.any_live_publisher) {
            const double idle =
                std::chrono::duration<double>(now - last_ingress_ok_).count();
            if (idle >= cfg_.ingress.stale_reconnect_sec) {
                std::fprintf(stderr,
                             "[UpstreamIngress] stale ingress idle=%.1fs "
                             "(live upstream frames) → reconnect\n",
                             idle);
                if (!reconnect("stale_no_frames")) {
                    sleep_interruptible(cfg_.ingress.reconnect_backoff_sec);
                }
            }
        }
    }
}

}  // namespace preprocess
}  // namespace yolo

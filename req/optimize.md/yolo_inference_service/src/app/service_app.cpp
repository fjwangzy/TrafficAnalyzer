/**
 * @file service_app.cpp
 * @brief ServiceApp 实现：全流水线装配（plans §6）与生命周期。
 *
 * 装配顺序（依赖正序）：
 *   engine(查 input_geometry) -> LocalRgbRing -> RGA -> EngineIngest
 *   -> backpressure -> postprocess×N -> reorder/passthrough -> track
 *   -> LatestTracker -> UpdatePublisher(bind->set_sndhwm) -> PublishThread
 *   -> ControlPlaneServer(bind) -> engine.start()+核对 -> ingress.start
 *   -> RGA 线程 -> serve_loop。
 * 关停顺序（依赖逆序，先关队列再 join，防 push_blocking 死锁）：
 *   ingress -> control -> 三条流水线队列 -> publish -> track -> reorder
 *   -> postprocess -> engine.stop -> RGA -> ring -> update_pub。
 */

#include "service_app.h"

#include <csignal>
#include <cstdio>
#include <fcntl.h>
#include <sys/file.h>
#include <thread>
#include <unistd.h>
#include <utility>

#include <zmq.hpp>

#ifdef HAS_SYSTEMD
#include <systemd/sd-daemon.h>
#endif

#include "control_plane_server.h"
#include "engine.h"
#include "i_inference_engine.h"
#include "rknn_backend.h"
#include "update_publisher.h"

#include "../backpressure/sample_backoff.h"
#include "../comm/control_ops.h"
#include "../comm/latest_tracker.h"
#include "../comm/publish_thread.h"
#include "../infer/engine_ingest.h"
#include "../postprocess/detection_queue.h"
#include "../postprocess/postprocess_worker.h"
#include "../preprocess/local_rgb_ring.h"
#include "../preprocess/rga3_preprocess.h"
#include "../reorder/admit_queue.h"
#include "../reorder/ordered_queue.h"
#include "../reorder/reorder_thread.h"
#include "../trace_track/track_thread.h"
#include "../trace_track/tracked_queue.h"
#include "../upstream/ingress.h"
#include "logger.h"

namespace {

constexpr char kTag[] = "app";

std::atomic<bool>* g_stop_target = nullptr;

void signal_handler(int /*sig*/) {
    if (g_stop_target) g_stop_target->store(true, std::memory_order_release);
}

std::string now_str() {
    char ts[32];
    const time_t t = ::time(nullptr);
    struct tm tmv;
    ::localtime_r(&t, &tmv);
    ::strftime(ts, sizeof(ts), "%Y-%m-%d %H:%M:%S", &tmv);
    return ts;
}

}  // namespace

struct ServiceApp::Impl {
    zmq::context_t zmq_ctx{1};

    std::unique_ptr<yolo::inference::SampleBackoff> backoff;
    std::unique_ptr<drn::core::rknn::IInferenceEngine> engine;

    std::unique_ptr<yolo::preprocess::LocalRgbRing> ring;
    std::unique_ptr<yolo::preprocess::Rga3Preprocess> rga;
    std::unique_ptr<yolo::preprocess::UpstreamIngress> ingress;
    std::unique_ptr<yolo::infer::EngineIngest> engine_ingest;

    std::unique_ptr<yolo::reorder::AdmitQueue> admit_queue;
    std::unique_ptr<yolo::postprocess::DetectionResultQueue> det_queue;
    std::unique_ptr<yolo::reorder::OrderedResultQueue> ordered_queue;
    std::unique_ptr<yolo::trace_track::TrackedResultQueue> tracked_queue;

    std::vector<std::unique_ptr<yolo::postprocess::PostprocessWorker>> posts;
    std::unique_ptr<yolo::reorder::ReorderThread> reorder_thread;
    std::unique_ptr<yolo::reorder::PassthroughThread> passthrough;
    std::unique_ptr<yolo::trace_track::TrackThread> track_thread;

    std::unique_ptr<yolo::comm::LatestTracker> latest;
    std::unique_ptr<drn::core::tp::UpdatePublisher> update_pub;
    std::unique_ptr<yolo::comm::PublishThread> publish_thread;
    std::unique_ptr<yolo::comm::ControlOps> control_ops;
    std::unique_ptr<drn::core::tp::ControlPlaneServer> control;

    std::atomic<bool> rga_stop{false};
    std::thread rga_thr;

    ~Impl() { join_rga(); }

    void join_rga() {
        rga_stop.store(true, std::memory_order_release);
        if (rga_thr.joinable()) rga_thr.join();
    }

    void rga_loop(const yolo::app::ServiceConfig& cfg) {
        while (!rga_stop.load(std::memory_order_acquire)) {
            if (!ingress || !rga || !ring) break;
            auto frame = ingress->pop(100);
            if (!frame) continue;
            const double captured_at = frame->captured_at;
            const double stream_time_sec = frame->stream_time_sec;
            const bool has_stream_time = frame->has_stream_time;
            const bool ok = rga->process(std::move(*frame), *ring,
                                          cfg.pre.local_ring.drop_when_busy);
            if (ok && engine_ingest && ring) {
                engine_ingest->on_frame_published(ring->latest_seq(),
                                                  captured_at,
                                                  stream_time_sec,
                                                  has_stream_time);
            }
        }
    }
};

ServiceApp::ServiceApp() = default;

ServiceApp::~ServiceApp() {
    shutdown();
}

void ServiceApp::request_stop() {
    if (g_stop_target) g_stop_target->store(true, std::memory_order_release);
}

int ServiceApp::run(const std::string& config_path) {
    try {
        cfg_ = yolo::app::load_service_config(config_path);
    } catch (const std::exception& e) {
        std::fprintf(stderr, "[app] FATAL config: %s\n", e.what());
        return 2;
    }

    loggers_inited_ = yolo::app::init_logger(cfg_.log_path, cfg_.log_level);

    setup_signals();
    if (!setup_lock()) return 69;  // EX_UNAVAILABLE：systemd 不重启

    if (!assemble()) {
        shutdown();
        return 1;
    }

    LOG_INFO(kTag, "READY ctrl=%s update=%s model=%s",
             cfg_.transport.endpoint.c_str(),
             cfg_.transport.update_endpoint.c_str(),
             cfg_.infer.model_path.c_str());
#ifdef HAS_SYSTEMD
    sd_notify(0, "READY=1");  // Type=notify 单元就绪；裸跑时无 NOTIFY_SOCKET 静默无害
#endif

    serve_loop();
    shutdown();
    return 0;
}

void ServiceApp::setup_signals() {
    g_stop_target = &stop_;
    std::signal(SIGINT, signal_handler);
    std::signal(SIGTERM, signal_handler);
    std::signal(SIGPIPE, SIG_IGN);
}

bool ServiceApp::setup_lock() {
    lock_fd_ = ::open(cfg_.lock_file.c_str(), O_CREAT | O_RDWR, 0644);
    if (lock_fd_ < 0) {
        LOG_ERROR(kTag, "open lock_file %s failed: %s",
                  cfg_.lock_file.c_str(), std::strerror(errno));
        return false;
    }
    if (::flock(lock_fd_, LOCK_EX | LOCK_NB) != 0) {
        LOG_ERROR(kTag, "another instance holds %s — exit EX_UNAVAILABLE",
                  cfg_.lock_file.c_str());
        ::close(lock_fd_);
        lock_fd_ = -1;
        return false;
    }
    return true;
}

bool ServiceApp::assemble() {
    impl_ = std::make_unique<Impl>();
    Impl& p = *impl_;

    // ---- 推理引擎（几何权威来源）----
    drn::core::rknn::EngineConfig ecfg;
    ecfg.model_path = cfg_.infer.model_path;
    ecfg.core_masks = cfg_.infer.core_masks;
    ecfg.instances_per_core = cfg_.infer.instances_per_core;
    ecfg.job_queue_capacity = cfg_.infer.job_queue_capacity;
    ecfg.output_queue_capacity = cfg_.infer.output_queue_capacity;
    ecfg.dmabuf_zero_copy = cfg_.infer.dmabuf_zero_copy;
    p.engine = drn::core::rknn::make_rknn_engine(
        ecfg, [](drn::core::rknn::LogLevel lv, const std::string& msg) {
            switch (lv) {
                case drn::core::rknn::LogLevel::Debug:
                    LOG_DEBUG("infer", "%s", msg.c_str()); break;
                case drn::core::rknn::LogLevel::Warn:
                    LOG_WARN("infer", "%s", msg.c_str()); break;
                case drn::core::rknn::LogLevel::Error:
                    LOG_ERROR("infer", "%s", msg.c_str()); break;
                default:
                    LOG_INFO("infer", "%s", msg.c_str()); break;
            }
        });
    if (!p.engine || !p.engine->input_geometry().valid()) {
        LOG_ERROR(kTag, "engine init failed (model=%s) or invalid geometry",
                  cfg_.infer.model_path.c_str());
        return false;
    }
    const auto geo = p.engine->input_geometry();
    if (geo.width != cfg_.post.imgsz || geo.height != cfg_.post.imgsz) {
        LOG_WARN(kTag,
                 "postprocess.imgsz=%d != model input %dx%d (model wins)",
                 cfg_.post.imgsz, geo.width, geo.height);
    }

    // ---- 降抽样（背压写库，服务保留）----
    if (!cfg_.infer.stream_db_path.empty()) {
        p.backoff = std::make_unique<yolo::inference::SampleBackoff>(
            cfg_.infer.stream_db_path, cfg_.infer.sample_backoff_ms,
            cfg_.infer.sample_backoff_cooldown_ms);
    }

    // ---- 本地 RGB 环（几何 = input_geometry）----
    p.ring = std::make_unique<yolo::preprocess::LocalRgbRing>(
        cfg_.pre.local_ring.capacity, geo.width, geo.height, geo.channels);
    if (!p.ring->ok()) {
        LOG_ERROR(kTag, "LocalRgbRing init failed");
        return false;
    }
    p.rga = std::make_unique<yolo::preprocess::Rga3Preprocess>(geo.width);
    if (!p.rga->bind_ring(*p.ring)) {
        LOG_ERROR(kTag, "Rga3Preprocess bind ring failed");
        return false;
    }

    // ---- 队列 ----
    p.det_queue = std::make_unique<yolo::postprocess::DetectionResultQueue>(
        static_cast<size_t>(cfg_.post.detection_queue_capacity));
    p.ordered_queue = std::make_unique<yolo::reorder::OrderedResultQueue>(
        static_cast<size_t>(cfg_.reorder.ordered_queue_capacity));
    p.tracked_queue = std::make_unique<yolo::trace_track::TrackedResultQueue>(
        static_cast<size_t>(cfg_.tracking.tracked_queue_capacity));
    p.admit_queue =
        std::make_unique<yolo::reorder::AdmitQueue>(
            static_cast<size_t>(cfg_.reorder.admit_queue_capacity));

    // ---- 环 -> 引擎衔接 ----
    p.engine_ingest = std::make_unique<yolo::infer::EngineIngest>(
        *p.ring, *p.engine, p.admit_queue.get());
    p.engine->set_backpressure_handler(
        [this](drn::core::rknn::BackpressureKind kind) {
            if (stop_.load(std::memory_order_acquire)) return;  // 停机静默
            if (impl_ && impl_->backoff) {
                impl_->backoff->try_apply_backoff(
                    kind == drn::core::rknn::BackpressureKind::kJobQueueFull
                        ? "job_queue_full"
                        : "output_queue_block");
            }
        });

    // ---- 后处理 ×N（直接 pop_output，raw 队列由组件承担）----
    yolo::postprocess::DecodeConfig decode;
    decode.conf_thres = cfg_.post.conf_thres;
    decode.iou_thres = cfg_.post.iou_thres;
    decode.imgsz = cfg_.post.imgsz;
    decode.obj_classes = cfg_.post.obj_classes;
    for (int i = 0; i < cfg_.post.worker_count; ++i) {
        p.posts.push_back(
            std::make_unique<yolo::postprocess::PostprocessWorker>(
                i, *p.engine, *p.det_queue, decode));
    }

    // ---- 重排 / 直通 ----
    if (cfg_.reorder.enabled) {
        p.reorder_thread =
            std::make_unique<yolo::reorder::ReorderThread>(
                *p.admit_queue, *p.det_queue, *p.ordered_queue,
                cfg_.reorder, p.backoff.get());
    } else {
        p.passthrough = std::make_unique<yolo::reorder::PassthroughThread>(
            *p.det_queue, *p.ordered_queue, cfg_.reorder.poll_timeout_ms);
    }

    // ---- 追踪 ----
    p.track_thread = std::make_unique<yolo::trace_track::TrackThread>(
        *p.ordered_queue, *p.tracked_queue, cfg_.tracking, p.backoff.get());

    // ---- 更新面（先 bind 再 set_sndhwm：bind 内部先置默认 1000）----
    p.latest = std::make_unique<yolo::comm::LatestTracker>();
    p.update_pub = std::make_unique<drn::core::tp::UpdatePublisher>(
        p.zmq_ctx,
        [](drn::core::tp::LogLevel lv, const std::string& msg) {
            if (lv >= drn::core::tp::LogLevel::Warn) {
                LOG_WARN("comm", "%s", msg.c_str());
            } else {
                LOG_INFO("comm", "%s", msg.c_str());
            }
        });
    if (!p.update_pub->bind(cfg_.transport.update_endpoint)) {
        LOG_ERROR(kTag, "UpdatePublisher bind %s failed",
                  cfg_.transport.update_endpoint.c_str());
        return false;
    }
    p.update_pub->set_sndhwm(cfg_.publish.update_hwm);

    p.publish_thread = std::make_unique<yolo::comm::PublishThread>(
        *p.tracked_queue, *p.latest, *p.update_pub,
        cfg_.publish.poll_timeout_ms);

    // ---- 控制面（health / status）----
    yolo::comm::ExtraStatusFn extra = [this] {
        std::vector<std::pair<std::string, std::string>> out;
        if (!impl_) return out;
        Impl& q = *impl_;
        const auto es = q.engine->stats();
        auto put = [&out](const char* k, uint64_t v) {
            out.emplace_back(k, std::to_string(v));
        };
        put("engine_submit_ok", es.submit_ok);
        put("engine_submit_reject", es.submit_reject);
        put("engine_release_calls", es.release_calls);
        put("engine_bp_job_full", es.backpressure_job_full);
        put("engine_bp_output_block", es.backpressure_output_block);
        put("engine_workers_online",
            static_cast<uint64_t>(es.workers.size()));
        uint64_t infer_ok = 0, infer_fail = 0, us_ewma = 0, us_max = 0;
        for (const auto& w : es.workers) {
            infer_ok += w.infer_ok;
            infer_fail += w.infer_fail;
            us_ewma += w.infer_us_ewma;
            if (w.infer_us_max > us_max) us_max = w.infer_us_max;
        }
        put("engine_infer_ok", infer_ok);
        put("engine_infer_fail", infer_fail);
        put("engine_infer_us_ewma", us_ewma);
        put("engine_infer_us_max", us_max);
        out.emplace_back(
            "engine_input_path",
            es.input_path == drn::core::rknn::InputPath::kZeroCopy
                ? "zero_copy" : "mmap_convert");
        if (q.backoff) {
            put("backoff_applied", q.backoff->applied_count());
            put("backoff_skipped", q.backoff->skipped_count());
            put("backoff_fail", q.backoff->fail_count());
        }
        if (q.engine_ingest) {
            put("ingest_accepted", q.engine_ingest->accepted_count());
            put("ingest_rejected", q.engine_ingest->rejected_count());
            put("ingest_acquire_miss", q.engine_ingest->acquire_miss_count());
        }
        if (q.rga) put("pre_rga_fail", q.rga->fail_count());
        if (q.ingress) {
            put("ingress_miss", q.ingress->data_miss_count());
            put("ingress_reconnect", q.ingress->reconnect_count());
        }
        if (q.reorder_thread) {
            put("reorder_released", q.reorder_thread->released_count());
        }
        if (q.track_thread) {
            put("track_assembled", q.track_thread->assembled_count());
        }
        return out;
    };
    p.control_ops = std::make_unique<yolo::comm::ControlOps>(
        cfg_.transport.update_endpoint, *p.latest, p.publish_thread.get(),
        stop_, std::move(extra));
    p.control = std::make_unique<drn::core::tp::ControlPlaneServer>(
        p.zmq_ctx,
        [this](const drn::core::tp::ControlRequest& req) {
            return impl_->control_ops->handle(req);
        },
        [](drn::core::tp::LogLevel lv, const std::string& msg) {
            if (lv >= drn::core::tp::LogLevel::Warn) {
                LOG_WARN("comm", "%s", msg.c_str());
            } else {
                LOG_INFO("comm", "%s", msg.c_str());
            }
        });
    if (!p.control->bind(cfg_.transport.endpoint)) {
        LOG_ERROR(kTag, "ControlPlaneServer bind %s failed",
                  cfg_.transport.endpoint.c_str());
        return false;
    }
    p.control->set_sndtimeo(cfg_.transport.send_timeout_ms);

    // ---- 引擎启动 + 编排核对（先于 ingress，杜绝帧到而 worker 未起）----
    p.engine->start();
    const size_t want = cfg_.infer.core_masks.size() *
                        static_cast<size_t>(cfg_.infer.instances_per_core);
    const size_t got = p.engine->stats().workers.size();
    if (got != want) {
        LOG_ERROR(kTag, "engine workers online=%zu != expected=%zu", got,
                  want);
        return false;
    }

    // ---- 上游接入（连接失败不致命，退避重连）----
    p.ingress = std::make_unique<yolo::preprocess::UpstreamIngress>(cfg_.pre);
    p.ingress->set_on_stream_removed([this](const std::string& sid) {
        if (!impl_) return;
        if (impl_->reorder_thread) impl_->reorder_thread->forget_stream(sid);
        if (impl_->track_thread) impl_->track_thread->forget_stream(sid);
        if (impl_->publish_thread) impl_->publish_thread->forget_stream(sid);
    });
    try {
        p.ingress->start();
    } catch (const std::exception& e) {
        LOG_WARN(kTag, "upstream not reachable yet (%s) — keep retrying",
                 e.what());
    }

    // ---- 线程启动 ----
    for (auto& w : p.posts) w->start();
    if (p.reorder_thread) p.reorder_thread->start();
    if (p.passthrough) p.passthrough->start();
    p.track_thread->start();
    p.publish_thread->start();
    p.rga_thr = std::thread([this] { impl_->rga_loop(cfg_); });

    return true;
}

void ServiceApp::serve_loop() {
    Impl& p = *impl_;
    while (!stop_.load(std::memory_order_acquire)) {
        try {
            p.control->poll_once(cfg_.transport.recv_timeout_ms);
        } catch (const std::exception& e) {
            LOG_ERROR(kTag, "control poll error: %s", e.what());
        }
    }
    LOG_INFO(kTag, "stopping at %s", now_str().c_str());
}

void ServiceApp::shutdown() {
    if (!impl_) {
        if (lock_fd_ >= 0) {
            ::flock(lock_fd_, LOCK_UN);
            ::close(lock_fd_);
            lock_fd_ = -1;
        }
        return;
    }
    Impl& p = *impl_;

#ifdef HAS_SYSTEMD
    sd_notify(0, "STOPPING=1");
#endif

    // 1. 停上游（含 release 队列 flush，fd 全部归还）
    if (p.ingress) p.ingress->stop();
    // 2. 停控制面（linger=0 + unlink）
    if (p.control) p.control->close();
    // 3. 先关流水线队列（唤醒阻塞 push/pop，防 join 死锁）
    if (p.tracked_queue) p.tracked_queue->stop();
    if (p.ordered_queue) p.ordered_queue->stop();
    if (p.det_queue) p.det_queue->stop();
    // 4. 倒序 join
    if (p.publish_thread) p.publish_thread->stop();
    if (p.track_thread) p.track_thread->stop();
    if (p.reorder_thread) p.reorder_thread->stop();
    if (p.passthrough) p.passthrough->stop();
    for (auto& w : p.posts) w->stop();
    p.posts.clear();
    // 5. 引擎（组件自管队列关闭与 worker join；抽干只归还缓冲）
    if (p.engine) p.engine->stop();
    // 6. RGA 线程 + 环
    p.join_rga();
    if (p.rga) p.rga->unbind_ring();
    // 7. 更新面（linger=0 + unlink）
    if (p.update_pub) p.update_pub->close();

    // 退出统计（一条 INFO 汇总，替代旧版裸 stderr 多行）
    if (p.engine && p.publish_thread) {
        const auto es = p.engine->stats();
        const auto ps = p.publish_thread->stats();
        LOG_INFO(kTag,
                 "stopped: submit_ok=%llu submit_reject=%llu infer_ok/fail,"
                 " pub_ok=%llu pub_drop=%llu emit=%llu",
                 static_cast<unsigned long long>(es.submit_ok),
                 static_cast<unsigned long long>(es.submit_reject),
                 static_cast<unsigned long long>(ps.publish_ok),
                 static_cast<unsigned long long>(ps.publish_drop),
                 static_cast<unsigned long long>(ps.emit_count));
    }

    impl_.reset();
    if (lock_fd_ >= 0) {
        ::flock(lock_fd_, LOCK_UN);
        ::close(lock_fd_);
        lock_fd_ = -1;
    }
    g_stop_target = nullptr;
}

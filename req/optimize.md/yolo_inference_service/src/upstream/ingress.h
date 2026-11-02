/**
 * @file ingress.h
 * @brief 控制面发现 + 更新面 SUB + 数据面取 fd → UpstreamFrame 队列。
 *
 * 对齐 yolo_inference_service_new_new 的流目录刷新语义，并补齐上游进程
 * 重启后的三平面自动重连（ZMQ IPC 幽灵连接 / 数据面 Broken pipe）。
 */

#ifndef YOLO_PREPROCESS_UPSTREAM_INGRESS_H_
#define YOLO_PREPROCESS_UPSTREAM_INGRESS_H_

#include "../app/service_config.h"
#include "../preprocess/types.h"

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <deque>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

namespace drn {
namespace c_client {
class ControlClient;
class FrameUpdateSubscriber;
class DataPlaneClient;
}  // namespace c_client
}  // namespace drn

namespace yolo {
namespace preprocess {

/**
 * @brief Ingress：独立线程收 FrameUpdate，数据面取 NV12 fd，按流有界队列 latest-wins。
 */
class UpstreamIngress {
public:
    /** @brief 流下架回调：stream_id。 */
    using StreamRemovedCallback = std::function<void(const std::string& stream_id)>;

    explicit UpstreamIngress(PreprocessServiceConfig cfg);
    ~UpstreamIngress();

    UpstreamIngress(const UpstreamIngress&) = delete;
    UpstreamIngress& operator=(const UpstreamIngress&) = delete;

    /**
     * @brief health 校验 + 连接更新面/数据面 + 启动 ingress 线程。
     * @throws std::runtime_error 首次连接失败。
     */
    void start();

    /** @brief 停 SUB、排空队列并 close 未处理 fd。 */
    void stop();

    /**
     * @brief 注册流下架回调（可在 start 后设置；供 reorder/track/store forget）。
     */
    void set_on_stream_removed(StreamRemovedCallback cb);

    /**
     * @brief 阻塞取一帧。
     * @param timeout_ms  等待超时；0 = 非阻塞。
     */
    std::optional<UpstreamFrame> pop(int timeout_ms);

    uint64_t data_miss_count() const {
        return data_miss_.load(std::memory_order_relaxed);
    }
    uint64_t generation_mismatch_count() const {
        return gen_mismatch_.load(std::memory_order_relaxed);
    }
    uint64_t reconnect_count() const {
        return reconnect_count_.load(std::memory_order_relaxed);
    }

private:
    struct StreamCache {
        uint64_t generation = 0;
        bool is_enabled = true;
        bool fault = false;
        int capacity = 0;
        uint64_t latest_seq = 0;
    };

    struct DirectoryDiff {
        std::vector<std::string> added;
        std::vector<std::string> removed;
        std::vector<std::string> generation_changed;
        bool any_live_publisher = false;
    };

    using SteadyClock = std::chrono::steady_clock;

    void ingress_loop();
    void connect_upstream();
    void disconnect_upstream();
    bool reconnect(const char* reason);
    DirectoryDiff refresh_descriptors();
    void apply_directory_diff(const DirectoryDiff& diff);
    void enqueue(UpstreamFrame&& frame);
    void enqueue_release(std::string stream_id, uint64_t seq);
    void flush_releases();
    void drain_queues();
    void purge_stream_queue(const std::string& stream_id);
    void sleep_interruptible(double sec);
    bool is_transport_error(const std::exception& e) const;
    void note_ingress_ok();

    PreprocessServiceConfig cfg_;
    std::unique_ptr<drn::c_client::ControlClient> control_;
    std::unique_ptr<drn::c_client::FrameUpdateSubscriber> sub_;
    std::unique_ptr<drn::c_client::DataPlaneClient> data_;

    std::string bound_update_endpoint_;
    std::string bound_data_endpoint_;

    std::unordered_map<std::string, StreamCache> descriptors_;
    std::mutex desc_mu_;

    std::unordered_map<std::string, std::deque<UpstreamFrame>> queues_;
    std::mutex q_mu_;
    std::condition_variable q_cv_;

    std::deque<std::pair<std::string, uint64_t>> pending_releases_;
    std::mutex release_mu_;

    StreamRemovedCallback on_stream_removed_;
    std::mutex cb_mu_;

    std::atomic<bool> stop_{false};
    std::thread thr_;

    SteadyClock::time_point last_ingress_ok_{};
    SteadyClock::time_point last_refresh_{};

    std::atomic<uint64_t> data_miss_{0};
    std::atomic<uint64_t> gen_mismatch_{0};
    std::atomic<uint64_t> reconnect_count_{0};
};

}  // namespace preprocess
}  // namespace yolo

#endif  /* YOLO_PREPROCESS_UPSTREAM_INGRESS_H_ */

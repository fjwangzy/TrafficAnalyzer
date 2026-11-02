/**
 * @file service_config.h
 * @brief yolo_inference_service 单份配置 + 严格校验（D2）。
 *
 * 汇总旧 6 份阶段配置的键集（值域沿旧部署值），归一到
 * services_config.yaml 顶层键 yolo_inference_service；节点缺失 /
 * 端点非法 / enabled 开关非法均致命。
 */

#ifndef YOLO_APP_SERVICE_CONFIG_H_
#define YOLO_APP_SERVICE_CONFIG_H_

#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

namespace yolo {

namespace preprocess {  // upstream/ingress 使用的组合配置（沿旧类型名）
struct UpstreamConfig {
    std::string control_endpoint = "ipc:///tmp/drn-rtsp-receive.sock";
    std::string update_endpoint;   /**< 空 -> health 发现 */
    std::string data_endpoint;     /**< 空 -> health 发现 */
    std::vector<std::string> subscribe_stream_ids;  /**< 空 = 全部 */
};

struct IngressConfig {
    int max_queue_per_stream = 4;
    int update_timeout_ms = 200;
    bool fallback_read_latest = true;
    double stream_refresh_interval_sec = 5.0;
    double reconnect_backoff_sec = 1.0;
    double stale_reconnect_sec = 10.0;
};

struct LocalRingConfig {
    int capacity = 16;
    bool drop_when_busy = true;
};

struct PreprocessServiceConfig {
    UpstreamConfig upstream;
    IngressConfig ingress;
    LocalRingConfig local_ring;
    std::string log_level = "INFO";
    std::string log_path;
};
}  // namespace preprocess

namespace infer_cfg {
struct InferConfig {
    bool enabled = true;             /**< D3：仅接受 true */
    std::string model_path;
    std::vector<std::string> core_masks = {"0", "1", "2"};
    int instances_per_core = 3;
    int job_queue_capacity = 512;
    int output_queue_capacity = 512;
    bool dmabuf_zero_copy = true;
    std::string stream_db_path;
    int sample_backoff_ms = 25;
    int sample_backoff_cooldown_ms = 60000;
};
}  // namespace infer_cfg

namespace postprocess {
struct PostprocessConfig {
    bool enabled = true;             /**< D3：仅接受 true */
    float conf_thres = 0.4f;
    float iou_thres = 0.7f;
    int imgsz = 640;
    std::vector<int> obj_classes;
    int detection_queue_capacity = 512;
    int worker_count = 6;
};
}  // namespace postprocess

namespace reorder {
struct ReorderConfig {
    bool enabled = true;             /**< false = PassthroughThread 直通 */
    double gap_timeout_sec = 2.0;
    int max_waiting_per_stream = 64;
    int poll_timeout_ms = 50;
    int admit_queue_capacity = 512;
    int ordered_queue_capacity = 512;
    bool sample_backoff_on_ordered_block = true;
};
}  // namespace reorder

namespace trace_track {
struct TrackingConfig {
    bool enabled = true;
    int frame_rate = 8;
    float track_thresh = 0.5f;
    int track_buffer = 30;
    float match_thresh = 0.8f;
    float low_score = 0.1f;
    float second_match_thresh = 0.5f;
    float unconfirmed_match_thresh = 0.7f;
    bool mot20 = false;
    int tracked_queue_capacity = 512;
    int poll_timeout_ms = 50;
    bool sample_backoff_on_tracked_block = true;
    std::string names_path;
};
}  // namespace trace_track

namespace comm {
struct TransportConfig {
    std::string endpoint = "ipc:///tmp/drn-yolo-inference.sock";
    std::string update_endpoint =
        "ipc:///tmp/drn-yolo-inference-updates.sock";
    int recv_timeout_ms = 100;
    int send_timeout_ms = 100;
};

struct PublishConfig {
    int poll_timeout_ms = 50;
    int update_hwm = 1024;
};
}  // namespace comm

namespace app {

struct ServiceConfig {
    std::string log_level = "INFO";
    std::string log_path;
    std::string lock_file = "/tmp/drn-yolo-inference.lock";

    preprocess::PreprocessServiceConfig pre;
    infer_cfg::InferConfig infer;
    postprocess::PostprocessConfig post;
    reorder::ReorderConfig reorder;
    trace_track::TrackingConfig tracking;
    comm::TransportConfig transport;
    comm::PublishConfig publish;
};

/**
 * @brief 加载并严格校验配置。
 * @throws std::runtime_error 文件不可读 / 节点缺失 / 键类型非法 /
 *         端点约束不满足 / D3 开关非法 / core_masks 为空。
 */
ServiceConfig load_service_config(const std::string& path);

/** Ultralytics names YAML -> id->name；失败返回空。 */
std::unordered_map<int, std::string> load_class_names(
    const std::string& names_path);

}  // namespace app
}  // namespace yolo

#endif  /* YOLO_APP_SERVICE_CONFIG_H_ */

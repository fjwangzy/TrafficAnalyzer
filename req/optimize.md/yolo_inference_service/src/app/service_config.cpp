/**
 * @file service_config.cpp
 * @brief 配置加载实现：YAML -> ServiceConfig + 严格校验。
 */

#include "service_config.h"

#include <stdexcept>

#include <yaml-cpp/yaml.h>

namespace yolo {
namespace app {

namespace {

[[noreturn]] void fatal(const std::string& msg) {
    throw std::runtime_error("yolo_inference_service config: " + msg);
}

void check_known_keys(const YAML::Node& n,
                      const std::vector<std::string>& known,
                      const char* where) {
    if (!n || !n.IsMap()) return;
    for (const auto& kv : n) {
        const std::string k = kv.first.as<std::string>();
        bool found = false;
        for (const auto& ok : known) {
            if (ok == k) {
                found = true;
                break;
            }
        }
        if (!found) fatal(std::string("unknown key ") + where + "." + k);
    }
}

template <typename T>
T get_req(const YAML::Node& n, const std::string& key, const char* where) {
    const auto v = n[key];
    if (!v) fatal(std::string("missing key ") + where + "." + key);
    try {
        return v.as<T>();
    } catch (const std::exception&) {
        fatal(std::string("bad type for ") + where + "." + key);
    }
}

template <typename T>
T get_opt(const YAML::Node& n, const std::string& key, T dflt,
          const char* where) {
    const auto v = n[key];
    if (!v) return dflt;
    try {
        return v.as<T>();
    } catch (const std::exception&) {
        fatal(std::string("bad type for ") + where + "." + key);
    }
}

void check_ipc_endpoint(const std::string& ep, const std::string& key) {
    if (ep.rfind("ipc:///", 0) != 0) {
        fatal(key + " must be ipc:/// endpoint, got: " + ep);
    }
}

}  // namespace

ServiceConfig load_service_config(const std::string& path) {
    YAML::Node root;
    try {
        root = YAML::LoadFile(path);
    } catch (const std::exception& e) {
        fatal(std::string("cannot read ") + path + ": " + e.what());
    }

    const auto node = root["yolo_inference_service"];
    if (!node || !node.IsMap()) {
        fatal("top-level node 'yolo_inference_service' missing in " + path);
    }
    check_known_keys(node,
                     {"log_level", "log_path", "server", "upstream", "ingress",
                      "local_ring", "infer", "postprocess", "reorder",
                      "tracking", "transport", "publish"},
                     "yolo_inference_service");

    ServiceConfig cfg;

    cfg.log_level = get_req<std::string>(node, "log_level", "root");
    cfg.log_path = get_req<std::string>(node, "log_path", "root");

    if (const auto srv = node["server"]) {
        check_known_keys(srv, {"lock_file"}, "server");
        cfg.lock_file = get_opt<std::string>(srv, "lock_file", cfg.lock_file,
                                             "server");
    }

    // ---- upstream / ingress / local_ring ----
    {
        const auto up = node["upstream"];
        if (!up) fatal("missing node upstream");
        check_known_keys(up,
                         {"control_endpoint", "update_endpoint",
                          "data_endpoint", "subscribe_stream_ids"},
                         "upstream");
        cfg.pre.upstream.control_endpoint =
            get_req<std::string>(up, "control_endpoint", "upstream");
        check_ipc_endpoint(cfg.pre.upstream.control_endpoint,
                           "upstream.control_endpoint");
        cfg.pre.upstream.update_endpoint =
            get_opt<std::string>(up, "update_endpoint", "", "upstream");
        cfg.pre.upstream.data_endpoint =
            get_opt<std::string>(up, "data_endpoint", "", "upstream");
        if (const auto ids = up["subscribe_stream_ids"]) {
            for (const auto& id : ids) {
                cfg.pre.upstream.subscribe_stream_ids.push_back(
                    id.as<std::string>());
            }
        }
    }
    {
        const auto ing = node["ingress"];
        if (!ing) fatal("missing node ingress");
        check_known_keys(ing,
                         {"max_queue_per_stream", "update_timeout_ms",
                          "fallback_read_latest",
                          "stream_refresh_interval_sec",
                          "reconnect_backoff_sec", "stale_reconnect_sec"},
                         "ingress");
        cfg.pre.ingress.max_queue_per_stream =
            get_req<int>(ing, "max_queue_per_stream", "ingress");
        cfg.pre.ingress.update_timeout_ms =
            get_req<int>(ing, "update_timeout_ms", "ingress");
        cfg.pre.ingress.fallback_read_latest =
            get_req<bool>(ing, "fallback_read_latest", "ingress");
        cfg.pre.ingress.stream_refresh_interval_sec =
            get_req<double>(ing, "stream_refresh_interval_sec", "ingress");
        cfg.pre.ingress.reconnect_backoff_sec =
            get_req<double>(ing, "reconnect_backoff_sec", "ingress");
        cfg.pre.ingress.stale_reconnect_sec =
            get_req<double>(ing, "stale_reconnect_sec", "ingress");
    }
    {
        const auto lr = node["local_ring"];
        if (!lr) fatal("missing node local_ring");
        check_known_keys(lr, {"capacity", "drop_when_busy"}, "local_ring");
        cfg.pre.local_ring.capacity =
            get_req<int>(lr, "capacity", "local_ring");
        cfg.pre.local_ring.drop_when_busy =
            get_req<bool>(lr, "drop_when_busy", "local_ring");
        if (cfg.pre.local_ring.capacity < 2) {
            fatal("local_ring.capacity must be >= 2");
        }
    }

    // ---- infer ----
    {
        const auto inf = node["infer"];
        if (!inf) fatal("missing node infer");
        check_known_keys(inf,
                         {"enabled", "model_path", "core_masks",
                          "instances_per_core", "job_queue_capacity",
                          "output_queue_capacity", "dmabuf_zero_copy",
                          "stream_db_path", "sample_backoff_ms",
                          "sample_backoff_cooldown_ms"},
                         "infer");
        cfg.infer.enabled = get_req<bool>(inf, "enabled", "infer");
        if (!cfg.infer.enabled) {
            fatal("infer.enabled=false is not supported (D3): this service "
                  "exists to run inference");
        }
        cfg.infer.model_path = get_req<std::string>(inf, "model_path", "infer");
        cfg.infer.core_masks =
            get_req<std::vector<std::string>>(inf, "core_masks", "infer");
        if (cfg.infer.core_masks.empty()) {
            fatal("infer.core_masks must not be empty");
        }
        cfg.infer.instances_per_core =
            get_req<int>(inf, "instances_per_core", "infer");
        cfg.infer.job_queue_capacity =
            get_req<int>(inf, "job_queue_capacity", "infer");
        cfg.infer.output_queue_capacity =
            get_req<int>(inf, "output_queue_capacity", "infer");
        cfg.infer.dmabuf_zero_copy =
            get_opt<bool>(inf, "dmabuf_zero_copy", true, "infer");
        cfg.infer.stream_db_path =
            get_req<std::string>(inf, "stream_db_path", "infer");
        cfg.infer.sample_backoff_ms =
            get_req<int>(inf, "sample_backoff_ms", "infer");
        cfg.infer.sample_backoff_cooldown_ms =
            get_req<int>(inf, "sample_backoff_cooldown_ms", "infer");
    }

    // ---- postprocess ----
    {
        const auto post = node["postprocess"];
        if (!post) fatal("missing node postprocess");
        check_known_keys(post,
                         {"enabled", "worker_count", "conf_thres",
                          "iou_thres", "imgsz", "obj_classes",
                          "detection_queue_capacity"},
                         "postprocess");
        cfg.post.enabled = get_req<bool>(post, "enabled", "postprocess");
        if (!cfg.post.enabled) {
            fatal("postprocess.enabled=false is not supported (D3): no "
                  "consumer for engine outputs");
        }
        cfg.post.worker_count = get_req<int>(post, "worker_count", "postprocess");
        cfg.post.conf_thres = get_req<float>(post, "conf_thres", "postprocess");
        cfg.post.iou_thres = get_req<float>(post, "iou_thres", "postprocess");
        cfg.post.imgsz = get_req<int>(post, "imgsz", "postprocess");
        if (const auto cls = post["obj_classes"]) {
            for (const auto& c : cls) cfg.post.obj_classes.push_back(c.as<int>());
        }
        cfg.post.detection_queue_capacity =
            get_req<int>(post, "detection_queue_capacity", "postprocess");
        if (cfg.post.worker_count < 1) fatal("postprocess.worker_count >= 1");
    }

    // ---- reorder ----
    {
        const auto ro = node["reorder"];
        if (!ro) fatal("missing node reorder");
        check_known_keys(ro,
                         {"enabled", "gap_timeout_sec",
                          "max_waiting_per_stream", "poll_timeout_ms",
                          "admit_queue_capacity", "ordered_queue_capacity",
                          "sample_backoff_on_ordered_block"},
                         "reorder");
        cfg.reorder.enabled = get_req<bool>(ro, "enabled", "reorder");
        cfg.reorder.gap_timeout_sec =
            get_req<double>(ro, "gap_timeout_sec", "reorder");
        cfg.reorder.max_waiting_per_stream =
            get_req<int>(ro, "max_waiting_per_stream", "reorder");
        cfg.reorder.poll_timeout_ms =
            get_req<int>(ro, "poll_timeout_ms", "reorder");
        cfg.reorder.admit_queue_capacity =
            get_req<int>(ro, "admit_queue_capacity", "reorder");
        cfg.reorder.ordered_queue_capacity =
            get_req<int>(ro, "ordered_queue_capacity", "reorder");
        cfg.reorder.sample_backoff_on_ordered_block =
            get_req<bool>(ro, "sample_backoff_on_ordered_block", "reorder");
    }

    // ---- tracking ----
    {
        const auto tr = node["tracking"];
        if (!tr) fatal("missing node tracking");
        check_known_keys(tr,
                         {"enabled", "frame_rate", "track_thresh",
                          "track_buffer", "match_thresh",
                          "low_score", "second_match_thresh",
                          "unconfirmed_match_thresh", "mot20",
                          "tracked_queue_capacity", "poll_timeout_ms",
                          "sample_backoff_on_tracked_block", "names_path"},
                         "tracking");
        cfg.tracking.enabled = get_req<bool>(tr, "enabled", "tracking");
        cfg.tracking.frame_rate = get_req<int>(tr, "frame_rate", "tracking");
        cfg.tracking.track_thresh =
            get_req<float>(tr, "track_thresh", "tracking");
        cfg.tracking.track_buffer =
            get_req<int>(tr, "track_buffer", "tracking");
        cfg.tracking.match_thresh =
            get_req<float>(tr, "match_thresh", "tracking");
        cfg.tracking.low_score = get_req<float>(tr, "low_score", "tracking");
        cfg.tracking.second_match_thresh =
            get_req<float>(tr, "second_match_thresh", "tracking");
        cfg.tracking.unconfirmed_match_thresh =
            get_req<float>(tr, "unconfirmed_match_thresh", "tracking");
        cfg.tracking.mot20 = get_req<bool>(tr, "mot20", "tracking");
        cfg.tracking.tracked_queue_capacity =
            get_req<int>(tr, "tracked_queue_capacity", "tracking");
        cfg.tracking.poll_timeout_ms =
            get_req<int>(tr, "poll_timeout_ms", "tracking");
        cfg.tracking.sample_backoff_on_tracked_block =
            get_req<bool>(tr, "sample_backoff_on_tracked_block", "tracking");
        cfg.tracking.names_path =
            get_req<std::string>(tr, "names_path", "tracking");
    }

    // ---- transport / publish ----
    {
        const auto tp = node["transport"];
        if (!tp) fatal("missing node transport");
        check_known_keys(tp,
                         {"endpoint", "update_endpoint", "recv_timeout_ms",
                          "send_timeout_ms"},
                         "transport");
        cfg.transport.endpoint =
            get_req<std::string>(tp, "endpoint", "transport");
        cfg.transport.update_endpoint =
            get_req<std::string>(tp, "update_endpoint", "transport");
        cfg.transport.recv_timeout_ms =
            get_req<int>(tp, "recv_timeout_ms", "transport");
        cfg.transport.send_timeout_ms =
            get_req<int>(tp, "send_timeout_ms", "transport");
        check_ipc_endpoint(cfg.transport.endpoint, "transport.endpoint");
        check_ipc_endpoint(cfg.transport.update_endpoint,
                           "transport.update_endpoint");
        if (cfg.transport.endpoint == cfg.transport.update_endpoint) {
            fatal("transport.endpoint and update_endpoint must differ");
        }
        // 与已知外部端点错开（上游 rtsp 三平面）
        const std::string rtsp_ctrl = cfg.pre.upstream.control_endpoint;
        if (cfg.transport.endpoint == rtsp_ctrl ||
            cfg.transport.update_endpoint == rtsp_ctrl) {
            fatal("transport endpoints must not collide with upstream "
                  "rtsp control endpoint");
        }
    }
    {
        const auto pb = node["publish"];
        if (!pb) fatal("missing node publish");
        check_known_keys(pb, {"poll_timeout_ms", "update_hwm"}, "publish");
        cfg.publish.poll_timeout_ms =
            get_req<int>(pb, "poll_timeout_ms", "publish");
        cfg.publish.update_hwm = get_req<int>(pb, "update_hwm", "publish");
    }

    return cfg;
}

std::unordered_map<int, std::string> load_class_names(
    const std::string& names_path) {
    std::unordered_map<int, std::string> out;
    if (names_path.empty()) return out;
    try {
        const YAML::Node names = YAML::LoadFile(names_path)["names"];
        if (!names || !names.IsMap()) return out;
        for (const auto& kv : names) {
            out[kv.first.as<int>()] = kv.second.as<std::string>();
        }
    } catch (const std::exception&) {
        return out;  // 空 = cls{id} 回退
    }
    return out;
}

}  // namespace app
}  // namespace yolo

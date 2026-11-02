/**
 * @file control_ops.cpp
 * @brief ControlOps 实现：health / status msgpack 打包（键集对齐旧版）。
 */

#include "control_ops.h"

#include <cstdio>

#include <msgpack.hpp>

namespace yolo {
namespace comm {

std::vector<uint8_t> ControlOps::handle(
    const drn::core::tp::ControlRequest& req) {
    if (stopping_.load(std::memory_order_acquire)) {
        throw drn::core::tp::ControlError("service_stopping",
                                          "shutdown in progress");
    }
    if (req.operation == "health") return pack_health();
    if (req.operation == "status") return pack_status();
    throw drn::core::tp::ControlError("invalid_operation", req.operation);
}

std::vector<uint8_t> ControlOps::pack_health() {
    msgpack::sbuffer sbuf;
    msgpack::packer<msgpack::sbuffer> pk(&sbuf);
    pk.pack_map(3);
    pk.pack("update_endpoint");
    pk.pack(update_endpoint_);
    pk.pack("known_streams");
    const auto streams = tracker_.known_streams();
    pk.pack_array(streams.size());
    for (const auto& s : streams) pk.pack(s);
    pk.pack("result_stream_count");
    pk.pack(static_cast<uint64_t>(streams.size()));
    return {sbuf.data(), sbuf.data() + sbuf.size()};
}

std::vector<uint8_t> ControlOps::pack_status() {
    const PublishThreadStats st =
        publish_ ? publish_->stats() : PublishThreadStats{};

    const auto extra = extra_status_ ? extra_status_()
                                     : std::vector<
                                           std::pair<std::string, std::string>>{};

    msgpack::sbuffer sbuf;
    msgpack::packer<msgpack::sbuffer> pk(&sbuf);
    pk.pack_map(6 + extra.size());
    pk.pack("update_endpoint");
    pk.pack(update_endpoint_);
    pk.pack("publish_ok");
    pk.pack(st.publish_ok);
    pk.pack("publish_drop");
    pk.pack(st.publish_drop);
    pk.pack("emit_count");
    pk.pack(st.emit_count);
    pk.pack("publish_pack_fail");
    pk.pack(st.publish_pack_fail);
    pk.pack("result_store_stream_count");
    pk.pack(static_cast<uint64_t>(tracker_.stream_count()));
    for (const auto& kv : extra) {
        pk.pack(kv.first);
        pk.pack(kv.second);
    }
    return {sbuf.data(), sbuf.data() + sbuf.size()};
}

}  // namespace comm
}  // namespace yolo

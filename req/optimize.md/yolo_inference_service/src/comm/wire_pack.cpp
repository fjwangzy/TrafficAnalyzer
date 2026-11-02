/**
 * @file wire_pack.cpp
 * @brief msgpack 手工组包（对齐 Python update_to_wire_dict）。
 */

#include "wire_pack.h"

#include <msgpack.hpp>

#include <string>

namespace yolo {
namespace comm_server {
namespace {

std::string class_name_of(const postprocess::Detection& d) {
    if (!d.class_name.empty()) return d.class_name;
    return "cls" + std::to_string(d.class_id);
}

template <typename Packer>
void pack_det(Packer& pk, const postprocess::Detection& d,
              bool include_track_id) {
    const bool write_tid = include_track_id && d.track_id >= 1;
    const std::size_t n = write_tid ? 5u : 4u;
    pk.pack_map(n);

    pk.pack("box");
    pk.pack_array(4);
    pk.pack(d.x1);
    pk.pack(d.y1);
    pk.pack(d.x2);
    pk.pack(d.y2);

    pk.pack("score");
    pk.pack(d.score);

    pk.pack("class_id");
    pk.pack(d.class_id);

    pk.pack("class_name");
    pk.pack(class_name_of(d));

    if (write_tid) {
        pk.pack("track_id");
        pk.pack(d.track_id);
    }
}

template <typename Packer>
void pack_result_map(Packer& pk, const reorder::OrderedFrameDetections& frame) {
    // stream_id, generation, source_epoch, seq, width, height, letterbox,
    // untracked_detections, detections  → 9 键 + D4 只增键（有值时）
    const bool write_captured = frame.captured_at > 0.0;
    const bool write_stream_time = frame.has_stream_time;
    pk.pack_map(9 + (write_captured ? 1u : 0u) +
                (write_stream_time ? 1u : 0u));

    pk.pack("stream_id");
    pk.pack(frame.stream_id);

    pk.pack("generation");
    pk.pack(frame.generation);

    pk.pack("source_epoch");
    pk.pack(std::to_string(frame.generation));

    pk.pack("seq");
    pk.pack(frame.seq);

    pk.pack("width");
    pk.pack(frame.letterbox.src_w);

    pk.pack("height");
    pk.pack(frame.letterbox.src_h);

    pk.pack("letterbox");
    pk.pack_map(7);
    pk.pack("scale");
    pk.pack(frame.letterbox.scale);
    pk.pack("pad_x");
    pk.pack(frame.letterbox.pad_x);
    pk.pack("pad_y");
    pk.pack(frame.letterbox.pad_y);
    pk.pack("dst_w");
    pk.pack(frame.letterbox.dst_w);
    pk.pack("dst_h");
    pk.pack(frame.letterbox.dst_h);
    pk.pack("new_w");
    pk.pack(frame.letterbox.new_w);
    pk.pack("new_h");
    pk.pack(frame.letterbox.new_h);

    pk.pack("untracked_detections");
    pk.pack_array(frame.dets.size());
    for (const auto& d : frame.dets) {
        pack_det(pk, d, /*include_track_id=*/false);
    }

    pk.pack("detections");
    pk.pack_array(frame.track_dets.size());
    for (const auto& d : frame.track_dets) {
        pack_det(pk, d, /*include_track_id=*/true);
    }

    if (write_captured) {
        pk.pack("captured_at");
        pk.pack(frame.captured_at);
    }
    if (write_stream_time) {
        pk.pack("stream_time_sec");
        pk.pack(frame.stream_time_sec);
    }
}

}  // namespace

void pack_wire_result_map(msgpack::packer<msgpack::sbuffer>& pk,
                          const reorder::OrderedFrameDetections& frame) {
    pack_result_map(pk, frame);
}

bool pack_wire_result(const reorder::OrderedFrameDetections& frame,
                      std::vector<uint8_t>* out) {
    if (!out) return false;
    try {
        msgpack::sbuffer sbuf;
        msgpack::packer<msgpack::sbuffer> pk(&sbuf);
        pack_result_map(pk, frame);
        out->assign(reinterpret_cast<const uint8_t*>(sbuf.data()),
                    reinterpret_cast<const uint8_t*>(sbuf.data()) + sbuf.size());
        return true;
    } catch (...) {
        return false;
    }
}

bool pack_inference_update(bool is_latest, double inferred_at,
                           const reorder::OrderedFrameDetections& frame,
                           std::vector<uint8_t>* out) {
    if (!out) return false;
    try {
        msgpack::sbuffer sbuf;
        msgpack::packer<msgpack::sbuffer> pk(&sbuf);
        pk.pack_map(3);
        pk.pack("is_latest");
        pk.pack(is_latest);
        pk.pack("inferred_at");
        pk.pack(inferred_at);
        pk.pack("result");
        pack_result_map(pk, frame);
        out->assign(reinterpret_cast<const uint8_t*>(sbuf.data()),
                    reinterpret_cast<const uint8_t*>(sbuf.data()) + sbuf.size());
        return true;
    } catch (...) {
        return false;
    }
}

}  // namespace comm_server
}  // namespace yolo

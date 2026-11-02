/**
 * @file meta_codec.cpp
 * @brief InferMeta 编解码实现（定长字段小端直写 + 变长字符串）。
 */

#include "meta_codec.h"

#include <cstring>

namespace yolo {
namespace infer {

namespace {

constexpr uint32_t kMagic = 0x44524E59u;  // "YNRD"

struct Reader {
    const uint8_t* p;
    size_t n;
    size_t off = 0;
    bool bad = false;

    void get(void* dst, size_t len) {
        if (bad || off + len > n) {
            bad = true;
            return;
        }
        std::memcpy(dst, p + off, len);
        off += len;
    }
    uint32_t u32() { uint32_t v = 0; get(&v, 4); return v; }
    uint64_t u64() { uint64_t v = 0; get(&v, 8); return v; }
    int32_t i32() { int32_t v = 0; get(&v, 4); return v; }
    double f64() { double v = 0; get(&v, 8); return v; }
    uint8_t u8() { uint8_t v = 0; get(&v, 1); return v; }
    std::string str() {
        const uint32_t len = u32();
        if (bad || off + len > n) {
            bad = true;
            return {};
        }
        std::string s(reinterpret_cast<const char*>(p + off), len);
        off += len;
        return s;
    }
};

struct Writer {
    std::vector<uint8_t> buf;
    void put(const void* src, size_t len) {
        const auto* b = static_cast<const uint8_t*>(src);
        buf.insert(buf.end(), b, b + len);
    }
    void u32(uint32_t v) { put(&v, 4); }
    void u64(uint64_t v) { put(&v, 8); }
    void i32(int32_t v) { put(&v, 4); }
    void f64(double v) { put(&v, 8); }
    void u8(uint8_t v) { put(&v, 1); }
    void str(const std::string& s) {
        u32(static_cast<uint32_t>(s.size()));
        put(s.data(), s.size());
    }
};

}  // namespace

std::vector<uint8_t> pack_meta(const InferMeta& m) {
    Writer w;
    w.u32(kMagic);
    w.u32(m.slot_index);
    w.str(m.stream_id);
    w.u64(m.seq);
    w.u64(m.generation);
    w.f64(m.letterbox.scale);
    w.i32(m.letterbox.pad_x);
    w.i32(m.letterbox.pad_y);
    w.i32(m.letterbox.dst_w);
    w.i32(m.letterbox.dst_h);
    w.i32(m.letterbox.new_w);
    w.i32(m.letterbox.new_h);
    w.i32(m.letterbox.src_w);
    w.i32(m.letterbox.src_h);
    w.f64(m.captured_at);
    w.u8(m.has_stream_time ? 1 : 0);
    w.f64(m.stream_time_sec);
    return std::move(w.buf);
}

bool unpack_meta(const std::vector<uint8_t>& raw, InferMeta* out) {
    if (!out || raw.size() < 4) return false;
    Reader r{raw.data(), raw.size()};
    if (r.u32() != kMagic) return false;
    out->slot_index = r.u32();
    out->stream_id = r.str();
    out->seq = r.u64();
    out->generation = r.u64();
    out->letterbox.scale = r.f64();
    out->letterbox.pad_x = r.i32();
    out->letterbox.pad_y = r.i32();
    out->letterbox.dst_w = r.i32();
    out->letterbox.dst_h = r.i32();
    out->letterbox.new_w = r.i32();
    out->letterbox.new_h = r.i32();
    out->letterbox.src_w = r.i32();
    out->letterbox.src_h = r.i32();
    out->captured_at = r.f64();
    out->has_stream_time = (r.u8() != 0);
    out->stream_time_sec = r.f64();
    if (r.bad) return false;
    // 侧表身份回填（LetterboxMeta 冗余键）
    out->letterbox.stream_id = out->stream_id;
    out->letterbox.seq = out->seq;
    out->letterbox.generation = out->generation;
    return true;
}

}  // namespace infer
}  // namespace yolo

/**
 * @file types.h
 * @brief 前处理流水线共享类型：UpstreamFrame / LetterboxMeta / 本地环帧句柄。
 */

#ifndef YOLO_PREPROCESS_TYPES_H_
#define YOLO_PREPROCESS_TYPES_H_

#include <cstdint>
#include <functional>
#include <string>
#include <utility>

#include <unistd.h>

namespace yolo {
namespace preprocess {

/** 网络输入边长（像素）。 */
constexpr int kNetSize = 640;

/** letterbox 垫色（RGB 各通道）。 */
constexpr uint8_t kLetterboxPadValue = 114;

/** RGB888 单槽字节数：640*640*3。 */
constexpr size_t kRgbSlotBytes =
    static_cast<size_t>(kNetSize) * static_cast<size_t>(kNetSize) * 3u;

/**
 * @brief letterbox 逆变换参数（供后处理坐标还原）。
 */
struct LetterboxMeta {
    std::string stream_id;
    uint64_t seq = 0;
    uint64_t generation = 0;
    int src_w = 0;
    int src_h = 0;
    double scale = 1.0;
    int pad_x = 0;   /**< left */
    int pad_y = 0;   /**< top */
    int dst_w = kNetSize;
    int dst_h = kNetSize;
    int new_w = 0;   /**< 缩放后有效宽 */
    int new_h = 0;   /**< 缩放后有效高 */
};

/**
 * @brief 上游 NV12 帧（持有数据面 dup'd dma_fd；析构 close）。
 */
struct UpstreamFrame {
    std::string stream_id;
    uint64_t seq = 0;
    uint64_t generation = 0;
    int buffer_index = 0;
    int width = 0;
    int height = 0;
    int stride_y = 0;
    int stride_uv = 0;
    int nv12_fd = -1;   /**< 所有权：本结构；处理后必须 close */
    double captured_at = 0.0;
    double stream_time_sec = 0.0;   /**< D4：上游流时间轴秒 */
    bool has_stream_time = false;
    std::function<void()> release_upstream; /**< fd 读完后异步释放上游环槽 */

    UpstreamFrame() = default;
    ~UpstreamFrame() { release(); }

    UpstreamFrame(const UpstreamFrame&) = delete;
    UpstreamFrame& operator=(const UpstreamFrame&) = delete;

    UpstreamFrame(UpstreamFrame&& o) noexcept { *this = std::move(o); }
    UpstreamFrame& operator=(UpstreamFrame&& o) noexcept {
        if (this == &o) return *this;
        release();
        stream_id = std::move(o.stream_id);
        seq = o.seq;
        generation = o.generation;
        buffer_index = o.buffer_index;
        width = o.width;
        height = o.height;
        stride_y = o.stride_y;
        stride_uv = o.stride_uv;
        nv12_fd = o.nv12_fd;
        captured_at = o.captured_at;
        stream_time_sec = o.stream_time_sec;
        has_stream_time = o.has_stream_time;
        release_upstream = std::move(o.release_upstream);
        o.nv12_fd = -1;
        o.release_upstream = {};
        return *this;
    }

    void release() {
        if (nv12_fd >= 0) {
            ::close(nv12_fd);
            nv12_fd = -1;
        }
        auto cb = std::move(release_upstream);
        release_upstream = {};
        if (cb) cb();
    }

    bool valid() const {
        return nv12_fd >= 0 && width > 0 && height > 0 && seq >= 1;
    }
};

/**
 * @brief 本服务 LocalRgbRing 已发布帧视图（dma_fd 为环槽 fd，勿 close）。
 */
struct LocalRgbFrame {
    uint64_t seq_local = 0;
    int slot_index = -1;
    int dma_fd = -1;            /**< 环槽 fd；调用方 acquire 后勿 close */
    size_t slot_size = kRgbSlotBytes;
    int width = kNetSize;
    int height = kNetSize;
    int wstride = kNetSize;
    LetterboxMeta letterbox;
    std::string upstream_stream_id;
    uint64_t upstream_seq = 0;
    uint64_t upstream_generation = 0;
};

}  // namespace preprocess
}  // namespace yolo

#endif  /* YOLO_PREPROCESS_TYPES_H_ */

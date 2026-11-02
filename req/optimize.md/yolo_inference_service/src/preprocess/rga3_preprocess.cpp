/**
 * @file rga3_preprocess.cpp
 * @brief Rga3Preprocess：imconfig(RGA3) + improcess(NV12→RGB888 letterbox)。
 */

#include "rga3_preprocess.h"

#include <im2d.h>
#include <rga.h>

#include <cmath>
#include <cstdio>
#include <cstring>

namespace yolo {
namespace preprocess {

Rga3Preprocess::Rga3Preprocess(int net_size)
    : net_(net_size >= 16 ? net_size : preprocess::kNetSize) {}

Rga3Preprocess::~Rga3Preprocess() {
    unbind_ring();
}

bool Rga3Preprocess::ensure_rga3_core() {
    // 每帧绑 RGA3，避免调度落到 RGA2
    const IM_STATUS st = imconfig(
        IM_CONFIG_SCHEDULER_CORE,
        IM_SCHEDULER_RGA3_CORE0 | IM_SCHEDULER_RGA3_CORE1);
    if (st != IM_STATUS_SUCCESS && st != IM_STATUS_NOERROR) {
        std::fprintf(stderr, "[Rga3Preprocess] imconfig RGA3 failed: %s\n",
                     imStrError(st));
        core_ok_ = false;
        return false;
    }
    core_ok_ = true;
    return true;
}

bool Rga3Preprocess::bind_ring(LocalRgbRing& ring) {
    unbind_ring();
    if (!ring.ok()) return false;
    ring_ = &ring;
    dst_handles_.assign(static_cast<size_t>(ring.capacity()), 0);
    for (int i = 0; i < ring.capacity(); ++i) {
        const int fd = ring.slot_fd(i);
        if (fd < 0) {
            unbind_ring();
            return false;
        }
        rga_buffer_handle_t h =
            importbuffer_fd(fd, static_cast<int>(ring.slot_size()));
        if (h == 0) {
            std::fprintf(stderr,
                         "[Rga3Preprocess] importbuffer_fd dst slot %d failed\n",
                         i);
            unbind_ring();
            return false;
        }
        dst_handles_[static_cast<size_t>(i)] = static_cast<uint32_t>(h);
    }
    bound_ = true;
    return true;
}

void Rga3Preprocess::unbind_ring() {
    for (auto& h : dst_handles_) {
        if (h != 0) {
            releasebuffer_handle(static_cast<rga_buffer_handle_t>(h));
            h = 0;
        }
    }
    dst_handles_.clear();
    ring_ = nullptr;
    bound_ = false;
}

uint32_t Rga3Preprocess::dst_handle_for(int slot_index) {
    if (slot_index < 0 ||
        static_cast<size_t>(slot_index) >= dst_handles_.size()) {
        return 0;
    }
    return dst_handles_[static_cast<size_t>(slot_index)];
}

LetterboxMeta Rga3Preprocess::compute_letterbox(const UpstreamFrame& f) const {
    LetterboxMeta m;
    m.stream_id = f.stream_id;
    m.seq = f.seq;
    m.generation = f.generation;
    m.src_w = f.width;
    m.src_h = f.height;
    m.dst_w = net_;
    m.dst_h = net_;

    const double scale = std::min(
        static_cast<double>(net_) / static_cast<double>(f.width),
        static_cast<double>(net_) / static_cast<double>(f.height));
    m.scale = scale;

    int new_w = static_cast<int>(std::lround(f.width * scale));
    int new_h = static_cast<int>(std::lround(f.height * scale));
    // RGA 惯例：偶数对齐
    new_w = new_w & ~1;
    new_h = new_h & ~1;
    if (new_w < 2) new_w = 2;
    if (new_h < 2) new_h = 2;
    if (new_w > net_) new_w = net_;
    if (new_h > net_) new_h = net_;

    // 对齐 preprocess.py / Ultralytics：±0.1 后 round
    const double dw = (net_ - new_w) / 2.0;
    const double dh = (net_ - new_h) / 2.0;
    m.pad_x = static_cast<int>(std::lround(dw - 0.1));
    m.pad_y = static_cast<int>(std::lround(dh - 0.1));
    if (m.pad_x < 0) m.pad_x = 0;
    if (m.pad_y < 0) m.pad_y = 0;
    if (m.pad_x + new_w > net_) m.pad_x = net_ - new_w;
    if (m.pad_y + new_h > net_) m.pad_y = net_ - new_h;

    m.new_w = new_w;
    m.new_h = new_h;
    return m;
}

bool Rga3Preprocess::process(UpstreamFrame&& frame, LocalRgbRing& ring,
                             bool drop_when_busy) {
    if (!bound_ || ring_ != &ring) {
        if (!bind_ring(ring)) {
            ++fail_count_;
            return false;
        }
    }
    if (!frame.valid()) {
        ++fail_count_;
        return false;
    }
    if (!ensure_rga3_core()) {
        ++fail_count_;
        return false;
    }

    auto slot_opt = ring.acquire_publish_slot(drop_when_busy);
    if (!slot_opt) {
        ++fail_count_;
        return false;
    }
    const int slot = *slot_opt;
    const LetterboxMeta meta = compute_letterbox(frame);

    // 几何变小：再 memset 114，避免旧内容露边
    if (last_new_w_ >= 0 &&
        (meta.new_w < last_new_w_ || meta.new_h < last_new_h_)) {
        ring.refill_pad(slot);
    }
    last_new_w_ = meta.new_w;
    last_new_h_ = meta.new_h;

    const int src_w = frame.width;
    const int src_h = frame.height;
    int wstride = frame.stride_y > 0 ? frame.stride_y : src_w;
    int hstride = src_h;

    // src：每帧 import / release。
    //      使用 4-arg importbuffer_fd 显式传递 width/height/format，
    //      避免 RGA 从 DMA-BUF 元数据自动检测格式（VPU 端 tiled 修饰符
    //      会导致格式识别错误）。
    rga_buffer_handle_t src_hnd =
        importbuffer_fd(frame.nv12_fd, src_w, src_h,
                        static_cast<int>(RK_FORMAT_YCbCr_420_SP));
    if (src_hnd == 0) {
        std::fprintf(stderr,
                     "[Rga3Preprocess] import src failed stream=%s seq=%llu\n",
                     frame.stream_id.c_str(),
                     static_cast<unsigned long long>(frame.seq));
        ++fail_count_;
        return false;
    }

    rga_buffer_handle_t dst_hnd =
        static_cast<rga_buffer_handle_t>(dst_handle_for(slot));
    if (dst_hnd == 0) {
        releasebuffer_handle(src_hnd);
        ++fail_count_;
        return false;
    }

    rga_buffer_t src = wrapbuffer_handle(src_hnd, src_w, src_h,
                                         RK_FORMAT_YCbCr_420_SP,
                                         wstride, hstride);
    rga_buffer_t dst = wrapbuffer_handle(dst_hnd, net_, net_,
                                         RK_FORMAT_RGB_888,
                                         net_, net_);

    im_rect srect{};
    srect.x = 0;
    srect.y = 0;
    srect.width = src_w;
    srect.height = src_h;

    im_rect drect{};
    drect.x = meta.pad_x;
    drect.y = meta.pad_y;
    drect.width = meta.new_w;
    drect.height = meta.new_h;

    im_rect prect{};
    rga_buffer_t pat{};

    IM_STATUS chk = imcheck(src, dst, srect, drect);
    if (chk != IM_STATUS_NOERROR) {
        std::fprintf(stderr,
                     "[Rga3Preprocess] imcheck fail stream=%s seq=%llu: %s\n",
                     frame.stream_id.c_str(),
                     static_cast<unsigned long long>(frame.seq),
                     imStrError(chk));
        releasebuffer_handle(src_hnd);
        ++fail_count_;
        return false;
    }

    // 禁止 IM_COLOR_FILL；同步 CSC+scale 写中心
    IM_STATUS st = improcess(src, dst, pat, srect, drect, prect, IM_SYNC);
    releasebuffer_handle(src_hnd);
    // UpstreamFrame 析构 close nv12_fd
    frame.release();

    if (st != IM_STATUS_SUCCESS && st != IM_STATUS_NOERROR) {
        std::fprintf(stderr,
                     "[Rga3Preprocess] improcess fail stream=%s seq=%llu: %s\n",
                     meta.stream_id.c_str(),
                     static_cast<unsigned long long>(meta.seq),
                     imStrError(st));
        ++fail_count_;
        return false;
    }

    ring.publish_commit(slot, meta, meta.stream_id, meta.seq, meta.generation);
    return true;
}

}  // namespace preprocess
}  // namespace yolo

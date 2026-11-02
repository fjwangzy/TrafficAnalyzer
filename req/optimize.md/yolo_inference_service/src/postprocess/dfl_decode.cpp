/**
 * @file dfl_decode.cpp
 * @brief DFL / box_process / filter / scale；热路径 score-first + NEON 融合解码。
 */

#include "dfl_decode.h"

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <vector>

#if defined(__ARM_NEON) || defined(__ARM_NEON__)
#include <arm_neon.h>
#define YOLO_DFL_USE_NEON 1
#else
#define YOLO_DFL_USE_NEON 0
#endif

#include <xtensor/xbuilder.hpp>
#include <xtensor/xmanipulation.hpp>
#include <xtensor/xmath.hpp>
#include <xtensor/xoperation.hpp>
#include <xtensor/xsort.hpp>
#include <xtensor/xview.hpp>

namespace yolo {
namespace postprocess {
namespace {

using shape_t = std::vector<std::size_t>;

shape_t sh(std::initializer_list<std::size_t> dims) {
    return shape_t(dims);
}

constexpr std::size_t kRegMax = 16;
constexpr std::size_t kSides = 4;

bool class_allowed(int cls, const std::vector<int>& allow) {
    if (allow.empty()) return true;
    return std::find(allow.begin(), allow.end(), cls) != allow.end();
}

/**
 * @brief reg_max=16 的 DFL 期望：softmax 加权求和。
 * @param logits 连续 16 个 logit（已 gather 到临时缓冲）。
 */
inline float dfl_expect_reg16(const float* logits) {
#if YOLO_DFL_USE_NEON
    float32x4_t v0 = vld1q_f32(logits + 0);
    float32x4_t v1 = vld1q_f32(logits + 4);
    float32x4_t v2 = vld1q_f32(logits + 8);
    float32x4_t v3 = vld1q_f32(logits + 12);

    float32x4_t m01 = vmaxq_f32(v0, v1);
    float32x4_t m23 = vmaxq_f32(v2, v3);
    float32x4_t m = vmaxq_f32(m01, m23);
    float32x2_t m_h = vmax_f32(vget_low_f32(m), vget_high_f32(m));
    m_h = vpmax_f32(m_h, m_h);
    const float vmax = vget_lane_f32(m_h, 0);

    // exp 走标量以保持与 Python 数值对齐；NEON 负责 max / 加权累加。
    alignas(16) float e[kRegMax];
    float sum = 0.f;
    for (std::size_t i = 0; i < kRegMax; ++i) {
        e[i] = std::exp(logits[i] - vmax);
        sum += e[i];
    }
    if (sum <= 0.f) return 0.f;

    float32x4_t e0 = vld1q_f32(e + 0);
    float32x4_t e1 = vld1q_f32(e + 4);
    float32x4_t e2 = vld1q_f32(e + 8);
    float32x4_t e3 = vld1q_f32(e + 12);
    const float32x4_t idx0 = {0.f, 1.f, 2.f, 3.f};
    const float32x4_t idx1 = {4.f, 5.f, 6.f, 7.f};
    const float32x4_t idx2 = {8.f, 9.f, 10.f, 11.f};
    const float32x4_t idx3 = {12.f, 13.f, 14.f, 15.f};
    float32x4_t acc = vmulq_f32(e0, idx0);
    acc = vmlaq_f32(acc, e1, idx1);
    acc = vmlaq_f32(acc, e2, idx2);
    acc = vmlaq_f32(acc, e3, idx3);
    float32x2_t acc_h = vadd_f32(vget_low_f32(acc), vget_high_f32(acc));
    acc_h = vpadd_f32(acc_h, acc_h);
    return vget_lane_f32(acc_h, 0) / sum;
#else
    float vmax = logits[0];
    for (std::size_t m = 1; m < kRegMax; ++m) {
        if (logits[m] > vmax) vmax = logits[m];
    }
    float sum = 0.f;
    float acc = 0.f;
    for (std::size_t m = 0; m < kRegMax; ++m) {
        const float ev = std::exp(logits[m] - vmax);
        sum += ev;
        acc += ev * static_cast<float>(m);
    }
    return (sum > 0.f) ? (acc / sum) : 0.f;
#endif
}

/** @brief 从 NCHW box 在 spatial 处 gather 一侧的 16 个 logit。 */
inline void gather_reg16(const float* box_nchw,
                         std::size_t side,
                         std::size_t spatial,
                         std::size_t hw,
                         float* out16) {
    const float* base = box_nchw + (side * kRegMax) * hw + spatial;
    for (std::size_t m = 0; m < kRegMax; ++m) {
        out16[m] = base[m * hw];
    }
}

}  // namespace

xt::xarray<float> dfl(const xt::xarray<float>& position) {
    if (position.dimension() != 4) {
        throw std::invalid_argument("dfl: position must be 4-D");
    }
    const auto& pos_sh = position.shape();
    const std::size_t n = pos_sh[0];
    const std::size_t c = pos_sh[1];
    const std::size_t h = pos_sh[2];
    const std::size_t w = pos_sh[3];
    constexpr std::size_t p_num = 4;
    if (c % p_num != 0) {
        throw std::invalid_argument("dfl: channel not divisible by 4");
    }
    const std::size_t mc = c / p_num;

    xt::xarray<float> out = xt::zeros<float>(sh({n, p_num, h, w}));
    for (std::size_t ni = 0; ni < n; ++ni) {
        for (std::size_t pi = 0; pi < p_num; ++pi) {
            for (std::size_t yi = 0; yi < h; ++yi) {
                for (std::size_t xi = 0; xi < w; ++xi) {
                    float vmax = position(ni, pi * mc + 0, yi, xi);
                    for (std::size_t m = 1; m < mc; ++m) {
                        const float v = position(ni, pi * mc + m, yi, xi);
                        if (v > vmax) vmax = v;
                    }
                    float sum = 0.f;
                    float acc = 0.f;
                    for (std::size_t m = 0; m < mc; ++m) {
                        const float e =
                            std::exp(position(ni, pi * mc + m, yi, xi) - vmax);
                        sum += e;
                        acc += e * static_cast<float>(m);
                    }
                    out(ni, pi, yi, xi) = (sum > 0.f) ? (acc / sum) : 0.f;
                }
            }
        }
    }
    return out;
}

xt::xarray<float> box_process(const xt::xarray<float>& position, int imgsz) {
    if (position.dimension() != 4 || position.shape()[0] != 1) {
        throw std::invalid_argument("box_process: expect (1,C,H,W)");
    }
    const std::size_t grid_h = position.shape()[2];
    const std::size_t grid_w = position.shape()[3];

    xt::xarray<float> col = xt::empty<float>(sh({1, 1, grid_h, grid_w}));
    xt::xarray<float> row = xt::empty<float>(sh({1, 1, grid_h, grid_w}));
    for (std::size_t i = 0; i < grid_h; ++i) {
        for (std::size_t j = 0; j < grid_w; ++j) {
            col(0, 0, i, j) = static_cast<float>(j);
            row(0, 0, i, j) = static_cast<float>(i);
        }
    }
    auto grid = xt::concatenate(xt::xtuple(col, row), 1);

    const float stride_h =
        static_cast<float>(imgsz) / static_cast<float>(grid_h);
    const float stride_w =
        static_cast<float>(imgsz) / static_cast<float>(grid_w);
    xt::xarray<float> stride = xt::zeros<float>(sh({1, 2, 1, 1}));
    stride(0, 0, 0, 0) = stride_w;
    stride(0, 1, 0, 0) = stride_h;

    auto dist = dfl(position);
    auto dist_lt =
        xt::view(dist, xt::all(), xt::range(0, 2), xt::all(), xt::all());
    auto dist_rb =
        xt::view(dist, xt::all(), xt::range(2, 4), xt::all(), xt::all());

    auto box_xy = grid + 0.5f - dist_lt;
    auto box_xy2 = grid + 0.5f + dist_rb;
    auto xyxy = xt::concatenate(
        xt::xtuple(xt::eval(box_xy * stride), xt::eval(box_xy2 * stride)), 1);
    return xt::eval(xyxy);
}

xt::xarray<float> sp_flatten(const xt::xarray<float>& arr) {
    if (arr.dimension() != 4 || arr.shape()[0] != 1) {
        throw std::invalid_argument("sp_flatten: expect (1,C,H,W)");
    }
    const std::size_t c = arr.shape()[1];
    const std::size_t h = arr.shape()[2];
    const std::size_t w = arr.shape()[3];
    auto t = xt::transpose(arr, {0, 2, 3, 1});
    return xt::eval(xt::reshape_view(t, sh({h * w, c})));
}

std::tuple<xt::xarray<float>, xt::xarray<int>, xt::xarray<float>>
filter_boxes(const xt::xarray<float>& boxes,
             const xt::xarray<float>& class_scores,
             float conf_thres) {
    if (boxes.dimension() != 2 || class_scores.dimension() != 2 ||
        boxes.shape()[0] != class_scores.shape()[0]) {
        throw std::invalid_argument("filter_boxes: shape mismatch");
    }
    const std::size_t n = boxes.shape()[0];
    if (n == 0) {
        return {xt::zeros<float>(sh({0, 4})), xt::zeros<int>(sh({0})),
                xt::zeros<float>(sh({0}))};
    }

    const std::size_t nc = class_scores.shape()[1];
    std::vector<std::size_t> keep_idx;
    std::vector<int> keep_cls;
    std::vector<float> keep_scores;
    keep_idx.reserve(n);
    keep_cls.reserve(n);
    keep_scores.reserve(n);
    for (std::size_t i = 0; i < n; ++i) {
        float best = class_scores(i, 0);
        int best_c = 0;
        for (std::size_t c = 1; c < nc; ++c) {
            const float s = class_scores(i, c);
            if (s > best) {
                best = s;
                best_c = static_cast<int>(c);
            }
        }
        if (best >= conf_thres) {
            keep_idx.push_back(i);
            keep_cls.push_back(best_c);
            keep_scores.push_back(best);
        }
    }

    const std::size_t k = keep_idx.size();
    xt::xarray<float> out_boxes = xt::zeros<float>(sh({k, 4}));
    xt::xarray<int> out_cls = xt::zeros<int>(sh({k}));
    xt::xarray<float> out_scores = xt::zeros<float>(sh({k}));
    for (std::size_t j = 0; j < k; ++j) {
        const std::size_t i = keep_idx[j];
        for (std::size_t c = 0; c < 4; ++c) {
            out_boxes(j, c) = boxes(i, c);
        }
        out_cls(j) = keep_cls[j];
        out_scores(j) = keep_scores[j];
    }
    return {out_boxes, out_cls, out_scores};
}

xt::xarray<float> scale_boxes_to_orig(const xt::xarray<float>& boxes,
                                      const preprocess::LetterboxMeta& meta) {
    auto out = xt::eval(boxes);
    if (out.dimension() != 2 || out.shape()[1] != 4) {
        throw std::invalid_argument("scale_boxes_to_orig: expect (N,4)");
    }
    const float left = static_cast<float>(meta.pad_x);
    const float top = static_cast<float>(meta.pad_y);
    const float ratio = static_cast<float>(meta.scale);
    if (ratio <= 0.f) {
        throw std::invalid_argument("scale_boxes_to_orig: invalid scale");
    }
    const float orig_w = static_cast<float>(meta.src_w);
    const float orig_h = static_cast<float>(meta.src_h);

    for (std::size_t i = 0; i < out.shape()[0]; ++i) {
        out(i, 0) = std::clamp((out(i, 0) - left) / ratio, 0.f, orig_w);
        out(i, 2) = std::clamp((out(i, 2) - left) / ratio, 0.f, orig_w);
        out(i, 1) = std::clamp((out(i, 1) - top) / ratio, 0.f, orig_h);
        out(i, 3) = std::clamp((out(i, 3) - top) / ratio, 0.f, orig_h);
    }
    return out;
}

void scale_decoded_box_to_orig(DecodedBox& box,
                               const preprocess::LetterboxMeta& meta) {
    const float left = static_cast<float>(meta.pad_x);
    const float top = static_cast<float>(meta.pad_y);
    const float ratio = static_cast<float>(meta.scale);
    if (ratio <= 0.f) {
        throw std::invalid_argument("scale_decoded_box_to_orig: invalid scale");
    }
    const float orig_w = static_cast<float>(meta.src_w);
    const float orig_h = static_cast<float>(meta.src_h);
    box.x1 = std::clamp((box.x1 - left) / ratio, 0.f, orig_w);
    box.x2 = std::clamp((box.x2 - left) / ratio, 0.f, orig_w);
    box.y1 = std::clamp((box.y1 - top) / ratio, 0.f, orig_h);
    box.y2 = std::clamp((box.y2 - top) / ratio, 0.f, orig_h);
}

void decode_branch_score_first(const float* box_nchw,
                               const float* cls_nchw,
                               std::size_t nc,
                               std::size_t grid_h,
                               std::size_t grid_w,
                               int imgsz,
                               float conf_thres,
                               const std::vector<int>& obj_classes,
                               std::vector<DecodedBox>& out) {
    if (!box_nchw || !cls_nchw || nc == 0 || grid_h == 0 || grid_w == 0) {
        return;
    }

    const std::size_t hw = grid_h * grid_w;
    const float stride_w =
        static_cast<float>(imgsz) / static_cast<float>(grid_w);
    const float stride_h =
        static_cast<float>(imgsz) / static_cast<float>(grid_h);

    alignas(16) float logits[kRegMax];

    for (std::size_t y = 0; y < grid_h; ++y) {
        for (std::size_t x = 0; x < grid_w; ++x) {
            const std::size_t spatial = y * grid_w + x;

            // 1) score-first：先扫 cls，过阈才做 DFL
            float best_score = cls_nchw[spatial];
            int best_cls = 0;
            for (std::size_t c = 1; c < nc; ++c) {
                const float s = cls_nchw[c * hw + spatial];
                if (s > best_score) {
                    best_score = s;
                    best_cls = static_cast<int>(c);
                }
            }
            if (best_score < conf_thres) continue;
            if (!class_allowed(best_cls, obj_classes)) continue;

            // 2/3) 融合 DFL+box：gather → 连续 16-float → NEON 期望 → xyxy
            float dist[kSides];
            for (std::size_t side = 0; side < kSides; ++side) {
                gather_reg16(box_nchw, side, spatial, hw, logits);
                dist[side] = dfl_expect_reg16(logits);
            }

            const float gx = static_cast<float>(x) + 0.5f;
            const float gy = static_cast<float>(y) + 0.5f;

            DecodedBox box;
            box.x1 = (gx - dist[0]) * stride_w;
            box.y1 = (gy - dist[1]) * stride_h;
            box.x2 = (gx + dist[2]) * stride_w;
            box.y2 = (gy + dist[3]) * stride_h;
            box.score = best_score;
            box.class_id = best_cls;
            out.push_back(box);
        }
    }
}

}  // namespace postprocess
}  // namespace yolo

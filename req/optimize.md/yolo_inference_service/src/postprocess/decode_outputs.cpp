/**
 * @file decode_outputs.cpp
 * @brief decode_rknn_outputs：score-first 融合 DFL → scale → per-class NMS。
 */

#include "decode_outputs.h"

#include "dfl_decode.h"

#include <algorithm>
#include <cstdio>
#include <set>
#include <stdexcept>
#include <vector>

#include <xtensor/xadapt.hpp>
#include <xtensor/xbuilder.hpp>

namespace yolo {
namespace postprocess {
namespace {

constexpr int kPairPerBranch = 3;
constexpr std::size_t kBoxChannels = 64;  // 4 * reg_max

FrameDetections make_empty_frame(const inference::InferRawResult& raw) {
    FrameDetections out;
    out.stream_id = raw.stream_id;
    out.seq = raw.seq;
    out.generation = raw.generation;
    out.letterbox = raw.letterbox;
    out.worker_id = raw.worker_id;
    out.core_mask = raw.core_mask;
    out.captured_at = raw.captured_at;
    out.stream_time_sec = raw.stream_time_sec;
    out.has_stream_time = raw.has_stream_time;
    return out;
}

std::vector<std::size_t> nms_decoded(const std::vector<DecodedBox>& boxes,
                                     const std::vector<std::size_t>& idx,
                                     float iou_thres) {
    const std::size_t n = idx.size();
    if (n == 0) return {};

    std::vector<float> x1(n), y1(n), x2(n), y2(n), areas(n), sc(n);
    for (std::size_t i = 0; i < n; ++i) {
        const auto& b = boxes[idx[i]];
        x1[i] = b.x1;
        y1[i] = b.y1;
        x2[i] = b.x2;
        y2[i] = b.y2;
        areas[i] = (x2[i] - x1[i]) * (y2[i] - y1[i]);
        sc[i] = b.score;
    }

    std::vector<std::size_t> order(n);
    for (std::size_t i = 0; i < n; ++i) order[i] = i;
    std::sort(order.begin(), order.end(),
              [&](std::size_t a, std::size_t b) { return sc[a] > sc[b]; });

    std::vector<std::size_t> keep;
    keep.reserve(n);
    std::vector<char> suppressed(n, 0);
    for (std::size_t oi = 0; oi < n; ++oi) {
        const std::size_t i = order[oi];
        if (suppressed[i]) continue;
        keep.push_back(idx[i]);
        for (std::size_t oj = oi + 1; oj < n; ++oj) {
            const std::size_t j = order[oj];
            if (suppressed[j]) continue;
            const float xx1 = std::max(x1[i], x1[j]);
            const float yy1 = std::max(y1[i], y1[j]);
            const float xx2 = std::min(x2[i], x2[j]);
            const float yy2 = std::min(y2[i], y2[j]);
            const float w = std::max(0.f, xx2 - xx1 + 1e-5f);
            const float h = std::max(0.f, yy2 - yy1 + 1e-5f);
            const float inter = w * h;
            const float ovr = inter / (areas[i] + areas[j] - inter);
            if (ovr > iou_thres) suppressed[j] = 1;
        }
    }
    return keep;
}

}  // namespace

FrameDetections decode_rknn_outputs(const inference::InferRawResult& raw,
                                    const DecodeConfig& cfg) {
    FrameDetections out = make_empty_frame(raw);

    const auto& tensors = raw.tensors;
    if (tensors.empty()) {
        return out;
    }
    if (static_cast<int>(tensors.size()) < kPairPerBranch ||
        tensors.size() % kPairPerBranch != 0) {
        std::fprintf(stderr,
                     "[postprocess] unexpected tensor count=%zu "
                     "(need multiple of 3)\n",
                     tensors.size());
        return out;
    }

    const int branch_count =
        static_cast<int>(tensors.size()) / kPairPerBranch;

    try {
        std::vector<DecodedBox> cands;
        cands.reserve(256);

        for (int i = 0; i < branch_count; ++i) {
            const auto& box_t =
                tensors[static_cast<std::size_t>(kPairPerBranch * i + 0)];
            const auto& cls_t =
                tensors[static_cast<std::size_t>(kPairPerBranch * i + 1)];

            if (!box_t.shape_matches_data() || !cls_t.shape_matches_data()) {
                throw std::invalid_argument("tensor dims/data size mismatch");
            }
            if (box_t.dims.size() != 4 || cls_t.dims.size() != 4 ||
                box_t.dims[0] != 1 || cls_t.dims[0] != 1) {
                throw std::invalid_argument("expect NCHW with N=1");
            }
            if (box_t.dims[1] != kBoxChannels) {
                throw std::invalid_argument("box channels must be 64 (DFL)");
            }
            if (box_t.dims[2] != cls_t.dims[2] ||
                box_t.dims[3] != cls_t.dims[3]) {
                throw std::invalid_argument("box/cls spatial mismatch");
            }

            const std::size_t nc = cls_t.dims[1];
            const std::size_t gh = box_t.dims[2];
            const std::size_t gw = box_t.dims[3];

            decode_branch_score_first(box_t.data.data(), cls_t.data.data(), nc,
                                      gh, gw, cfg.imgsz, cfg.conf_thres,
                                      cfg.obj_classes, cands);
        }

        if (cands.empty()) {
            return out;
        }

        for (auto& b : cands) {
            scale_decoded_box_to_orig(b, raw.letterbox);
        }

        std::set<int> unique_cls;
        for (const auto& b : cands) unique_cls.insert(b.class_id);

        std::vector<Detection> dets;
        dets.reserve(cands.size());
        for (int cls_id : unique_cls) {
            std::vector<std::size_t> mask;
            for (std::size_t i = 0; i < cands.size(); ++i) {
                if (cands[i].class_id == cls_id) mask.push_back(i);
            }
            auto keep = nms_decoded(cands, mask, cfg.iou_thres);
            for (std::size_t idx : keep) {
                const auto& b = cands[idx];
                Detection d;
                d.x1 = static_cast<int>(b.x1);
                d.y1 = static_cast<int>(b.y1);
                d.x2 = static_cast<int>(b.x2);
                d.y2 = static_cast<int>(b.y2);
                d.score = b.score;
                d.class_id = cls_id;
                dets.push_back(d);
            }
        }

        std::sort(dets.begin(), dets.end(),
                  [](const Detection& a, const Detection& b) {
                      return a.score > b.score;
                  });
        out.dets = std::move(dets);
    } catch (const std::exception& e) {
        std::fprintf(stderr,
                     "[postprocess] decode fail stream=%s seq=%llu: %s\n",
                     raw.stream_id.c_str(),
                     static_cast<unsigned long long>(raw.seq), e.what());
        out.dets.clear();
    }

    return out;
}

}  // namespace postprocess
}  // namespace yolo

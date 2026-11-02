/**
 * @file nms.cpp
 * @brief 贪心 NMS（与 Python `_nms` 同序：按 score 降序）。
 */

#include "nms.h"

#include <algorithm>
#include <cmath>
#include <numeric>
#include <stdexcept>

namespace yolo {
namespace postprocess {

std::vector<std::size_t> nms_xyxy(const xt::xarray<float>& boxes,
                                  const xt::xarray<float>& scores,
                                  float iou_thres) {
    if (boxes.dimension() != 2 || boxes.shape()[1] != 4) {
        throw std::invalid_argument("nms_xyxy: boxes must be (N,4)");
    }
    if (scores.dimension() != 1 || scores.shape()[0] != boxes.shape()[0]) {
        throw std::invalid_argument("nms_xyxy: scores shape mismatch");
    }

    const std::size_t n = boxes.shape()[0];
    if (n == 0) return {};

    std::vector<float> x1(n), y1(n), x2(n), y2(n), areas(n), sc(n);
    for (std::size_t i = 0; i < n; ++i) {
        x1[i] = boxes(i, 0);
        y1[i] = boxes(i, 1);
        x2[i] = boxes(i, 2);
        y2[i] = boxes(i, 3);
        areas[i] = (x2[i] - x1[i]) * (y2[i] - y1[i]);
        sc[i] = scores(i);
    }

    std::vector<std::size_t> order(n);
    std::iota(order.begin(), order.end(), 0);
    std::sort(order.begin(), order.end(),
              [&](std::size_t a, std::size_t b) { return sc[a] > sc[b]; });

    std::vector<std::size_t> keep;
    keep.reserve(n);
    while (!order.empty()) {
        const std::size_t i = order[0];
        keep.push_back(i);

        std::vector<std::size_t> rest;
        rest.reserve(order.size());
        for (std::size_t k = 1; k < order.size(); ++k) {
            const std::size_t j = order[k];
            const float xx1 = std::max(x1[i], x1[j]);
            const float yy1 = std::max(y1[i], y1[j]);
            const float xx2 = std::min(x2[i], x2[j]);
            const float yy2 = std::min(y2[i], y2[j]);
            const float w = std::max(0.f, xx2 - xx1 + 1e-5f);
            const float h = std::max(0.f, yy2 - yy1 + 1e-5f);
            const float inter = w * h;
            const float ovr = inter / (areas[i] + areas[j] - inter);
            if (ovr <= iou_thres) {
                rest.push_back(j);
            }
        }
        order.swap(rest);
    }
    return keep;
}

}  // namespace postprocess
}  // namespace yolo

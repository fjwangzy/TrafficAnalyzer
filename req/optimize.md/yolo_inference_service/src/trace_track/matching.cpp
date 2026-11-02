/**
 * @file matching.cpp
 * @brief IoU / fuse / Hungarian / linear_assignment。
 */

#include "matching.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <set>

#include <xtensor/xbuilder.hpp>
#include <xtensor/xview.hpp>

namespace yolo {
namespace trace_track {
namespace {

/**
 * @brief 方形代价矩阵 Hungarian（Munkres），返回 row→col 指派（-1=未分配）。
 *
 * 非方阵时先 pad 到 max(n,m)，多余行/列代价为 0。
 */
std::vector<int> hungarian(const std::vector<float>& cost, int n_rows,
                           int n_cols) {
    const int n = std::max(n_rows, n_cols);
    const float INF = 1e9f;
    std::vector<float> a(static_cast<std::size_t>(n * n), 0.f);
    for (int i = 0; i < n_rows; ++i) {
        for (int j = 0; j < n_cols; ++j) {
            a[static_cast<std::size_t>(i * n + j)] =
                cost[static_cast<std::size_t>(i * n_cols + j)];
        }
    }

    // Kuhn-Munkres (assignment problem) — O(n^3)
    std::vector<float> u(n + 1, 0.f), v(n + 1, 0.f);
    std::vector<int> p(n + 1, 0), way(n + 1, 0);
    for (int i = 1; i <= n; ++i) {
        p[0] = i;
        int j0 = 0;
        std::vector<float> minv(n + 1, INF);
        std::vector<char> used(n + 1, 0);
        do {
            used[j0] = 1;
            int i0 = p[j0];
            float delta = INF;
            int j1 = 0;
            for (int j = 1; j <= n; ++j) {
                if (used[j]) continue;
                float cur =
                    a[static_cast<std::size_t>((i0 - 1) * n + (j - 1))] -
                    u[i0] - v[j];
                if (cur < minv[j]) {
                    minv[j] = cur;
                    way[j] = j0;
                }
                if (minv[j] < delta) {
                    delta = minv[j];
                    j1 = j;
                }
            }
            for (int j = 0; j <= n; ++j) {
                if (used[j]) {
                    u[p[j]] += delta;
                    v[j] -= delta;
                } else {
                    minv[j] -= delta;
                }
            }
            j0 = j1;
        } while (p[j0] != 0);
        do {
            int j1 = way[j0];
            p[j0] = p[j1];
            j0 = j1;
        } while (j0);
    }

    std::vector<int> assignment(n_rows, -1);
    for (int j = 1; j <= n; ++j) {
        if (p[j] == 0) continue;
        int row = p[j] - 1;
        int col = j - 1;
        if (row < n_rows && col < n_cols) {
            assignment[row] = col;
        }
    }
    return assignment;
}

}  // namespace

xt::xarray<float> ious(const xt::xarray<float>& atlbrs,
                       const xt::xarray<float>& btlbrs) {
    const auto ma = atlbrs.shape().size() >= 1 ? atlbrs.shape(0) : 0;
    const auto nb = btlbrs.shape().size() >= 1 ? btlbrs.shape(0) : 0;
    if (ma == 0 || nb == 0) {
        return xt::zeros<float>({ma, nb});
    }

    xt::xarray<float> out = xt::zeros<float>({ma, nb});
    for (std::size_t i = 0; i < ma; ++i) {
        const float ax1 = atlbrs(i, 0);
        const float ay1 = atlbrs(i, 1);
        const float ax2 = atlbrs(i, 2);
        const float ay2 = atlbrs(i, 3);
        const float area_a = (ax2 - ax1) * (ay2 - ay1);
        for (std::size_t j = 0; j < nb; ++j) {
            const float bx1 = btlbrs(j, 0);
            const float by1 = btlbrs(j, 1);
            const float bx2 = btlbrs(j, 2);
            const float by2 = btlbrs(j, 3);
            const float area_b = (bx2 - bx1) * (by2 - by1);
            const float lx = std::max(ax1, bx1);
            const float ly = std::max(ay1, by1);
            const float rx = std::min(ax2, bx2);
            const float ry = std::min(ay2, by2);
            const float w = std::max(0.f, rx - lx);
            const float h = std::max(0.f, ry - ly);
            const float inter = w * h;
            const float uni = area_a + area_b - inter;
            out(i, j) = uni > 0.f ? inter / uni : 0.f;
        }
    }
    return out;
}

xt::xarray<float> iou_distance(const std::vector<STrackPtr>& atracks,
                               const std::vector<STrackPtr>& btracks) {
    const auto ma = atracks.size();
    const auto nb = btracks.size();
    if (ma == 0 || nb == 0) {
        return xt::zeros<float>({ma, nb});
    }
    xt::xarray<float> a = xt::zeros<float>({ma, static_cast<std::size_t>(4)});
    xt::xarray<float> b = xt::zeros<float>({nb, static_cast<std::size_t>(4)});
    for (std::size_t i = 0; i < ma; ++i) {
        auto tlbr = atracks[i]->tlbr();
        for (int k = 0; k < 4; ++k) a(i, k) = tlbr[static_cast<std::size_t>(k)];
    }
    for (std::size_t j = 0; j < nb; ++j) {
        auto tlbr = btracks[j]->tlbr();
        for (int k = 0; k < 4; ++k) b(j, k) = tlbr[static_cast<std::size_t>(k)];
    }
    auto iou = ious(a, b);
    return 1.f - iou;
}

xt::xarray<float> fuse_score(const xt::xarray<float>& cost_matrix,
                             const std::vector<STrackPtr>& detections) {
    if (cost_matrix.size() == 0) return cost_matrix;
    const auto rows = cost_matrix.shape(0);
    const auto cols = cost_matrix.shape(1);
    xt::xarray<float> out = xt::zeros<float>({rows, cols});
    for (std::size_t i = 0; i < rows; ++i) {
        for (std::size_t j = 0; j < cols; ++j) {
            const float iou_sim = 1.f - cost_matrix(i, j);
            const float score =
                j < detections.size() ? detections[j]->score : 0.f;
            out(i, j) = 1.f - iou_sim * score;
        }
    }
    return out;
}

AssignmentResult linear_assignment(const xt::xarray<float>& cost_matrix,
                                   float thresh) {
    AssignmentResult res;
    if (cost_matrix.size() == 0) {
        const auto rows =
            cost_matrix.dimension() >= 1 ? cost_matrix.shape(0) : 0;
        const auto cols =
            cost_matrix.dimension() >= 2 ? cost_matrix.shape(1) : 0;
        for (std::size_t i = 0; i < rows; ++i)
            res.unmatched_a.push_back(static_cast<int>(i));
        for (std::size_t j = 0; j < cols; ++j)
            res.unmatched_b.push_back(static_cast<int>(j));
        return res;
    }

    const int n_rows = static_cast<int>(cost_matrix.shape(0));
    const int n_cols = static_cast<int>(cost_matrix.shape(1));
    std::vector<float> masked(static_cast<std::size_t>(n_rows * n_cols));
    for (int i = 0; i < n_rows; ++i) {
        for (int j = 0; j < n_cols; ++j) {
            float c = cost_matrix(i, j);
            if (c > thresh) c = thresh + 1e5f;
            masked[static_cast<std::size_t>(i * n_cols + j)] = c;
        }
    }

    auto assignment = hungarian(masked, n_rows, n_cols);
    std::set<int> matched_a;
    std::set<int> matched_b;
    for (int r = 0; r < n_rows; ++r) {
        int c = assignment[static_cast<std::size_t>(r)];
        if (c < 0) continue;
        if (cost_matrix(r, c) <= thresh) {
            res.matches.emplace_back(r, c);
            matched_a.insert(r);
            matched_b.insert(c);
        }
    }
    for (int i = 0; i < n_rows; ++i) {
        if (!matched_a.count(i)) res.unmatched_a.push_back(i);
    }
    for (int j = 0; j < n_cols; ++j) {
        if (!matched_b.count(j)) res.unmatched_b.push_back(j);
    }
    return res;
}

}  // namespace trace_track
}  // namespace yolo

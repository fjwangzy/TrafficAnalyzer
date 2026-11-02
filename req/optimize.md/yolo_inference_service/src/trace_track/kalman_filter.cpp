/**
 * @file kalman_filter.cpp
 * @brief KalmanFilter：initiate / predict / project / update / multi_predict。
 */

#include "kalman_filter.h"

#include <cmath>
#include <stdexcept>

#include <xtensor/xbuilder.hpp>
#include <xtensor/xview.hpp>

namespace yolo {
namespace trace_track {
namespace {

bool cholesky_lower(const float* A, float* L, int n) {
    for (int i = 0; i < n; ++i) {
        for (int j = 0; j <= i; ++j) {
            float sum = A[i * n + j];
            for (int k = 0; k < j; ++k) {
                sum -= L[i * n + k] * L[j * n + k];
            }
            if (i == j) {
                if (sum <= 1e-12f) return false;
                L[i * n + j] = std::sqrt(sum);
            } else {
                L[i * n + j] = sum / L[j * n + j];
            }
        }
        for (int j = i + 1; j < n; ++j) L[i * n + j] = 0.f;
    }
    return true;
}

void forward_sub(const float* L, const float* b, float* y, int n) {
    for (int i = 0; i < n; ++i) {
        float sum = b[i];
        for (int j = 0; j < i; ++j) sum -= L[i * n + j] * y[j];
        y[i] = sum / L[i * n + i];
    }
}

void back_sub(const float* L, const float* y, float* x, int n) {
    for (int i = n - 1; i >= 0; --i) {
        float sum = y[i];
        for (int j = i + 1; j < n; ++j) sum -= L[j * n + i] * x[j];
        x[i] = sum / L[i * n + i];
    }
}

bool cho_solve(const float* A, const float* B, float* X, int n, int m) {
    float L[16];
    if (n > 4) return false;
    if (!cholesky_lower(A, L, n)) return false;
    float y[4], col_b[4], col_x[4];
    for (int c = 0; c < m; ++c) {
        for (int r = 0; r < n; ++r) col_b[r] = B[r * m + c];
        forward_sub(L, col_b, y, n);
        back_sub(L, y, col_x, n);
        for (int r = 0; r < n; ++r) X[r * m + c] = col_x[r];
    }
    return true;
}

KalmanCov diag_sq(const float* std8) {
    KalmanCov cov = xt::zeros<float>({8, 8});
    for (int i = 0; i < 8; ++i) cov(i, i) = std8[i] * std8[i];
    return cov;
}

}  // namespace

KalmanFilter::KalmanFilter() {
    motion_mat_ = xt::eye<float>(8);
    for (int i = 0; i < 4; ++i) motion_mat_(i, 4 + i) = 1.f;
    update_mat_ = xt::zeros<float>({4, 8});
    for (int i = 0; i < 4; ++i) update_mat_(i, i) = 1.f;
}

std::pair<KalmanMean, KalmanCov> KalmanFilter::initiate(
    const KalmanMeas& measurement) const {
    KalmanMean mean = xt::zeros<float>({8});
    for (int i = 0; i < 4; ++i) mean(i) = measurement(i);
    const float h = measurement(3);
    // 噪声统一锚定高度 h：宽若按自身缩放，入镜初期 w 小→噪声小→涨不动。
    float stdv[8] = {
        2.f * std_weight_position_ * h,
        2.f * std_weight_position_ * h,
        2.f * std_weight_position_ * h,
        2.f * std_weight_position_ * h,
        10.f * std_weight_velocity_ * h,
        10.f * std_weight_velocity_ * h,
        10.f * std_weight_velocity_ * h,
        10.f * std_weight_velocity_ * h,
    };
    return {mean, diag_sq(stdv)};
}

std::pair<KalmanMean, KalmanCov> KalmanFilter::predict(
    const KalmanMean& mean, const KalmanCov& covariance) const {
    const float h = mean(3);
    float stdv[8] = {
        std_weight_position_ * h,
        std_weight_position_ * h,
        std_weight_position_ * h,
        std_weight_position_ * h,
        std_weight_velocity_ * h,
        std_weight_velocity_ * h,
        std_weight_velocity_ * h,
        std_weight_velocity_ * h,
    };
    KalmanCov motion_cov = diag_sq(stdv);

    KalmanMean new_mean = xt::zeros<float>({8});
    for (int i = 0; i < 8; ++i) {
        float s = 0.f;
        for (int j = 0; j < 8; ++j) s += motion_mat_(i, j) * mean(j);
        new_mean(i) = s;
    }

    KalmanCov tmp = xt::zeros<float>({8, 8});
    for (int i = 0; i < 8; ++i) {
        for (int j = 0; j < 8; ++j) {
            float s = 0.f;
            for (int k = 0; k < 8; ++k)
                s += motion_mat_(i, k) * covariance(k, j);
            tmp(i, j) = s;
        }
    }
    KalmanCov new_cov = xt::zeros<float>({8, 8});
    for (int i = 0; i < 8; ++i) {
        for (int j = 0; j < 8; ++j) {
            float s = 0.f;
            for (int k = 0; k < 8; ++k) s += tmp(i, k) * motion_mat_(j, k);
            new_cov(i, j) = s + motion_cov(i, j);
        }
    }
    return {new_mean, new_cov};
}

std::pair<KalmanMean, KalmanCov> KalmanFilter::project(
    const KalmanMean& mean, const KalmanCov& covariance) const {
    const float h = mean(3);
    float std_obs[4] = {
        std_weight_position_ * h,
        std_weight_position_ * h,
        std_weight_position_ * h,
        std_weight_position_ * h,
    };

    KalmanMean proj_mean = xt::zeros<float>({4});
    for (int i = 0; i < 4; ++i) {
        float s = 0.f;
        for (int j = 0; j < 8; ++j) s += update_mat_(i, j) * mean(j);
        proj_mean(i) = s;
    }

    float cov4[16] = {0};
    float tmp[32] = {0};
    for (int i = 0; i < 4; ++i) {
        for (int j = 0; j < 8; ++j) {
            float s = 0.f;
            for (int k = 0; k < 8; ++k)
                s += update_mat_(i, k) * covariance(k, j);
            tmp[i * 8 + j] = s;
        }
    }
    for (int i = 0; i < 4; ++i) {
        for (int j = 0; j < 4; ++j) {
            float s = 0.f;
            for (int k = 0; k < 8; ++k) s += tmp[i * 8 + k] * update_mat_(j, k);
            cov4[i * 4 + j] = s;
        }
        cov4[i * 4 + i] += std_obs[i] * std_obs[i];
    }

    // 返回 4 维 mean 与 4×4 cov（打包在 xarray 内；update 只读前 4）
    KalmanMean out_mean = proj_mean;
    KalmanCov out_cov = xt::zeros<float>({4, 4});
    for (int i = 0; i < 4; ++i)
        for (int j = 0; j < 4; ++j) out_cov(i, j) = cov4[i * 4 + j];
    return {out_mean, out_cov};
}

std::pair<KalmanMean, KalmanCov> KalmanFilter::update(
    const KalmanMean& mean, const KalmanCov& covariance,
    const KalmanMeas& measurement) const {
    auto projected = project(mean, covariance);
    const KalmanMean& projected_mean = projected.first;
    const KalmanCov& projected_cov = projected.second;

    float P[16];
    for (int i = 0; i < 4; ++i)
        for (int j = 0; j < 4; ++j) P[i * 4 + j] = projected_cov(i, j);

    float Bt[32];
    for (int r = 0; r < 4; ++r) {
        for (int c = 0; c < 8; ++c) {
            float s = 0.f;
            for (int k = 0; k < 8; ++k)
                s += covariance(c, k) * update_mat_(r, k);
            Bt[r * 8 + c] = s;
        }
    }

    float Xt[32];
    if (!cho_solve(P, Bt, Xt, 4, 8)) {
        return {mean, covariance};
    }
    float K[32];
    for (int i = 0; i < 8; ++i)
        for (int j = 0; j < 4; ++j) K[i * 4 + j] = Xt[j * 8 + i];

    float innov[4];
    for (int i = 0; i < 4; ++i) innov[i] = measurement(i) - projected_mean(i);

    KalmanMean new_mean = mean;
    for (int i = 0; i < 8; ++i) {
        float s = 0.f;
        for (int j = 0; j < 4; ++j) s += innov[j] * K[i * 4 + j];
        new_mean(i) = mean(i) + s;
    }

    float KP[32];
    for (int i = 0; i < 8; ++i) {
        for (int j = 0; j < 4; ++j) {
            float s = 0.f;
            for (int k = 0; k < 4; ++k) s += K[i * 4 + k] * P[k * 4 + j];
            KP[i * 4 + j] = s;
        }
    }
    KalmanCov new_cov = covariance;
    for (int i = 0; i < 8; ++i) {
        for (int j = 0; j < 8; ++j) {
            float s = 0.f;
            for (int k = 0; k < 4; ++k) s += KP[i * 4 + k] * K[j * 4 + k];
            new_cov(i, j) = covariance(i, j) - s;
        }
    }
    return {new_mean, new_cov};
}

void KalmanFilter::multi_predict(xt::xarray<float>& means,
                                 xt::xarray<float>& covariances) const {
    const auto n = static_cast<std::size_t>(means.shape(0));
    for (std::size_t i = 0; i < n; ++i) {
        KalmanMean m = xt::zeros<float>({8});
        KalmanCov c = xt::zeros<float>({8, 8});
        for (int j = 0; j < 8; ++j) m(j) = means(i, j);
        for (int r = 0; r < 8; ++r)
            for (int col = 0; col < 8; ++col)
                c(r, col) = covariances(i, r, col);
        auto out = predict(m, c);
        for (int j = 0; j < 8; ++j) means(i, j) = out.first(j);
        for (int r = 0; r < 8; ++r)
            for (int col = 0; col < 8; ++col)
                covariances(i, r, col) = out.second(r, col);
    }
}

xt::xarray<float> KalmanFilter::gating_distance(
    const KalmanMean& mean, const KalmanCov& covariance,
    const xt::xarray<float>& measurements, bool only_position,
    const std::string& metric) const {
    auto projected = project(mean, covariance);
    int dim = only_position ? 2 : 4;
    const std::size_t N = measurements.shape(0);
    xt::xarray<float> out = xt::zeros<float>({N});

    float mean_v[4];
    float cov_m[16];
    for (int i = 0; i < dim; ++i) {
        mean_v[i] = projected.first(i);
        for (int j = 0; j < dim; ++j)
            cov_m[i * dim + j] = projected.second(i, j);
    }

    if (metric == "gaussian") {
        for (std::size_t n = 0; n < N; ++n) {
            float s = 0.f;
            for (int i = 0; i < dim; ++i) {
                float d = measurements(n, i) - mean_v[i];
                s += d * d;
            }
            out(n) = s;
        }
        return out;
    }
    if (metric != "maha") {
        throw std::invalid_argument("invalid distance metric: " + metric);
    }

    float L[16];
    if (!cholesky_lower(cov_m, L, dim)) return out;
    for (std::size_t n = 0; n < N; ++n) {
        float d[4];
        for (int i = 0; i < dim; ++i) d[i] = measurements(n, i) - mean_v[i];
        float z[4];
        forward_sub(L, d, z, dim);
        float s = 0.f;
        for (int i = 0; i < dim; ++i) s += z[i] * z[i];
        out(n) = s;
    }
    return out;
}

}  // namespace trace_track
}  // namespace yolo

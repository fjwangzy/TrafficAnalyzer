/**
 * @file kalman_filter.h
 * @brief ByteTrack 8 维边界框卡尔曼滤波（xtensor）。
 */

#ifndef YOLO_TRACE_TRACK_KALMAN_FILTER_H_
#define YOLO_TRACE_TRACK_KALMAN_FILTER_H_

#include <string>
#include <utility>
#include <vector>

#include <xtensor/xarray.hpp>

namespace yolo {
namespace trace_track {

/** 8 维均值。 */
using KalmanMean = xt::xarray<float>;
/** 8×8 协方差。 */
using KalmanCov = xt::xarray<float>;
/** 4 维观测 (x, y, w, h)。 */
using KalmanMeas = xt::xarray<float>;

class KalmanFilter {
public:
    KalmanFilter();

    std::pair<KalmanMean, KalmanCov> initiate(const KalmanMeas& measurement) const;

    std::pair<KalmanMean, KalmanCov> predict(const KalmanMean& mean,
                                            const KalmanCov& covariance) const;

    std::pair<KalmanMean, KalmanCov> project(const KalmanMean& mean,
                                            const KalmanCov& covariance) const;

    std::pair<KalmanMean, KalmanCov> update(const KalmanMean& mean,
                                           const KalmanCov& covariance,
                                           const KalmanMeas& measurement) const;

    void multi_predict(xt::xarray<float>& means,
                       xt::xarray<float>& covariances) const;

    xt::xarray<float> gating_distance(const KalmanMean& mean,
                                      const KalmanCov& covariance,
                                      const xt::xarray<float>& measurements,
                                      bool only_position = false,
                                      const std::string& metric = "maha") const;

private:
    xt::xarray<float> motion_mat_;   // 8x8
    xt::xarray<float> update_mat_;   // 4x8
    float std_weight_position_ = 1.f / 20.f;
    float std_weight_velocity_ = 1.f / 160.f;
};

}  // namespace trace_track
}  // namespace yolo

#endif  /* YOLO_TRACE_TRACK_KALMAN_FILTER_H_ */

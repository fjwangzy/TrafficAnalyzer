/**
 * @file nms.h
 * @brief 单类别贪心 NMS（xyxy），对齐 postprocess.py `_nms`。
 */

#ifndef YOLO_POSTPROCESS_NMS_H_
#define YOLO_POSTPROCESS_NMS_H_

#include <vector>

#include <xtensor/xarray.hpp>

namespace yolo {
namespace postprocess {

/**
 * @brief 单类别 NMS。
 * @param boxes  `(N,4)` xyxy。
 * @param scores `(N,)`。
 * @param iou_thres IoU 阈值。
 * @return 保留框在输入中的下标。
 */
std::vector<std::size_t> nms_xyxy(const xt::xarray<float>& boxes,
                                  const xt::xarray<float>& scores,
                                  float iou_thres);

}  // namespace postprocess
}  // namespace yolo

#endif  /* YOLO_POSTPROCESS_NMS_H_ */

/**
 * @file dfl_decode.h
 * @brief DFL 解码与框过滤 / letterbox 坐标还原。
 *
 * 对齐 postprocess.py：_dfl / _box_process / _sp_flatten / _filter_boxes /
 * _scale_boxes_to_orig。热路径使用 score-first + 融合 DFL/box（NEON）。
 */

#ifndef YOLO_POSTPROCESS_DFL_DECODE_H_
#define YOLO_POSTPROCESS_DFL_DECODE_H_

#include <cstddef>
#include <tuple>
#include <utility>
#include <vector>

#include <xtensor/xarray.hpp>

#include "../preprocess/types.h"

namespace yolo {
namespace postprocess {

/** @brief letterbox 坐标系下的浮点候选框（NMS / scale 前）。 */
struct DecodedBox {
    float x1 = 0.f;
    float y1 = 0.f;
    float x2 = 0.f;
    float y2 = 0.f;
    float score = 0.f;
    int class_id = 0;
};

/**
 * @brief Distribution Focal Loss 解码（全网格参考实现）。
 * @param position 形状 `(n, 4*reg_max, h, w)`。
 * @return `(n, 4, h, w)` 到四边的距离（grid 单位）。
 */
xt::xarray<float> dfl(const xt::xarray<float>& position);

/**
 * @brief 单尺度 box 分布 → letterbox 坐标系 xyxy（全网格）。
 * @param position 形状 `(1, 64, h, w)`（reg_max=16）。
 * @param imgsz 模型输入边长（640）。
 * @return `(1, 4, h, w)` xyxy。
 */
xt::xarray<float> box_process(const xt::xarray<float>& position, int imgsz);

/**
 * @brief `(1, c, h, w)` → `(h*w, c)`。
 */
xt::xarray<float> sp_flatten(const xt::xarray<float>& arr);

/**
 * @brief 按类别最大分数过滤。
 * @return (boxes_xyxy [N,4], class_ids [N], scores [N])。
 */
std::tuple<xt::xarray<float>, xt::xarray<int>, xt::xarray<float>>
filter_boxes(const xt::xarray<float>& boxes,
             const xt::xarray<float>& class_scores,
             float conf_thres);

/**
 * @brief letterbox xyxy → 原图像素坐标（对齐 LetterboxMeta）。
 */
xt::xarray<float> scale_boxes_to_orig(const xt::xarray<float>& boxes,
                                      const preprocess::LetterboxMeta& meta);

/**
 * @brief 将单个浮点框从 letterbox 还原到原图（原地）。
 */
void scale_decoded_box_to_orig(DecodedBox& box,
                               const preprocess::LetterboxMeta& meta);

/**
 * @brief Score-first + 融合 DFL/box：仅对 conf 过阈格子做 DFL。
 *
 * box/cls 均为 NCHW 连续缓冲：box `(1, 4*reg_max, H, W)`、cls `(1, nc, H, W)`。
 * 候选追加到 @p out（letterbox 坐标，尚未 scale / NMS）。
 *
 * @param obj_classes 非空时仅保留白名单类别；空 = 不过滤。
 */
void decode_branch_score_first(const float* box_nchw,
                               const float* cls_nchw,
                               std::size_t nc,
                               std::size_t grid_h,
                               std::size_t grid_w,
                               int imgsz,
                               float conf_thres,
                               const std::vector<int>& obj_classes,
                               std::vector<DecodedBox>& out);

}  // namespace postprocess
}  // namespace yolo

#endif  /* YOLO_POSTPROCESS_DFL_DECODE_H_ */

/**
 * @file types.h
 * @brief 后处理共享类型：Detection / FrameDetections / DecodeConfig。
 *
 * 对应计划：plans/postprocess_dfl_nms_xtensor_plan.md
 * 对齐 Python：decode_rknn_outputs 返回的 dict 列表。
 */

#ifndef YOLO_POSTPROCESS_TYPES_H_
#define YOLO_POSTPROCESS_TYPES_H_

#include <cstdint>
#include <string>
#include <vector>

#include "../preprocess/types.h"

namespace yolo {
namespace postprocess {

/** 单框检测结果（原图像素坐标，整数框）。 */
struct Detection {
    int x1 = 0;
    int y1 = 0;
    int x2 = 0;
    int y2 = 0;
    float score = 0.f;
    int class_id = -1;
    int track_id = -1;       /**< ByteTrack 轨迹 ID；原始通道保持 -1 */
    std::string class_name;  /**< assemble 内 enrich；缺省空 */
};

/**
 * @brief 单帧后处理结果（含身份旁路键，供重排/追踪）。
 */
struct FrameDetections {
    std::string stream_id;
    uint64_t seq = 0;
    uint64_t generation = 0;
    preprocess::LetterboxMeta letterbox;
    std::vector<Detection> dets;
    int worker_id = -1;
    int core_mask = -1;
    double captured_at = 0.0;        /**< D4：上游采集时刻透传（缺省 0） */
    double stream_time_sec = 0.0;    /**< D4：上游流时间轴秒 */
    bool has_stream_time = false;
};

/**
 * @brief DFL/NMS 解码参数（对齐 postprocess.py 默认值）。
 */
struct DecodeConfig {
    float conf_thres = 0.25f;
    float iou_thres = 0.45f;
    int imgsz = preprocess::kNetSize;
    /** 空 = 不过滤；非空则仅保留列表中的 class_id。 */
    std::vector<int> obj_classes;
};

}  // namespace postprocess
}  // namespace yolo

#endif  /* YOLO_POSTPROCESS_TYPES_H_ */

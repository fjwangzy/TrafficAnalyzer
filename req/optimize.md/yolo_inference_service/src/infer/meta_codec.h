/**
 * @file meta_codec.h
 * @brief InferMeta <-> InferJob::user_meta 紧凑编解码（身份旁路）。
 *
 * rknn_engine 强制意见 8：业务身份以不透明字节随任务往返，组件不解析。
 * 布局（小端、无对齐填充，手工定长头 + 变长字符串）：
 *   [u32 magic][u32 slot][str stream_id][u64 seq][u64 gen]
 *   [f64 scale][i32 pad_x][i32 pad_y][i32 dst_w][i32 dst_h][i32 new_w][i32 new_h]
 *   [i32 src_w][i32 src_h][f64 captured_at][u8 has_st][f64 stream_time_sec]
 */

#ifndef YOLO_INFER_META_CODEC_H_
#define YOLO_INFER_META_CODEC_H_

#include <cstdint>
#include <string>
#include <vector>

#include "../preprocess/types.h"

namespace yolo {
namespace infer {

struct InferMeta {
    uint32_t slot_index = 0;
    std::string stream_id;
    uint64_t seq = 0;
    uint64_t generation = 0;
    preprocess::LetterboxMeta letterbox;
    double captured_at = 0.0;
    double stream_time_sec = 0.0;
    bool has_stream_time = false;
};

std::vector<uint8_t> pack_meta(const InferMeta& m);
bool unpack_meta(const std::vector<uint8_t>& raw, InferMeta* out);

}  // namespace infer
}  // namespace yolo

#endif  /* YOLO_INFER_META_CODEC_H_ */

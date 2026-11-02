/**
 * @file wire_pack.h
 * @brief OrderedFrameDetections → InferenceUpdate msgpack bytes。
 */

#ifndef YOLO_COMM_SERVER_WIRE_PACK_H_
#define YOLO_COMM_SERVER_WIRE_PACK_H_

#include <cstdint>
#include <string>
#include <vector>

#include <msgpack.hpp>

#include "../reorder/types.h"

namespace yolo {
namespace comm_server {

/** 将 result map 写入已有 packer（供控制面嵌套应答）。 */
void pack_wire_result_map(msgpack::packer<msgpack::sbuffer>& pk,
                          const reorder::OrderedFrameDetections& frame);

bool pack_inference_update(bool is_latest, double inferred_at,
                           const reorder::OrderedFrameDetections& frame,
                           std::vector<uint8_t>* out);

bool pack_wire_result(const reorder::OrderedFrameDetections& frame,
                      std::vector<uint8_t>* out);

}  // namespace comm_server
}  // namespace yolo

#endif  /* YOLO_COMM_SERVER_WIRE_PACK_H_ */

/**
 * @file rga3_preprocess.h
 * @brief 仅 RGA3：NV12→RGB888 letterbox 写 LocalRgbRing 槽中心（禁止 imfill/RGA2）。
 */

#ifndef YOLO_PREPROCESS_RGA3_PREPROCESS_H_
#define YOLO_PREPROCESS_RGA3_PREPROCESS_H_

#include "local_rgb_ring.h"
#include "types.h"

#include <cstdint>
#include <vector>

namespace yolo {
namespace preprocess {

/**
 * @brief RGA3 前处理器：同步 im*；dst handle 按槽缓存。
 *
 * 线程模型：仅由单条 RGA 工作线程调用。
 */
class Rga3Preprocess {
public:
    explicit Rga3Preprocess(int net_size = preprocess::kNetSize);
    ~Rga3Preprocess();

    Rga3Preprocess(const Rga3Preprocess&) = delete;
    Rga3Preprocess& operator=(const Rga3Preprocess&) = delete;

    /**
     * @brief 为 LocalRgbRing 各槽 import 一次并缓存 handle。
     * @return true 成功。
     */
    bool bind_ring(LocalRgbRing& ring);

    /** @brief 释放全部已缓存 dst handle。 */
    void unbind_ring();

    /**
     * @brief 对 UpstreamFrame 做 letterbox 写入 ring 并 publish。
     * @return true 已 publish；false 失败或环忙。
     */
    bool process(UpstreamFrame&& frame, LocalRgbRing& ring,
                 bool drop_when_busy);

    /** @brief 累计失败次数。 */
    uint64_t fail_count() const { return fail_count_; }

private:
    LetterboxMeta compute_letterbox(const UpstreamFrame& f) const;
    bool ensure_rga3_core();
    uint32_t dst_handle_for(int slot_index);

    bool bound_ = false;
    bool core_ok_ = false;
    LocalRgbRing* ring_ = nullptr;
    std::vector<uint32_t> dst_handles_;  /**< rga_buffer_handle_t */
    uint64_t fail_count_ = 0;
    int net_ = preprocess::kNetSize;   /**< 网络边长（input_geometry 注入） */
    int last_new_w_ = -1;
    int last_new_h_ = -1;
};

}  // namespace preprocess
}  // namespace yolo

#endif  /* YOLO_PREPROCESS_RGA3_PREPROCESS_H_ */

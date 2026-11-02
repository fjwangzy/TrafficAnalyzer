/**
 * @file local_rgb_ring.h
 * @brief 本服务 RGB888 640×640 环：core_module RingBuffer 适配层。
 *
 * 环本体是 core_module/c_cpp_module 的 drn::core::RingBuffer（定长槽 +
 * DMA-BUF 底层 + RejectWrite）。本类保留 RGB 语义：槽 mmap+memset(114)、
 * LetterboxMeta/上游身份侧表（seq 哨兵保护）、publish/acquire/release。
 */

#ifndef YOLO_PREPROCESS_LOCAL_RGB_RING_H_
#define YOLO_PREPROCESS_LOCAL_RGB_RING_H_

#include "ring_buffer.h"
#include "types.h"

#include <atomic>
#include <cstdint>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

namespace yolo {
namespace preprocess {

/**
 * @brief LocalRgbRing：latest-wins 语义；槽 fd 长期存活；推理侧 acquire/release。
 */
class LocalRgbRing {
public:
    LocalRgbRing(int capacity, int net_w, int net_h, int channels);
    ~LocalRgbRing();

    LocalRgbRing(const LocalRgbRing&) = delete;
    LocalRgbRing& operator=(const LocalRgbRing&) = delete;

    bool ok() const { return ok_; }
    const char* allocator_name() const { return "core_ring:dmabuf"; }
    int capacity() const { return capacity_; }
    uint64_t latest_seq() const {
        return ring_ ? ring_->latest_seq() : 0;
    }

    /**
     * @brief 预留下一可写槽；目标槽被推理持有时返回 nullopt（丢帧）。
     * @param drop_when_busy  true 时全忙打印丢帧日志。
     */
    std::optional<int> acquire_publish_slot(bool drop_when_busy = true);

    /** @brief 槽 DMA-BUF fd（勿 close）。 */
    int slot_fd(int index) const;

    /** @brief 槽字节数。 */
    size_t slot_size() const { return slot_bytes_; }

    /**
     * @brief 几何变小时重新 memset(114) 该槽（仍在 DMA-BUF 上）。
     */
    void refill_pad(int index);

    /**
     * @brief 提交发布：写元数据侧表并推进 seq_local。
     */
    void publish_commit(int index, const LetterboxMeta& meta,
                        const std::string& upstream_stream_id,
                        uint64_t upstream_seq,
                        uint64_t upstream_generation);

    /**
     * @brief 取最新已发布帧；refcount++。
     */
    std::optional<LocalRgbFrame> acquire_latest();

    /**
     * @brief 按本地 seq 取帧；refcount++。
     */
    std::optional<LocalRgbFrame> acquire(uint64_t seq_local);

    /** @brief 推理结束归还。 */
    void release(int slot_index);

    /** @brief 槽当前 refcount。 */
    int refcount(int slot_index) const;

private:
    /** @brief 槽级领域元数据，seq 哨兵保护（core 环只管槽/序号/引用）。 */
    struct SideMeta {
        std::atomic<uint64_t> seq{0}; /**< 0=空；>0=已提交帧序号 */
        LetterboxMeta letterbox;
        std::string upstream_stream_id;
        uint64_t upstream_seq = 0;
        uint64_t upstream_generation = 0;
    };

    bool init_slots();
    bool mmap_memset_pad(int fd);

    int net_w_ = kNetSize;    /**< 槽几何（engine input_geometry 注入） */
    int net_h_ = kNetSize;
    size_t slot_bytes_ = kRgbSlotBytes;

    int capacity_ = 0;
    bool ok_ = false;
    std::unique_ptr<drn::core::RingBuffer> ring_; /**< core 环本体 */
    drn::core::PublishToken pending_; /**< 单写者当前 core 预留 */
    std::unique_ptr<SideMeta[]> side_; /**< 每槽领域元数据侧表 */
    mutable std::mutex meta_mu_;       /**< 保护 SideMeta 非原子字段 */
};

}  // namespace preprocess
}  // namespace yolo

#endif  /* YOLO_PREPROCESS_LOCAL_RGB_RING_H_ */

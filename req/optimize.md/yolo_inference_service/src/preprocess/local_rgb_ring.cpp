/**
 * @file local_rgb_ring.cpp
 * @brief LocalRgbRing 实现（core RingBuffer 适配，seq % capacity 槽映射）。
 *
 * 槽分配、seq 哨兵、refcount 覆盖保护全部复用 drn::core::RingBuffer；
 * 本文件只做 RGB 垫色 memset、LetterboxMeta/上游身份侧表的维护，
 * 以及“按槽下标 release”到“按 seq release”的换算。
 */

#include "local_rgb_ring.h"

#include <cstdio>
#include <cstring>

#include <sys/mman.h>
#include <unistd.h>

namespace yolo {
namespace preprocess {

LocalRgbRing::LocalRgbRing(int capacity, int net_w, int net_h, int channels)
    : capacity_(capacity < 2 ? 2 : capacity)
    , net_w_(net_w > 2 ? net_w : kNetSize)
    , net_h_(net_h > 2 ? net_h : kNetSize)
    , slot_bytes_(static_cast<size_t>(net_w_) *
                  static_cast<size_t>(net_h_) *
                  static_cast<size_t>(channels > 0 ? channels : 3)) {
    ok_ = init_slots();
    if (ok_) {
        std::fprintf(stderr,
                     "[LocalRgbRing] ready capacity=%d %dx%dx%d "
                     "slot_bytes=%zu backend=%s\n",
                     capacity_, net_w_, net_h_,
                     channels > 0 ? channels : 3, slot_bytes_,
                     allocator_name());
    }
}

LocalRgbRing::~LocalRgbRing() {
    ring_.reset();
    side_.reset();
    ok_ = false;
}

bool LocalRgbRing::mmap_memset_pad(int fd) {
    void* p = ::mmap(nullptr, slot_bytes_, PROT_READ | PROT_WRITE, MAP_SHARED,
                     fd, 0);
    if (p == MAP_FAILED) {
        std::perror("[LocalRgbRing] mmap");
        return false;
    }
    std::memset(p, kLetterboxPadValue, slot_bytes_);
    ::munmap(p, slot_bytes_);
    return true;
}

bool LocalRgbRing::init_slots() {
    drn::core::RingCreateConfig config;
    config.backing = drn::core::RingBacking::DmaBuf;
    config.full_policy = drn::core::FullPolicy::RejectWrite;
    config.width = net_w_;
    config.height = net_h_;
    ring_ = drn::core::RingBuffer::create_fixed(capacity_, slot_bytes_,
                                                config);
    if (!ring_) {
        std::fprintf(stderr, "[LocalRgbRing] core RingBuffer create failed\n");
        return false;
    }

    // core 环不负责垫色；每槽先整体 memset(114)。
    for (int i = 0; i < capacity_; ++i) {
        const int fd = ring_->slot_fd(i);
        if (fd < 0 || !mmap_memset_pad(fd)) {
            ring_.reset();
            return false;
        }
    }

    side_ = std::make_unique<SideMeta[]>(static_cast<size_t>(capacity_));
    return true;
}

std::optional<int> LocalRgbRing::acquire_publish_slot(bool drop_when_busy) {
    if (!ok_ || !ring_) return std::nullopt;

    // 上一帧 RGA 失败未 commit：先取消遗留预留，否则 core 环会一直拒绝新发布。
    if (pending_.valid) {
        ring_->publish_abort(pending_);
        pending_ = drn::core::PublishToken{};
    }

    drn::core::PublishToken token;
    if (!ring_->publish_begin(&token)) {
        if (drop_when_busy) {
            std::fprintf(stderr, "[LocalRgbRing] all slots busy, drop frame\n");
        }
        return std::nullopt;
    }
    pending_ = token;
    return token.index;
}

int LocalRgbRing::slot_fd(int index) const {
    return ring_ ? ring_->slot_fd(index) : -1;
}

void LocalRgbRing::refill_pad(int index) {
    if (!ring_ || index < 0 || index >= capacity_) return;
    const int fd = ring_->slot_fd(index);
    if (fd >= 0) mmap_memset_pad(fd);
}

void LocalRgbRing::publish_commit(int index, const LetterboxMeta& meta,
                                  const std::string& upstream_stream_id,
                                  uint64_t upstream_seq,
                                  uint64_t upstream_generation) {
    if (!ring_ || index < 0 || index >= capacity_) return;
    if (!pending_.valid || pending_.index != index) return;

    // 先写侧表（seq 哨兵最后落盘），再 core commit 发布序号，
    // 保证读者看到新 seq 时领域元数据一定已就绪。
    {
        std::lock_guard<std::mutex> lk(meta_mu_);
        SideMeta& entry = side_[static_cast<size_t>(index)];
        entry.letterbox = meta;
        entry.upstream_stream_id = upstream_stream_id;
        entry.upstream_seq = upstream_seq;
        entry.upstream_generation = upstream_generation;
        entry.seq.store(pending_.seq, std::memory_order_release);
    }

    drn::core::RingMetadata core_meta;
    core_meta.width = net_w_;
    core_meta.height = net_h_;
    core_meta.user0 = upstream_seq;
    core_meta.user1 = upstream_generation;
    if (!ring_->publish_commit(pending_, core_meta, slot_bytes_)) {
        // 提交失败回滚侧表哨兵，槽保持不可读。
        std::lock_guard<std::mutex> lk(meta_mu_);
        side_[static_cast<size_t>(index)].seq.store(0,
                                                    std::memory_order_release);
    }
    pending_ = drn::core::PublishToken{};
}

std::optional<LocalRgbFrame> LocalRgbRing::acquire_latest() {
    const uint64_t seq = latest_seq();
    if (seq == 0) return std::nullopt;
    return acquire(seq);
}

std::optional<LocalRgbFrame> LocalRgbRing::acquire(uint64_t seq_local) {
    if (!ok_ || !ring_ || seq_local == 0) return std::nullopt;
    const int index =
        static_cast<int>(seq_local % static_cast<uint64_t>(capacity_));

    if (!ring_->acquire(seq_local)) return std::nullopt;

    LocalRgbFrame out;
    {
        std::lock_guard<std::mutex> lk(meta_mu_);
        const SideMeta& entry = side_[static_cast<size_t>(index)];
        const uint64_t s1 = entry.seq.load(std::memory_order_acquire);
        if (s1 != seq_local) {
            // 槽元数据已被下一帧覆盖：core acquire 成功但侧表不一致，
            // 不可能发生（refcount 挡住覆盖），防御性回滚。
            ring_->release(seq_local);
            return std::nullopt;
        }
        out.letterbox = entry.letterbox;
        out.upstream_stream_id = entry.upstream_stream_id;
        out.upstream_seq = entry.upstream_seq;
        out.upstream_generation = entry.upstream_generation;
        if (entry.seq.load(std::memory_order_acquire) != s1) {
            ring_->release(seq_local);
            return std::nullopt;
        }
    }

    out.seq_local = seq_local;
    out.slot_index = index;
    out.dma_fd = ring_->slot_fd(index);
    out.slot_size = slot_bytes_;
    out.width = net_w_;
    out.height = net_h_;
    out.wstride = net_w_;
    return out;
}

void LocalRgbRing::release(int slot_index) {
    if (!ring_ || slot_index < 0 || slot_index >= capacity_) return;
    // 换算到当前槽内 seq；refcount>0 期间该槽不会被覆盖，seq 稳定。
    const uint64_t seq =
        side_[static_cast<size_t>(slot_index)].seq.load(std::memory_order_acquire);
    if (seq != 0) {
        ring_->release(seq);
    }
}

int LocalRgbRing::refcount(int slot_index) const {
    return ring_ ? ring_->refcount_at_index(slot_index) : 0;
}

}  // namespace preprocess
}  // namespace yolo

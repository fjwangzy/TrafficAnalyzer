/**
 * @file test_yolo_front_back.cpp
 * @brief yolo 前后端算法单测（纯 CPU，无 NPU / RGA 运行时依赖）。
 *
 * 覆盖：
 *   - letterbox 几何（对齐 Ultralytics ±0.1 舍入惯例）；
 *   - frame_meta 打包 / 解包往返（engine 身份旁路）；
 *   - DFL score-first 数值（均匀 logits → 期望 7.5）；
 *   - per-class NMS 抑制边界；
 *   - decode_rknn_outputs 编排（张量布局校验 / 异常回退 / 类别过滤）；
 *   - mock 引擎端到端链路（submit → pop → 解码，数值闭环）；
 *   - 配置缺省回退。
 */

#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <memory>
#include <vector>

#include "config.h"               // yolo::postprocess::load_decode_config
#include "../src/preprocess/config.h"
#include "../src/preprocess/rga3_preprocess.h"
#include "../src/preprocess/types.h"

#include "../src/postprocess/config.h"
#include "../src/postprocess/decode_outputs.h"
#include "../src/postprocess/dfl_decode.h"
#include "../src/postprocess/frame_meta.h"
#include "../src/postprocess/nms.h"
#include "../src/postprocess/types.h"

#include "engine.h"
#include "mock_backend.h"

using namespace drn::core::rknn;
using yolo::preprocess::LetterboxMeta;
using yolo::preprocess::UpstreamFrame;

namespace {

int g_failures = 0;

#define CHECK(cond)                                                     \
    do {                                                                \
        if (!(cond)) {                                                  \
            std::fprintf(stderr, "CHECK fail %s:%d: %s\n", __FILE__,    \
                         __LINE__, #cond);                              \
            ++g_failures;                                               \
        }                                                               \
    } while (0)

bool feq(float a, float b, float eps = 1e-3f) {
    return std::fabs(a - b) <= eps;
}

// ---- 1. letterbox 几何 ----
void test_letterbox_geometry() {
    yolo::preprocess::Rga3Preprocess rga;  // 未绑环 → net_size = kNetSize

    UpstreamFrame f;
    f.width = 1920;
    f.height = 1080;
    const auto m = rga.compute_letterbox(f);
    CHECK(feq(static_cast<float>(m.scale), 640.f / 1920.f));
    CHECK(m.new_w == 640);
    CHECK(m.new_h == 360);
    CHECK(m.pad_x == 0);
    CHECK(m.pad_y == 140);   // lround((640-360)/2 - 0.1) = 140
    CHECK(m.dst_w == 640 && m.dst_h == 640);

    UpstreamFrame square;
    square.width = 640;
    square.height = 640;
    const auto m2 = rga.compute_letterbox(square);
    CHECK(feq(static_cast<float>(m2.scale), 1.0f));
    CHECK(m2.new_w == 640 && m2.new_h == 640);
    CHECK(m2.pad_x == 0 && m2.pad_y == 0);

    // 竖屏 720×1280：宽受限
    UpstreamFrame portrait;
    portrait.width = 720;
    portrait.height = 1280;
    const auto m3 = rga.compute_letterbox(portrait);
    CHECK(feq(static_cast<float>(m3.scale), 640.f / 1280.f, 1e-4f));
    CHECK(m3.new_w == 360 && m3.new_h == 640);
    CHECK(m3.pad_x == 140 && m3.pad_y == 0);
}

// ---- 2. frame_meta 往返 ----
void test_frame_meta_roundtrip() {
    yolo::postprocess::FrameIdentity id;
    id.stream_id = "cam-42";
    id.seq = 123456789ULL;
    id.generation = 7;
    id.letterbox.src_w = 1920;
    id.letterbox.src_h = 1080;
    id.letterbox.scale = 640.0 / 1920.0;
    id.letterbox.pad_x = 0;
    id.letterbox.pad_y = 140;
    id.letterbox.new_w = 640;
    id.letterbox.new_h = 360;

    const auto buf = yolo::postprocess::pack_frame_meta(id);
    CHECK(!buf.empty());

    yolo::postprocess::FrameIdentity back;
    CHECK(yolo::postprocess::unpack_frame_meta(buf, back));
    CHECK(back.stream_id == id.stream_id);
    CHECK(back.seq == id.seq);
    CHECK(back.generation == id.generation);
    CHECK(back.letterbox.src_w == 1920 && back.letterbox.src_h == 1080);
    CHECK(feq(static_cast<float>(back.letterbox.scale),
              static_cast<float>(id.letterbox.scale)));
    CHECK(back.letterbox.pad_y == 140);
    CHECK(back.letterbox.new_h == 360);

    // 截断 / 版本破坏 → false
    auto truncated = buf;
    truncated.resize(truncated.size() - 4);
    CHECK(!yolo::postprocess::unpack_frame_meta(truncated, back));
    auto bad_ver = buf;
    bad_ver[0] = 0xFF;
    CHECK(!yolo::postprocess::unpack_frame_meta(bad_ver, back));
}

// ---- 3. DFL 数值：均匀 logits → 期望 7.5 ----
void test_dfl_numeric() {
    constexpr std::size_t kH = 8, kW = 8, kNc = 2, kBoxC = 64;
    std::vector<float> box(1 * kBoxC * kH * kW, 1.f);   // 均匀 logit
    std::vector<float> cls(1 * kNc * kH * kW, 0.f);
    const std::size_t cell_y = 3, cell_x = 2;
    cls[0 * kH * kW + cell_y * kW + cell_x] = 0.9f;

    std::vector<yolo::postprocess::DecodedBox> cands;
    yolo::postprocess::decode_branch_score_first(
        box.data(), cls.data(), kNc, kH, kW, 640, 0.4f, {}, cands);
    CHECK(cands.size() == 1);

    // dist = 7.5（0..15 均匀 softmax 期望）；stride = 640/8 = 80
    // gx=2.5, gy=3.5 → x1=(2.5-7.5)*80, y1=(3.5-7.5)*80, ...
    auto b = cands[0];
    CHECK(feq(b.x1, (2.5f - 7.5f) * 80.f));
    CHECK(feq(b.y1, (3.5f - 7.5f) * 80.f));
    CHECK(feq(b.x2, (2.5f + 7.5f) * 80.f));
    CHECK(feq(b.y2, (3.5f + 7.5f) * 80.f));
    CHECK(feq(b.score, 0.9f));
    CHECK(b.class_id == 0);

    // letterbox 还原 + clamp（scale=1/3、pad=(0,140)、src=1920×1080）
    LetterboxMeta meta;
    meta.src_w = 1920;
    meta.src_h = 1080;
    meta.scale = 640.0 / 1920.0;
    meta.pad_x = 0;
    meta.pad_y = 140;
    yolo::postprocess::scale_decoded_box_to_orig(b, meta);
    CHECK(feq(b.x1, 0.f));            // (-400-0)*3 → clamp 0
    CHECK(feq(b.y1, 0.f));            // (-320-140)*3 → clamp 0
    CHECK(feq(b.x2, 1920.f));         // 800*3 → clamp 1920
    CHECK(feq(b.y2, 1080.f));         // (880-140)*3=2220 → clamp 1080
}

// ---- 4. NMS ----
void test_nms() {
    std::vector<yolo::postprocess::DecodedBox> boxes = {
        {0.f, 0.f, 100.f, 100.f, 0.9f, 0},
        {10.f, 10.f, 110.f, 110.f, 0.8f, 0},   // 与 A IoU≈0.68
        {300.f, 300.f, 400.f, 400.f, 0.7f, 0},
    };
    const std::vector<std::size_t> all = {0, 1, 2};

    auto keep045 = yolo::postprocess::nms_decoded(boxes, all, 0.45f);
    CHECK(keep045.size() == 2);
    CHECK(keep045[0] == 0 && keep045[1] == 2);

    auto keep070 = yolo::postprocess::nms_decoded(boxes, all, 0.70f);
    CHECK(keep070.size() == 3);   // 0.68 < 0.7 不抑制
}

// ---- 5. decode_rknn_outputs 编排 ----
TensorData make_tensor(std::vector<std::size_t> dims, float fill,
                       const std::function<void(std::vector<float>&)>& patch) {
    std::size_t n = 1;
    for (auto d : dims) n *= d;
    std::vector<float> data(n, fill);
    if (patch) patch(data);
    return TensorData(std::move(data), 0, std::move(dims));
}

void test_decode_outputs_orchestration() {
    constexpr std::size_t kH = 8, kW = 8, kNc = 2;
    const std::size_t cell = 3 * kW + 2;

    std::vector<TensorData> tensors;
    tensors.push_back(make_tensor({1, 64, kH, kW}, 1.f, nullptr));
    tensors.push_back(make_tensor(
        {1, kNc, kH, kW}, 0.f,
        [&](std::vector<float>& d) { d[cell] = 0.9f; }));
    tensors.push_back(make_tensor({1, 8, kH, kW}, 0.f, nullptr));  // 未用

    yolo::postprocess::FrameIdentity id;
    id.stream_id = "s1";
    id.seq = 9;
    id.letterbox.src_w = 1920;
    id.letterbox.src_h = 1080;
    id.letterbox.scale = 640.0 / 1920.0;
    id.letterbox.pad_x = 0;
    id.letterbox.pad_y = 140;

    yolo::postprocess::DecodeConfig cfg;
    const auto out = yolo::postprocess::decode_rknn_outputs(
        tensors, id, cfg, 3, 1);
    CHECK(out.stream_id == "s1" && out.seq == 9);
    CHECK(out.worker_id == 3 && out.core_mask == 1);
    CHECK(out.dets.size() == 1);
    if (!out.dets.empty()) {
        const auto& d = out.dets[0];
        CHECK(d.x1 == 0 && d.y1 == 0);
        CHECK(d.x2 == 1920 && d.y2 == 1080);
        CHECK(d.class_id == 0);
        CHECK(feq(d.score, 0.9f));
    }

    // 张量数非 3 的倍数 → 空结果（不致命）
    auto bad = tensors;
    bad.push_back(make_tensor({1, 4}, 0.f, nullptr));
    const auto out2 =
        yolo::postprocess::decode_rknn_outputs(bad, id, cfg);
    CHECK(out2.dets.empty());

    // obj_classes 白名单不含 class 0 → 空
    yolo::postprocess::DecodeConfig flt;
    flt.obj_classes = {1};
    const auto out3 =
        yolo::postprocess::decode_rknn_outputs(tensors, id, flt);
    CHECK(out3.dets.empty());
}

// ---- 6. mock 引擎端到端链路 ----
void test_mock_engine_chain() {
    constexpr std::size_t kH = 8, kW = 8, kNc = 2;

    MockPlan plan;
    plan.geometry = InputGeometry{640, 640, 3, PixelFmt::kUint8Nhwc,
                                  640 * 640 * 3};
    plan.output_dims = {{1, 64, kH, kW}, {1, kNc, kH, kW}, {1, 8, kH, kW}};
    plan.fill = [&](std::size_t i, std::vector<float>& d) {
        if (i == 0) {
            std::fill(d.begin(), d.end(), 1.f);  // 均匀 box logits
        } else if (i == 1) {
            d[3 * kW + 2] = 0.9f;                // 单格子高分
        }
    };

    EngineConfig cfg;
    cfg.core_masks = {"0"};
    cfg.instances_per_core = 1;
    cfg.job_queue_capacity = 8;
    cfg.output_queue_capacity = 8;

    Engine engine(cfg, make_mock_backend_factory(plan));
    engine.start();

    // 服务接入层 glue（未来 main.cpp 逻辑）：pin → 组 job → submit
    std::atomic<uint64_t> released{0};
    InferJob job;
    job.dma_fd = 1;
    job.size = 640 * 640 * 3;
    job.release = [&released] { released.fetch_add(1); };

    yolo::postprocess::FrameIdentity id;
    id.stream_id = "chain";
    id.seq = 77;
    id.generation = 3;
    id.letterbox.src_w = 1920;
    id.letterbox.src_h = 1080;
    id.letterbox.scale = 640.0 / 1920.0;
    id.letterbox.pad_x = 0;
    id.letterbox.pad_y = 140;
    job.user_meta = yolo::postprocess::pack_frame_meta(id);

    CHECK(engine.submit(std::move(job)));

    auto out = engine.pop_output(std::chrono::milliseconds(1000));
    CHECK(out.has_value());
    CHECK(out->ok);
    CHECK(released.load() == 1);   // release 先于结果交付
    CHECK(out->tensors.size() == 3);

    yolo::postprocess::FrameIdentity back;
    CHECK(yolo::postprocess::unpack_frame_meta(out->user_meta, back));
    CHECK(back.stream_id == "chain" && back.seq == 77);

    yolo::postprocess::DecodeConfig dcfg;
    const auto frame = yolo::postprocess::decode_rknn_outputs(
        out->tensors, back, dcfg, out->worker_id, out->core_mask);
    CHECK(frame.stream_id == "chain");
    CHECK(frame.dets.size() == 1);
    if (!frame.dets.empty()) {
        const auto& d = frame.dets[0];
        CHECK(d.x1 == 0 && d.y1 == 0 && d.x2 == 1920 && d.y2 == 1080);
        CHECK(feq(d.score, 0.9f));
    }

    engine.stop();
}

// ---- 7. 配置缺省回退 ----
void test_config_defaults() {
    const auto pre =
        yolo::preprocess::load_preprocess_config("/nonexistent.yaml");
    CHECK(pre.ring_capacity == 16);
    CHECK(pre.drop_when_busy);
    CHECK(pre.frame_queue_capacity == 8);
    CHECK(pre.net_size == 640);

    const auto post =
        yolo::postprocess::load_decode_config("/nonexistent.yaml");
    CHECK(feq(post.conf_thres, 0.4f));
    CHECK(feq(post.iou_thres, 0.7f));
    CHECK(post.imgsz == 640);
    CHECK(post.obj_classes.empty());
}

}  // namespace

int main() {
    test_letterbox_geometry();
    test_frame_meta_roundtrip();
    test_dfl_numeric();
    test_nms();
    test_decode_outputs_orchestration();
    test_mock_engine_chain();
    test_config_defaults();

    if (g_failures == 0) {
        std::fprintf(stderr, "all yolo front/back checks passed\n");
        return 0;
    }
    std::fprintf(stderr, "yolo front/back checks FAILED: %d\n", g_failures);
    return 1;
}

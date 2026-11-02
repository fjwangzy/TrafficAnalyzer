/**
 * @file control_ops.h
 * @brief 控制面 2 个 RPC（health / status）领域打包；传输在 core three_plane。
 *
 * D5：get_latest / list_latest 已删除（index_calcu 补洞经其配置
 * fallback_poll_sec=0 禁用）。未知操作由 Handler 抛 invalid_operation。
 */

#ifndef YOLO_COMM_CONTROL_OPS_H_
#define YOLO_COMM_CONTROL_OPS_H_

#include <atomic>
#include <cstdint>
#include <string>
#include <vector>

#include "control_plane_server.h"

#include "latest_tracker.h"
#include "publish_thread.h"

namespace yolo {
namespace comm {

/** status 扩展键值（engine 统计 + 阶段计数，值统一字符串化）。 */
using ExtraStatusFn =
    std::function<std::vector<std::pair<std::string, std::string>>()>;

class ControlOps {
public:
    ControlOps(std::string update_endpoint, LatestTracker& tracker,
               PublishThread* publish, std::atomic<bool>& stopping,
               ExtraStatusFn extra_status = {})
        : update_endpoint_(std::move(update_endpoint))
        , tracker_(tracker)
        , publish_(publish)
        , stopping_(stopping)
        , extra_status_(std::move(extra_status)) {}

    /** @brief ControlPlaneServer Handler：解析 operation 并打包 payload。 */
    std::vector<uint8_t> handle(const drn::core::tp::ControlRequest& req);

private:
    std::vector<uint8_t> pack_health();
    std::vector<uint8_t> pack_status();

    std::string update_endpoint_;
    LatestTracker& tracker_;
    PublishThread* publish_;
    std::atomic<bool>& stopping_;
    ExtraStatusFn extra_status_;
};

}  // namespace comm
}  // namespace yolo

#endif  /* YOLO_COMM_CONTROL_OPS_H_ */

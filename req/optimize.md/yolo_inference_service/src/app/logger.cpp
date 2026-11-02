/**
 * @file logger.cpp
 * @brief init_logger 实现：建目录 + stderr 追加重定向到 service.log。
 */

#include "logger.h"

#include <cerrno>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/types.h>

#include <cstdlib>
#include <cstring>

namespace yolo {
namespace app {

bool init_logger(const std::string& log_path, const std::string& level) {
    log_level_ref() = parse_log_level(level);
    if (log_path.empty()) return false;

    // 逐级 mkdir（log_path 为目录）
    std::string cur;
    for (size_t i = 0; i <= log_path.size(); ++i) {
        const bool sep =
            (i == log_path.size() || log_path[i] == '/');
        if (sep && !cur.empty() && cur != "/") {
            ::mkdir(cur.c_str(), 0755);
        }
        if (i < log_path.size()) cur.push_back(log_path[i]);
    }
    ::mkdir(log_path.c_str(), 0755);

    const std::string file = log_path + "/service.log";
    FILE* f = std::fopen(file.c_str(), "a");
    if (!f) return false;
    if (::dup2(::fileno(f), STDERR_FILENO) < 0) {
        std::fclose(f);
        return false;
    }
    std::setvbuf(stderr, nullptr, _IOLBF, 0);
    std::fprintf(stderr, "\n===== yolo_inference_service log start =====\n");
    return true;
}

}  // namespace app
}  // namespace yolo

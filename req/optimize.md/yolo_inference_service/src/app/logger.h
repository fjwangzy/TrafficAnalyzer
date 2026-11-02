/**
 * @file logger.h
 * @brief 轻量进程日志：stderr 重定向到 <log_path>/service.log + 级别过滤。
 *
 * 迁入的各阶段模块沿用 fprintf(stderr)（历史行为），经 stderr 重定向
 * 统一落盘；新代码使用 LOG* 宏（带时间戳 / 级别 / 模块标签）。
 */

#ifndef YOLO_APP_LOGGER_H_
#define YOLO_APP_LOGGER_H_

#include <cstdarg>
#include <cstdio>
#include <ctime>
#include <string>

namespace yolo {
namespace app {

enum class LogLevel { Debug = 0, Info, Warn, Error };

inline LogLevel parse_log_level(const std::string& s) {
    if (s == "TRACE" || s == "DEBUG") return LogLevel::Debug;
    if (s == "WARNING") return LogLevel::Warn;
    if (s == "ERROR" || s == "CRITICAL") return LogLevel::Error;
    return LogLevel::Info;
}

/** 全局级别（init_logger 设置）。 */
inline LogLevel& log_level_ref() {
    static LogLevel lv = LogLevel::Info;
    return lv;
}

/**
 * @brief 初始化日志：建目录、stderr 追加重定向到 <log_path>/service.log。
 * @return true 成功（失败时保持 stderr，服务仍可跑，日志走 journal）。
 */
bool init_logger(const std::string& log_path, const std::string& level);

inline void log_line(LogLevel lv, const char* tag, const char* fmt, ...) {
    if (lv < log_level_ref()) return;
    char ts[32];
    const time_t now = ::time(nullptr);
    struct tm tmv;
    ::localtime_r(&now, &tmv);
    ::strftime(ts, sizeof(ts), "%Y-%m-%d %H:%M:%S", &tmv);
    const char* lvstr = "INFO";
    switch (lv) {
        case LogLevel::Debug: lvstr = "DEBUG"; break;
        case LogLevel::Warn:  lvstr = "WARN";  break;
        case LogLevel::Error: lvstr = "ERROR"; break;
        case LogLevel::Info:  break;
    }
    std::fprintf(stderr, "[%s] [%s] [%s] ", ts, lvstr, tag);
    va_list ap;
    va_start(ap, fmt);
    std::vfprintf(stderr, fmt, ap);
    va_end(ap);
    std::fprintf(stderr, "\n");
}

}  // namespace app
}  // namespace yolo

#define LOG_DEBUG(tag, ...) \
    ::yolo::app::log_line(::yolo::app::LogLevel::Debug, tag, __VA_ARGS__)
#define LOG_INFO(tag, ...) \
    ::yolo::app::log_line(::yolo::app::LogLevel::Info, tag, __VA_ARGS__)
#define LOG_WARN(tag, ...) \
    ::yolo::app::log_line(::yolo::app::LogLevel::Warn, tag, __VA_ARGS__)
#define LOG_ERROR(tag, ...) \
    ::yolo::app::log_line(::yolo::app::LogLevel::Error, tag, __VA_ARGS__)

#endif  /* YOLO_APP_LOGGER_H_ */

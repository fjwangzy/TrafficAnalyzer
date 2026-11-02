/**
 * @file service_app.h
 * @brief 进程壳：配置、日志、flock、装配、serve_loop、倒序关停。
 */

#ifndef YOLO_APP_SERVICE_APP_H_
#define YOLO_APP_SERVICE_APP_H_

#include <atomic>
#include <memory>
#include <string>

#include "service_config.h"

class ServiceApp {
public:
    ServiceApp();
    ~ServiceApp();
    ServiceApp(const ServiceApp&) = delete;
    ServiceApp& operator=(const ServiceApp&) = delete;

    /** @return 进程退出码（0 正常；非 0 各致命错误）。 */
    int run(const std::string& config_path);

    static void request_stop();

private:
    void setup_signals();
    bool setup_lock();
    bool assemble();
    void serve_loop();
    void shutdown();

    yolo::app::ServiceConfig cfg_;
    std::atomic<bool> stop_{false};
    int lock_fd_ = -1;
    bool loggers_inited_ = false;

    struct Impl;
    std::unique_ptr<Impl> impl_;
};

#endif  /* YOLO_APP_SERVICE_APP_H_ */

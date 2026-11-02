/**
 * @file main.cpp
 * @brief yolo_inference_service 入口：--config -> ServiceApp::run。
 *
 * Usage: yolo_inference_service --config <services_config.yaml>
 */

#include <cstdio>
#include <cstring>
#include <string>

#include "app/service_app.h"

int main(int argc, char* argv[]) {
    std::string config_path;
    for (int i = 1; i + 1 < argc; ++i) {
        if (std::strcmp(argv[i], "--config") == 0) {
            config_path = argv[i + 1];
        }
    }
    if (config_path.empty()) {
        if (argc >= 2 && std::strncmp(argv[1], "--", 2) != 0) {
            config_path = argv[1];  // 兼容旧版位置参数
        } else {
            std::fprintf(stderr,
                         "Usage: %s --config <services_config.yaml>\n",
                         argc > 0 ? argv[0] : "yolo_inference_service");
            return 1;
        }
    }

    ServiceApp app;
    return app.run(config_path);
}

# CMakeLists.txt — service_ultimate/yolo_inference_service
cmake_minimum_required(VERSION 3.14)
project(yolo_inference_service LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Debug 下 xtensor 表达式模板后处理可达数秒/帧 —— 强制 Release（沿旧约束）
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

set(DRN_CPP_CORE
    "${CMAKE_CURRENT_SOURCE_DIR}/../../core_module/c_cpp_module")
set(DRN_THREE_PLANE "${DRN_CPP_CORE}/three_plane")
set(DRN_TP_CLIENT "${DRN_CPP_CORE}/three_plane_client")
set(DRN_RKNN_ENGINE "${DRN_CPP_CORE}/rknn_engine")

set(DRN_THREE_PLANE_BUILD_TESTS OFF CACHE BOOL "" FORCE)
add_subdirectory("${DRN_THREE_PLANE}" "${CMAKE_BINARY_DIR}/three_plane")
add_subdirectory("${DRN_TP_CLIENT}" "${CMAKE_BINARY_DIR}/three_plane_client")
set(DRN_RKNN_ENGINE_BUILD_TESTS OFF CACHE BOOL "" FORCE)
add_subdirectory("${DRN_RKNN_ENGINE}" "${CMAKE_BINARY_DIR}/rknn_engine")

add_executable(yolo_inference_service
    main.cpp
    app/logger.cpp
    app/service_config.cpp
    app/service_app.cpp
    upstream/upstream_ingress.cpp
    preprocess/local_rgb_ring.cpp
    preprocess/rga3_preprocess.cpp
    infer/meta_codec.cpp
    infer/engine_ingest.cpp
    postprocess/decode_outputs.cpp
    postprocess/dfl_decode.cpp
    postprocess/nms.cpp
    postprocess/postprocess_worker.cpp
    reorder/reorder_buffer.cpp
    reorder/reorder_thread.cpp
    trace_track/byte_tracker.cpp
    trace_track/kalman_filter.cpp
    trace_track/matching.cpp
    trace_track/strack.cpp
    trace_track/tracker_hub.cpp
    trace_track/track_thread.cpp
    comm/wire_pack.cpp
    comm/latest_tracker.cpp
    comm/publish_thread.cpp
    comm/control_ops.cpp
    backpressure/sample_backoff.cpp
    "${DRN_CPP_CORE}/ring_buffer.cpp"
)

target_include_directories(yolo_inference_service PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${DRN_CPP_CORE}
    ${DRN_THREE_PLANE}/include
    ${DRN_TP_CLIENT}
)

# ---- spdlog（优先旧树构建缓存，否则 FetchContent）----
include(FetchContent)
set(_DRN_SPDLOG_LOCAL
    "${CMAKE_CURRENT_SOURCE_DIR}/../../../../service_new_new/rtsp_receive_service/build/_deps/spdlog-src")
if(EXISTS "${_DRN_SPDLOG_LOCAL}/CMakeLists.txt")
    message(STATUS "Using local spdlog: ${_DRN_SPDLOG_LOCAL}")
    add_subdirectory("${_DRN_SPDLOG_LOCAL}" "${CMAKE_BINARY_DIR}/_deps/spdlog-build"
                     EXCLUDE_FROM_ALL)
else()
    FetchContent_Declare(
        spdlog
        GIT_REPOSITORY https://github.com/gabime/spdlog.git
        GIT_TAG        v1.14.1
    )
    FetchContent_MakeAvailable(spdlog)
endif()
target_link_libraries(yolo_inference_service PRIVATE spdlog::spdlog)

# ---- xtensor / xtl（header-only，优先旧树构建缓存）----
set(_DRN_XTL_LOCAL
    "${CMAKE_CURRENT_SOURCE_DIR}/../../../../service_new_new_new/yolo_inference_service/build/_deps/xtl-src/include")
set(_DRN_XTENSOR_LOCAL
    "${CMAKE_CURRENT_SOURCE_DIR}/../../../../service_new_new_new/yolo_inference_service/build/_deps/xtensor-src/include")
if(EXISTS "${_DRN_XTENSOR_LOCAL}/xtensor/xarray.hpp")
    message(STATUS "Using local xtensor: ${_DRN_XTENSOR_LOCAL}")
    target_include_directories(yolo_inference_service PRIVATE
        ${_DRN_XTL_LOCAL} ${_DRN_XTENSOR_LOCAL})
else()
    FetchContent_Declare(xtl
        GIT_REPOSITORY https://github.com/xtensor-stack/xtl.git
        GIT_TAG        0.7.7)
    FetchContent_Declare(xtensor
        GIT_REPOSITORY https://github.com/xtensor-stack/xtensor.git
        GIT_TAG        0.25.0)
    FetchContent_MakeAvailable(xtl xtensor)
    target_link_libraries(yolo_inference_service PRIVATE xtensor)
endif()

find_package(PkgConfig REQUIRED)

pkg_check_modules(YAMLCPP REQUIRED yaml-cpp)
target_include_directories(yolo_inference_service PRIVATE ${YAMLCPP_INCLUDE_DIRS})
target_link_libraries(yolo_inference_service PRIVATE ${YAMLCPP_LIBRARIES})

pkg_check_modules(RGA REQUIRED librga)
target_include_directories(yolo_inference_service PRIVATE ${RGA_INCLUDE_DIRS})
target_link_libraries(yolo_inference_service PRIVATE ${RGA_LIBRARIES})

pkg_check_modules(SQLITE3 REQUIRED sqlite3)
target_include_directories(yolo_inference_service PRIVATE ${SQLITE3_INCLUDE_DIRS})
target_link_libraries(yolo_inference_service PRIVATE ${SQLITE3_LIBRARIES})

find_package(cppzmq REQUIRED)
find_package(msgpack-cxx REQUIRED)
target_link_libraries(yolo_inference_service PRIVATE
    drn_core_three_plane
    drn_core_three_plane_client
    drn_core_rknn_engine
    cppzmq msgpack-cxx pthread dl rt)

pkg_check_modules(LIBSYSTEMD libsystemd)
if(LIBSYSTEMD_FOUND)
    target_include_directories(yolo_inference_service PRIVATE ${LIBSYSTEMD_INCLUDE_DIRS})
    target_link_libraries(yolo_inference_service PRIVATE ${LIBSYSTEMD_LIBRARIES})
    target_compile_definitions(yolo_inference_service PRIVATE HAS_SYSTEMD)
endif()

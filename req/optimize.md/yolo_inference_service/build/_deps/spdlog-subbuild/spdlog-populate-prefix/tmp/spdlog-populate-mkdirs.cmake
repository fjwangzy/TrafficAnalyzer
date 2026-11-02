# Distributed under the OSI-approved BSD 3-Clause License.  See accompanying
# file Copyright.txt or https://cmake.org/licensing for details.

cmake_minimum_required(VERSION 3.5)

file(MAKE_DIRECTORY
  "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/spdlog-src"
  "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/spdlog-build"
  "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/spdlog-subbuild/spdlog-populate-prefix"
  "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/spdlog-subbuild/spdlog-populate-prefix/tmp"
  "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/spdlog-subbuild/spdlog-populate-prefix/src/spdlog-populate-stamp"
  "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/spdlog-subbuild/spdlog-populate-prefix/src"
  "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/spdlog-subbuild/spdlog-populate-prefix/src/spdlog-populate-stamp"
)

set(configSubDirs )
foreach(subDir IN LISTS configSubDirs)
    file(MAKE_DIRECTORY "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/spdlog-subbuild/spdlog-populate-prefix/src/spdlog-populate-stamp/${subDir}")
endforeach()
if(cfgdir)
  file(MAKE_DIRECTORY "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/spdlog-subbuild/spdlog-populate-prefix/src/spdlog-populate-stamp${cfgdir}") # cfgdir has leading slash
endif()

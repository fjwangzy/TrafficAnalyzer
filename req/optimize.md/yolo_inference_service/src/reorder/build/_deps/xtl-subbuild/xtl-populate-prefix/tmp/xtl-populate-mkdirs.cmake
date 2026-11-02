# Distributed under the OSI-approved BSD 3-Clause License.  See accompanying
# file Copyright.txt or https://cmake.org/licensing for details.

cmake_minimum_required(VERSION 3.5)

file(MAKE_DIRECTORY
  "/root/project/model_deployment/device_run_new/service_new_new_new/yolo_inference_service/src/reorder/build/_deps/xtl-src"
  "/root/project/model_deployment/device_run_new/service_new_new_new/yolo_inference_service/src/reorder/build/_deps/xtl-build"
  "/root/project/model_deployment/device_run_new/service_new_new_new/yolo_inference_service/src/reorder/build/_deps/xtl-subbuild/xtl-populate-prefix"
  "/root/project/model_deployment/device_run_new/service_new_new_new/yolo_inference_service/src/reorder/build/_deps/xtl-subbuild/xtl-populate-prefix/tmp"
  "/root/project/model_deployment/device_run_new/service_new_new_new/yolo_inference_service/src/reorder/build/_deps/xtl-subbuild/xtl-populate-prefix/src/xtl-populate-stamp"
  "/root/project/model_deployment/device_run_new/service_new_new_new/yolo_inference_service/src/reorder/build/_deps/xtl-subbuild/xtl-populate-prefix/src"
  "/root/project/model_deployment/device_run_new/service_new_new_new/yolo_inference_service/src/reorder/build/_deps/xtl-subbuild/xtl-populate-prefix/src/xtl-populate-stamp"
)

set(configSubDirs )
foreach(subDir IN LISTS configSubDirs)
    file(MAKE_DIRECTORY "/root/project/model_deployment/device_run_new/service_new_new_new/yolo_inference_service/src/reorder/build/_deps/xtl-subbuild/xtl-populate-prefix/src/xtl-populate-stamp/${subDir}")
endforeach()
if(cfgdir)
  file(MAKE_DIRECTORY "/root/project/model_deployment/device_run_new/service_new_new_new/yolo_inference_service/src/reorder/build/_deps/xtl-subbuild/xtl-populate-prefix/src/xtl-populate-stamp${cfgdir}") # cfgdir has leading slash
endif()

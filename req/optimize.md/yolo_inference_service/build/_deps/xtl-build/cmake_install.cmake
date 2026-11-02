# Install script for directory: /root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src

# Set the install prefix
if(NOT DEFINED CMAKE_INSTALL_PREFIX)
  set(CMAKE_INSTALL_PREFIX "/usr/local")
endif()
string(REGEX REPLACE "/$" "" CMAKE_INSTALL_PREFIX "${CMAKE_INSTALL_PREFIX}")

# Set the install configuration name.
if(NOT DEFINED CMAKE_INSTALL_CONFIG_NAME)
  if(BUILD_TYPE)
    string(REGEX REPLACE "^[^A-Za-z0-9_]+" ""
           CMAKE_INSTALL_CONFIG_NAME "${BUILD_TYPE}")
  else()
    set(CMAKE_INSTALL_CONFIG_NAME "Release")
  endif()
  message(STATUS "Install configuration: \"${CMAKE_INSTALL_CONFIG_NAME}\"")
endif()

# Set the component getting installed.
if(NOT CMAKE_INSTALL_COMPONENT)
  if(COMPONENT)
    message(STATUS "Install component: \"${COMPONENT}\"")
    set(CMAKE_INSTALL_COMPONENT "${COMPONENT}")
  else()
    set(CMAKE_INSTALL_COMPONENT)
  endif()
endif()

# Install shared libraries without execute permission?
if(NOT DEFINED CMAKE_INSTALL_SO_NO_EXE)
  set(CMAKE_INSTALL_SO_NO_EXE "1")
endif()

# Is this installation the result of a crosscompile?
if(NOT DEFINED CMAKE_CROSSCOMPILING)
  set(CMAKE_CROSSCOMPILING "FALSE")
endif()

# Set default install directory permissions.
if(NOT DEFINED CMAKE_OBJDUMP)
  set(CMAKE_OBJDUMP "/usr/bin/objdump")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/include/xtl" TYPE FILE FILES
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src/include/xtl/xany.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src/include/xtl/xbasic_fixed_string.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src/include/xtl/xbase64.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src/include/xtl/xclosure.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src/include/xtl/xcompare.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src/include/xtl/xcomplex.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src/include/xtl/xcomplex_sequence.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src/include/xtl/xspan.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src/include/xtl/xspan_impl.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src/include/xtl/xdynamic_bitset.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src/include/xtl/xfunctional.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src/include/xtl/xhalf_float.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src/include/xtl/xhalf_float_impl.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src/include/xtl/xhash.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src/include/xtl/xhierarchy_generator.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src/include/xtl/xiterator_base.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src/include/xtl/xjson.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src/include/xtl/xmasked_value_meta.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src/include/xtl/xmasked_value.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src/include/xtl/xmeta_utils.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src/include/xtl/xmultimethods.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src/include/xtl/xoptional_meta.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src/include/xtl/xoptional.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src/include/xtl/xoptional_sequence.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src/include/xtl/xplatform.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src/include/xtl/xproxy_wrapper.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src/include/xtl/xsequence.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src/include/xtl/xsystem.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src/include/xtl/xtl_config.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src/include/xtl/xtype_traits.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src/include/xtl/xvariant.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src/include/xtl/xvariant_impl.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-src/include/xtl/xvisitor.hpp"
    )
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/cmake/xtl" TYPE FILE FILES
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-build/xtlConfig.cmake"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-build/xtlConfigVersion.cmake"
    )
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  if(EXISTS "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/share/cmake/xtl/xtlTargets.cmake")
    file(DIFFERENT _cmake_export_file_changed FILES
         "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/share/cmake/xtl/xtlTargets.cmake"
         "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-build/CMakeFiles/Export/2fc63ec57839ed115fc15a5438bb5aec/xtlTargets.cmake")
    if(_cmake_export_file_changed)
      file(GLOB _cmake_old_config_files "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/share/cmake/xtl/xtlTargets-*.cmake")
      if(_cmake_old_config_files)
        string(REPLACE ";" ", " _cmake_old_config_files_text "${_cmake_old_config_files}")
        message(STATUS "Old export file \"$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/share/cmake/xtl/xtlTargets.cmake\" will be replaced.  Removing files [${_cmake_old_config_files_text}].")
        unset(_cmake_old_config_files_text)
        file(REMOVE ${_cmake_old_config_files})
      endif()
      unset(_cmake_old_config_files)
    endif()
    unset(_cmake_export_file_changed)
  endif()
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/cmake/xtl" TYPE FILE FILES "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-build/CMakeFiles/Export/2fc63ec57839ed115fc15a5438bb5aec/xtlTargets.cmake")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/pkgconfig" TYPE FILE FILES "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtl-build/xtl.pc")
endif()


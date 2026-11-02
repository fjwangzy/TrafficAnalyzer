# Install script for directory: /root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src

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
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/include/xtensor" TYPE FILE FILES
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xaccessible.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xaccumulator.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xadapt.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xarray.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xassign.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xaxis_iterator.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xaxis_slice_iterator.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xblockwise_reducer.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xblockwise_reducer_functors.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xbroadcast.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xbuffer_adaptor.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xbuilder.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xchunked_array.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xchunked_assign.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xchunked_view.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xcomplex.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xcontainer.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xcsv.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xdynamic_view.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xeval.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xexception.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xexpression.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xexpression_holder.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xexpression_traits.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xfixed.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xfunction.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xfunctor_view.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xgenerator.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xhistogram.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xindex_view.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xinfo.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xio.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xiterable.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xiterator.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xjson.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xlayout.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xmanipulation.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xmasked_view.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xmath.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xmime.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xmultiindex_iterator.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xnoalias.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xnorm.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xnpy.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xoffset_view.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xoperation.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xoptional.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xoptional_assembly.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xoptional_assembly_base.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xoptional_assembly_storage.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xpad.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xrandom.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xreducer.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xrepeat.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xscalar.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xsemantic.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xset_operation.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xshape.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xslice.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xsort.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xstorage.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xstrided_view.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xstrided_view_base.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xstrides.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xtensor.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xtensor_config.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xtensor_forward.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xtensor_simd.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xutils.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xvectorize.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xview.hpp"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-src/include/xtensor/xview_utils.hpp"
    )
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/cmake/xtensor" TYPE FILE FILES
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-build/xtensorConfig.cmake"
    "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-build/xtensorConfigVersion.cmake"
    )
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  if(EXISTS "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/share/cmake/xtensor/xtensorTargets.cmake")
    file(DIFFERENT _cmake_export_file_changed FILES
         "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/share/cmake/xtensor/xtensorTargets.cmake"
         "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-build/CMakeFiles/Export/0f2a327e949144b0b747c96acb1eb12f/xtensorTargets.cmake")
    if(_cmake_export_file_changed)
      file(GLOB _cmake_old_config_files "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/share/cmake/xtensor/xtensorTargets-*.cmake")
      if(_cmake_old_config_files)
        string(REPLACE ";" ", " _cmake_old_config_files_text "${_cmake_old_config_files}")
        message(STATUS "Old export file \"$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/share/cmake/xtensor/xtensorTargets.cmake\" will be replaced.  Removing files [${_cmake_old_config_files_text}].")
        unset(_cmake_old_config_files_text)
        file(REMOVE ${_cmake_old_config_files})
      endif()
      unset(_cmake_old_config_files)
    endif()
    unset(_cmake_export_file_changed)
  endif()
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/cmake/xtensor" TYPE FILE FILES "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-build/CMakeFiles/Export/0f2a327e949144b0b747c96acb1eb12f/xtensorTargets.cmake")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/pkgconfig" TYPE FILE FILES "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/_deps/xtensor-build/xtensor.pc")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/include" TYPE FILE FILES "/root/project/model_deployment/device_run_new/service_ultimate/yolo_inference_service/build/xtensor.hpp")
endif()


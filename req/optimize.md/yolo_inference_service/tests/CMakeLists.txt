# CMakeLists.txt — yolo 前后端单元测试

add_executable(test_yolo_front_back test_yolo_front_back.cpp)

target_link_libraries(test_yolo_front_back PRIVATE
    yolo_preprocess
    yolo_postprocess
)

add_test(NAME yolo_front_back COMMAND test_yolo_front_back)

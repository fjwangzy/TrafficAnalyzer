import os
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")  # MPS设备NMS等操作回退CPU

import hydra
from nodes.VideoReader import VideoReader
from nodes.ShowNode import ShowNode
from nodes.VideoSaverNode import VideoSaverNode
from nodes.DetectionTrackingNodes import DetectionTrackingNodes
from nodes.TrackerInfoUpdateNode import TrackerInfoUpdateNode
from nodes.CalcStatisticsNode import CalcStatisticsNode
from nodes.FlaskServerVideoNode import VideoServer
from elements.VideoEndBreakElement import VideoEndBreakElement
from nodes.KafkaProducerNode import KafkaProducerNode
from nodes.HomographyCalibrationNode import HomographyCalibrationNode
from nodes.SpeedEstimationNode import SpeedEstimationNode
from nodes.DirectionFlowNode import DirectionFlowNode
from nodes.LaneAnalysisNode import LaneAnalysisNode
from nodes.TrajectoryNode import TrajectoryNode
from nodes.ConflictDetectionNode import ConflictDetectionNode
from nodes.MotionCompensationNode import MotionCompensationNode
from utils_local.utils import check_and_set_env_var


@hydra.main(version_base=None, config_path="configs", config_name="app_config")
def main(config) -> None:
    video_reader = VideoReader(config["video_reader"], config.get("telemetry"))
    detection_node = DetectionTrackingNodes(config)
    homography_node = HomographyCalibrationNode(config)
    motion_compensation_node = MotionCompensationNode(config)
    tracker_info_update_node = TrackerInfoUpdateNode(config)
    speed_node = SpeedEstimationNode(config)
    direction_flow_node = DirectionFlowNode(config)
    lane_analysis_node = LaneAnalysisNode(config)
    trajectory_node = TrajectoryNode(config)
    conflict_node = ConflictDetectionNode(config)
    calc_statistics_node = CalcStatisticsNode(config)
    show_node = ShowNode(config)

    save_video = config["pipeline"]["save_video"]
    show_in_web = config["pipeline"]["show_in_web"]
    send_info_kafka = config["pipeline"]["send_info_kafka"]

    if save_video:
        video_saver_node = VideoSaverNode(config["video_saver_node"])
    if send_info_kafka:
        kafka_producer_node = KafkaProducerNode(config)
    if show_in_web:
        video_server_node = VideoServer(config)

    for frame_element in video_reader.process():

        frame_element = detection_node.process(frame_element)
        frame_element = homography_node.process(frame_element)
        frame_element = motion_compensation_node.process(frame_element)
        frame_element = tracker_info_update_node.process(frame_element)
        frame_element = speed_node.process(frame_element)
        frame_element = direction_flow_node.process(frame_element)
        frame_element = lane_analysis_node.process(frame_element)
        frame_element = trajectory_node.process(frame_element)
        frame_element = conflict_node.process(frame_element)
        frame_element = calc_statistics_node.process(frame_element)
        if send_info_kafka:
            frame_element = kafka_producer_node.process(frame_element)
        frame_element = show_node.process(frame_element)

        if save_video:
            video_saver_node.process(frame_element)

        if show_in_web:
            video_server_node.process(frame_element)


if __name__ == "__main__":
    # 检查并设置环境变量（如果不存在）
    check_and_set_env_var("VIDEO_SRC", "test_videos/test_video.mp4")
    check_and_set_env_var("ROADS_JSON", "configs/entry_exit_lanes.json")
    check_and_set_env_var("TOPIC_NAME", "statistics_1")
    check_and_set_env_var("CAMERA_ID", 1)
    main()
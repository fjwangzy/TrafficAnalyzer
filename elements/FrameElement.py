import numpy as np
import time

class FrameElement:
    # 包含有关视频流特定帧信息的类
    def __init__(
        self,
        source: str,
        frame: np.ndarray,
        timestamp: float,
        frame_num: float,
        roads_info: dict,
        frame_result: np.ndarray | None = None,
        detected_conf: list | None = None,
        detected_cls: list | None = None,
        detected_cls_ids: list[int] | None = None,
        detected_xyxy: list[list] | None = None,
        tracked_conf: list | None = None,
        tracked_cls: list | None = None,
        tracked_cls_ids: list[int] | None = None,
        tracked_xyxy: list[list] | None = None,
        id_list: list | None = None,
        buffer_tracks: dict | None = None,
    ) -> None:
        self.source = source  # 视频路径或我们获取流的摄像机编号
        self.frame = frame  # BGR格式的帧
        self.timestamp = timestamp  # 自流开始以来的时间值（秒）
        self.frame_num = frame_num  # 流的帧号
        self.roads_info = roads_info  # 包含环形交叉路口相邻道路坐标的字典
        self.frame_result = frame_result  # 最终处理的帧
        self.timestamp_date = time.time()  # 处理帧时的时间（Unix格式，秒）
        # YOLO的输出结果：
        self.detected_conf = detected_conf  # 检测到的对象的置信度列表
        self.detected_cls = detected_cls  # 检测到的对象的类列表
        self.detected_cls_ids = detected_cls_ids  # YOLO 原始类别 ID，供独立跟踪模块使用
        self.detected_xyxy = detected_xyxy  # 带xyxy框坐标的列表
        self.detection_diagnostics: dict | None = None  # 检测框几何质量与丢弃原因
        # 跟踪算法修正结果：
        self.tracked_conf = tracked_conf  # 检测到的对象的置信度列表
        self.tracked_cls = tracked_cls  # 检测到的对象的类列表
        self.tracked_cls_ids = tracked_cls_ids  # YOLO 原始类别 ID 列表
        self.tracked_xyxy = tracked_xyxy  # 带xyxy框坐标的列表
        self.id_list = id_list  # 检测到的可跟踪对象ID列表
        self.yolo_model_id: str | None = None  # 权重文件名 + 内容摘要
        # 帧的后处理：
        self.buffer_tracks = buffer_tracks  # 选定分析时间段内的活动跟踪缓冲区
        self.info = {}  # 结果统计字典（道路拥堵程度+车辆数量）
        self.send_info_of_frame_to_db = False  # 标志是否从该帧向数据库发送信息

        # ── 新增：遥测与标定 ──
        self.telemetry: dict | None = None  # MQTT遥测数据（与帧同步后的）
        self.calibration_mode: str | None = None  # "runtime_map" | "telemetry" | "reference_points" | None
        self.homography_matrix: np.ndarray | None = None  # 3×3 单应性矩阵（像素→世界米坐标）
        self.dist_coeffs: list[float] | None = None  # 镜头畸变系数 [k1,k2,p1,p2,k3]
        self.camera_intrinsics: dict | None = None  # 相机内参（畸变校正用）

        # ── 新增：运动补偿 ──
        self.anchor_gcj02: tuple | None = None  # (longitude, latitude) canonical map anchor
        self.map_version_id: str | None = None
        self.runtime_map_bundle: dict | None = None
        self.runtime_visual_registration: dict | None = None
        self.drone_displacement_m: np.ndarray | None = None  # [easting, northing] 无人机位移(m)
        self.drone_velocity_ms: np.ndarray | None = None  # [v_east, v_north] 无人机速度(m/s)
        self.gimbal_yaw_delta: float = 0.0  # 当前云台偏航 - 首帧云台偏航(度)
        self.gimbal_yaw_initial: float | None = None  # 首帧云台偏航角(度)
        self.is_hovering: bool = False  # 是否悬停

        # ── 巡航/悬停融合地理参考 ──
        self.flight_phase: str = "telemetry_unavailable"
        self.flight_segment_id: str | None = None
        self.pixel_to_map_enu: np.ndarray | None = None
        # Canonical association warp: background image motion only.  Geographic
        # pose motion is kept separately so H/telemetry noise cannot affect IDs.
        self.camera_motion_warp: np.ndarray | None = None
        self.pose_motion_warp: np.ndarray | None = None
        self.visual_motion_quality: dict | None = None
        self.geo_reference_quality: dict | None = None
        self.tracking_diagnostics: dict | None = None
        self.formal_analytics_eligible: bool = False
        self.association_id_list: list[int] | None = None
        self.formal_track_ids: list[int] | None = None
        self.formal_track_id_by_association: dict[int, int] | None = None
        self.previous_formal_track_id_by_association: dict[int, int] | None = None
        self.association_trajectories: list[dict] | None = None
        self.candidate_trajectories: list[dict] | None = None

        # ── 新增：交通态势统计 ──
        self.direction_stats: dict | None = None  # 方向流量统计（DirectionFlowNode始终输出）
        self.lane_stats: dict | None = None  # 车道级统计（LaneAnalysisNode，仅点位命中时输出）
        self.lane_polygons: dict | None = None  # 车道多边形数据（VideoReader加载）
        self.queue_count: int = 0  # 当前排队车辆数
        self.conflict_events: list[dict] | None = None  # 冲突事件列表
        self.completed_tracks: list[dict] | None = None  # 本帧完成的轨迹数据
        self.inferred_lanes: dict | None = None  # 自动推断的车道（AutoLaneInferenceNode输出）
        self.lane_source: str | None = None       # 车道数据来源: "manual" | "model" | "auto" | None
        self.detected_lane_polygons: dict | None = None  # 模型检测的车道多边形（LaneDetectionNode输出）

        # ── 新增：性能指标 ──
        self.inference_ms: float = 0.0  # YOLO推理耗时（毫秒）
        self.source_capture_time: float | None = None
        self.source_is_realtime: bool = False
        self.source_drop_count: int = 0
        self.source_drop_reason: str | None = None

        # ── 新增：Kafka发送控制 ──
        self.send_to_kafka: bool = False  # 本帧是否已发送到Kafka

        # ── 新增：SharedMemory 优化 ──
        self.shm_name: str | None = None
        self.shm_shape: tuple | None = None
        self.shm_dtype: str | None = None

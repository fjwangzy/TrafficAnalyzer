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
        detected_xyxy: list[list] | None = None,
        tracked_conf: list | None = None,
        tracked_cls: list | None = None,
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
        self.detected_xyxy = detected_xyxy  # 带xyxy框坐标的列表
        # 跟踪算法修正结果：
        self.tracked_conf = tracked_conf  # 检测到的对象的置信度列表
        self.tracked_cls = tracked_cls  # 检测到的对象的类列表
        self.tracked_xyxy = tracked_xyxy  # 带xyxy框坐标的列表
        self.id_list = id_list  # 检测到的可跟踪对象ID列表
        # 帧的后处理：
        self.buffer_tracks = buffer_tracks  # 选定分析时间段内的活动跟踪缓冲区
        self.info = {}  # 结果统计字典（道路拥堵程度+车辆数量）
        self.send_info_of_frame_to_db = False  # 标志是否从该帧向数据库发送信息

        # ── 新增：遥测与标定 ──
        self.telemetry: dict | None = None  # MQTT遥测数据（与帧同步后的）
        self.calibration_mode: str | None = None  # "telemetry" | "reference_points" | None
        self.homography_matrix: np.ndarray | None = None  # 3×3 单应性矩阵（像素→世界米坐标）

        # ── 新增：运动补偿 ──
        self.world_anchor_lat_lon: tuple | None = None  # (lat, lon) 世界锚点GPS
        self.drone_displacement_m: np.ndarray | None = None  # [easting, northing] 无人机位移(m)
        self.drone_velocity_ms: np.ndarray | None = None  # [v_east, v_north] 无人机速度(m/s)
        self.gimbal_yaw_delta: float = 0.0  # 当前云台偏航 - 首帧云台偏航(度)
        self.gimbal_yaw_initial: float | None = None  # 首帧云台偏航角(度)
        self.is_hovering: bool = False  # 是否悬停

        # ── 新增：交通态势统计 ──
        self.direction_stats: dict | None = None  # 方向流量统计（DirectionFlowNode始终输出）
        self.lane_stats: dict | None = None  # 车道级统计（LaneAnalysisNode，仅点位命中时输出）
        self.lane_polygons: dict | None = None  # 车道多边形数据（VideoReader加载）
        self.queue_count: int = 0  # 当前排队车辆数
        self.conflict_events: list[dict] | None = None  # 冲突事件列表
        self.completed_tracks: list[dict] | None = None  # 本帧完成的轨迹数据
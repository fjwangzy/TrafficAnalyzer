class TrackElement:
    # 包含有关特定车辆跟踪信息的类
    def __init__(
        self,
        id: int,
        timestamp_first: float,
        start_road: int | None = None,
    ) -> None:
        self.id = id  # 此跟踪的编号
        self.timestamp_first = timestamp_first  # 初始化时间戳（秒）
        self.timestamp_last = timestamp_first  # 最后检测的时间戳（秒）
        self.start_road = start_road  # 车辆来自的道路编号
        self.timestamp_init_road = timestamp_first  # 道路编号初始化时间戳（秒）
        # 注意：如果未确定道路，则值将保持等于首次出现的时间

        # ── 新增：速度 ──
        self.position_history: list[tuple[float, float, float]] = []  # [(cx, cy, timestamp)] 最近N帧
        self.velocity_ms = None  # np.ndarray[easting,northing]，世界坐标速度向量（m/s）
        self.speed_kmh: float = 0.0  # 当前瞬时车速
        self.avg_speed_kmh: float = 0.0  # EMA平滑车速
        self.max_speed_kmh: float = 0.0  # 轨迹内最大车速

        # ── 新增：车道（可选，仅LaneAnalysisNode使用）──
        self.current_lane: str | None = None  # 当前所在车道ID
        self.lane_history: list[tuple[str, float]] = []  # [(lane_id, timestamp)]

        # ── 新增：方向 ──
        self.heading_angle: float | None = None  # 当前运动方向角度（度）
        self.direction_class: str | None = None  # "straight"|"left_turn"|"right_turn"|"u_turn"

        # ── 新增：轨迹 ──
        self.exit_road: int | None = None  # 车辆离开的道路编号
        self.turn_behavior: str | None = None  # 转向行为分类
        self.trajectory_points: list[tuple[float, float]] = []  # [(cx, cy)] 像素坐标序列
        self.trajectory_timestamps_sec: list[float] = []  # 与 trajectory_points 等长的源视频时间

        # ── 新增：分类 ──
        self.vehicle_class: str = "unknown"  # "motor"|"non_motor"|"unknown"
        self.yolo_class_id: int | None = None  # YOLO原始检测类别ID
        self.yolo_class_name: str | None = None  # 推理时模型字典中的原始类别名
        self.yolo_model_id: str | None = None  # 权重文件名 + 内容摘要
        self.class_mapping_version: str | None = None  # 原始类别到业务类别的映射版本

        # ── 新增：冲突 ──
        self.in_conflict: bool = False
        self.conflict_events: list[dict] = []

    def update(self, timestamp):
        # 更新最后检测时间
        self.timestamp_last = timestamp

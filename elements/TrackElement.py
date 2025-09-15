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

    def update(self, timestamp):
        # 更新最后检测时间
        self.timestamp_last = timestamp
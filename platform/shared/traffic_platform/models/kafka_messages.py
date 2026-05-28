"""Kafka message models"""
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class LaneStatsInMessage(BaseModel):
    """Kafka 消息中的车道级统计"""
    lane_id: int
    flow_veh_per_min: float
    headway_sec: Optional[float] = None
    queue_length_m: float = 0.0
    vehicle_count: int = 0
    avg_speed_kmh: float = 0.0


class StatsMessage(BaseModel):
    """路口统计消息（每秒推送）"""
    msg_type: str = "stats"
    intersection_id: str
    timestamp: datetime

    # 路口级指标
    total_vehicles: int
    congestion_index: float  # 0-5
    avg_speed_kmh: float

    # 车道级指标（5 项核心指标）
    lanes: list[LaneStatsInMessage]

    # 兼容字段
    calib_quality: str = "good"
    lane_match_rate: float = 1.0


class DetectionInMessage(BaseModel):
    """Kafka 消息中的单个检测结果"""
    track_id: int
    class_id: int
    class_name: str
    bbox: list[float]
    confidence: float
    lane_id: Optional[int] = None
    speed_kmh: Optional[float] = None


class DetectionsMessage(BaseModel):
    """车辆检测消息（每帧，可选）"""
    msg_type: str = "detections"
    intersection_id: str
    frame_id: int
    timestamp: datetime
    detections: list[DetectionInMessage]


class LaneChangeEventInMessage(BaseModel):
    """Kafka 消息中的换道事件"""
    from_lane: int
    to_lane: int
    bev_x: float
    bev_y: float
    timestamp: float


class TrackCompleteMessage(BaseModel):
    """轨迹完成消息（车辆离开视野）"""
    msg_type: str = "track_complete"
    intersection_id: str
    track_id: int
    class_name: str
    start_lane: Optional[int] = None
    end_lane: Optional[int] = None
    positions_bev: list[list[float]]  # [[x, y, timestamp], ...]
    duration_sec: float
    total_distance_m: float
    avg_speed_kmh: float
    turn_behavior: Optional[str] = None  # straight/left_turn/right_turn/u_turn
    lane_changes: list[LaneChangeEventInMessage] = []
    is_anomaly: bool = False
    timestamp: datetime


class VLMAnalysisMessage(BaseModel):
    """VLM 语义分析消息（每 45 帧）"""
    msg_type: str = "vlm_analysis"
    intersection_id: str
    frame_id: int
    timestamp: datetime

    # VLM 分析结果
    congestion_level: int  # 0-5
    congestion_description: str  # "畅通", "轻度拥堵", etc.
    anomaly_detected: bool = False
    anomaly_description: Optional[str] = None
    visible_lanes: int
    lane_utilization: dict[str, float]  # {lane_id: percentage}

    # AI 摘要
    summary: str
    key_observations: list[str] = []


class SystemMetricsMessage(BaseModel):
    """系统指标消息（每 5 秒）"""
    msg_type: str = "system_metrics"
    timestamp: datetime

    # 管道性能
    fps: float
    inference_ms: float
    tracking_ms: float

    # GPU 指标
    gpu_utilization: float  # 0-100
    gpu_memory_used_mb: int
    gpu_memory_total_mb: int
    gpu_temperature: Optional[float] = None

    # Kafka 指标
    kafka_lag: int
    kafka_throughput_msg_sec: float

"""Vehicle and Track domain models"""
from pydantic import BaseModel
from typing import Optional
from enum import Enum


class TurnBehavior(str, Enum):
    """转向行为分类"""
    STRAIGHT = "straight"  # 直行
    LEFT_TURN = "left_turn"  # 左转
    RIGHT_TURN = "right_turn"  # 右转
    U_TURN = "u_turn"  # 掉头


class LaneChangeEvent(BaseModel):
    """单次换道事件"""
    from_lane: int  # 换道前车道 ID
    to_lane: int  # 换道后车道 ID
    bev_x: float  # 换道发生位置 X（米）
    bev_y: float  # 换道发生位置 Y（米）
    timestamp: float  # 换道发生时刻


class VehicleDetection(BaseModel):
    """单帧车辆检测结果"""
    track_id: int
    class_id: int  # COCO class ID
    class_name: str  # "car", "truck", "bus"
    bbox: list[float]  # [x1, y1, x2, y2] pixel coordinates
    confidence: float  # 检测置信度
    lane_id: Optional[int] = None  # 所属车道
    speed_kmh: Optional[float] = None  # 速度 km/h


class Track(BaseModel):
    """完整车辆轨迹"""
    track_id: int
    class_name: str
    start_lane: Optional[int] = None
    end_lane: Optional[int] = None
    positions_bev: list[list[float]]  # [[x, y, timestamp], ...]
    duration_sec: float  # 轨迹持续时间
    total_distance_m: float  # 总行驶距离
    avg_speed_kmh: float  # 平均速度
    turn_behavior: Optional[TurnBehavior] = None  # 转向行为
    lane_changes: list[LaneChangeEvent] = []  # 换道事件列表
    is_anomaly: bool = False  # 是否异常轨迹

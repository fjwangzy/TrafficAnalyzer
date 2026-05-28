"""Intersection and Lane domain models"""
from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class Lane(BaseModel):
    """车道模型"""
    id: int  # 1, 2, 3...
    name: str  # "南向北直行"
    direction: str  # inbound/outbound
    compass: str  # north/south/east/west
    width_m: float = 3.5
    polygon_bev: list[list[float]]  # [[x,y],...] BEV coordinates in meters
    polygon_pixel: Optional[list[list[float]]] = None  # pixel coordinates (optional)
    speed_limit: Optional[int] = None  # km/h


class LaneStats(BaseModel):
    """车道级实时统计（每秒刷新）"""
    lane_id: int
    flow_veh_per_min: float  # 交通流量（辆/分钟）
    headway_sec: Optional[float] = None  # 车头时距（秒），<2 辆车时为 None
    queue_length_m: float = 0.0  # 排队长度（米），<2 辆车时为 0
    vehicle_count: int = 0  # 当前车道内车辆数
    avg_speed_kmh: float = 0.0  # 车道内平均速度


class Intersection(BaseModel):
    """路口模型"""
    id: str  # "INT_小清河水屯"
    name: str  # "小清河北路×水屯路"
    center_lat: float  # 36.7029103
    center_lon: float  # 117.0222766
    lane_count: int = 5
    lanes: list[Lane] = []
    status: str = "inactive"  # active/inactive/error
    current_drone_id: Optional[str] = None
    last_active_at: Optional[datetime] = None
    created_at: datetime = None
    updated_at: datetime = None

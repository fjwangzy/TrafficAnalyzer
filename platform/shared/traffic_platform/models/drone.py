"""Drone domain models"""
from pydantic import BaseModel
from typing import Optional
from enum import Enum


class DroneStatus(str, Enum):
    """无人机状态"""
    OFFLINE = "offline"
    ONLINE = "online"
    FLYING = "flying"
    HOVERING = "hovering"
    RETURNING = "returning"


class DroneTelemetry(BaseModel):
    """无人机遥测数据（从 SRT 解析）"""
    lat: float  # 纬度
    lon: float  # 经度
    alt_agl: float  # 相对高度 (Above Ground Level) 米
    gimbal_pitch: float  # 云台俯仰角
    gimbal_roll: float  # 云台横滚角
    gimbal_yaw: float  # 云台偏航角
    drone_pitch: Optional[float] = None  # 机身俯仰角
    drone_roll: Optional[float] = None  # 机身横滚角
    drone_yaw: Optional[float] = None  # 机身偏航角
    gps_type: str = "RTK_FIX"  # GPS 类型: RTK_FIX/RTK_FLOAT/SINGLE
    battery_pct: int = 100  # 电池百分比
    wind_speed: Optional[float] = None  # 风速 m/s
    timestamp: float  # 时间戳


class Drone(BaseModel):
    """无人机模型"""
    id: str  # "drone_001"
    name: str  # "小清河一号"
    status: DroneStatus = DroneStatus.OFFLINE
    current_intersection_id: Optional[str] = None
    last_telemetry: Optional[DroneTelemetry] = None
    battery_pct: int = 100
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

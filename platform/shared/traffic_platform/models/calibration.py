"""Calibration domain models"""
from pydantic import BaseModel
from typing import Optional
from enum import Enum


class CalibrationQuality(str, Enum):
    """标定质量等级"""
    EXCELLENT = "excellent"  # 优秀（重投影误差 < 2px）
    GOOD = "good"  # 良好（2-5px）
    ACCEPTABLE = "acceptable"  # 可接受（5-10px）
    POOR = "poor"  # 差（> 10px）


class CalibrationRecord(BaseModel):
    """标定记录（存储在 calibration_db.json）"""
    id: str  # "INT_小清河水屯__H120__P-85"
    intersection_id: str
    altitude_m: float  # 飞行高度
    gimbal_pitch: float  # 云台俯仰角
    H_mat: list[list[float]]  # 3x3 透视变换矩阵
    lane_polygons_bev: dict[str, list[list[float]]]  # 车道多边形 BEV 坐标
    quality: CalibrationQuality = CalibrationQuality.GOOD
    reprojection_error: Optional[float] = None  # 重投影误差（像素）
    calibrated_at: str  # ISO timestamp
    calibrated_by: Optional[str] = None  # 标定人员
    version: int = 1
    locked: bool = False  # 是否锁定编辑

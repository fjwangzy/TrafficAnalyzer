"""Report domain models"""
from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class Report(BaseModel):
    """分析报告模型"""
    id: str  # UUID
    intersection_id: str
    title: str
    period_start: datetime
    period_end: datetime

    # 基础统计
    total_vehicles: int
    avg_flow_veh_per_min: float
    max_congestion_index: float

    # 车道级分析
    lane_utilization: dict[str, float]  # {lane_id: percentage}
    lane_headway_stats: dict[str, dict]  # {lane_id: {avg, min, p50, p95}}
    lane_queue_stats: dict[str, dict]  # {lane_id: {avg, max}}

    # 转向行为分析
    turn_distribution: dict[str, int]  # {turn_type: count}
    turn_flow_matrix: list[list[int]]  # [start_lane][turn_type] -> count

    # 换道行为分析
    lane_change_rate: float  # 换道率（次/车辆）
    lane_change_matrix: list[list[int]]  # [from_lane][to_lane] -> count
    lane_change_heatmap: list[dict]  # [{x, y, intensity}, ...]

    # 拥堵时段
    congestion_periods: list[dict]  # [{start, end, duration, peak_index}, ...]

    # 异常事件
    anomaly_events: list[str]  # alert_ids

    # AI 摘要
    ai_summary: Optional[str] = None  # Qwen-VL 生成

    # PDF 报告
    pdf_path: Optional[str] = None
    status: str = "pending"  # pending/generating/completed/failed

    created_at: datetime
    generated_at: Optional[datetime] = None

"""Pydantic domain models"""
from .intersection import Intersection, Lane, LaneStats
from .vehicle import VehicleDetection, Track, TurnBehavior, LaneChangeEvent
from .alert import Alert, AlertType, AlertSeverity, AlertStatus
from .drone import Drone, DroneTelemetry, DroneStatus
from .calibration import CalibrationRecord, CalibrationQuality
from .report import Report
from .webhook import Webhook, WebhookChannel, AlertPushLog
from .kafka_messages import StatsMessage, DetectionsMessage, TrackCompleteMessage, VLMAnalysisMessage, SystemMetricsMessage

__all__ = [
    # Intersection
    "Intersection", "Lane", "LaneStats",
    # Vehicle
    "VehicleDetection", "Track", "TurnBehavior", "LaneChangeEvent",
    # Alert
    "Alert", "AlertType", "AlertSeverity", "AlertStatus",
    # Drone
    "Drone", "DroneTelemetry", "DroneStatus",
    # Calibration
    "CalibrationRecord", "CalibrationQuality",
    # Report
    "Report",
    # Webhook
    "Webhook", "WebhookChannel", "AlertPushLog",
    # Kafka Messages
    "StatsMessage", "DetectionsMessage", "TrackCompleteMessage",
    "VLMAnalysisMessage", "SystemMetricsMessage",
]

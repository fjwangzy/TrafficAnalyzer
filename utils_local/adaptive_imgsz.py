"""Altitude-aware fixed inference-size selection for aerial detection."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from statistics import median


@dataclass(frozen=True)
class ImageSizeDecision:
    imgsz: int
    diagnostics: dict


class AdaptiveImageSizePolicy:
    """Select one of three YOLO input sizes from synchronized AGL telemetry."""

    def __init__(self, config: dict | None, *, fallback_imgsz: int) -> None:
        cfg = config or {}
        self.enabled = bool(cfg.get("enabled", False))
        self.fallback_imgsz = int(fallback_imgsz)
        self.low_imgsz = int(cfg.get("low_imgsz", 640))
        self.medium_imgsz = int(cfg.get("medium_imgsz", 960))
        self.high_imgsz = int(cfg.get("high_imgsz", 1280))
        self.low_to_medium_agl_m = float(cfg.get("low_to_medium_agl_m", 112.0))
        self.medium_to_high_agl_m = float(cfg.get("medium_to_high_agl_m", 157.0))
        self.hysteresis_m = float(cfg.get("hysteresis_m", 5.0))
        self.stable_frames = max(int(cfg.get("stable_frames", 5)), 1)
        self._agl_window_size = max(int(cfg.get("agl_window_size", 5)), 1)
        self.telemetry_hold_sec = max(float(cfg.get("telemetry_hold_sec", 2.0)), 0.0)
        self._agl_values: list[float] = []
        self._last_valid_timestamp_sec: float | None = None
        self._current_tier: str | None = None
        self._pending_tier: str | None = None
        self._pending_count = 0
        self._switch_count = 0

    def select(
        self,
        telemetry: dict | None,
        *,
        source_timestamp_sec: float,
    ) -> ImageSizeDecision:
        raw_agl, source = self._agl(telemetry)
        if raw_agl is None and self.enabled and self._current_tier is not None:
            elapsed = (
                float(source_timestamp_sec) - self._last_valid_timestamp_sec
                if self._last_valid_timestamp_sec is not None
                else None
            )
            if elapsed is not None and 0.0 <= elapsed <= self.telemetry_hold_sec:
                held_imgsz = self._size_for(self._current_tier)
                filtered_agl = (
                    round(float(median(self._agl_values)), 3)
                    if self._agl_values
                    else None
                )
                return ImageSizeDecision(
                    held_imgsz,
                    {
                        "enabled": True,
                        "raw_agl_m": None,
                        "filtered_agl_m": filtered_agl,
                        "agl_source": None,
                        "effective_imgsz": held_imgsz,
                        "tier": self._current_tier,
                        "status": "telemetry_held",
                        "switch_reason": "last_valid_altitude",
                        "switch_count": self._switch_count,
                    },
                )
        if raw_agl is None or not self.enabled:
            return ImageSizeDecision(
                self.fallback_imgsz,
                {
                    "enabled": self.enabled,
                    "raw_agl_m": raw_agl,
                    "filtered_agl_m": raw_agl,
                    "agl_source": source,
                    "effective_imgsz": self.fallback_imgsz,
                    "tier": "fallback",
                    "status": "disabled" if not self.enabled else "telemetry_missing",
                    "switch_reason": "configured_fallback",
                    "switch_count": self._switch_count,
                },
            )

        self._last_valid_timestamp_sec = float(source_timestamp_sec)
        self._agl_values.append(raw_agl)
        self._agl_values = self._agl_values[-self._agl_window_size :]
        filtered_agl = float(median(self._agl_values))
        tier = self._tier_for(filtered_agl)
        reason = "steady"
        if self._current_tier is None:
            self._current_tier = tier
            reason = "initial_altitude"
        else:
            requested_tier = self._tier_with_hysteresis(filtered_agl)
            if requested_tier == self._current_tier:
                self._pending_tier = None
                self._pending_count = 0
            else:
                if requested_tier != self._pending_tier:
                    self._pending_tier = requested_tier
                    self._pending_count = 0
                self._pending_count += 1
                reason = "pending_altitude"
                if self._pending_count >= self.stable_frames:
                    self._current_tier = requested_tier
                    self._pending_tier = None
                    self._pending_count = 0
                    self._switch_count += 1
                    reason = "stable_altitude"
        return ImageSizeDecision(
            self._size_for(self._current_tier),
            {
                "enabled": True,
                "raw_agl_m": round(raw_agl, 3),
                "filtered_agl_m": round(filtered_agl, 3),
                "agl_source": source,
                "effective_imgsz": self._size_for(self._current_tier),
                "tier": self._current_tier,
                "status": "adaptive",
                "switch_reason": reason,
                "switch_count": self._switch_count,
            },
        )

    @staticmethod
    def _agl(telemetry: dict | None) -> tuple[float | None, str | None]:
        if not isinstance(telemetry, dict):
            return None, None
        for key in ("altitude_agl", "height"):
            value = telemetry.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                agl = float(value)
                if isfinite(agl) and agl > 0:
                    return agl, key
        return None, None

    def _tier_for(self, agl_m: float) -> str:
        if agl_m < self.low_to_medium_agl_m:
            return "low"
        if agl_m < self.medium_to_high_agl_m:
            return "medium"
        return "high"

    def _tier_with_hysteresis(self, agl_m: float) -> str:
        if self._current_tier == "low":
            if agl_m >= self.medium_to_high_agl_m + self.hysteresis_m:
                return "high"
            if agl_m >= self.low_to_medium_agl_m + self.hysteresis_m:
                return "medium"
            return "low"
        if self._current_tier == "high":
            if agl_m < self.low_to_medium_agl_m - self.hysteresis_m:
                return "low"
            if agl_m < self.medium_to_high_agl_m - self.hysteresis_m:
                return "medium"
            return "high"
        if agl_m >= self.medium_to_high_agl_m + self.hysteresis_m:
            return "high"
        if agl_m < self.low_to_medium_agl_m - self.hysteresis_m:
            return "low"
        return "medium"

    def _size_for(self, tier: str) -> int:
        return {
            "low": self.low_imgsz,
            "medium": self.medium_imgsz,
            "high": self.high_imgsz,
        }[tier]

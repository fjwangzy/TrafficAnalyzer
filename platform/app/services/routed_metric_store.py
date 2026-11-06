"""Fixed business Topics route by explicit payload profile, never by suffix."""

from app.services.metric_store import MetricContractError


class RoutedMetricStore:
    def __init__(self, primary, live, replay):
        self.primary, self.live, self.replay = primary, live, replay

    def __getattr__(self, name):
        return getattr(self.primary, name)

    def for_payload(self, payload):
        profile = payload.get("storage_profile")
        if profile not in {"live", "replay_v2"}:
            raise MetricContractError("fixed Topic requires explicit storage_profile")
        if payload.get("msg_type") in {"uav_system_metrics", "uav_enforcement_clue"}:
            return self.live
        return self.replay if profile == "replay_v2" else self.live

"""Owned immutable track views used only beyond the analysis boundary."""

from dataclasses import dataclass


class RenderTrackSnapshot:
    def __init__(self, values):
        object.__setattr__(self, "_values", values)

    def __getattr__(self, name):
        try:
            return object.__getattribute__(self, "_values")[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name, value):
        raise AttributeError("render snapshots are read-only")

    def __reduce__(self):
        return type(self), (self._values,)


@dataclass(frozen=True)
class RenderSnapshot:
    frame_num: int
    tracks: tuple[RenderTrackSnapshot, ...]
    tail_points: int = 30

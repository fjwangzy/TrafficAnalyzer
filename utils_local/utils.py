import logging
import os
import time
import numpy as np
from shapely.geometry import Point, Polygon

logger_profile = logging.getLogger("profile")


def check_and_set_env_var(var_name, value_new):
    """
    检查环境变量 `var_name` 是否已设置。如果未设置，
    则为其赋值 `value_new`
    """
    value = os.getenv(var_name)
    if value is None:
        os.environ[var_name] = str(value_new)
        print(f"值 {value_new} 已保存到环境变量 {var_name} 中。")
    else:
        print(f"环境变量 {var_name} 已设置: {value}")


def profile_time(func):
    def exec_and_print_status(*args, **kwargs):
        t_start = time.time()
        out = func(*args, **kwargs)
        t_end = time.time()
        dt_msecs = (t_end - t_start) * 1000

        self = args[0]
        logger_profile.debug(
            f"{self.__class__.__name__}.{func.__name__}, 耗时 {dt_msecs:.2f} 毫秒"
        )
        return out

    return exec_and_print_status


class FPS_Counter:
    def __init__(self, calc_time_perion_N_frames: int) -> None:
        """基于视频有限部分（滑动窗口）的FPS计数器。

        Args:
            calc_time_perion_N_frames (int): 统计窗口的帧数。
        """
        self.time_buffer = []
        self.calc_time_perion_N_frames = calc_time_perion_N_frames

    def calc_FPS(self) -> float:
        """根据多个视频帧计算FPS。

        Returns:
            float: FPS值。
        """
        time_buffer_is_full = len(self.time_buffer) == self.calc_time_perion_N_frames
        t = time.time()
        self.time_buffer.append(t)

        if time_buffer_is_full:
            self.time_buffer.pop(0)
            fps = len(self.time_buffer) / (self.time_buffer[-1] - self.time_buffer[0])
            return np.round(fps, 2)
        else:
            return 0.0


def intersects_central_point(tracked_xyxy, polygons):
    """该函数确定bbox中心点是否存在于道路多边形区域内

    Args:
        tracked_xyxy: bbox坐标
        polygons: 多边形字典

    Returns:
        要么是None，要么是键值（道路编号 - int）
    """
    # bbox中心点：
    center_point = [
        (tracked_xyxy[0] + tracked_xyxy[2]) / 2,
        (tracked_xyxy[1] + tracked_xyxy[3]) / 2,
    ]
    center_point = Point(center_point)
    for key, polygon in polygons.items():
        polygon = Polygon([(polygon[i], polygon[i + 1]) for i in range(0, len(polygon), 2)])
        if polygon.contains(center_point):
            return int(key)
    return None
#!/usr/bin/env python3
"""WebSocket测试数据注入脚本 — 向Monitor页面注入模拟实时统计数据。

用途:
  - Kafka不可用时验证Monitor页面前端显示
  - 开发调试前端组件
  - 端到端集成测试

前置条件:
  - Platform容器运行 (http://localhost:8000)
  - websocket-client 已安装 (pip install websocket-client)

用法:
  python3 scripts/inject_test_data.py
  python3 scripts/inject_test_data.py --continuous  # 每秒注入一次
  python3 scripts/inject_test_data.py --intersection INT_camera_2
"""

import argparse
import json
import time
import websocket

WS_URL = "ws://localhost:8000/ws/realtime"
DEFAULT_INTERSECTION = "INT_camera_1"

# inter_xqh 交叉路口的典型遥测参数
INTER_XQH_CONFIG = {
    "center_lat": 36.702909,
    "center_lon": 117.022330,
    "height": 130.0,
    "gimbal_pitch": -90.0,
}


def inject_stats(ws, intersection_id, iteration=0):
    """注入一条统计数据消息"""
    stats = {
        "cars": 15 + iteration % 10,
        "total_vehicles": 15 + iteration % 10,
        "fps": 25.0 - (iteration % 10) * 0.5,
        "inference_ms": 45 + (iteration % 10) * 2,
        "active_tracks": 12 + iteration % 5,
        "congestion_index": round(1.5 + iteration * 0.02, 2),
        "road_1": 5 + iteration % 3,
        "road_2": 3 + iteration % 2,
        "road_3": 4 + iteration % 4,
        "road_4": 2 + iteration % 2,
        "road_5": 1,
        "direction_flow": {
            "straight": {"vehicle_count": 10 + iteration % 5, "avg_speed_kmh": 22.5},
            "left_turn": {"vehicle_count": 3 + iteration % 2, "avg_speed_kmh": 15.0},
            "right_turn": {"vehicle_count": 2 + iteration % 3, "avg_speed_kmh": 18.0},
            "u_turn": {"vehicle_count": iteration % 3, "avg_speed_kmh": 0},
        },
        "avg_speed_kmh": 18.5,
        "drone_position": {
            "anchor_lat": INTER_XQH_CONFIG["center_lat"],
            "anchor_lon": INTER_XQH_CONFIG["center_lon"],
            "easting_m": round(iteration * 0.1, 2),
            "northing_m": round(iteration * 0.05, 2),
        },
        "is_hovering": True,
    }

    msg = json.dumps({
        "action": "publish",
        "channel": f"uav_intersection:{intersection_id}",
        "type": "uav_stats",
        "data": stats,
    })
    ws.send(msg)
    result = ws.recv()
    print(f"  [{iteration}] Injected: cars={stats['cars']}, fps={stats['fps']:.1f}, "
          f"congestion={stats['congestion_index']}, hover={stats['is_hovering']}")
    return stats


def inject_track_complete(ws, intersection_id, track_id=42):
    """注入一条轨迹完成消息"""
    track_msg = json.dumps({
        "action": "publish",
        "channel": f"uav_intersection:{intersection_id}",
        "type": "uav_track_complete",
        "data": {
            "track_id": track_id,
            "turn_behavior": "left_turn",
            "vehicle_class": "car",
            "duration_sec": 6.5,
            "avg_speed_kmh": 15.0,
            "is_anomaly": False,
        },
    })
    ws.send(track_msg)
    ws.recv()
    print(f"  Track complete: id={track_id}, turn=left_turn")


def main():
    parser = argparse.ArgumentParser(description="WebSocket test data injection")
    parser.add_argument("--continuous", action="store_true", help="持续注入 (每秒)")
    parser.add_argument("--intersection", default=DEFAULT_INTERSECTION, help="路口ID")
    parser.add_argument("--iterations", type=int, default=5, help="注入次数")
    args = parser.parse_args()

    ws = websocket.create_connection(WS_URL)
    print(f"Connected to {WS_URL}")

    # Subscribe
    ws.send(json.dumps({
        "action": "subscribe",
        "channel": f"uav_intersection:{args.intersection}"
    }))
    ws.recv()
    print(f"Subscribed to uav_intersection:{args.intersection}")

    iteration = 0
    try:
        while iteration < args.iterations or args.continuous:
            inject_stats(ws, args.intersection, iteration)
            if iteration % 10 == 0 and iteration > 0:
                inject_track_complete(ws, args.intersection, track_id=iteration)
            iteration += 1
            if args.continuous:
                time.sleep(1)
    except KeyboardInterrupt:
        print(f"\nStopped after {iteration} iterations")

    ws.close()
    print(f"Disconnected. Total iterations: {iteration}")


if __name__ == "__main__":
    main()

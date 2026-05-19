import cv2
import json
import numpy as np
import sys
import os

if len(sys.argv) < 3:
    print("Usage: python generate_lanes.py <video_path> <output_json_path>")
    sys.exit(1)

video_path = sys.argv[1]
output_json = sys.argv[2]

if not os.path.exists(video_path):
    print(f"Error: Video file not found at {video_path}")
    sys.exit(1)

cap = cv2.VideoCapture(video_path)
ret, frame = cap.read()
if not ret:
    print("Failed to read video.")
    sys.exit(1)

lanes = {}
current_points = []
lane_id = 1

# If the video resolution is very high, we might want to scale it down for display,
# but the coordinates MUST match the original resolution. 
# For simplicity, we assume the window fits the screen. If not, the user can adjust.
def mouse_callback(event, x, y, flags, param):
    global current_points, lane_id, frame_copy
    if event == cv2.EVENT_LBUTTONDOWN:
        current_points.append((x, y))
        cv2.circle(frame_copy, (x, y), 5, (0, 255, 0), -1)
        if len(current_points) > 1:
            cv2.line(frame_copy, current_points[-2], current_points[-1], (0, 255, 0), 2)
        if len(current_points) == 4:
            cv2.line(frame_copy, current_points[-1], current_points[0], (0, 255, 0), 2)
            
            # format as list of 8 floats
            pts = []
            for p in current_points:
                pts.extend([float(p[0]), float(p[1])])
            lanes[str(lane_id)] = pts
            
            # draw polygon overlay
            pts_np = np.array(current_points, np.int32).reshape((-1, 1, 2))
            overlay = frame_copy.copy()
            cv2.fillPoly(overlay, [pts_np], (0, 255, 0))
            cv2.addWeighted(overlay, 0.3, frame_copy, 0.7, 0, frame_copy)
            cv2.putText(frame_copy, str(lane_id), current_points[0], cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            
            print(f"Lane {lane_id} saved: {pts}")
            lane_id += 1
            current_points = []
        cv2.imshow("Draw Lanes", frame_copy)

frame_copy = frame.copy()
cv2.namedWindow("Draw Lanes")
cv2.setMouseCallback("Draw Lanes", mouse_callback)

print("="*50)
print("INSTRUCTIONS:")
print("1. Click 4 points on the image to define a lane polygon.")
print("2. Once 4 points are clicked, the lane is saved in memory and numbered.")
print("3. Press 'c' to cancel/clear the points of the current lane being drawn.")
print("4. Press 'r' to reset and delete ALL drawn lanes.")
print("5. Press 's' or 'q' to save the coordinates and exit.")
print("="*50)

while True:
    cv2.imshow("Draw Lanes", frame_copy)
    key = cv2.waitKey(1) & 0xFF
    if key == ord('q') or key == ord('s'):
        break
    elif key == ord('c'):
        current_points = []
        frame_copy = frame.copy()
        # redraw existing lanes
        for lid, pts in lanes.items():
            poly = [(int(pts[i]), int(pts[i+1])) for i in range(0, 8, 2)]
            poly_np = np.array(poly, np.int32).reshape((-1, 1, 2))
            cv2.polylines(frame_copy, [poly_np], True, (0, 255, 0), 2)
            cv2.putText(frame_copy, lid, poly[0], cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
    elif key == ord('r'):
        lanes = {}
        lane_id = 1
        current_points = []
        frame_copy = frame.copy()
        print("All lanes reset.")

output_dir = os.path.dirname(output_json)
if output_dir and not os.path.exists(output_dir):
    os.makedirs(output_dir)

with open(output_json, "w") as f:
    json.dump(lanes, f, indent=4)
print(f"Successfully saved {len(lanes)} lanes to {output_json}")

cv2.destroyAllWindows()

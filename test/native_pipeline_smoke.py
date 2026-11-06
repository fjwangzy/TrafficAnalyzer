"""Explicit CPU-only synthetic native pipeline smoke; does not evaluate Ascend throughput."""
import os
from pathlib import Path
import subprocess
import cv2
import numpy as np

video = '/tmp/native-smoke.avi'
writer = cv2.VideoWriter(video, cv2.VideoWriter_fourcc(*'MJPG'), 10, (320, 240))
assert writer.isOpened()
for _ in range(12):
    writer.write(np.zeros((240, 320, 3), dtype=np.uint8))
writer.release()
root = Path('/native')
command = [str(root / 'bin/python3'), str(root / 'app/main_optimized.py'),
           'hydra/job_logging=stdout', 'hydra.run.dir=/tmp', 'pipeline.send_info_kafka=False',
           'pipeline.save_video=False', 'pipeline.show_in_web=True', 'show_node.imshow=False',
           'video_saver_node.save_conflict_clips=False', 'telemetry.enabled=False',
           'detection_node.device=cpu', 'detection_node.imgsz=640', 'detection_node.adaptive_imgsz.enabled=False']
result = subprocess.run(command, cwd='/tmp', timeout=120, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        env={**os.environ, 'VIDEO_SRC': video, 'FRAME_STRIDE': '1', 'VIDEO_PORT': '8100',
                             'VIDEO_BIND_HOST': '127.0.0.1', 'DETECTION_WEIGHT_PATH': '/models/yolo11s-visdrone.pt',
                             'CAMERA_ID': '1', 'TOPIC_NAME': 'uav_statistics_1'})
output = result.stdout.decode(errors='replace')
print(output)
assert result.returncode == 0, result.returncode
for marker in ('MJPEG_READY', 'PIPELINE_EXIT', 'DETECTOR_DEVICE device=cpu'):
    assert marker in output, marker
assert 'Pipeline worker' not in output
assert 'Traceback (most recent call last)' not in output
assert 'leaked shared_memory' not in output
workers=4 if os.environ.get('PIPELINE_EGRESS_ENABLED','false').lower()=='true' else 3
if workers==4:
    assert 'ARCHIVER_READY protocol=1' in output and 'EGRESS_COMPLETE' in output
print(f'PASS real main_optimized.py {workers} workers, synthetic video, explicit CPU inference and natural EOF; NPU/FPS not_evaluated')

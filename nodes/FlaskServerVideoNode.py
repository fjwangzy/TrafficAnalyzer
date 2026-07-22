from flask import Flask, render_template, Response
from threading import Thread, Lock
import time
import numpy as np
import cv2

from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement


class EndpointAction(object):

    def __init__(self, action):
        self.action = action

    def __call__(self, *args):
        result = self.action()
        response = Response(result, status=200, headers={})
        return response


class VideoServer(object):
    app = None
    def __init__(self, config):
        import os as _os
        config_server = config["video_server_node"]
        self.app = Flask(__name__, template_folder=config_server["template_folder"])
        self.app.add_url_rule('/', 'index', EndpointAction(self._index))
        self.app.add_url_rule('/video', 'video', self._update_page)

        self.host_ip = config_server["host_ip"]
        # 支持 VIDEO_PORT 环境变量覆盖（多管道并行时避免端口冲突）
        self.port = int(_os.environ.get("VIDEO_PORT", config_server["port"]))
        self.index_page = config_server["index_page"]
        self.output_size = config_server["output_size"]
        self.target_fps = config_server.get("target_fps", 15)  # MJPEG 输出帧率上限
        self.jpeg_quality = int(config_server.get("jpeg_quality", 92))

        # 预编码JPEG：encode一次，多个客户端共享同一份bytes，避免重复编码
        init_jpeg = cv2.imencode(
            '.jpg',
            np.zeros(shape=(self.output_size[1], self.output_size[0], 3), dtype=np.uint8),
            [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality],
        )[1]
        self._jpeg_bytes: bytes = init_jpeg.tobytes()
        self._frame_lock = Lock()
        self.run()

    def _index(self) -> str:
        return render_template(self.index_page)

    def _gen(self):
        frame_interval = 1.0 / self.target_fps
        while True:
            t_start = time.time()

            with self._frame_lock:
                encoded_image = self._jpeg_bytes  # 读取预编码的JPEG（零拷贝引用）

            # Content-Length 是 MJPEG 标准要求的，部分浏览器缺少此头无法正确解析帧边界
            yield (b'--frame\r\n'
                b'Content-Type: image/jpeg\r\n'
                b'Content-Length: ' + str(len(encoded_image)).encode() + b'\r\n\r\n'
                + encoded_image + b'\r\n')

            # 帧率控制：避免CPU空转和网络带宽浪费
            elapsed = time.time() - t_start
            sleep_time = frame_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _update_page(self) -> Response:
        return Response(
            self._gen(),
            mimetype='multipart/x-mixed-replace; boundary=frame',
            headers={
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'X-Accel-Buffering': 'no',  # Tell nginx to not buffer
            },
        )

    def update_image(self, image: np.array):
        resized = cv2.resize(image, self.output_size)
        ret, jpeg = cv2.imencode('.jpg', resized, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
        with self._frame_lock:
            self._jpeg_bytes = jpeg.tobytes()

    def process(self, frame_element: FrameElement):
        # 如果是VideoEndBreakElement而不是FrameElement则退出处理
        if isinstance(frame_element, VideoEndBreakElement):
            return
        self.update_image(frame_element.frame_result)

    def run(self):
        # MJPEG 流需要持久连接，浏览器才能持续读取无限帧流。
        # Werkzeug 3.x 强制设置 Connection: close + Transfer-Encoding: chunked，
        # 导致浏览器拒绝渲染 MJPEG。改用 wsgiref + ThreadingMixIn（标准库），
        # HTTP/1.0 无 chunked、无 Connection: close，原生适合 MJPEG 流。
        from wsgiref.simple_server import make_server, WSGIServer, WSGIRequestHandler
        from socketserver import ThreadingMixIn

        class _ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
            daemon_threads = True
            allow_reuse_address = True

        class _QuietHandler(WSGIRequestHandler):
            def log_message(self, format, *args):
                pass  # 抑制每帧请求日志

        self._httpd = make_server(
            self.host_ip, self.port, self.app,
            server_class=_ThreadingWSGIServer,
            handler_class=_QuietHandler,
        )
        self.app_thread = Thread(target=self._httpd.serve_forever, daemon=True)
        self.app_thread.start()
        # Platform waits for this marker before publishing the pipeline as running.
        # make_server has already bound the socket, so browser requests are safe now.
        print(f"MJPEG_READY port={self.port}", flush=True)

    def stop_server(self):
        if hasattr(self, '_httpd'):
            self._httpd.shutdown()
        self.app_thread.join()



if __name__ == "__main__":
    config = {
        "video_server_node": {
            "index_page": "index.html",
            "host_ip": "localhost",
            "port": 8100,
            "template_folder": "../utils_local/templates",
            "output_size": [1280, 720],
            "jpeg_quality": 92,
            "target_fps": 15,
        }
    }
    video_server = VideoServer(config)  # __init__ 内已调用 run()
    while True:
        img = np.random.randint(0, 255, size=(480, 640, 3), dtype=np.uint8)
        video_server.update_image(img)

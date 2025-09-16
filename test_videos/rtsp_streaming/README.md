# 从mp4进行RTSP流传输

启动mediamtx服务器：

```
cd test_videos/rtsp_streaming
docker compose -p rtsp_server up -d --build
```
然后运行`ffmpeg_rtsp.ipynb`笔记本并指定您想要开始流式传输的视频。启动后，将可获得RTSP流链接。
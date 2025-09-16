# 从mp4进行RTSP流传输

启动mediamtx服务器：

```
cd test_videos/rtsp_streaming
docker compose -p rtsp_server up -d --build
```
Далее запустите ноутбук `ffmpeg_rtsp.ipynb` и укажите видео что хотите начать стримить. После запуска станет доступна rtsp ссылка на поток.
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_console_proxy_enforces_uat_upload_security_and_cache_contract():
    config = _read("console2/nginx.conf")

    assert "client_max_body_size 8g;" in config
    assert "access_log off;" in config
    assert "proxy_buffering off;" in config
    assert "proxy_set_header X-Forwarded-Proto $scheme;" in config
    assert "worker-src 'self' blob:" in config
    assert "Cache-Control \"public, max-age=31536000, immutable\"" in config
    assert "Cache-Control \"no-cache\"" in config


def test_root_proxy_never_serves_media_without_platform_authorization():
    config = _read("services/nginx/nginx.conf")

    assert "client_max_body_size 8g;" in config
    assert "alias /hls/;" not in config
    assert "traffic_analyzer_camera_$camera_id" not in config
    assert "rewrite ^/camera_(\\d+)$ /api/v1/video/camera/$1 break;" in config
    camera_location = config.split("location ~ ^/camera_", maxsplit=1)[1]
    assert "proxy_pass http://platform:8000;" in camera_location
    assert "location /hls/" in config
    assert config.count("access_log off;") >= 3

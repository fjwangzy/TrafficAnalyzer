from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import httpx

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_mp4new_runtime.py"
SPEC = spec_from_file_location("validate_mp4new_runtime", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_websocket_uses_cookie_session_without_query_token():
    cookies = httpx.Cookies()
    cookies.set("uav_media_session", "secret-jwt")

    url = MODULE._ws_url("http://127.0.0.1:8000")
    assert url == "ws://127.0.0.1:8000/ws/realtime"
    assert MODULE._cookie_header(cookies) == "uav_media_session=secret-jwt"
    assert "secret-jwt" not in url

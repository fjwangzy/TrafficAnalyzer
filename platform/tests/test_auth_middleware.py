import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.middleware.auth import AuthMiddleware, _is_active_user
from app.services.auth_service import create_access_token


async def _ok_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


class _SessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_args):
        return False


class AuthMiddlewareTest(unittest.IsolatedAsyncioTestCase):
    async def _call(self, headers=None, path="/api/v1/users"):
        sent = []
        app = AuthMiddleware(_ok_app)
        async def send(message):
            sent.append(message)

        scope = {
            "type": "http",
            "path": path,
            "headers": headers or [],
        }
        await app(scope, lambda: None, send)
        return sent

    async def test_protected_endpoint_requires_token(self):
        sent = await self._call()

        self.assertEqual(sent[0]["status"], 401)

    async def test_protected_endpoint_accepts_valid_bearer_token(self):
        token = create_access_token({"sub": "1", "username": "admin", "role": "admin"})
        with patch("app.middleware.auth._is_active_user", AsyncMock(return_value=True)):
            sent = await self._call([(b"authorization", f"Bearer {token}".encode())])

        self.assertEqual(sent[0]["status"], 200)

    async def test_protected_endpoint_rejects_inactive_bearer_identity(self):
        token = create_access_token({"sub": "7", "username": "disabled", "role": "viewer"})
        with patch("app.middleware.auth._is_active_user", AsyncMock(return_value=False)):
            sent = await self._call([(b"authorization", f"Bearer {token}".encode())])

        self.assertEqual(sent[0]["status"], 401)

    async def test_active_user_refreshes_current_database_role(self):
        payload = {"sub": "7", "username": "old-admin", "role": "admin"}
        session = SimpleNamespace(
            scalar=AsyncMock(
                return_value=SimpleNamespace(
                    id=7,
                    username="current-viewer",
                    role="viewer",
                    is_active=True,
                )
            )
        )
        with patch(
            "app.middleware.auth.async_session_maker",
            return_value=_SessionContext(session),
        ):
            active = await _is_active_user(payload)

        self.assertTrue(active)
        self.assertEqual(payload["username"], "current-viewer")
        self.assertEqual(payload["role"], "viewer")

    async def test_camera_mjpeg_proxy_requires_media_cookie(self):
        sent = await self._call(path="/api/v1/video/camera/11")

        self.assertEqual(sent[0]["status"], 401)

        token = create_access_token({"sub": "1", "username": "admin", "role": "admin"})
        with patch("app.middleware.auth._is_active_user", AsyncMock(return_value=True)):
            sent = await self._call(
                [(b"cookie", f"uav_media_session={token}".encode())],
                path="/api/v1/video/camera/11",
            )
        self.assertEqual(sent[0]["status"], 200)

    async def test_hls_requires_active_media_cookie(self):
        sent = await self._call(path="/hls/1/index.m3u8")
        self.assertEqual(sent[0]["status"], 401)

        token = create_access_token({"sub": "1", "username": "admin", "role": "admin"})
        cookie = [(b"cookie", f"uav_media_session={token}".encode())]
        with patch("app.middleware.auth._is_active_user", AsyncMock(return_value=False)):
            sent = await self._call(cookie, path="/hls/1/index.m3u8")
        self.assertEqual(sent[0]["status"], 401)
        with patch("app.middleware.auth._is_active_user", AsyncMock(return_value=True)):
            sent = await self._call(cookie, path="/hls/1/index.m3u8")
        self.assertEqual(sent[0]["status"], 200)

    async def test_public_paths_are_exact_not_prefixes(self):
        sent = await self._call(path="/health/private")
        self.assertEqual(sent[0]["status"], 401)

    async def test_register_requires_admin_role(self):
        viewer = create_access_token({"sub": "2", "username": "viewer", "role": "viewer"})
        with patch("app.middleware.auth._is_active_user", AsyncMock(return_value=True)):
            sent = await self._call(
                [(b"authorization", f"Bearer {viewer}".encode())],
                path="/api/v1/auth/register",
            )
        self.assertEqual(sent[0]["status"], 403)

    async def test_system_management_requires_admin_role(self):
        token = create_access_token({"sub": "2", "username": "viewer", "role": "viewer"})
        with patch("app.middleware.auth._is_active_user", AsyncMock(return_value=True)):
            sent = await self._call(
                [(b"authorization", f"Bearer {token}".encode())],
                path="/api/v1/system/health",
            )

        self.assertEqual(sent[0]["status"], 403)

    async def test_admin_can_access_calibration(self):
        token = create_access_token({"sub": "1", "username": "admin", "role": "admin"})
        with patch("app.middleware.auth._is_active_user", AsyncMock(return_value=True)):
            sent = await self._call(
                [(b"authorization", f"Bearer {token}".encode())],
                path="/api/v1/calibration/records",
            )

        self.assertEqual(sent[0]["status"], 200)

    async def test_calibration_task_images_require_admin_role(self):
        token = create_access_token({"sub": "2", "username": "viewer", "role": "viewer"})
        with patch("app.middleware.auth._is_active_user", AsyncMock(return_value=True)):
            sent = await self._call(
                [(b"authorization", f"Bearer {token}".encode())],
                path="/api/v1/calibration/lane-tasks/TASK-1/image",
            )

        self.assertEqual(sent[0]["status"], 403)

    async def test_websocket_requires_cookie_and_rejects_query_token(self):
        sent = []
        app = AuthMiddleware(_ok_app)

        async def send(message):
            sent.append(message)

        token = create_access_token({"sub": "1", "username": "admin", "role": "admin"})
        await app({"type": "websocket", "path": "/ws/realtime", "query_string": f"access_token={token}".encode(), "headers": []}, lambda: None, send)

        self.assertEqual(sent[0]["type"], "websocket.close")
        self.assertEqual(sent[0]["code"], 4401)

    async def test_websocket_rejects_invalid_query_token(self):
        sent = []
        app = AuthMiddleware(_ok_app)

        async def send(message):
            sent.append(message)

        await app(
            {"type": "websocket", "path": "/ws/realtime", "query_string": b"access_token=invalid", "headers": []},
            lambda: None,
            send,
        )

        self.assertEqual(sent[0]["type"], "websocket.close")
        self.assertEqual(sent[0]["code"], 4401)

    async def test_websocket_accepts_valid_cookie_and_injects_user(self):
        captured = {}
        sent = []

        async def websocket_app(scope, receive, send):
            captured.update(scope)
            await send({"type": "websocket.close", "code": 1000})

        async def send(message):
            sent.append(message)

        token = create_access_token({"sub": "1", "username": "admin", "role": "admin"})
        app = AuthMiddleware(websocket_app)
        with patch("app.middleware.auth._is_active_user", AsyncMock(return_value=True)):
            await app(
                {
                    "type": "websocket",
                    "path": "/ws/realtime",
                    "query_string": b"",
                    "headers": [(b"cookie", f"uav_media_session={token}".encode())],
                },
                lambda: None,
                send,
            )

        self.assertEqual(captured["state"]["user"]["username"], "admin")
        self.assertEqual(sent[0]["code"], 1000)

    async def test_websocket_rejects_inactive_cookie_identity(self):
        sent = []

        async def send(message):
            sent.append(message)

        token = create_access_token({"sub": "7", "username": "disabled", "role": "viewer"})
        app = AuthMiddleware(_ok_app)
        with patch("app.middleware.auth._is_active_user", AsyncMock(return_value=False)):
            await app(
                {
                    "type": "websocket",
                    "path": "/ws/realtime",
                    "query_string": b"",
                    "headers": [(b"cookie", f"uav_media_session={token}".encode())],
                },
                lambda: None,
                send,
            )
        self.assertEqual(sent[0]["code"], 4401)

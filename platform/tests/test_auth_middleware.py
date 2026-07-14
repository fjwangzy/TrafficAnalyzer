import unittest

from app.middleware.auth import AuthMiddleware
from app.services.auth_service import create_access_token


async def _ok_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


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
        sent = await self._call([(b"authorization", f"Bearer {token}".encode("utf-8"))])

        self.assertEqual(sent[0]["status"], 200)

    async def test_camera_mjpeg_proxy_is_public_for_img_tags(self):
        sent = await self._call(path="/api/v1/video/camera/11")

        self.assertEqual(sent[0]["status"], 200)

    async def test_system_management_requires_admin_role(self):
        token = create_access_token({"sub": "2", "username": "viewer", "role": "viewer"})
        sent = await self._call(
            [(b"authorization", f"Bearer {token}".encode("utf-8"))],
            path="/api/v1/system/health",
        )

        self.assertEqual(sent[0]["status"], 403)

    async def test_admin_can_access_calibration(self):
        token = create_access_token({"sub": "1", "username": "admin", "role": "admin"})
        sent = await self._call(
            [(b"authorization", f"Bearer {token}".encode("utf-8"))],
            path="/api/v1/calibration/records",
        )

        self.assertEqual(sent[0]["status"], 200)

    async def test_calibration_task_images_require_admin_role(self):
        token = create_access_token({"sub": "2", "username": "viewer", "role": "viewer"})
        sent = await self._call(
            [(b"authorization", f"Bearer {token}".encode("utf-8"))],
            path="/api/v1/calibration/lane-tasks/TASK-1/image",
        )

        self.assertEqual(sent[0]["status"], 403)

    async def test_websocket_requires_query_token(self):
        sent = []
        app = AuthMiddleware(_ok_app)

        async def send(message):
            sent.append(message)

        await app({"type": "websocket", "path": "/ws/realtime", "query_string": b"", "headers": []}, lambda: None, send)

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

    async def test_websocket_accepts_valid_query_token_and_injects_user(self):
        captured = {}
        sent = []

        async def websocket_app(scope, receive, send):
            captured.update(scope)
            await send({"type": "websocket.close", "code": 1000})

        async def send(message):
            sent.append(message)

        token = create_access_token({"sub": "1", "username": "admin", "role": "admin"})
        app = AuthMiddleware(websocket_app)
        await app(
            {
                "type": "websocket",
                "path": "/ws/realtime",
                "query_string": f"access_token={token}".encode("utf-8"),
                "headers": [],
            },
            lambda: None,
            send,
        )

        self.assertEqual(captured["state"]["user"]["username"], "admin")
        self.assertEqual(sent[0]["code"], 1000)

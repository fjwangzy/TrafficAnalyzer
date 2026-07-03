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

"""Authentication Middleware — pure ASGI implementation.

BaseHTTPMiddleware cannot properly handle WebSocket connections because
it wraps the ASGI scope in a Request object, which breaks the WebSocket
upgrade protocol. This pure ASGI implementation validates REST Bearer tokens
and WebSocket query-string tokens before forwarding either scope.
"""
from http.cookies import SimpleCookie
from urllib.parse import parse_qs

from sqlalchemy import select

from app.core.config import settings
from app.core.database import async_session_maker
from app.models.user import User
from app.services.auth_service import verify_token

# Public paths that skip authentication
PUBLIC_PATHS = [
    "/health",
    "/ready",
    "/api/v1/auth/login",
    "/api/v1/auth/logout",
    "/docs",
    "/openapi.json",
    "/redoc",
]


def _is_public_path(path: str) -> bool:
    return path in PUBLIC_PATHS


def _is_media_path(path: str) -> bool:
    return (
        path.startswith("/video/")
        or path.startswith("/api/v1/video/camera/")
        or path.startswith("/hls/")
        or path == "/api/v1/auth/media-session"
    )


def _cookie_token(headers: list[tuple[bytes, bytes]]) -> str | None:
    cookie = SimpleCookie()
    for key, value in headers:
        if key.lower() == b"cookie":
            cookie.load(value.decode("latin-1"))
    morsel = cookie.get(settings.media_cookie_name)
    return morsel.value if morsel else None


async def _is_active_user(payload: dict) -> bool:
    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        return False
    try:
        async with async_session_maker() as session:
            user = await session.scalar(select(User).where(User.id == user_id))
        if user is None or not user.is_active:
            return False
        # JWTs identify the session; authorization follows the current DB role
        # so a demotion takes effect without waiting for token expiry.
        payload["username"] = user.username
        payload["role"] = user.role
        return True
    except Exception:
        return False


class AuthMiddleware:
    """JWT authentication middleware — pure ASGI implementation.

    Correctly handles WebSocket connections without wrapping their scope and
    enforces the same JWT identity used by authenticated HTTP routes.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        """ASGI middleware entry point."""
        # Pass through non-HTTP/WebSocket scopes (lifespan, etc.)
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        # WebSocket clients authenticate only with the HttpOnly media cookie.
        if scope["type"] == "websocket":
            query = parse_qs(scope.get("query_string", b"").decode("utf-8"))
            if "access_token" in query:
                await send({"type": "websocket.close", "code": 4401, "reason": "Query token is not allowed"})
                return
            token = _cookie_token(scope.get("headers", []))
            if not token:
                await send({"type": "websocket.close", "code": 4401, "reason": "Missing access token"})
                return
            try:
                payload = verify_token(token)
                if not await _is_active_user(payload):
                    raise ValueError("inactive user")
                scope.setdefault("state", {})
                scope["state"]["user"] = payload
            except Exception:
                await send({"type": "websocket.close", "code": 4401, "reason": "Invalid access token"})
                return
            await self.app(scope, receive, send)
            return

        # HTTP: check if path is public
        path = scope.get("path", "")
        if _is_public_path(path):
            await self.app(scope, receive, send)
            return

        if _is_media_path(path):
            token = _cookie_token(scope.get("headers", []))
            if not token:
                await self._send_json_response(send, 401, {"detail": "Missing media session"})
                return
            try:
                payload = verify_token(token)
                if not await _is_active_user(payload):
                    raise ValueError("inactive user")
                scope.setdefault("state", {})
                scope["state"]["user"] = payload
            except Exception:
                await self._send_json_response(send, 401, {"detail": "Invalid media session"})
                return
            await self.app(scope, receive, send)
            return

        # HTTP: extract and validate JWT token from Authorization header
        headers = dict(scope.get("headers", []))
        # headers are bytes pairs, decode the Authorization header
        auth_header = None
        for key, value in headers.items():
            if key == b"authorization":
                auth_header = value.decode("utf-8")
                break

        if not auth_header:
            # Return 401 JSON response
            await self._send_json_response(send, 401, {"detail": "Missing Authorization header"})
            return

        if not auth_header.startswith("Bearer "):
            await self._send_json_response(send, 401, {"detail": "Invalid Authorization header format"})
            return

        token = auth_header.replace("Bearer ", "")

        try:
            payload = verify_token(token)
            if not await _is_active_user(payload):
                raise ValueError("inactive user")
            # Inject user info into scope state
            scope.setdefault("state", {})
            scope["state"]["user"] = payload
        except Exception as e:
            await self._send_json_response(send, 401, {"detail": f"Invalid token: {str(e)}"})
            return

        admin_prefixes = (
            "/api/v1/system",
            "/api/v1/users",
            "/api/v1/calibration",
            "/api/v1/auth/register",
        )
        is_admin_path = any(
            path == prefix or path.startswith(f"{prefix}/")
            for prefix in admin_prefixes
        )
        if is_admin_path and payload.get("role") != "admin":
            await self._send_json_response(send, 403, {"detail": "Administrator role required"})
            return

        # Auth passed — continue to app
        await self.app(scope, receive, send)

    async def _send_json_response(self, send, status_code, body: dict):
        """Send a JSON HTTP response directly through ASGI."""
        import json

        body_bytes = json.dumps(body, default=str).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                [b"content-type", b"application/json"],
                [b"content-length", str(len(body_bytes)).encode()],
            ],
        })
        await send({
            "type": "http.response.body",
            "body": body_bytes,
        })

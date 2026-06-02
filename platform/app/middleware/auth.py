"""Authentication Middleware — pure ASGI implementation.

BaseHTTPMiddleware cannot properly handle WebSocket connections because
it wraps the ASGI scope in a Request object, which breaks the WebSocket
upgrade protocol. This implementation uses pure ASGI to correctly
pass through WebSocket connections while enforcing JWT auth on HTTP routes.
"""
from app.services.auth_service import verify_token


# Public paths that skip authentication
PUBLIC_PATHS = [
    "/health",
    "/ready",
    "/ws/",          # WebSocket connections (auth handled via channel subscriptions)
    "/video/",       # Video stream endpoints (MJPEG proxy)
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/pipelines/proxy-map",  # Camera port mapping for Vite dev proxy
    "/docs",
    "/openapi.json",
    "/redoc",
]


class AuthMiddleware:
    """JWT authentication middleware — pure ASGI implementation.

    Correctly handles WebSocket connections by passing them through
    without attempting JWT validation. HTTP routes are validated normally.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        """ASGI middleware entry point."""
        # Pass through non-HTTP/WebSocket scopes (lifespan, etc.)
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        # Pass through WebSocket connections without auth check
        if scope["type"] == "websocket":
            await self.app(scope, receive, send)
            return

        # HTTP: check if path is public
        path = scope.get("path", "")
        if any(path.startswith(prefix) for prefix in PUBLIC_PATHS):
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
            # Inject user info into scope state
            scope.setdefault("state", {})
            scope["state"]["user"] = payload
        except Exception as e:
            await self._send_json_response(send, 401, {"detail": f"Invalid token: {str(e)}"})
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

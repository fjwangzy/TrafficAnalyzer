"""Authentication Middleware"""
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from traffic_platform.auth import verify_token
import os


class AuthMiddleware(BaseHTTPMiddleware):
    """JWT authentication middleware for the gateway"""

    async def dispatch(self, request: Request, call_next):
        """Validate JWT token for protected routes"""

        # Skip authentication for health checks and public endpoints
        public_paths = [
            "/health",
            "/ready",
            "/api/v1/auth/login",
            "/api/v1/auth/register",
            "/docs",
            "/openapi.json",
            "/redoc",
        ]

        if any(request.url.path.startswith(path) for path in public_paths):
            return await call_next(request)

        # Extract Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing Authorization header"},
            )

        # Validate Bearer token format
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid Authorization header format"},
            )

        token = auth_header.replace("Bearer ", "")

        # Verify JWT token
        try:
            payload = verify_token(token)
            # Attach user info to request state for downstream services
            request.state.user = payload
        except Exception as e:
            return JSONResponse(
                status_code=401,
                content={"detail": f"Invalid token: {str(e)}"},
            )

        # Continue to next middleware or route
        response = await call_next(request)
        return response

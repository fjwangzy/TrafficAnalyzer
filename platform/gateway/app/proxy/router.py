"""Request Router"""
from fastapi import Request
from fastapi.responses import Response, JSONResponse
from typing import Optional
import os

from .client import ProxyClient


class ProxyRouter:
    """Routes requests to appropriate microservices"""

    def __init__(self, client: ProxyClient):
        self.client = client

        # Service URLs from environment variables
        self.services = {
            "operations": os.getenv("OPERATIONS_URL", "http://localhost:8001"),
            "vision": os.getenv("VISION_URL", "http://localhost:8002"),
            "flight": os.getenv("FLIGHT_URL", "http://localhost:8003"),
            "annotation": os.getenv("ANNOTATION_URL", "http://localhost:8004"),
        }

        # Route mapping: path prefix -> service name
        self.routes = {
            # Operations service - intersections, alerts, webhooks, reports
            "api/v1/intersections": "operations",
            "api/v1/alerts": "operations",
            "api/v1/webhooks": "operations",
            "api/v1/reports": "operations",
            "api/v1/auth": "operations",

            # Vision service - video streams, trajectories, detection
            "api/v1/video": "vision",
            "api/v1/trajectories": "vision",
            "api/v1/detection": "vision",
            "api/v1/tracks": "vision",

            # Flight service - drones, missions, telemetry
            "api/v1/drones": "flight",
            "api/v1/missions": "flight",
            "api/v1/telemetry": "flight",

            # Annotation service - calibration, labels
            "api/v1/calibration": "annotation",
            "api/v1/labels": "annotation",
        }

    def get_target_service(self, path: str) -> Optional[str]:
        """
        Determine which service should handle this request

        Args:
            path: Request path (e.g., "api/v1/intersections/123")

        Returns:
            Service name or None if no match
        """
        # Find the longest matching prefix
        best_match = None
        best_match_length = 0

        for prefix, service in self.routes.items():
            if path.startswith(prefix) and len(prefix) > best_match_length:
                best_match = service
                best_match_length = len(prefix)

        return best_match

    def build_target_url(self, service_name: str, path: str) -> str:
        """
        Build the full URL for the target service

        Args:
            service_name: Name of the service (operations, vision, etc.)
            path: Request path

        Returns:
            Full URL to forward the request to
        """
        base_url = self.services.get(service_name)
        if not base_url:
            raise ValueError(f"Unknown service: {service_name}")

        # Ensure path starts with /
        if not path.startswith("/"):
            path = f"/{path}"

        return f"{base_url}{path}"

    async def route(self, request: Request, path: str) -> Response:
        """
        Route a request to the appropriate microservice

        Args:
            request: Incoming FastAPI request
            path: Request path

        Returns:
            Response from the downstream service
        """
        # Determine target service
        service_name = self.get_target_service(path)
        if not service_name:
            return JSONResponse(
                status_code=404,
                content={
                    "detail": f"No service found for path: /{path}",
                    "available_routes": list(self.routes.keys()),
                },
            )

        # Build target URL
        try:
            target_url = self.build_target_url(service_name, path)
        except ValueError as e:
            return JSONResponse(
                status_code=500,
                content={"detail": str(e)},
            )

        # Read request body
        content = await request.body()

        # Extract headers
        headers = dict(request.headers)

        # Add user info from auth middleware (if available)
        if hasattr(request.state, "user"):
            headers["X-User-ID"] = request.state.user.sub
            headers["X-User-Name"] = request.state.user.username
            headers["X-User-Role"] = request.state.user.role

        # Forward the request
        try:
            response = await self.client.forward_request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=content if content else None,
                params=dict(request.query_params),
            )

            # Build response with same status, headers, and content
            response_headers = dict(response.headers)

            # Remove hop-by-hop headers from response
            headers_to_remove = [
                "content-encoding",
                "content-length",
                "transfer-encoding",
                "connection",
            ]
            for header in headers_to_remove:
                response_headers.pop(header, None)

            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=response_headers,
            )

        except Exception as e:
            return JSONResponse(
                status_code=502,
                content={
                    "detail": f"Failed to forward request to {service_name}",
                    "error": str(e),
                    "target_url": target_url,
                },
            )

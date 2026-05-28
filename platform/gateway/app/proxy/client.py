"""HTTP Proxy Client"""
import httpx
from typing import Optional


class ProxyClient:
    """HTTP client for proxying requests to microservices"""

    def __init__(self, timeout: float = 30.0):
        self.client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
        )

    async def forward_request(
        self,
        method: str,
        url: str,
        headers: dict,
        content: Optional[bytes] = None,
        params: Optional[dict] = None,
    ) -> httpx.Response:
        """
        Forward a request to a downstream service

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            url: Full URL to the downstream service
            headers: Request headers
            content: Request body (optional)
            params: Query parameters (optional)

        Returns:
            httpx.Response from the downstream service
        """
        # Remove hop-by-hop headers that shouldn't be forwarded
        headers_to_remove = [
            "host",
            "content-length",
            "transfer-encoding",
            "connection",
        ]
        clean_headers = {
            k: v for k, v in headers.items()
            if k.lower() not in headers_to_remove
        }

        # Forward the request
        response = await self.client.request(
            method=method,
            url=url,
            headers=clean_headers,
            content=content,
            params=params,
        )

        return response

    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()

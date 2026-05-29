"""API Gateway - Main Application"""
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import os
import httpx

from .middleware.auth import AuthMiddleware
from .proxy.router import ProxyRouter
from .proxy.client import ProxyClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    app.state.proxy_client = ProxyClient()
    app.state.proxy_router = ProxyRouter(app.state.proxy_client)
    print("🚀 Gateway started")
    print(f"   - Operations service: {os.getenv('OPERATIONS_URL', 'http://localhost:8001')}")
    print(f"   - Vision service: {os.getenv('VISION_URL', 'http://localhost:8002')}")
    print(f"   - Flight service: {os.getenv('FLIGHT_URL', 'http://localhost:8003')}")
    print(f"   - Annotation service: {os.getenv('ANNOTATION_URL', 'http://localhost:8004')}")

    yield

    # Shutdown
    await app.state.proxy_client.close()
    print("🛑 Gateway stopped")


app = FastAPI(
    title="Traffic Platform Gateway",
    description="API Gateway for Traffic Platform microservices",
    version="0.1.0",
    lifespan=lifespan,
)

# Add authentication middleware
app.add_middleware(AuthMiddleware)


@app.get("/health")
async def health_check():
    """Gateway health check"""
    return {"status": "healthy", "service": "gateway"}


@app.get("/ready")
async def readiness_check(request: Request):
    """Check if all downstream services are ready"""
    proxy_client: ProxyClient = request.app.state.proxy_client

    services = {
        "operations": os.getenv("OPERATIONS_URL", "http://localhost:8001"),
        "vision": os.getenv("VISION_URL", "http://localhost:8002"),
        "flight": os.getenv("FLIGHT_URL", "http://localhost:8003"),
        "annotation": os.getenv("ANNOTATION_URL", "http://localhost:8004"),
    }

    results = {}
    all_ready = True

    for name, url in services.items():
        try:
            response = await proxy_client.client.get(f"{url}/health", timeout=2.0)
            # Fall back to root if /health is not available (e.g. annotation service)
            if response.status_code == 404:
                response = await proxy_client.client.get(f"{url}/", timeout=2.0)
            is_healthy = 200 <= response.status_code < 300
            results[name] = {
                "status": "healthy" if is_healthy else "unhealthy",
                "url": url,
            }
            if not is_healthy:
                all_ready = False
        except Exception as e:
            results[name] = {
                "status": "unreachable",
                "url": url,
                "error": str(e),
            }
            all_ready = False

    return JSONResponse(
        status_code=200 if all_ready else 503,
        content={
            "status": "ready" if all_ready else "not_ready",
            "services": results,
        },
    )


# WebSocket proxy to Vision service
@app.websocket("/ws/realtime")
async def ws_proxy(websocket: WebSocket):
    """Proxy WebSocket connections to Vision service"""
    await websocket.accept()

    vision_ws_url = os.getenv("VISION_WS_URL", "ws://localhost:8002/ws/realtime")

    try:
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", vision_ws_url.replace("ws://", "http://").replace("wss://", "https://")) as _:
                pass
    except Exception:
        pass

    # Use websockets library for actual WebSocket proxy
    try:
        import websockets
        async with websockets.connect(vision_ws_url) as upstream:
            import asyncio

            async def forward_client_to_upstream():
                while True:
                    msg = await websocket.receive_text()
                    await upstream.send(msg)

            async def forward_upstream_to_client():
                while True:
                    msg = await upstream.recv()
                    await websocket.send_text(msg)

            done, pending = await asyncio.wait(
                [
                    asyncio.ensure_future(forward_client_to_upstream()),
                    asyncio.ensure_future(forward_upstream_to_client()),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass


# Catch-all route for proxying requests — register all methods explicitly
@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_request(request: Request, path: str):
    """Proxy all requests to appropriate microservice"""
    proxy_router: ProxyRouter = request.app.state.proxy_router
    return await proxy_router.route(request, path)

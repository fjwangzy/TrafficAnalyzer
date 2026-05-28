"""API Gateway - Main Application"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import os

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
            results[name] = {
                "status": "healthy" if response.status_code == 200 else "unhealthy",
                "url": url,
            }
            if response.status_code != 200:
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


# Catch-all route for proxying requests
@app.api_route("/{path:path}")
async def proxy_request(request: Request, path: str):
    """Proxy all requests to appropriate microservice"""
    proxy_router: ProxyRouter = request.app.state.proxy_router
    return await proxy_router.route(request, path)

"""Operations service configuration."""
from pydantic_settings import BaseSettings
from traffic_platform.config.settings import Settings as SharedSettings


class OperationsSettings(BaseSettings):
    """Operations service specific settings."""

    # Database
    database_url: str = "postgresql+asyncpg://traffic:traffic@localhost:5432/traffic_platform"

    # Service
    service_name: str = "operations"
    service_port: int = 8001
    debug: bool = False

    # CORS
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:8080"]

    class Config:
        env_file = ".env"
        env_prefix = "OPS_"
        case_sensitive = False


# Global settings instances
shared_settings = SharedSettings()
ops_settings = OperationsSettings()

"""Flight Service configuration."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class FlightSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FLIGHT_", env_file=".env")
    service_name: str = "flight"
    service_port: int = 8003
    debug: bool = False
    cors_origins: list[str] = ["*"]


settings = FlightSettings()

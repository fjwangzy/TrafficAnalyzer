"""Application settings using pydantic-settings"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class DatabaseSettings(BaseSettings):
    """PostgreSQL 数据库配置"""
    model_config = SettingsConfigDict(env_prefix="DB_")

    host: str = "localhost"
    port: int = 5432
    user: str = "traffic"
    password: str = "traffic123"
    database: str = "traffic_platform"

    @property
    def url(self) -> str:
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"

    @property
    def sync_url(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


class KafkaSettings(BaseSettings):
    """Kafka 配置"""
    model_config = SettingsConfigDict(env_prefix="KAFKA_")

    bootstrap_servers: str = "localhost:9092"
    consumer_group: str = "platform-api"
    auto_offset_reset: str = "latest"
    enable_auto_commit: bool = True


class InfluxDBSettings(BaseSettings):
    """InfluxDB 配置"""
    model_config = SettingsConfigDict(env_prefix="INFLUX_")

    host: str = "localhost"
    port: int = 8086
    database: str = "traffic"
    username: str = ""
    password: str = ""
    retention_policy: str = "autogen"

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"


class JWTSettings(BaseSettings):
    """JWT 配置"""
    model_config = SettingsConfigDict(env_prefix="JWT_")

    secret_key: str = "your-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30


class Settings(BaseSettings):
    """应用总配置"""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # 应用基础配置
    app_name: str = "Traffic Platform"
    debug: bool = False
    api_prefix: str = "/api/v1"

    # 子配置
    db: DatabaseSettings = DatabaseSettings()
    kafka: KafkaSettings = KafkaSettings()
    influx: InfluxDBSettings = InfluxDBSettings()
    jwt: JWTSettings = JWTSettings()


@lru_cache()
def get_settings() -> Settings:
    """获取全局配置（单例）"""
    return Settings()

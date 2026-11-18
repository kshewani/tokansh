from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: str = "sqlite:///./data/tokansh.db"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    demo_auth_enabled: bool = True
    tokansh_gateway_secret: str | None = None
    tokansh_operator_secret: str | None = None
    drunix_gateway_url: str | None = None
    drunix_gateway_timeout_seconds: float = 7.0

    @field_validator("drunix_gateway_url")
    @classmethod
    def private_gateway(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = urlsplit(value)
        if (parts.scheme != "http" or parts.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parts.username or parts.password or parts.path not in {"", "/"} or parts.query or parts.fragment
                or not parts.port):
            raise ValueError("DRUNIX_GATEWAY_URL must be an explicit loopback HTTP origin")
        return value.rstrip("/")

    @field_validator("drunix_gateway_timeout_seconds")
    @classmethod
    def bounded_gateway_timeout(cls, value: float) -> float:
        if not 0.1 <= value <= 12:
            raise ValueError("Gateway timeout must be between 0.1 and 12 seconds")
        return value

    @field_validator("app_port")
    @classmethod
    def valid_port(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError("APP_PORT must be between 1 and 65535")
        return value

    @field_validator("database_url")
    @classmethod
    def sqlite_database(cls, value: str) -> str:
        try:
            url = make_url(value)
        except ArgumentError as exc:
            raise ValueError("DATABASE_URL must be a valid SQLite connection URL") from exc
        if (url.drivername not in {"sqlite", "sqlite+pysqlite"} or url.query
                or url.host or url.username or url.password or url.port):
            raise ValueError("M2 requires a SQLite application database")
        if not url.database or url.database == ":memory:":
            raise ValueError("Use a persistent SQLite file, including for isolated tests")
        return value

    @field_validator("cors_origins")
    @classmethod
    def explicit_origins(cls, value: str) -> str:
        for origin in value.split(","):
            parts = urlsplit(origin.strip())
            if (parts.scheme not in {"http", "https"} or not parts.hostname
                    or parts.username or parts.password or parts.path or parts.query or parts.fragment):
                raise ValueError("CORS_ORIGINS must contain explicit HTTP(S) origins without paths")
        return value

    @model_validator(mode="after")
    def development_auth_only(self):
        if self.app_env == "production" and self.demo_auth_enabled:
            raise ValueError("Demo header authentication must be disabled in production")
        return self

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",")]


@lru_cache
def get_settings() -> Settings:
    return Settings()

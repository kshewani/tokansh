from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ResponseMeta(BaseModel):
    correlation_id: str


class Envelope(BaseModel, Generic[T]):
    data: T
    meta: ResponseMeta


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    error: ErrorDetail
    meta: ResponseMeta


class SystemComponent(BaseModel):
    name: str
    status: Literal["CONNECTED", "UNAVAILABLE", "UNKNOWN", "DEGRADED"]
    detail: str | None = None


class SystemStatus(BaseModel):
    components: list[SystemComponent]
    last_ledger_operation: None = None


class Readiness(SystemStatus):
    ready: Literal[False]


class HealthStatus(BaseModel):
    status: Literal["UP"]


class SafeConfiguration(BaseModel):
    app_env: Literal["development", "test", "production"]
    demo_auth_enabled: bool
    ledger_integration: Literal["NOT_IMPLEMENTED"]

"""Private read-only Go boundary. No DRUNIX SDK, signing keys, writes or fallback data."""
import re
import json
import time
from datetime import datetime, timezone
from typing import Annotated, Generic, Literal, TypeVar

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.dependencies import DemoActor, demo_actor
from app.errors import ApplicationError, success
from app.schemas import Envelope

T = TypeVar("T")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class DiagnosticAsset(StrictModel):
    ID: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")]
    Color: str
    Size: int
    Owner: str
    AppraisedValue: int


class DiagnosticObservation(StrictModel, Generic[T]):
    source: Literal["DRUNIX_EVALUATE"]
    channel: Literal["mychannel"]
    chaincode: Literal["basic"]
    function: Literal["GetAllAssets", "ReadAsset", "AssetExists"]
    observed_at: str
    result: T

    @field_validator("observed_at")
    @classmethod
    def fresh_observation(cls, value: str) -> str:
        # Go emits RFC3339Nano; Python 3.10 accepts only 3 or 6 fractional digits.
        match = re.fullmatch(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})", value)
        if match is None:
            raise ValueError("Observation must be RFC3339")
        fraction = (match[2] or "").ljust(6, "0")[:6]
        instant = datetime.fromisoformat(match[1] + "." + fraction + match[3].replace("Z", "+00:00"))
        if instant.utcoffset() is None:
            raise ValueError("Observation must have a timezone")
        age = (datetime.now(timezone.utc) - instant).total_seconds()
        if not -5 <= age <= 30:
            raise ValueError("Observation is stale or in the future")
        return value


class GatewayMeta(StrictModel):
    correlation_id: str


class GatewayEnvelope(StrictModel, Generic[T]):
    data: T
    meta: GatewayMeta


class GatewayHealth(StrictModel):
    status: Literal["UP"]
    mode: Literal["READ_ONLY"]


class TokanshContractInfo(StrictModel):
    contract: Literal["tokansh"]
    schema_version: Literal[1]
    functions: list[str]
    supply_interpretation: str


class GatewayAdapter:
    def __init__(self, base_url: str | None, client: httpx.Client):
        self.base_url = base_url
        self.client = client

    def _get(self, path: str, correlation_id: str, model):
        if self.base_url is None:
            raise ApplicationError(503, "GATEWAY_UNAVAILABLE", "Read-only gateway is not configured.")
        try:
            deadline = time.monotonic() + (self.client.timeout.read or 7)
            with self.client.stream("GET", self.base_url + path, headers={"X-Correlation-ID": correlation_id}) as response:
                if response.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
                    raise ValueError("Unsupported content type")
                body = bytearray()
                for chunk in response.iter_bytes():
                    if time.monotonic() > deadline:
                        raise ApplicationError(504, "GATEWAY_TIMEOUT", "The private gateway response exceeded its deadline.")
                    body.extend(chunk)
                    if len(body) > 1 << 20:
                        raise ApplicationError(502, "GATEWAY_BAD_RESPONSE", "Gateway response exceeds the diagnostic limit.")
                if response.headers.get("X-Correlation-ID") != correlation_id:
                    raise ValueError("Response correlation does not match")
                if response.status_code != 200:
                    # Validate an error envelope, but never forward raw upstream error messages.
                    payload = json.loads(body)
                    if (set(payload) != {"error", "meta"} or payload["meta"] != {"correlation_id": correlation_id}
                            or set(payload["error"]) != {"code", "message"} or not isinstance(payload["error"]["message"], str)):
                        raise ValueError("Invalid error envelope")
                    code = payload["error"]["code"]
                    errors = {"LEDGER_UNAVAILABLE": (503, "DRUNIX diagnostic evaluation is unavailable."),
                              "LEDGER_TIMEOUT": (504, "DRUNIX diagnostic evaluation timed out."),
                              "REQUEST_CANCELLED": (408, "DRUNIX diagnostic evaluation was cancelled."),
                              "ASSET_NOT_FOUND": (404, "Diagnostic asset was not found."),
                              "INVALID_ARGUMENT": (400, "Diagnostic request arguments are invalid."),
                              "MALFORMED_LEDGER_RESPONSE": (502, "DRUNIX returned invalid diagnostic data.")}
                    if code not in errors or errors[code][0] != response.status_code:
                        raise ValueError("Unsupported gateway error")
                    raise ApplicationError(errors[code][0], code, errors[code][1])
                frame = GatewayEnvelope[model].model_validate_json(body)
                if frame.meta.correlation_id != correlation_id:
                    raise ValueError("Envelope correlation does not match")
                return frame.data
        except httpx.TimeoutException as exc:
            raise ApplicationError(504, "GATEWAY_TIMEOUT", "The private gateway did not respond in time.") from exc
        except httpx.RequestError as exc:
            raise ApplicationError(503, "GATEWAY_UNAVAILABLE", "The private gateway could not be reached.") from exc
        except (ValidationError, ValueError, TypeError, KeyError, AttributeError) as exc:
            raise ApplicationError(502, "GATEWAY_BAD_RESPONSE", "The private gateway returned an unsupported response.") from exc

    def health(self, correlation_id: str):
        return self._get("/health", correlation_id, GatewayHealth)

    def contract_info(self, correlation_id: str):
        if self.base_url is None:
            raise ApplicationError(503, "GATEWAY_UNAVAILABLE", "Read-only gateway is not configured.")
        try:
            with self.client.stream("GET", self.base_url + "/v1/tokansh/contract-info",
                                    headers={"X-Correlation-ID": correlation_id}) as response:
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 1 << 20:
                        raise ApplicationError(502, "GATEWAY_BAD_RESPONSE", "Gateway response exceeds the diagnostic limit.")
                if response.status_code != 200:
                    raise ApplicationError(503, "LEDGER_UNAVAILABLE", "DRUNIX diagnostic evaluation is unavailable.")
                payload = json.loads(body)
                data = payload.get("data", payload) if isinstance(payload, dict) else None
                if not isinstance(data, dict) or data.get("contract") != "tokansh":
                    raise ApplicationError(502, "GATEWAY_BAD_RESPONSE", "The private gateway returned an unsupported response.")
                return data
        except httpx.TimeoutException as exc:
            raise ApplicationError(504, "GATEWAY_TIMEOUT", "The private gateway did not respond in time.") from exc
        except httpx.RequestError as exc:
            raise ApplicationError(503, "GATEWAY_UNAVAILABLE", "The private gateway could not be reached.") from exc
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise ApplicationError(502, "GATEWAY_BAD_RESPONSE", "The private gateway returned an unsupported response.") from exc

    def all_assets(self, correlation_id: str):
        observation = self._get("/v1/basic/assets", correlation_id, DiagnosticObservation[list[DiagnosticAsset]])
        if observation.function != "GetAllAssets" or len({asset.ID for asset in observation.result}) != len(observation.result):
            raise ApplicationError(502, "GATEWAY_BAD_RESPONSE", "The diagnostic result does not match the request.")
        return observation

    def read_asset(self, asset_id: str, correlation_id: str):
        self._validate_id(asset_id)
        observation = self._get(f"/v1/basic/assets/{asset_id}", correlation_id, DiagnosticObservation[DiagnosticAsset])
        if observation.function != "ReadAsset" or observation.result.ID != asset_id:
            raise ApplicationError(502, "GATEWAY_BAD_RESPONSE", "The diagnostic result does not match the request.")
        return observation

    def asset_exists(self, asset_id: str, correlation_id: str):
        self._validate_id(asset_id)
        observation = self._get(f"/v1/basic/assets/{asset_id}/exists", correlation_id, DiagnosticObservation[bool])
        if observation.function != "AssetExists":
            raise ApplicationError(502, "GATEWAY_BAD_RESPONSE", "The diagnostic result does not match the request.")
        return observation

    @staticmethod
    def _validate_id(asset_id: str):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", asset_id):
            raise ApplicationError(400, "INVALID_REQUEST", "Diagnostic asset ID is invalid.")

    def connectivity(self, correlation_id: str) -> tuple[str, str]:
        try:
            self.health(correlation_id)
        except ApplicationError as exc:
            return ("DEGRADED" if exc.code == "GATEWAY_BAD_RESPONSE" else "UNAVAILABLE"), "UNKNOWN"
        try:
            self.contract_info(correlation_id)
        except ApplicationError as exc:
            return "CONNECTED", "UNAVAILABLE" if exc.code.startswith("LEDGER_") else "UNKNOWN"
        return "CONNECTED", "CONNECTED"


def get_gateway(request: Request) -> GatewayAdapter:
    return request.app.state.gateway


def diagnostic_admin(actor: Annotated[DemoActor, Depends(demo_actor)]) -> DemoActor:
    if actor.role != "ADMIN":
        raise ApplicationError(403, "INSUFFICIENT_PERMISSIONS", "Diagnostics require the admin demo role.")
    return actor


router = APIRouter(prefix="/api/v1/diagnostics/drunix/basic", tags=["read-only diagnostics"])


@router.get("/assets", response_model=Envelope[DiagnosticObservation[list[DiagnosticAsset]]])
def diagnostic_assets(request: Request, actor: Annotated[DemoActor, Depends(diagnostic_admin)],
                      gateway: Annotated[GatewayAdapter, Depends(get_gateway)]):
    return success(request, gateway.all_assets(request.state.correlation_id))

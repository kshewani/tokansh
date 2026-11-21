"""Runtime configuration from environment variables (AGENTS.md section 11).

There is deliberately no ledger "mode" setting: the running application always
uses the real DRUNIX gateway adapter (ADR-005, DRUNIX_INTEGRATION 8.1).
"""
import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


@dataclass(frozen=True)
class Settings:
    app_env: str = "development"
    database_url: str = "sqlite:///./data/tokansh.db"
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"])
    # Optional regex for extra allowed origins, e.g. Vercel preview URLs: https://.*\.vercel\.app
    cors_origin_regex: str | None = None
    # Private TokANSH Go gateway (gateway/, see gateway/TRANSACTIONS.md). Loopback only.
    # Empty = not configured: every ledger operation fails safely.
    drunix_gateway_url: str = ""
    # Two distinct random 32-byte secrets (64 hex chars) shared with the gateway process.
    tokansh_gateway_secret: str = ""
    tokansh_operator_secret: str = ""
    # Optional pin "MSP:sha256-of-signer-certificate"; when set, prepared artifacts must match it.
    drunix_signer: str = ""
    drunix_channel: str = "mychannel"
    drunix_chaincode: str = "tokansh"
    drunix_timeout_seconds: float = 7.0
    commit_poll_attempts: int = 3
    commit_poll_interval_seconds: float = 1.0
    # Demonstration LTV threshold in basis points (Rule 8.5: configurable, not in the UI).
    max_ltv_bps: int = 6000

    @classmethod
    def from_env(cls) -> "Settings":
        origins = os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
        return cls(
            app_env=os.environ.get("APP_ENV", "development"),
            database_url=os.environ.get("DATABASE_URL", "sqlite:///./data/tokansh.db"),
            cors_origins=[o.strip() for o in origins.split(",") if o.strip()],
            cors_origin_regex=os.environ.get("CORS_ORIGIN_REGEX") or None,
            drunix_gateway_url=os.environ.get("DRUNIX_GATEWAY_URL", "").rstrip("/"),
            tokansh_gateway_secret=os.environ.get("TOKANSH_GATEWAY_SECRET", ""),
            tokansh_operator_secret=os.environ.get("TOKANSH_OPERATOR_SECRET", ""),
            drunix_signer=os.environ.get("DRUNIX_SIGNER", ""),
            # DRUNIX_CHAINCODE names the gateway's diagnostic chaincode ("basic"); ours is fixed.
            drunix_channel=os.environ.get("DRUNIX_CHANNEL", "mychannel"),
            drunix_chaincode=os.environ.get("TOKANSH_CHAINCODE", "tokansh"),
            drunix_timeout_seconds=_float("DRUNIX_GATEWAY_TIMEOUT_SECONDS", 7.0),
            commit_poll_attempts=_int("DRUNIX_COMMIT_POLL_ATTEMPTS", 3),
            commit_poll_interval_seconds=_float("DRUNIX_COMMIT_POLL_INTERVAL_SECONDS", 1.0),
            max_ltv_bps=_int("MAX_LTV_BPS", 6000),
        )

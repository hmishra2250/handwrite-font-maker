from __future__ import annotations

import hmac
import os
from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping


class DeploymentMode(StrEnum):
    LOCAL = "local"
    INVITE_BETA = "invite_beta"
    PRODUCTION = "production"


class SecurityError(RuntimeError):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class RuntimeConfig:
    mode: DeploymentMode
    database_url: str | None
    supabase_url: str | None
    supabase_service_role_key: str | None
    supabase_anon_key: str | None
    internal_api_key: str | None
    process_jobs_inline: bool
    storage_bucket: str
    daily_upload_limit: int
    daily_upload_bytes_limit: int
    daily_preview_limit: int
    daily_build_limit: int
    active_job_limit: int

    @property
    def auth_required(self) -> bool:
        return self.mode in {DeploymentMode.INVITE_BETA, DeploymentMode.PRODUCTION}


def load_runtime_config(env: Mapping[str, str] | None = None) -> RuntimeConfig:
    source = os.environ if env is None else env
    explicit_mode = source.get("DEPLOYMENT_MODE")
    stripped_mode = explicit_mode.strip() if explicit_mode is not None else None
    has_deployment_credentials = any(_present(source.get(name)) for name in ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_ANON_KEY", "INTERNAL_API_KEY"))
    if (stripped_mode is None or stripped_mode == "") and has_deployment_credentials:
        raise RuntimeError("DEPLOYMENT_MODE must be explicit when deployment credentials are present; set DEPLOYMENT_MODE=local for local development.")
    raw_mode = stripped_mode.lower() if stripped_mode else "local"
    try:
        mode = DeploymentMode(raw_mode)
    except ValueError as exc:
        if raw_mode in {"paid", "billing", "subscriptions"}:
            raise RuntimeError("Paid deployment mode is unavailable until provider verification and a ledger exist.") from exc
        raise RuntimeError("DEPLOYMENT_MODE must be local, invite_beta, or production.") from exc

    process_jobs_inline = _env_bool(source.get("PROCESS_JOBS_INLINE", "1"))
    if _env_bool(source.get("BILLING_ENABLED", "0")):
        raise RuntimeError("Billing is unavailable until provider verification and a project ledger exist.")
    config = RuntimeConfig(
        mode=mode,
        database_url=_present(source.get("DATABASE_URL")),
        supabase_url=_present(source.get("SUPABASE_URL")),
        supabase_service_role_key=_present(source.get("SUPABASE_SERVICE_ROLE_KEY")),
        supabase_anon_key=_present(source.get("SUPABASE_ANON_KEY")),
        internal_api_key=_present(source.get("INTERNAL_API_KEY")),
        process_jobs_inline=process_jobs_inline,
        storage_bucket=_present(source.get("SUPABASE_STORAGE_BUCKET")) or "handwrite-font-jobs",
        daily_upload_limit=_env_int(source, "DAILY_UPLOAD_LIMIT", 150),
        daily_upload_bytes_limit=_env_int(source, "DAILY_UPLOAD_BYTES_LIMIT", 200 * 1024 * 1024),
        daily_preview_limit=_env_int(source, "DAILY_PREVIEW_LIMIT", 120),
        daily_build_limit=_env_int(source, "DAILY_BUILD_LIMIT", 5),
        active_job_limit=_env_int(source, "ACTIVE_JOB_LIMIT", 2),
    )
    validate_runtime_config(config)
    return config


def validate_runtime_config(config: RuntimeConfig) -> None:
    if not config.auth_required:
        return
    missing = [
        name
        for name, value in (
            ("DATABASE_URL", config.database_url),
            ("SUPABASE_URL", config.supabase_url),
            ("SUPABASE_SERVICE_ROLE_KEY", config.supabase_service_role_key),
            ("SUPABASE_ANON_KEY", config.supabase_anon_key),
            ("INTERNAL_API_KEY", config.internal_api_key),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"{config.mode.value} requires: {', '.join(missing)}")
    if len(config.internal_api_key or "") < 32:
        raise RuntimeError(f"{config.mode.value} requires INTERNAL_API_KEY to be at least 32 characters.")
    if config.process_jobs_inline:
        raise RuntimeError(f"{config.mode.value} requires PROCESS_JOBS_INLINE=0.")


@dataclass(frozen=True)
class AuthContext:
    owner_id: str
    access_token: str | None = None
    email: str | None = None


def authenticate_request(headers: Mapping[str, str], config: RuntimeConfig) -> AuthContext:
    if not config.auth_required:
        return AuthContext(owner_id="local_dev")
    provided_key = headers.get("x-internal-api-key") or headers.get("X-Internal-Api-Key") or ""
    if not hmac.compare_digest(provided_key, config.internal_api_key or ""):
        raise SecurityError(401, "UNAUTHORIZED", "Missing or invalid internal API key.")
    token = _bearer_token(headers.get("authorization") or headers.get("Authorization"))
    if token is None:
        raise SecurityError(401, "UNAUTHORIZED", "Missing bearer access token.")
    return verify_supabase_access_token(token, config)


def verify_supabase_access_token(access_token: str, config: RuntimeConfig) -> AuthContext:
    if not config.supabase_url or not config.supabase_anon_key:
        raise SecurityError(503, "CONFIGURATION_ERROR", "Authentication provider is not configured.")
    data = _fetch_supabase_user(config.supabase_url.rstrip("/"), config.supabase_anon_key, access_token)
    user_id = data.get("id") or data.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise SecurityError(401, "UNAUTHORIZED", "Supabase access token did not identify a user.")
    if config.mode == DeploymentMode.INVITE_BETA:
        app_metadata = data.get("app_metadata")
        if not isinstance(app_metadata, dict) or app_metadata.get("handwrite_beta") is not True:
            raise SecurityError(403, "INVITE_REQUIRED", "This account is not enabled for the invite beta.")
    email_raw = data.get("email")
    return AuthContext(owner_id=user_id, access_token=access_token, email=email_raw if isinstance(email_raw, str) else None)


def _fetch_supabase_user(supabase_url: str, anon_key: str, access_token: str) -> dict[str, object]:
    import requests

    try:
        response = requests.get(
            f"{supabase_url}/auth/v1/user",
            headers={"apikey": anon_key, "authorization": f"Bearer {access_token}"},
            timeout=20,
        )
    except requests.RequestException as exc:
        raise SecurityError(503, "AUTH_PROVIDER_UNAVAILABLE", "Authentication provider is unavailable.") from exc
    if response.status_code >= 500:
        raise SecurityError(503, "AUTH_PROVIDER_UNAVAILABLE", "Authentication provider is unavailable.")
    if response.status_code != 200:
        raise SecurityError(401, "UNAUTHORIZED", "Supabase access token could not be verified.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise SecurityError(503, "AUTH_PROVIDER_UNAVAILABLE", "Authentication provider returned an invalid response.") from exc
    if not isinstance(payload, dict):
        raise SecurityError(503, "AUTH_PROVIDER_UNAVAILABLE", "Authentication provider returned an invalid response.")
    return payload


def _bearer_token(header: str | None) -> str | None:
    if not header:
        return None
    scheme, _, token = header.strip().partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _present(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _env_bool(value: str | None) -> bool:
    return str(value or "").strip().lower() not in {"0", "false", "no", "off"}


def _env_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc
    if value < 0:
        raise RuntimeError(f"{name} must be non-negative.")
    return value

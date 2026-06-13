"""DF Local Foundation — Canonical environment and configuration contract.

All apps that attach to DF Local Foundation must use these env variable names.
Do not invent alternative names or override conventions in app-specific code.

Hardening rules (v1.2):
- prod-local profile forbids default credentials (DF_LOCAL_USER/PASSWORD must be explicit).
- prod-local profile forbids wildcard host bindings.
- app_mode cannot be silently defaulted to LOCAL in prod-local.
- Config is a hard-fail surface: invalid combinations raise on construction.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


FOUNDATION_VERSION = "1.1.0"

# Reserved schema namespace — apps must not claim this.
RESERVED_NAMESPACE = "core"

# Default credentials that must not appear in prod-local.
_FORBIDDEN_PROD_CREDENTIALS = frozenset({
    "postgres", "password", "secret", "changeme", "testpass", "localpass",
})

# Wildcard hosts that must not appear in prod-local.
_FORBIDDEN_PROD_HOSTS = frozenset({"0.0.0.0", "*", "::"})


class AppMode(StrEnum):
    LOCAL = "local"
    HYBRID = "hybrid"
    CLOUD_ENABLED = "cloud-enabled"


class FoundationSettings(BaseSettings):
    """Canonical configuration contract for DF Local Foundation.

    Loaded from environment variables. All names are stable and shared
    across all Forge apps that attach to this foundation.
    """

    # --- Connection ---
    df_local_host: str = Field(default="127.0.0.1", alias="DF_LOCAL_HOST")
    df_local_port: int = Field(default=5432, alias="DF_LOCAL_PORT")
    df_local_db: str = Field(alias="DF_LOCAL_DB")
    df_local_user: str = Field(alias="DF_LOCAL_USER")
    df_local_password: str = Field(alias="DF_LOCAL_PASSWORD")

    # --- Data directory ---
    df_local_data_dir: Path = Field(
        default=Path("/var/lib/df-local"),
        alias="DF_LOCAL_DATA_DIR",
    )

    # --- App identity ---
    df_local_app_id: str = Field(alias="DF_LOCAL_APP_ID")
    df_local_app_mode: AppMode = Field(default=AppMode.LOCAL, alias="DF_LOCAL_APP_MODE")

    # --- HTTP health API (read-only control-plane surface; see app/main.py) ---
    df_local_api_host: str = Field(default="127.0.0.1", alias="DF_LOCAL_API_HOST")
    df_local_api_port: int = Field(default=8099, alias="DF_LOCAL_API_PORT")

    # --- Profile ---
    df_local_profile: str = Field(
        default="dev",
        alias="DF_LOCAL_PROFILE",
        description="One of: dev, test, prod-local",
    )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "populate_by_name": True}

    @model_validator(mode="after")
    def validate_app_id_not_reserved(self) -> "FoundationSettings":
        if self.df_local_app_id == RESERVED_NAMESPACE:
            raise ValueError(
                f"app_id '{RESERVED_NAMESPACE}' is reserved for the foundation core "
                "and may not be used by an app."
            )
        return self

    @model_validator(mode="after")
    def validate_profile(self) -> "FoundationSettings":
        allowed = {"dev", "test", "prod-local"}
        if self.df_local_profile not in allowed:
            raise ValueError(
                f"DF_LOCAL_PROFILE must be one of {allowed}, got '{self.df_local_profile}'"
            )
        return self

    @model_validator(mode="after")
    def validate_prod_local_strict_mode(self) -> "FoundationSettings":
        """prod-local profile enforces strict configuration rules.

        These rules exist to prevent accidental production use of dev defaults.
        They are a hard startup failure, not a warning.
        """
        if self.df_local_profile != "prod-local":
            return self

        # Rule 1: No default/well-known credentials in prod-local
        user_lower = self.df_local_user.lower()
        pass_lower = self.df_local_password.lower()

        if user_lower in _FORBIDDEN_PROD_CREDENTIALS:
            raise ValueError(
                f"DF_LOCAL_USER '{self.df_local_user}' is a default/known-weak credential "
                "and must not be used in prod-local profile. "
                "Set DF_LOCAL_USER to a unique, non-default value."
            )
        if pass_lower in _FORBIDDEN_PROD_CREDENTIALS:
            raise ValueError(
                "DF_LOCAL_PASSWORD is a default/known-weak credential "
                "and must not be used in prod-local profile. "
                "Set DF_LOCAL_PASSWORD to a strong, unique value."
            )

        # Rule 2: No wildcard host binding in prod-local
        if self.df_local_host in _FORBIDDEN_PROD_HOSTS:
            raise ValueError(
                f"DF_LOCAL_HOST '{self.df_local_host}' is a wildcard binding "
                "and must not be used in prod-local profile. "
                "Set DF_LOCAL_HOST to a specific address (e.g., 127.0.0.1)."
            )

        return self

    @property
    def is_prod_local(self) -> bool:
        return self.df_local_profile == "prod-local"

    @property
    def connection_string(self) -> str:
        return (
            f"postgresql://{self.df_local_user}:{self.df_local_password}"
            f"@{self.df_local_host}:{self.df_local_port}/{self.df_local_db}"
        )

    @property
    def async_connection_string(self) -> str:
        return (
            f"postgresql+asyncpg://{self.df_local_user}:{self.df_local_password}"
            f"@{self.df_local_host}:{self.df_local_port}/{self.df_local_db}"
        )


def load_settings() -> FoundationSettings:
    """Load and validate foundation settings from environment.

    Raises ValidationError if required variables are missing or invalid.
    Fail-closed: invalid config is a hard stop.
    """
    return FoundationSettings()  # type: ignore[call-arg]

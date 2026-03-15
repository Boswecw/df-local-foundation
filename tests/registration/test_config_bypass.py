"""Tests: Config bypass prevention.

Acceptance criteria:
- prod-local with default credentials raises on construction
- prod-local with wildcard host raises
- Reserved app_id blocked
- Invalid profile blocked
- Valid prod-local config accepted
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.config.settings import FoundationSettings


def _base_settings(**overrides) -> dict:
    base = {
        "df_local_db": "myapp_prod",
        "df_local_user": "myapp_user",
        "df_local_password": "X9k#mQ2!vZ",
        "df_local_app_id": "authorforge",
        "df_local_profile": "prod-local",
    }
    base.update(overrides)
    return base


class TestProdLocalStrictMode:
    def test_valid_prod_local_config_accepted(self) -> None:
        settings = FoundationSettings(**_base_settings())
        assert settings.is_prod_local is True

    def test_default_user_blocked_in_prod_local(self) -> None:
        with pytest.raises(ValidationError, match="default/known-weak credential"):
            FoundationSettings(**_base_settings(df_local_user="postgres"))

    def test_default_password_blocked_in_prod_local(self) -> None:
        with pytest.raises(ValidationError, match="default/known-weak credential"):
            FoundationSettings(**_base_settings(df_local_password="password"))

    def test_changeme_password_blocked(self) -> None:
        with pytest.raises(ValidationError, match="default/known-weak credential"):
            FoundationSettings(**_base_settings(df_local_password="changeme"))

    def test_testpass_password_blocked(self) -> None:
        with pytest.raises(ValidationError, match="default/known-weak credential"):
            FoundationSettings(**_base_settings(df_local_password="testpass"))

    def test_wildcard_host_blocked_in_prod_local(self) -> None:
        with pytest.raises(ValidationError, match="wildcard binding"):
            FoundationSettings(**_base_settings(df_local_host="0.0.0.0"))

    def test_double_colon_host_blocked(self) -> None:
        with pytest.raises(ValidationError, match="wildcard binding"):
            FoundationSettings(**_base_settings(df_local_host="::"))

    def test_wildcard_star_host_blocked(self) -> None:
        with pytest.raises(ValidationError, match="wildcard binding"):
            FoundationSettings(**_base_settings(df_local_host="*"))

    def test_localhost_ip_allowed_in_prod_local(self) -> None:
        # 127.0.0.1 is the default and is allowed in prod-local
        settings = FoundationSettings(**_base_settings(df_local_host="127.0.0.1"))
        assert settings.df_local_host == "127.0.0.1"


class TestDevModePermissive:
    def test_default_credentials_allowed_in_dev(self) -> None:
        """Dev profile allows default credentials — it is not a prod environment."""
        settings = FoundationSettings(
            df_local_db="devdb",
            df_local_user="postgres",
            df_local_password="password",
            df_local_app_id="authorforge",
            df_local_profile="dev",
        )
        assert settings.df_local_profile == "dev"

    def test_wildcard_host_allowed_in_dev(self) -> None:
        settings = FoundationSettings(
            df_local_db="devdb",
            df_local_user="devuser",
            df_local_password="devpass",
            df_local_app_id="authorforge",
            df_local_host="0.0.0.0",
            df_local_profile="dev",
        )
        assert settings.df_local_host == "0.0.0.0"


class TestReservedNamespace:
    def test_reserved_app_id_blocked(self) -> None:
        with pytest.raises(ValidationError, match="reserved"):
            FoundationSettings(
                df_local_db="testdb",
                df_local_user="testuser",
                df_local_password="testpass",
                df_local_app_id="core",
            )


class TestInvalidProfile:
    def test_unknown_profile_blocked(self) -> None:
        with pytest.raises(ValidationError):
            FoundationSettings(
                df_local_db="testdb",
                df_local_user="testuser",
                df_local_password="testpass",
                df_local_app_id="authorforge",
                df_local_profile="staging",  # Not a valid profile
            )

    def test_empty_profile_blocked(self) -> None:
        with pytest.raises(ValidationError):
            FoundationSettings(
                df_local_db="testdb",
                df_local_user="testuser",
                df_local_password="testpass",
                df_local_app_id="authorforge",
                df_local_profile="",
            )

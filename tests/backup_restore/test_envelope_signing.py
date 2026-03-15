"""Tests: HMAC envelope signing and verification.

Acceptance criteria:
- Signed envelope round-trip verifies
- Tampered envelope blocked
- Unsigned envelope blocked by default
- --allow-unsigned flag accepts unsigned envelopes with warning
- Signing is deterministic (same inputs → same HMAC)
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.backup.signing import (
    EnvelopeVerificationError,
    SigningKeyError,
    load_or_create_signing_key,
    sign_envelope,
    verify_envelope,
    _canonicalize,
)
from core.backup.manager import BackupEnvelope, BackupManager, RestoreBlockedError
from core.config.settings import FoundationSettings


def _make_settings(data_dir: Path | None = None) -> FoundationSettings:
    return FoundationSettings(
        df_local_db="testdb",
        df_local_user="testuser",
        df_local_password="testpass",
        df_local_app_id="authorforge",
        df_local_data_dir=data_dir or Path("/tmp/df-test"),
    )


def _sample_envelope_dict() -> dict:
    return {
        "app_id": "authorforge",
        "foundation_version": "1.1.0",
        "schema_version": "0002",
        "backup_at": "2026-03-15T00:00:00+00:00",
        "format_version": "1",
        "integrity_hash": "sha256:abcdef1234",
        "includes_namespaces": ["core", "authorforge"],
    }


class TestSigningRoundTrip:
    def test_sign_and_verify_succeeds(self) -> None:
        key = b"a" * 32
        envelope = _sample_envelope_dict()
        hmac_value = sign_envelope(envelope, key)
        # Must not raise
        verify_envelope(envelope, hmac_value, key)

    def test_signing_is_deterministic(self) -> None:
        key = b"b" * 32
        envelope = _sample_envelope_dict()
        h1 = sign_envelope(envelope, key)
        h2 = sign_envelope(envelope, key)
        assert h1 == h2

    def test_different_keys_produce_different_hmacs(self) -> None:
        key1 = b"a" * 32
        key2 = b"b" * 32
        envelope = _sample_envelope_dict()
        assert sign_envelope(envelope, key1) != sign_envelope(envelope, key2)

    def test_hmac_format_is_prefixed(self) -> None:
        key = b"c" * 32
        envelope = _sample_envelope_dict()
        hmac_value = sign_envelope(envelope, key)
        assert hmac_value.startswith("hmac-sha256:")
        hex_part = hmac_value[len("hmac-sha256:"):]
        assert len(hex_part) == 64
        assert all(c in "0123456789abcdef" for c in hex_part)


class TestTamperedEnvelopeBlocked:
    def test_tampered_app_id_blocked(self) -> None:
        key = b"d" * 32
        envelope = _sample_envelope_dict()
        hmac_value = sign_envelope(envelope, key)

        tampered = dict(envelope)
        tampered["app_id"] = "maliciousapp"

        with pytest.raises(EnvelopeVerificationError):
            verify_envelope(tampered, hmac_value, key)

    def test_tampered_schema_version_blocked(self) -> None:
        key = b"e" * 32
        envelope = _sample_envelope_dict()
        hmac_value = sign_envelope(envelope, key)

        tampered = dict(envelope)
        tampered["schema_version"] = "9999"

        with pytest.raises(EnvelopeVerificationError):
            verify_envelope(tampered, hmac_value, key)

    def test_tampered_integrity_hash_blocked(self) -> None:
        key = b"f" * 32
        envelope = _sample_envelope_dict()
        hmac_value = sign_envelope(envelope, key)

        tampered = dict(envelope)
        tampered["integrity_hash"] = "sha256:00000000"

        with pytest.raises(EnvelopeVerificationError):
            verify_envelope(tampered, hmac_value, key)

    def test_wrong_key_blocked(self) -> None:
        key1 = b"g" * 32
        key2 = b"h" * 32
        envelope = _sample_envelope_dict()
        hmac_value = sign_envelope(envelope, key1)

        with pytest.raises(EnvelopeVerificationError):
            verify_envelope(envelope, hmac_value, key2)


class TestSigningKeyCanonicalization:
    def test_field_order_does_not_affect_hmac(self) -> None:
        """HMAC must be deterministic regardless of dict key insertion order."""
        key = b"i" * 32
        e1 = _sample_envelope_dict()
        # Reverse the key order
        e2 = dict(reversed(list(e1.items())))
        assert sign_envelope(e1, key) == sign_envelope(e2, key)

    def test_namespace_list_order_normalized(self) -> None:
        """Namespace list order must not affect HMAC."""
        key = b"j" * 32
        e1 = _sample_envelope_dict()
        e2 = dict(e1)
        e2["includes_namespaces"] = ["authorforge", "core"]  # reversed order
        # Both should canonicalize to sorted order → same HMAC
        assert sign_envelope(e1, key) == sign_envelope(e2, key)


class TestSigningKeyManagement:
    def test_key_created_with_correct_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            key = load_or_create_signing_key(data_dir)

            key_path = data_dir / "signing.key"
            assert key_path.exists()
            mode = key_path.stat().st_mode & 0o777
            assert mode == 0o600
            assert len(key) == 32

    def test_key_loaded_consistently(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            key1 = load_or_create_signing_key(data_dir)
            key2 = load_or_create_signing_key(data_dir)
            assert key1 == key2

    def test_key_with_wrong_permissions_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            key_path = data_dir / "signing.key"
            key_path.write_bytes(b"x" * 32)
            key_path.chmod(0o644)  # Too permissive

            with pytest.raises(SigningKeyError, match="unsafe permissions"):
                load_or_create_signing_key(data_dir)

    def test_missing_data_dir_raises(self) -> None:
        with pytest.raises(SigningKeyError, match="does not exist"):
            load_or_create_signing_key(Path("/nonexistent/path/df-local"))


class TestUnsignedEnvelopeRestoreBlocked:
    @pytest.mark.asyncio
    async def test_unsigned_envelope_blocked_by_default(self) -> None:
        pool = AsyncMock()
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = _make_settings(data_dir=Path(tmpdir))
            manager = BackupManager(settings, pool)

            backup_path = Path(tmpdir) / "backup.dump"
            backup_path.write_bytes(b"data")

            # Envelope without hmac
            envelope = BackupEnvelope(
                app_id="authorforge",
                foundation_version="1.1.0",
                schema_version="0002",
                backup_at="2026-03-15T00:00:00+00:00",
                format_version="1",
                integrity_hash=_sha256_str(b"data"),
                includes_namespaces=["core"],
                envelope_hmac=None,
            )
            sidecar = backup_path.with_suffix(".envelope.json")
            sidecar.write_text(json.dumps(envelope.__dict__))

            with pytest.raises(RestoreBlockedError) as exc_info:
                await manager.restore(input_path=backup_path, confirm=True)

            assert exc_info.value.error_class == "integrity_failure"
            assert "unsigned" in exc_info.value.reason.lower()

    @pytest.mark.asyncio
    async def test_unsigned_envelope_accepted_with_allow_unsigned(self) -> None:
        pool = AsyncMock()
        pool.execute = AsyncMock()
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = _make_settings(data_dir=Path(tmpdir))
            manager = BackupManager(settings, pool)

            backup_path = Path(tmpdir) / "backup.dump"
            backup_path.write_bytes(b"data")

            envelope = BackupEnvelope(
                app_id="authorforge",
                foundation_version="1.1.0",
                schema_version="0002",
                backup_at="2026-03-15T00:00:00+00:00",
                format_version="1",
                integrity_hash=_sha256_str(b"data"),
                includes_namespaces=["core"],
                envelope_hmac=None,
            )
            sidecar = backup_path.with_suffix(".envelope.json")
            sidecar.write_text(json.dumps(envelope.__dict__))

            # Should pass validation (pg_restore will fail but we test the validation gate)
            with pytest.raises(RestoreBlockedError) as exc_info:
                await manager.restore(
                    input_path=backup_path,
                    confirm=True,
                    allow_unsigned=True,
                )
            # Fails on pg_restore, not on signing — which means signing gate passed
            assert exc_info.value.error_class == "integrity_failure"
            assert "pg_restore" in exc_info.value.reason

    @pytest.mark.asyncio
    async def test_dry_run_passes_without_applying(self) -> None:
        pool = AsyncMock()
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = _make_settings(data_dir=Path(tmpdir))
            manager = BackupManager(settings, pool)

            backup_path = Path(tmpdir) / "backup.dump"
            backup_path.write_bytes(b"data")

            # Create a properly signed envelope
            signing_key = load_or_create_signing_key(Path(tmpdir))
            envelope_dict = {
                "app_id": "authorforge",
                "foundation_version": "1.1.0",
                "schema_version": "0002",
                "backup_at": "2026-03-15T00:00:00+00:00",
                "format_version": "1",
                "integrity_hash": _sha256_str(b"data"),
                "includes_namespaces": ["core"],
            }
            hmac_val = sign_envelope(envelope_dict, signing_key)
            from core.backup.signing import SIGNED_FIELDS
            envelope = BackupEnvelope(
                **envelope_dict,
                envelope_hmac=hmac_val,
                hmac_covers=sorted(SIGNED_FIELDS),
            )
            sidecar = backup_path.with_suffix(".envelope.json")
            sidecar.write_text(json.dumps(envelope.__dict__))

            # dry_run=True — should complete without error and without calling pg_restore
            await manager.restore(input_path=backup_path, confirm=True, dry_run=True)

            # pg_restore was never called
            # (pool.execute is for DB logging, not pg_restore — we just verify no exception)


def _sha256_str(data: bytes) -> str:
    import hashlib
    return f"sha256:{hashlib.sha256(data).hexdigest()}"

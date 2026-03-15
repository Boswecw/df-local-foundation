"""Red-team tests: Restore abuse fixtures.

These tests use hostile backup fixtures to probe every restore failure mode.
All 12 hostile fixtures from plan v1.2 section 3.2.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from core.backup.manager import BackupEnvelope, BackupManager, RestoreBlockedError
from core.backup.signing import load_or_create_signing_key, sign_envelope, SIGNED_FIELDS
from core.config.settings import FoundationSettings


def _make_settings(app_id: str = "authorforge", data_dir: Path | None = None) -> FoundationSettings:
    return FoundationSettings(
        df_local_db="testdb",
        df_local_user="testuser",
        df_local_password="testpass",
        df_local_app_id=app_id,
        df_local_data_dir=data_dir or Path("/tmp/df-redteam"),
    )


def _sha256(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _write_envelope(sidecar_path: Path, envelope: BackupEnvelope) -> None:
    sidecar_path.write_text(json.dumps(envelope.__dict__))


def _signed_envelope(envelope_dict: dict, key: bytes) -> BackupEnvelope:
    hmac_val = sign_envelope(envelope_dict, key)
    return BackupEnvelope(**envelope_dict, envelope_hmac=hmac_val, hmac_covers=sorted(SIGNED_FIELDS))


class TestRestoreRedTeam:
    @pytest.mark.asyncio
    async def test_hostile_01_wrong_app_id(self) -> None:
        """Fixture: backup from a different app."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pool = AsyncMock()
            settings = _make_settings(app_id="authorforge", data_dir=Path(tmpdir))
            manager = BackupManager(settings, pool)

            backup_path = Path(tmpdir) / "backup.dump"
            payload = b"backup data"
            backup_path.write_bytes(payload)

            key = load_or_create_signing_key(Path(tmpdir))
            ed = {"app_id": "otherapp", "foundation_version": "1.1.0", "schema_version": "0002",
                  "backup_at": "2026-03-15T00:00:00+00:00", "format_version": "1",
                  "integrity_hash": _sha256(payload), "includes_namespaces": ["core"]}
            _write_envelope(backup_path.with_suffix(".envelope.json"), _signed_envelope(ed, key))

            with pytest.raises(RestoreBlockedError) as exc:
                await manager.restore(input_path=backup_path, confirm=True)
            assert exc.value.error_class == "compatibility_failure"

    @pytest.mark.asyncio
    async def test_hostile_02_truncated_payload_hash_mismatch(self) -> None:
        """Fixture: backup file was truncated after signing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pool = AsyncMock()
            settings = _make_settings(data_dir=Path(tmpdir))
            manager = BackupManager(settings, pool)

            backup_path = Path(tmpdir) / "backup.dump"
            original_payload = b"full backup data"
            backup_path.write_bytes(b"truncated")  # Different content

            key = load_or_create_signing_key(Path(tmpdir))
            ed = {"app_id": "authorforge", "foundation_version": "1.1.0", "schema_version": "0002",
                  "backup_at": "2026-03-15T00:00:00+00:00", "format_version": "1",
                  "integrity_hash": _sha256(original_payload),  # Hash of original, not truncated
                  "includes_namespaces": ["core"]}
            _write_envelope(backup_path.with_suffix(".envelope.json"), _signed_envelope(ed, key))

            with pytest.raises(RestoreBlockedError) as exc:
                await manager.restore(input_path=backup_path, confirm=True)
            assert exc.value.error_class == "integrity_failure"

    @pytest.mark.asyncio
    async def test_hostile_03_tampered_envelope_hmac(self) -> None:
        """Fixture: envelope HMAC was modified after signing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pool = AsyncMock()
            settings = _make_settings(data_dir=Path(tmpdir))
            manager = BackupManager(settings, pool)

            payload = b"valid payload"
            backup_path = Path(tmpdir) / "backup.dump"
            backup_path.write_bytes(payload)

            key = load_or_create_signing_key(Path(tmpdir))
            ed = {"app_id": "authorforge", "foundation_version": "1.1.0", "schema_version": "0002",
                  "backup_at": "2026-03-15T00:00:00+00:00", "format_version": "1",
                  "integrity_hash": _sha256(payload), "includes_namespaces": ["core"]}
            envelope = _signed_envelope(ed, key)

            # Tamper the HMAC
            tampered = BackupEnvelope(
                **{k: v for k, v in envelope.__dict__.items() if k not in ("envelope_hmac", "hmac_covers")},
                envelope_hmac="hmac-sha256:" + "0" * 64,  # Wrong HMAC
                hmac_covers=envelope.hmac_covers,
            )
            _write_envelope(backup_path.with_suffix(".envelope.json"), tampered)

            with pytest.raises(RestoreBlockedError) as exc:
                await manager.restore(input_path=backup_path, confirm=True)
            assert exc.value.error_class == "integrity_failure"

    @pytest.mark.asyncio
    async def test_hostile_04_unsigned_envelope_default_blocked(self) -> None:
        """Fixture: unsigned envelope (no envelope_hmac) blocked by default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pool = AsyncMock()
            settings = _make_settings(data_dir=Path(tmpdir))
            manager = BackupManager(settings, pool)

            payload = b"data"
            backup_path = Path(tmpdir) / "backup.dump"
            backup_path.write_bytes(payload)

            unsigned = BackupEnvelope(
                app_id="authorforge", foundation_version="1.1.0", schema_version="0002",
                backup_at="2026-03-15T00:00:00+00:00", format_version="1",
                integrity_hash=_sha256(payload), includes_namespaces=["core"],
                envelope_hmac=None,
            )
            _write_envelope(backup_path.with_suffix(".envelope.json"), unsigned)

            with pytest.raises(RestoreBlockedError) as exc:
                await manager.restore(input_path=backup_path, confirm=True)
            assert exc.value.error_class == "integrity_failure"
            assert "unsigned" in exc.value.reason.lower()

    @pytest.mark.asyncio
    async def test_hostile_05_unsupported_format_version(self) -> None:
        """Fixture: format_version = '99' is not supported."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pool = AsyncMock()
            settings = _make_settings(data_dir=Path(tmpdir))
            manager = BackupManager(settings, pool)

            payload = b"data"
            backup_path = Path(tmpdir) / "backup.dump"
            backup_path.write_bytes(payload)

            key = load_or_create_signing_key(Path(tmpdir))
            ed = {"app_id": "authorforge", "foundation_version": "1.1.0", "schema_version": "0002",
                  "backup_at": "2026-03-15T00:00:00+00:00", "format_version": "99",
                  "integrity_hash": _sha256(payload), "includes_namespaces": ["core"]}
            _write_envelope(backup_path.with_suffix(".envelope.json"), _signed_envelope(ed, key))

            with pytest.raises(RestoreBlockedError) as exc:
                await manager.restore(input_path=backup_path, confirm=True)
            assert exc.value.error_class == "compatibility_failure"

    @pytest.mark.asyncio
    async def test_hostile_06_missing_envelope_sidecar(self) -> None:
        """Fixture: backup file exists but envelope sidecar is missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pool = AsyncMock()
            settings = _make_settings(data_dir=Path(tmpdir))
            manager = BackupManager(settings, pool)

            backup_path = Path(tmpdir) / "backup.dump"
            backup_path.write_bytes(b"data")
            # No sidecar written

            with pytest.raises(RestoreBlockedError) as exc:
                await manager.restore(input_path=backup_path, confirm=True)
            assert exc.value.error_class == "integrity_failure"

    @pytest.mark.asyncio
    async def test_hostile_07_malformed_envelope_json(self) -> None:
        """Fixture: envelope sidecar contains invalid JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pool = AsyncMock()
            settings = _make_settings(data_dir=Path(tmpdir))
            manager = BackupManager(settings, pool)

            backup_path = Path(tmpdir) / "backup.dump"
            backup_path.write_bytes(b"data")
            backup_path.with_suffix(".envelope.json").write_text("{broken json")

            with pytest.raises(RestoreBlockedError) as exc:
                await manager.restore(input_path=backup_path, confirm=True)
            assert exc.value.error_class == "integrity_failure"

    @pytest.mark.asyncio
    async def test_hostile_08_missing_confirm_flag(self) -> None:
        """Fixture: restore called without confirm=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pool = AsyncMock()
            settings = _make_settings(data_dir=Path(tmpdir))
            manager = BackupManager(settings, pool)

            with pytest.raises(RestoreBlockedError) as exc:
                await manager.restore(input_path=Path(tmpdir) / "backup.dump", confirm=False)
            assert exc.value.error_class == "restore_blocked"

    @pytest.mark.asyncio
    async def test_hostile_09_missing_backup_file(self) -> None:
        """Fixture: envelope exists but backup file is missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pool = AsyncMock()
            settings = _make_settings(data_dir=Path(tmpdir))
            manager = BackupManager(settings, pool)

            backup_path = Path(tmpdir) / "nonexistent.dump"

            key = load_or_create_signing_key(Path(tmpdir))
            ed = {"app_id": "authorforge", "foundation_version": "1.1.0", "schema_version": "0002",
                  "backup_at": "2026-03-15T00:00:00+00:00", "format_version": "1",
                  "integrity_hash": "sha256:placeholder", "includes_namespaces": ["core"]}
            _write_envelope(backup_path.with_suffix(".envelope.json"), _signed_envelope(ed, key))

            with pytest.raises(RestoreBlockedError) as exc:
                await manager.restore(input_path=backup_path, confirm=True)
            assert exc.value.error_class == "integrity_failure"

    @pytest.mark.asyncio
    async def test_hostile_10_reserved_app_id_in_envelope(self) -> None:
        """Fixture: envelope claims app_id='core' (reserved namespace)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pool = AsyncMock()
            # Settings app_id is authorforge — envelope claims core
            settings = _make_settings(app_id="authorforge", data_dir=Path(tmpdir))
            manager = BackupManager(settings, pool)

            payload = b"data"
            backup_path = Path(tmpdir) / "backup.dump"
            backup_path.write_bytes(payload)

            key = load_or_create_signing_key(Path(tmpdir))
            ed = {"app_id": "core", "foundation_version": "1.1.0", "schema_version": "0002",
                  "backup_at": "2026-03-15T00:00:00+00:00", "format_version": "1",
                  "integrity_hash": _sha256(payload), "includes_namespaces": ["core"]}
            _write_envelope(backup_path.with_suffix(".envelope.json"), _signed_envelope(ed, key))

            with pytest.raises(RestoreBlockedError) as exc:
                await manager.restore(input_path=backup_path, confirm=True)
            # app_id mismatch: settings has "authorforge", envelope has "core"
            assert exc.value.error_class == "compatibility_failure"

    @pytest.mark.asyncio
    async def test_hostile_11_allow_unsigned_flag_permits_and_logs(self) -> None:
        """Fixture: allow_unsigned=True permits unsigned envelope (with warning)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pool = AsyncMock()
            settings = _make_settings(data_dir=Path(tmpdir))
            manager = BackupManager(settings, pool)

            payload = b"data"
            backup_path = Path(tmpdir) / "backup.dump"
            backup_path.write_bytes(payload)

            unsigned = BackupEnvelope(
                app_id="authorforge", foundation_version="1.1.0", schema_version="0002",
                backup_at="2026-03-15T00:00:00+00:00", format_version="1",
                integrity_hash=_sha256(payload), includes_namespaces=["core"],
                envelope_hmac=None,
            )
            _write_envelope(backup_path.with_suffix(".envelope.json"), unsigned)

            # Should fail on pg_restore, not on the signing gate
            with pytest.raises(RestoreBlockedError) as exc:
                await manager.restore(input_path=backup_path, confirm=True, allow_unsigned=True)
            # pg_restore failure (not a signing failure) — signing gate passed
            assert exc.value.error_class == "integrity_failure"
            assert "pg_restore" in exc.value.reason

    @pytest.mark.asyncio
    async def test_hostile_12_dry_run_passes_without_applying(self) -> None:
        """Fixture: dry_run=True validates without applying — should pass if valid."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pool = AsyncMock()
            settings = _make_settings(data_dir=Path(tmpdir))
            manager = BackupManager(settings, pool)

            payload = b"valid data"
            backup_path = Path(tmpdir) / "backup.dump"
            backup_path.write_bytes(payload)

            key = load_or_create_signing_key(Path(tmpdir))
            ed = {"app_id": "authorforge", "foundation_version": "1.1.0", "schema_version": "0002",
                  "backup_at": "2026-03-15T00:00:00+00:00", "format_version": "1",
                  "integrity_hash": _sha256(payload), "includes_namespaces": ["core"]}
            _write_envelope(backup_path.with_suffix(".envelope.json"), _signed_envelope(ed, key))

            # dry_run: all checks pass, no pg_restore called, no exception raised
            await manager.restore(input_path=backup_path, confirm=True, dry_run=True)

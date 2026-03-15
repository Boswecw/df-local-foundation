"""Tests: Backup/restore validation gates.

Acceptance criteria:
- Restore blocked on integrity/compatibility mismatch
- Operator can prove what a backup/export belongs to
- Invalid restore payloads block cleanly
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.backup.manager import (
    BackupEnvelope,
    BackupManager,
    RestoreBlockedError,
    _compute_hash,
)
from core.config.settings import AppMode, FoundationSettings


def _make_settings(app_id: str = "authorforge") -> FoundationSettings:
    return FoundationSettings(
        df_local_db="testdb",
        df_local_user="testuser",
        df_local_password="testpass",
        df_local_app_id=app_id,
    )


def _make_envelope(app_id: str = "authorforge", integrity_hash: str = "") -> BackupEnvelope:
    return BackupEnvelope(
        app_id=app_id,
        foundation_version="1.1.0",
        schema_version="0002",
        backup_at="2026-03-15T00:00:00+00:00",
        format_version="1",
        integrity_hash=integrity_hash,
        includes_namespaces=["core"],
    )


class TestRestoreRequiresConfirm:
    @pytest.mark.asyncio
    async def test_restore_blocked_without_confirm(self) -> None:
        pool = AsyncMock()
        settings = _make_settings()
        manager = BackupManager(settings, pool)

        with tempfile.NamedTemporaryFile(suffix=".backup") as f:
            backup_path = Path(f.name)

        with pytest.raises(RestoreBlockedError) as exc_info:
            await manager.restore(input_path=backup_path, confirm=False)

        assert exc_info.value.error_class == "restore_blocked"


class TestRestoreEnvelopeValidation:
    @pytest.mark.asyncio
    async def test_missing_envelope_blocks_restore(self) -> None:
        pool = AsyncMock()
        settings = _make_settings()
        manager = BackupManager(settings, pool)

        with tempfile.NamedTemporaryFile(suffix=".backup", delete=False) as f:
            backup_path = Path(f.name)
            f.write(b"fake backup data")

        # No sidecar envelope file
        with pytest.raises(RestoreBlockedError) as exc_info:
            await manager.restore(input_path=backup_path, confirm=True)

        assert exc_info.value.error_class == "integrity_failure"

    @pytest.mark.asyncio
    async def test_malformed_envelope_blocks_restore(self) -> None:
        pool = AsyncMock()
        settings = _make_settings()
        manager = BackupManager(settings, pool)

        with tempfile.TemporaryDirectory() as tmpdir:
            backup_path = Path(tmpdir) / "backup.dump"
            backup_path.write_bytes(b"fake backup data")

            sidecar_path = backup_path.with_suffix(".envelope.json")
            sidecar_path.write_text("{ broken json }")

            with pytest.raises(RestoreBlockedError) as exc_info:
                await manager.restore(input_path=backup_path, confirm=True)

            assert exc_info.value.error_class == "integrity_failure"

    @pytest.mark.asyncio
    async def test_wrong_app_id_blocks_restore(self) -> None:
        pool = AsyncMock()
        settings = _make_settings(app_id="authorforge")
        manager = BackupManager(settings, pool)

        with tempfile.TemporaryDirectory() as tmpdir:
            backup_path = Path(tmpdir) / "backup.dump"
            backup_path.write_bytes(b"backup data from different app")

            envelope = _make_envelope(app_id="otherapp", integrity_hash="sha256:placeholder")
            sidecar_path = backup_path.with_suffix(".envelope.json")
            sidecar_path.write_text(json.dumps(envelope.__dict__))

            with pytest.raises(RestoreBlockedError) as exc_info:
                await manager.restore(input_path=backup_path, confirm=True)

            assert exc_info.value.error_class == "compatibility_failure"

    @pytest.mark.asyncio
    async def test_integrity_hash_mismatch_blocks_restore(self) -> None:
        pool = AsyncMock()
        settings = _make_settings()
        manager = BackupManager(settings, pool)

        with tempfile.TemporaryDirectory() as tmpdir:
            backup_path = Path(tmpdir) / "backup.dump"
            backup_path.write_bytes(b"legitimate backup data")

            # Envelope with wrong hash
            envelope = _make_envelope(
                app_id="authorforge",
                integrity_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
            )
            sidecar_path = backup_path.with_suffix(".envelope.json")
            sidecar_path.write_text(json.dumps(envelope.__dict__))

            with pytest.raises(RestoreBlockedError) as exc_info:
                await manager.restore(input_path=backup_path, confirm=True)

            assert exc_info.value.error_class == "integrity_failure"

    @pytest.mark.asyncio
    async def test_unsupported_format_version_blocks_restore(self) -> None:
        pool = AsyncMock()
        settings = _make_settings()
        manager = BackupManager(settings, pool)

        with tempfile.TemporaryDirectory() as tmpdir:
            backup_path = Path(tmpdir) / "backup.dump"
            backup_path.write_bytes(b"backup data")

            envelope = BackupEnvelope(
                app_id="authorforge",
                foundation_version="1.1.0",
                schema_version="0002",
                backup_at="2026-03-15T00:00:00+00:00",
                format_version="99",   # Unsupported
                integrity_hash="sha256:placeholder",
                includes_namespaces=["core"],
            )
            sidecar_path = backup_path.with_suffix(".envelope.json")
            sidecar_path.write_text(json.dumps(envelope.__dict__))

            with pytest.raises(RestoreBlockedError) as exc_info:
                await manager.restore(input_path=backup_path, confirm=True)

            assert exc_info.value.error_class == "compatibility_failure"


class TestIntegrityHashing:
    def test_hash_is_stable_for_same_content(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = Path(f.name)
            f.write(b"stable content")

        h1 = _compute_hash(path)
        h2 = _compute_hash(path)
        assert h1 == h2

    def test_hash_changes_on_content_change(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = Path(f.name)
            f.write(b"original content")

        h1 = _compute_hash(path)
        path.write_bytes(b"modified content")
        h2 = _compute_hash(path)
        assert h1 != h2

    def test_hash_format_is_sha256_prefixed(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = Path(f.name)
            f.write(b"test data")

        h = _compute_hash(path)
        assert h.startswith("sha256:")
        hex_part = h[len("sha256:"):]
        assert len(hex_part) == 64
        assert all(c in "0123456789abcdef" for c in hex_part)

"""DF Local Foundation — Backup and restore manager.

Implements the backup/export/restore doctrine from
docs/backup-export-restore.md.

Rules:
- Backups are explicit, versioned, integrity-checked, and HMAC-signed.
- Restore validates all checks (including HMAC) before applying anything.
- Restore is blocked on any mismatch — fail closed.
- Unsigned envelopes are blocked by default; allow_unsigned=True is explicit opt-in.
- No silent fallbacks.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import asyncpg

from ..config.settings import FOUNDATION_VERSION, FoundationSettings
from .signing import (
    EnvelopeVerificationError,
    SigningKeyError,
    load_or_create_signing_key,
    sign_envelope,
    verify_envelope,
)

logger = logging.getLogger(__name__)

# Supported export format version
CURRENT_FORMAT_VERSION = "1"
SUPPORTED_FORMAT_VERSIONS = {"1"}


@dataclass(frozen=True)
class BackupEnvelope:
    """Metadata envelope attached to every backup/export file.

    Conforms to the envelope spec in docs/backup-export-restore.md.
    Never contains customer data or domain content.

    Fields:
        integrity_hash: SHA-256 of the backup payload file.
        envelope_hmac:  HMAC-SHA256 over the signed metadata fields.
                        "hmac-sha256:<hex>" or None for unsigned envelopes.
        hmac_covers:    List of field names included in the HMAC computation.
    """
    app_id: str
    foundation_version: str
    schema_version: str
    backup_at: str                          # ISO8601
    format_version: str
    integrity_hash: str                     # sha256:...
    includes_namespaces: list[str]
    envelope_hmac: str | None = None        # hmac-sha256:<hex> or None if unsigned
    hmac_covers: list[str] | None = None    # fields included in HMAC


@dataclass
class BackupResult:
    """Result of a completed backup operation."""
    success: bool
    output_path: Path | None
    envelope: BackupEnvelope | None
    error_class: str | None = None
    error_detail: str | None = None         # Internal only — not exposed to health surface


class RestoreBlockedError(Exception):
    """Raised when restore validation fails.

    This is fail-closed behavior. Restore is not applied.
    """
    def __init__(self, reason: str, error_class: str) -> None:
        self.reason = reason
        self.error_class = error_class
        super().__init__(f"Restore blocked [{error_class}]: {reason}")


class BackupManager:
    """Manages backup, export, and restore operations.

    All operations are logged to core_backup_log / core_export_log.
    Restore validates all envelope checks before applying anything.
    Fail-closed on any mismatch or integrity failure.
    """

    def __init__(self, settings: FoundationSettings, pool: asyncpg.Pool) -> None:
        self._settings = settings
        self._pool = pool
        self._signing_key: bytes | None = None

    def _get_signing_key(self) -> bytes:
        """Load or create the signing key (cached per instance)."""
        if self._signing_key is None:
            self._signing_key = load_or_create_signing_key(
                self._settings.df_local_data_dir
            )
        return self._signing_key

    async def backup(
        self,
        output_path: Path,
        namespaces: list[str] | None = None,
    ) -> BackupResult:
        """Create a versioned local backup.

        Args:
            output_path: Where to write the backup file.
            namespaces: Which schema namespaces to include. Defaults to ['core'].

        Returns:
            BackupResult with envelope and path on success.
        """
        if namespaces is None:
            namespaces = ["core"]

        schema_version = await self._get_core_schema_version()
        backup_at = datetime.now(UTC).isoformat()

        # Use pg_dump to produce the backup
        try:
            await self._pg_dump(output_path, namespaces)
        except Exception as exc:
            logger.error("df_local.backup_failed", error=str(type(exc).__name__))
            await self._log_backup(
                output_path=str(output_path),
                schema_version=schema_version,
                namespaces=namespaces,
                integrity_hash="",
                status="failed",
                error_class="startup_failure",
            )
            return BackupResult(
                success=False,
                output_path=None,
                envelope=None,
                error_class="startup_failure",
                error_detail=str(exc),
            )

        integrity_hash = _compute_hash(output_path)

        # Build the unsigned envelope first so we can sign its fields
        unsigned_envelope_dict = {
            "app_id": self._settings.df_local_app_id,
            "foundation_version": FOUNDATION_VERSION,
            "schema_version": schema_version,
            "backup_at": backup_at,
            "format_version": CURRENT_FORMAT_VERSION,
            "integrity_hash": integrity_hash,
            "includes_namespaces": namespaces,
        }

        try:
            signing_key = self._get_signing_key()
            envelope_hmac = sign_envelope(unsigned_envelope_dict, signing_key)
            from .signing import SIGNED_FIELDS
            hmac_covers = sorted(SIGNED_FIELDS)
        except SigningKeyError as exc:
            logger.error("df_local.signing_key_error", error=str(exc))
            # Signing failure is a hard stop — do not produce unsigned backups silently
            await self._log_backup(
                output_path=str(output_path),
                schema_version=schema_version,
                namespaces=namespaces,
                integrity_hash=integrity_hash,
                status="failed",
                error_class="integrity_failure",
            )
            return BackupResult(
                success=False,
                output_path=None,
                envelope=None,
                error_class="integrity_failure",
                error_detail=str(exc),
            )

        envelope = BackupEnvelope(
            **unsigned_envelope_dict,
            envelope_hmac=envelope_hmac,
            hmac_covers=hmac_covers,
        )

        # Write the envelope sidecar
        sidecar_path = output_path.with_suffix(".envelope.json")
        sidecar_path.write_text(json.dumps(envelope.__dict__, indent=2))

        await self._log_backup(
            output_path=str(output_path),
            schema_version=schema_version,
            namespaces=namespaces,
            integrity_hash=integrity_hash,
            status="completed",
            error_class=None,
        )

        logger.info(
            "df_local.backup_completed",
            output_path=str(output_path),
            integrity_hash=integrity_hash,
        )

        return BackupResult(success=True, output_path=output_path, envelope=envelope)

    async def restore(
        self,
        input_path: Path,
        confirm: bool = False,
        allow_unsigned: bool = False,
        dry_run: bool = False,
    ) -> None:
        """Restore from a backup.

        All validation checks must pass before any changes are applied.
        Fail-closed: any check failure raises RestoreBlockedError.

        Args:
            input_path: Path to the backup file.
            confirm: Must be True. Explicit operator intent required.
            allow_unsigned: If True, unsigned envelopes (no envelope_hmac) are accepted.
                            Default is False — unsigned envelopes are blocked.
            dry_run: If True, run all validation without applying the restore.
                     Exits cleanly if validation passes. No DB changes made.

        Raises:
            RestoreBlockedError: If any validation check fails.
        """
        if not confirm:
            raise RestoreBlockedError(
                reason="Restore requires explicit operator confirmation (confirm=True).",
                error_class="restore_blocked",
            )

        # Load and validate the envelope
        sidecar_path = input_path.with_suffix(".envelope.json")
        if not sidecar_path.exists():
            raise RestoreBlockedError(
                reason="Backup envelope sidecar not found. Cannot validate restore.",
                error_class="integrity_failure",
            )

        try:
            envelope_data = json.loads(sidecar_path.read_text())
            envelope = BackupEnvelope(**envelope_data)
        except Exception as exc:
            raise RestoreBlockedError(
                reason=f"Backup envelope is malformed: {type(exc).__name__}",
                error_class="integrity_failure",
            ) from exc

        # Check: format version
        if envelope.format_version not in SUPPORTED_FORMAT_VERSIONS:
            raise RestoreBlockedError(
                reason=f"Unsupported format version: {envelope.format_version}",
                error_class="compatibility_failure",
            )

        # Check: app identity
        if envelope.app_id != self._settings.df_local_app_id:
            raise RestoreBlockedError(
                reason=(
                    f"Backup app_id '{envelope.app_id}' does not match "
                    f"current app_id '{self._settings.df_local_app_id}'."
                ),
                error_class="compatibility_failure",
            )

        # Check: backup file exists
        if not input_path.exists():
            raise RestoreBlockedError(
                reason=f"Backup file not found: {input_path}",
                error_class="integrity_failure",
            )

        # Check: integrity hash
        computed_hash = _compute_hash(input_path)
        if computed_hash != envelope.integrity_hash:
            raise RestoreBlockedError(
                reason=f"Integrity hash mismatch. Expected {envelope.integrity_hash}, got {computed_hash}.",
                error_class="integrity_failure",
            )

        # Check: HMAC signature
        if envelope.envelope_hmac is None:
            if not allow_unsigned:
                raise RestoreBlockedError(
                    reason=(
                        "Envelope has no HMAC signature. Unsigned backups are blocked by default. "
                        "Pass --allow-unsigned to accept unsigned envelopes."
                    ),
                    error_class="integrity_failure",
                )
            logger.warning(
                "df_local.restore_unsigned_envelope_accepted",
                extra={"app_id": envelope.app_id},
            )
        else:
            try:
                signing_key = self._get_signing_key()
                # Verify against the metadata fields (excluding hmac fields themselves)
                fields_for_verify = {
                    k: v for k, v in envelope.__dict__.items()
                    if k not in ("envelope_hmac", "hmac_covers")
                }
                verify_envelope(fields_for_verify, envelope.envelope_hmac, signing_key)
            except (EnvelopeVerificationError, SigningKeyError) as exc:
                raise RestoreBlockedError(
                    reason=f"Envelope HMAC verification failed: {type(exc).__name__}",
                    error_class="integrity_failure",
                ) from exc

        # dry_run: validation passed, do not apply
        if dry_run:
            logger.info(
                "df_local.restore_dry_run_passed",
                app_id=envelope.app_id,
                schema_version=envelope.schema_version,
            )
            return

        # All checks passed — proceed with restore
        logger.info(
            "df_local.restore_starting",
            app_id=envelope.app_id,
            schema_version=envelope.schema_version,
        )

        try:
            await self._pg_restore(input_path)
        except Exception as exc:
            raise RestoreBlockedError(
                reason=f"pg_restore execution failed: {type(exc).__name__}",
                error_class="integrity_failure",
            ) from exc

        logger.info("df_local.restore_completed", app_id=envelope.app_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_core_schema_version(self) -> str:
        row = await self._pool.fetchrow(
            "SELECT current_version FROM core_schema_versions WHERE target = 'core'"
        )
        return row["current_version"] if row else "unknown"

    async def _pg_dump(self, output_path: Path, namespaces: list[str]) -> None:
        schema_args = []
        for ns in namespaces:
            schema_args.extend(["--schema", ns])

        cmd = [
            "pg_dump",
            "--format=custom",
            *schema_args,
            f"--file={output_path}",
            self._settings.connection_string,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"pg_dump failed (rc={proc.returncode}): {stderr.decode()[:256]}")

    async def _pg_restore(self, input_path: Path) -> None:
        cmd = [
            "pg_restore",
            "--clean",
            "--if-exists",
            f"--dbname={self._settings.connection_string}",
            str(input_path),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"pg_restore failed (rc={proc.returncode}): {stderr.decode()[:256]}")

    async def _log_backup(
        self,
        output_path: str,
        schema_version: str,
        namespaces: list[str],
        integrity_hash: str,
        status: str,
        error_class: str | None,
    ) -> None:
        try:
            await self._pool.execute(
                """
                INSERT INTO core_backup_log
                    (app_id, foundation_version, schema_version, output_path,
                     integrity_hash, includes_namespaces, status, error_class)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                self._settings.df_local_app_id,
                FOUNDATION_VERSION,
                schema_version,
                output_path,
                integrity_hash,
                namespaces,
                status,
                error_class,
            )
        except Exception as exc:
            logger.warning("df_local.backup_log_write_failed", error=str(type(exc).__name__))


def _compute_hash(path: Path) -> str:
    """Compute SHA-256 hash of a file. Returns 'sha256:<hex>'."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"

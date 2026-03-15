"""DF Local Foundation — Export manager.

Namespace-scoped exports with metadata envelope and integrity hash.
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

logger = logging.getLogger(__name__)

CURRENT_FORMAT_VERSION = "1"


@dataclass(frozen=True)
class ExportEnvelope:
    app_id: str
    foundation_version: str
    schema_version: str
    export_at: str          # ISO8601
    format_version: str
    integrity_hash: str     # sha256:...
    namespace: str


@dataclass
class ExportResult:
    success: bool
    output_path: Path | None
    envelope: ExportEnvelope | None
    error_class: str | None = None


class ExportManager:
    """Produces namespace-scoped exports with metadata envelopes.

    The export file contains only the declared namespace.
    The envelope carries metadata for restore validation.
    No customer data is exposed via the export metadata surface.
    """

    def __init__(self, settings: FoundationSettings, pool: asyncpg.Pool) -> None:
        self._settings = settings
        self._pool = pool

    async def export(self, namespace: str, output_path: Path) -> ExportResult:
        """Export a single schema namespace.

        Args:
            namespace: The PostgreSQL schema to export (e.g., 'authorforge').
            output_path: Where to write the export file.

        Returns:
            ExportResult with envelope and path on success.
        """
        if namespace == "core":
            # Core exports go through backup, not export
            return ExportResult(
                success=False,
                output_path=None,
                envelope=None,
                error_class="compatibility_failure",
            )

        schema_version = await self._get_app_schema_version(namespace)
        export_at = datetime.now(UTC).isoformat()

        try:
            await self._pg_dump_namespace(output_path, namespace)
        except Exception as exc:
            logger.error("df_local.export_failed", namespace=namespace, error=str(type(exc).__name__))
            await self._log_export(
                namespace=namespace,
                output_path=str(output_path),
                schema_version=schema_version,
                integrity_hash="",
                status="failed",
                error_class="startup_failure",
            )
            return ExportResult(
                success=False,
                output_path=None,
                envelope=None,
                error_class="startup_failure",
            )

        integrity_hash = _compute_hash(output_path)
        envelope = ExportEnvelope(
            app_id=self._settings.df_local_app_id,
            foundation_version=FOUNDATION_VERSION,
            schema_version=schema_version,
            export_at=export_at,
            format_version=CURRENT_FORMAT_VERSION,
            integrity_hash=integrity_hash,
            namespace=namespace,
        )

        sidecar_path = output_path.with_suffix(".envelope.json")
        sidecar_path.write_text(json.dumps(envelope.__dict__, indent=2))

        await self._log_export(
            namespace=namespace,
            output_path=str(output_path),
            schema_version=schema_version,
            integrity_hash=integrity_hash,
            status="completed",
            error_class=None,
        )

        logger.info(
            "df_local.export_completed",
            namespace=namespace,
            output_path=str(output_path),
        )
        return ExportResult(success=True, output_path=output_path, envelope=envelope)

    async def _get_app_schema_version(self, namespace: str) -> str:
        row = await self._pool.fetchrow(
            "SELECT current_version FROM core_schema_versions WHERE schema_namespace = $1",
            namespace,
        )
        return row["current_version"] if row else "unknown"

    async def _pg_dump_namespace(self, output_path: Path, namespace: str) -> None:
        cmd = [
            "pg_dump",
            "--format=custom",
            "--schema", namespace,
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

    async def _log_export(
        self,
        namespace: str,
        output_path: str,
        schema_version: str,
        integrity_hash: str,
        status: str,
        error_class: str | None,
    ) -> None:
        try:
            await self._pool.execute(
                """
                INSERT INTO core_export_log
                    (app_id, foundation_version, schema_version, output_path,
                     namespace, integrity_hash, status, error_class)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                self._settings.df_local_app_id,
                FOUNDATION_VERSION,
                schema_version,
                output_path,
                namespace,
                integrity_hash,
                status,
                error_class,
            )
        except Exception as exc:
            logger.warning("df_local.export_log_write_failed", error=str(type(exc).__name__))


def _compute_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"

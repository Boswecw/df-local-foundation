"""Read-only public-application services for DF Local Foundation."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Protocol

logger = logging.getLogger(__name__)

_PUBLIC_APPLICATIONS_SQL = """
    SELECT application_name, display_name, owns_service_name, ownership_class,
           visibility_class, forgecustomer_product_ref, is_public, is_enabled,
           created_at, updated_at
    FROM service_registry.public_applications
    WHERE is_enabled = true AND is_public = true
    ORDER BY application_name
"""


class PublicApplicationsReadError(RuntimeError):
    """Raised when the support foundation cannot read public-application rows."""


class PublicApplicationsReader(Protocol):
    async def fetch_public_application_rows(self) -> list[dict[str, Any]]:
        """Fetch public application ownership rows."""


class AsyncpgPublicApplicationsReader:
    """Asyncpg-backed public-applications reader for the support foundation."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def fetch_public_application_rows(self) -> list[dict[str, Any]]:
        import asyncpg

        try:
            conn = await asyncpg.connect(self._dsn)
            try:
                return [dict(row) for row in await conn.fetch(_PUBLIC_APPLICATIONS_SQL)]
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning("df_local.public_applications_read_failed error=%s", type(exc).__name__)
            raise PublicApplicationsReadError("public_applications_read_failed") from exc


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def compute_public_applications_response(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return enabled public applications in consumer-safe order."""
    public_rows = [
        row
        for row in rows
        if row.get("is_enabled") is True and row.get("is_public") is True
    ]
    return [
        {
            "application_name": row["application_name"],
            "display_name": row["display_name"],
            "owns_service_name": row["owns_service_name"],
            "ownership_class": row["ownership_class"],
            "visibility_class": row["visibility_class"],
            "forgecustomer_product_ref": row["forgecustomer_product_ref"],
            "is_public": row["is_public"],
            "is_enabled": row["is_enabled"],
            "created_at": _iso(row["created_at"]),
            "updated_at": _iso(row["updated_at"]),
        }
        for row in sorted(public_rows, key=lambda item: item["application_name"])
    ]


async def build_public_applications_response(
    reader: PublicApplicationsReader,
) -> list[dict[str, Any]]:
    return compute_public_applications_response(await reader.fetch_public_application_rows())

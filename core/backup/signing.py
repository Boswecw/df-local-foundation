"""DF Local Foundation — Envelope signing with HMAC-SHA256.

Signs backup and export envelopes with a locally-held secret key.
Verifies envelope authenticity on restore.

Design decisions:
- HMAC-SHA256 with a per-install key stored in {data_dir}/signing.key (mode 0600).
- Key is generated on first foundation init and never leaves the data directory.
- HMAC covers the envelope metadata fields (not backup content itself —
  the SHA-256 integrity_hash covers that).
- Canonicalization: fields sorted alphabetically, JSON-serialized (compact, no trailing whitespace).
  This makes HMAC deterministic regardless of dict insertion order.
- Unsigned envelopes are blocked on restore by default.
  Operator must pass allow_unsigned=True to accept unsigned envelopes.

Threat model note:
  If an attacker has filesystem access to {data_dir}, they already own the machine.
  HMAC signing protects against offline tampering of backup files transported elsewhere,
  not against local privileged attackers.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import stat
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Fields included in the HMAC computation.
# Order here does not matter — they are sorted before signing.
SIGNED_FIELDS = frozenset({
    "app_id",
    "foundation_version",
    "schema_version",
    "backup_at",
    "format_version",
    "integrity_hash",
    "includes_namespaces",
})

# For export envelopes the 'includes_namespaces' field is absent; 'namespace' is used instead.
SIGNED_FIELDS_EXPORT = frozenset({
    "app_id",
    "foundation_version",
    "schema_version",
    "export_at",
    "format_version",
    "integrity_hash",
    "namespace",
})

KEY_FILENAME = "signing.key"
KEY_LENGTH_BYTES = 32  # 256-bit key


class SigningKeyError(Exception):
    """Raised when the signing key cannot be loaded or created."""
    pass


class EnvelopeVerificationError(Exception):
    """Raised when HMAC verification fails.

    Callers should treat this as integrity_failure and block the restore.
    """
    pass


def load_or_create_signing_key(data_dir: Path) -> bytes:
    """Load the signing key from disk, creating it if it does not exist.

    The key file is stored at {data_dir}/signing.key with mode 0600.
    If the file exists with wrong permissions, it is rejected (SigningKeyError).

    Args:
        data_dir: The foundation data directory (from settings.df_local_data_dir).

    Returns:
        Raw key bytes (32 bytes).

    Raises:
        SigningKeyError: If the key cannot be read or created safely.
    """
    key_path = data_dir / KEY_FILENAME

    if key_path.exists():
        # Verify permissions — reject loose permissions
        mode = key_path.stat().st_mode & 0o777
        if mode != 0o600:
            raise SigningKeyError(
                f"Signing key at {key_path} has unsafe permissions (mode={oct(mode)}). "
                "Expected 0600. Refusing to load."
            )
        raw = key_path.read_bytes()
        if len(raw) != KEY_LENGTH_BYTES:
            raise SigningKeyError(
                f"Signing key at {key_path} has unexpected length ({len(raw)} bytes). "
                f"Expected {KEY_LENGTH_BYTES} bytes."
            )
        return raw

    # Key does not exist — generate a new one
    if not data_dir.exists():
        raise SigningKeyError(
            f"Data directory {data_dir} does not exist. "
            "Foundation must be initialized before signing key can be created."
        )

    raw = secrets.token_bytes(KEY_LENGTH_BYTES)
    key_path.write_bytes(raw)
    key_path.chmod(0o600)

    logger.info("df_local.signing_key_created", path=str(key_path))
    return raw


def sign_envelope(envelope_dict: dict[str, Any], key: bytes) -> str:
    """Compute HMAC-SHA256 over the envelope's signed fields.

    Canonicalization:
    1. Extract only the signed fields from the dict.
    2. Sort fields alphabetically.
    3. JSON-serialize (compact, no trailing whitespace, sorted keys).
    4. HMAC-SHA256 over the UTF-8 bytes of the canonical string.

    Args:
        envelope_dict: The envelope as a plain dict.
        key: The 32-byte HMAC key.

    Returns:
        "hmac-sha256:<hex>" string.
    """
    canonical = _canonicalize(envelope_dict)
    mac = hmac.new(key, canonical, hashlib.sha256)
    return f"hmac-sha256:{mac.hexdigest()}"


def verify_envelope(envelope_dict: dict[str, Any], claimed_hmac: str, key: bytes) -> None:
    """Verify the envelope HMAC.

    Uses constant-time comparison to prevent timing attacks.

    Args:
        envelope_dict: The envelope fields (without the hmac field).
        claimed_hmac: The "hmac-sha256:<hex>" string from the envelope.
        key: The 32-byte HMAC key.

    Raises:
        EnvelopeVerificationError: If verification fails.
    """
    expected = sign_envelope(envelope_dict, key)
    if not hmac.compare_digest(expected, claimed_hmac):
        raise EnvelopeVerificationError(
            "Envelope HMAC verification failed. "
            "The envelope may have been tampered with."
        )


def _canonicalize(envelope_dict: dict[str, Any]) -> bytes:
    """Produce a deterministic bytes representation of the signed envelope fields.

    Only fields present in SIGNED_FIELDS or SIGNED_FIELDS_EXPORT are included.
    Fields are sorted alphabetically.
    Lists are JSON-serialized with sorted elements where applicable.
    """
    # Determine which field set applies
    if "backup_at" in envelope_dict:
        fields = SIGNED_FIELDS
    else:
        fields = SIGNED_FIELDS_EXPORT

    subset = {k: v for k, v in envelope_dict.items() if k in fields}

    # Normalize lists (sort string lists for determinism)
    for k, v in subset.items():
        if isinstance(v, list):
            subset[k] = sorted(v)

    canonical_str = json.dumps(subset, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return canonical_str.encode("utf-8")

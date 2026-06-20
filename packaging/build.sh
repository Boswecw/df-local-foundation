#!/usr/bin/env bash
#
# Build the DF Local Foundation control-surface sidecar as a single frozen
# binary (PyInstaller onefile). Consumed by Forge desktop apps (AuthorForge)
# as a Tauri externalBin.
#
#   Output: packaging/dist/df-local-foundation
#
# Usage:
#   packaging/build.sh                # build (creates .venv-freeze if missing)
#   TARGET_TRIPLE=x86_64-unknown-linux-gnu packaging/build.sh
#       # also copy the artifact to packaging/dist/<name>-<triple> for Tauri
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
VENV="$ROOT/.venv-freeze"
cd "$ROOT"

if [ ! -x "$VENV/bin/pyinstaller" ]; then
  echo "[build] creating freeze venv at $VENV"
  python3 -m venv "$VENV"
  "$VENV/bin/python" -m pip install -q --upgrade pip
  "$VENV/bin/python" -m pip install -q \
    "asyncpg>=0.29.0" "jsonschema>=4.21.0" "pydantic>=2.7.0" "pydantic-settings>=2.3.0" \
    "fastapi>=0.109.0" "uvicorn>=0.27.0" pyinstaller
fi

"$VENV/bin/pyinstaller" packaging/df-local-foundation.spec --clean --noconfirm \
  --distpath packaging/dist --workpath packaging/build

BIN="packaging/dist/df-local-foundation"
echo "[build] built: $BIN"

# Optionally stamp a Tauri target-triple copy for externalBin consumption.
if [ -n "${TARGET_TRIPLE:-}" ]; then
  cp "$BIN" "packaging/dist/df-local-foundation-${TARGET_TRIPLE}"
  echo "[build] tauri sidecar copy: packaging/dist/df-local-foundation-${TARGET_TRIPLE}"
fi

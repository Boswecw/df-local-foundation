# PyInstaller spec — DF Local Foundation control-surface sidecar (onefile).
#
# Produces a single self-contained binary that boots the :8099 health/control
# API. Bundled as a Tauri externalBin by consuming desktop apps (AuthorForge).
#
# Build (from repo root, inside a venv with runtime deps + pyinstaller):
#     pyinstaller packaging/df-local-foundation.spec --clean --noconfirm
# Output: dist/df-local-foundation
#
# Data files:
#   contracts/  — health.schema.json is loaded at import time by
#                 core/health/reporter.py via Path(__file__).parents[2], which
#                 resolves to _MEIPASS at runtime; the binary will not boot
#                 without it.
#   sql/        — core/app migrations (applied out-of-band; bundled so the
#                 binary carries its own schema definitions).

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# SPECPATH is the directory holding this spec (…/packaging); the repo root is its
# parent. Anchor every path to it so the build is invocation-directory agnostic.
repo_root = os.path.dirname(SPECPATH)

hiddenimports = []
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("asyncpg")
hiddenimports += ["app.main", "core.config.settings"]

datas = [
    (os.path.join(repo_root, "contracts"), "contracts"),
    (os.path.join(repo_root, "sql"), "sql"),
]
# jsonschema validates the health contract at import; ship its bundled metaschemas.
datas += collect_data_files("jsonschema")

a = Analysis(
    [os.path.join(SPECPATH, "freeze_entry.py")],
    pathex=[repo_root],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tests"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="df-local-foundation",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
)

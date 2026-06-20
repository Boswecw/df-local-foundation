## 4. Project Structure

### 4.1 Directory Layout

```text
df-local-foundation/
├── app/          # read-only HTTP health API (FastAPI; see §8)
├── contracts/    # JSON Schema contracts (health, migration-status, app-registration)
├── core/         # lifecycle, health reporter, config, backup/export
├── doc/
├── docs/
├── packaging/    # PyInstaller freeze → single-binary sidecar (build.sh, .spec, freeze_entry.py)
├── sql/          # core.* migrations + per-app attach + app schema (sql/apps/<app>)
├── tests/
├── tools/        # db-status / db-backup / db-export / db-restore CLIs
```

### 4.1.1 Sidecar Packaging

`packaging/` freezes the control-surface API into one self-contained binary
(`packaging/build.sh` → `packaging/dist/df-local-foundation`) for Forge desktop
apps to launch as a Tauri-managed `externalBin`. The entrypoint hands uvicorn the
app object directly (not the `app.main:app` import string), and `contracts/` +
`sql/` are bundled as data. Build artifacts (`dist/`, `build/`, `.venv-freeze/`)
are git-ignored; the binary is reproducible from source.

### 4.2 Documentation Rule

- `doc/system/` is the canonical modular source for the root `SYSTEM.md`
- `scripts/context-bundle.sh` is the selective context assembly surface
- `CLAUDE.md` is the repo-local AI instruction file

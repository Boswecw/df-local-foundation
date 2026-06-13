## 4. Project Structure

### 4.1 Directory Layout

```text
df-local-foundation/
├── app/          # read-only HTTP health API (FastAPI; see §8)
├── contracts/    # JSON Schema contracts (health, migration-status, app-registration)
├── core/         # lifecycle, health reporter, config, backup/export
├── doc/
├── docs/
├── sql/          # core.* migrations + per-app attach (sql/apps/<app>)
├── tests/
├── tools/        # db-status / db-backup / db-export / db-restore CLIs
```

### 4.2 Documentation Rule

- `doc/system/` is the canonical modular source for the root `SYSTEM.md`
- `scripts/context-bundle.sh` is the selective context assembly surface
- `CLAUDE.md` is the repo-local AI instruction file

# Setup

## Option A — Docker Desktop (recommended)

Requirements: Windows 10/11 with Docker Desktop (WSL 2 backend).

1. Copy the environment template and set secrets:
   ```powershell
   cd "D:\Project Files\Finance Tracker"
   copy .env.example .env
   python -c "import secrets; print(secrets.token_urlsafe(32))"   # use for POSTGRES_PASSWORD
   python -c "import secrets; print(secrets.token_urlsafe(48))"   # use for SECRET_KEY
   notepad .env
   ```
   Also update the password inside `DATABASE_URL` / `TEST_DATABASE_URL` (only used outside Docker).
2. Start everything:
   ```powershell
   docker compose up -d --build
   docker compose ps          # db, backend (healthy), frontend
   ```
3. Open <http://127.0.0.1:8420>. The first visit asks you to create the single user
   (password ≥ 10 characters).

What runs:

| Service | Purpose | Exposure |
|---|---|---|
| `db` | PostgreSQL 16, volume `pgdata` | `127.0.0.1:5433` (loopback only, for tools/tests) |
| `backend` | FastAPI + local Tesseract OCR, volumes `statements`, `backups` | internal network only |
| `frontend` | nginx serving the app and proxying `/api` | `127.0.0.1:8420` |

Migrations run automatically on backend start (`alembic upgrade head`); the app never creates
tables implicitly. Data persists in Docker volumes across restarts and rebuilds.

Useful commands:

```powershell
docker compose logs -f backend
docker compose exec backend python -m app.cli backup          # see docs/BACKUP.md
docker compose exec backend python -m app.cli reset-password <username>
docker compose down            # stop (data kept)   — never add -v unless you want to DELETE data
```

### Upgrading

```powershell
git pull
docker compose exec backend python -m app.cli backup
docker compose up -d --build
```

## Option B — without Docker

Requirements: Python 3.10+, Node 20+, PostgreSQL 15/16 (EDB Windows installer),
optionally Tesseract OCR (UB-Mannheim Windows build).

1. Create databases `finance` and `finance_test` owned by a `finance` role.
2. `copy .env.example .env` and set `DATABASE_URL` / `TEST_DATABASE_URL` to your server
   (e.g. port 5432), plus `SECRET_KEY`. If Tesseract is not on PATH set
   `TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe`.
3. Backend:
   ```powershell
   cd backend
   python -m venv .venv
   .\.venv\Scripts\pip install -r requirements-dev.txt
   .\.venv\Scripts\alembic upgrade head
   .\.venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```
4. Frontend (second terminal):
   ```powershell
   cd frontend
   npm ci
   npm run build
   npx vite preview --port 8420        # serves the build and proxies /api to :8000
   ```
   For development use `..\scripts\dev.ps1` instead (hot reload on :5173).

Statement files go to `private/statements` and backups to `private/backups` (both git-ignored)
unless `STORAGE_DIR` / `BACKUP_DIR` say otherwise.

## Configuration reference (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `POSTGRES_*`, `DB_PORT` | — | Database credentials / host port for Docker |
| `SECRET_KEY` | — | Required; long random value |
| `AUTH_ENABLED` | `true` | Single-user sign-in. Only disable on a machine nobody else uses |
| `COOKIE_SECURE` | `false` | Set `true` when served over HTTPS |
| `CORS_ORIGINS` | dev origins | Leave empty in Docker (same origin) |
| `OCR_ENABLED` / `TESSERACT_CMD` | `true` / empty | Local OCR for scanned PDFs |
| `DOCUMENT_RETENTION_DAYS` | `0` | Delete stored statement files older than N days (ledger kept) |
| `APP_PORT` / `BIND_ADDRESS` | `8420` / `127.0.0.1` | Where the UI listens |

Matching window, amount tolerance and duplicate window are edited in **Settings → Matching**.

## Moving to another machine

1. On the old machine: **Settings → Backups → Create backup**, download the ZIP
   (or `docker compose exec backend python -m app.cli backup` and copy it out with
   `docker compose cp backend:/data/backups/<file> .`).
2. Install the same app version on the new machine (Option A or B), start it, and create a
   temporary user.
3. **Settings → Backups → Restore from a backup file**, validate, confirm. Sign in with your
   original username/password (users are part of the backup).
4. Check the dashboard and **Reconciliation → Statements**.

The backup's schema revision must match the app version; restore into the same version first,
then upgrade.

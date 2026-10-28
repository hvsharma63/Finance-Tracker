# Backup and restore

## What a backup contains

A ZIP (`finance-backup-YYYYMMDD-HHMMSS.zip`) with:

* `manifest.json` — format version, schema revision, creation time, row counts and SHA-256 of
  every table file and document;
* `tables/*.json` — every row of every table (accounts, transactions, statements, imports and
  staged rows, relationships, categories, rules, aliases, budgets, investments, settings, audit
  log, users);
* `documents/…` — every stored statement file.

**Excluded:** sign-in sessions (you sign in again after a restore) and the backup history table.

After writing, the archive is re-opened and CRC-checked before success is reported.

## Create

* UI: **Settings → Backups → Create backup now** (download from the list).
* CLI (Docker): `docker compose exec backend python -m app.cli backup`
* CLI (no Docker): `cd backend; .\.venv\Scripts\python -m app.cli backup`

Docker backups are written to the `backups` volume (`/data/backups`). Copy one out with
`docker compose cp backend:/data/backups/<file> D:\Backups\`.

## Restore

UI: **Settings → Backups → Restore from a backup file → Validate → Restore… → Replace all data**,
or Restore… on a backup in the list.

CLI: `python -m app.cli restore <file.zip> --yes`

Restore verifies every checksum and the schema revision, then truncates and reloads all tables
**in a single database transaction** — on any error nothing changes. Documents are written only
after the data load succeeds. Sequences are reset so new records get fresh IDs.

## Scheduling (Windows Task Scheduler)

Create a daily task with action:

```
Program:   C:\Program Files\Docker\Docker\resources\bin\docker.exe   (or "docker" if on PATH)
Arguments: compose -f "D:\Project Files\Finance Tracker\docker-compose.yml" exec -T backend python -m app.cli backup
```

Then copy the newest ZIP to separate, encrypted storage (external disk/NAS). Keep several
generations; delete old ones manually from the volume when needed.

## Belt and braces: raw PostgreSQL dump

```powershell
docker compose exec -T db pg_dump -U finance -Fc finance > finance.dump
```

This covers the database only (not statement files). Restore with `pg_restore` into an empty
database of the same app version.

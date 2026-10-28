# Starts an isolated backend for end-to-end tests: fresh finance_e2e database, temp storage, auth on.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root ".env"
$vars = @{}
Get-Content $envFile | Where-Object { $_ -match '^\s*[A-Z_]+=' } | ForEach-Object {
    $k, $v = $_ -split '=', 2; $vars[$k.Trim()] = $v.Trim()
}
$user = $vars["POSTGRES_USER"]; $pw = $vars["POSTGRES_PASSWORD"]; $port = $vars["DB_PORT"]
Push-Location $root
docker compose exec -T db psql -U $user -d postgres -c "DROP DATABASE IF EXISTS finance_e2e WITH (FORCE);" | Out-Null
docker compose exec -T db psql -U $user -d postgres -c "CREATE DATABASE finance_e2e;" | Out-Null
Pop-Location

$tmp = Join-Path $env:TEMP "ft-e2e"
if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
$env:DATABASE_URL = "postgresql+psycopg://${user}:${pw}@127.0.0.1:${port}/finance_e2e"
$env:STORAGE_DIR = Join-Path $tmp "statements"
$env:BACKUP_DIR = Join-Path $tmp "backups"
$env:AUTH_ENABLED = "true"
$env:CORS_ORIGINS = ""
Set-Location (Join-Path $root "backend")
& .\.venv\Scripts\alembic.exe upgrade head
& .\.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8001

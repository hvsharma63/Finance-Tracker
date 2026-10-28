# Development: starts the backend (:8000, auto-reload) and frontend (:5173) in separate windows.
# Requires the database: docker compose up -d db
$root = Split-Path -Parent $PSScriptRoot
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\backend'; .\.venv\Scripts\alembic upgrade head; .\.venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\frontend'; npm run dev"
Write-Host "Backend http://127.0.0.1:8000/api/docs  Frontend http://127.0.0.1:5173"

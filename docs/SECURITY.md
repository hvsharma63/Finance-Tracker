# Security and privacy

## Data flow

All processing is local. The application makes **no outbound network requests**: no bank
aggregators, no market-data or NAV feeds, no AI services, no parsing services, no analytics or
telemetry. Statement parsing (pdfplumber), OCR (Tesseract) and all calculations run inside the
backend process/container.

## Controls implemented

| Area | Control |
|---|---|
| Network exposure | UI bound to `127.0.0.1:8420`; backend not published; PostgreSQL on loopback `5433` only |
| Authentication | Single user, Argon2id password hashing, ≥10-character passwords |
| Sessions | Random 256-bit token, stored hashed; `HttpOnly`, `SameSite=Strict` cookie (`Secure` when `COOKIE_SECURE=true`); 12-hour expiry |
| Brute force | 5 sign-in attempts/minute per client; 5-minute lock after 10 failures |
| CSRF | Every state-changing API call must send `X-Requested-With: finance-tracker` (not sendable cross-site without CORS) + SameSite=Strict |
| CORS | Disabled in Docker (same origin); dev origins explicitly listed |
| Input validation | Pydantic schemas on every endpoint; enumerations enforced by DB CHECK constraints |
| SQL injection | SQLAlchemy parameterised queries only |
| XSS | React escapes output; strict Content-Security-Policy from nginx; API responses `default-src 'none'` |
| Uploads | Size limit (25 MB), real type sniffed from content (PDF/ZIP-XLSX/OLE-XLS/HTML/CSV), extension allow-list, binary rejection, filename sanitised, content-addressed storage, path traversal guarded |
| Statement files | Never served by the web server; only reachable through import logic; container dir mode 700, non-root user |
| PDF passwords | Saved only if you choose (default on at upload, or Settings → PDF passwords). Encrypted with Fernet (AES-128-CBC + HMAC-SHA256) under a key derived from `SECRET_KEY`; never returned by the API, never logged. Changing `SECRET_KEY` makes them unreadable (re-enter them). Included, still encrypted, in backups |
| Account numbers | Only the last four digits are stored |
| Exports | CSV/Excel cells starting with `= + - @` are neutralised against formula injection |
| Errors/logging | Generic 500 responses; no statement contents or amounts logged |
| Secrets | `.env` (git-ignored); no credentials in code; `.env.example` contains placeholders only |

## Encryption at rest — not provided by the application

The database and statement files are **not encrypted by the app**. Protect them with full-disk
encryption: enable **BitLocker** on the drive holding Docker's data (`%LOCALAPPDATA%\Docker\wsl`)
and the project folder, and keep backup ZIPs on encrypted storage. Backups contain everything,
including statements, in plain form.

## Remote access

Default: this machine only. If you need access from other devices:

* **Preferred:** a private VPN (Tailscale/WireGuard). Keep `BIND_ADDRESS=127.0.0.1` and use the
  VPN's port forwarding, or set `BIND_ADDRESS` to the VPN interface IP only.
* **LAN:** set `BIND_ADDRESS` to the PC's LAN IP on a trusted network only.
* **Over the internet:** only behind an authenticated HTTPS reverse proxy (e.g. Caddy with TLS
  and an extra auth layer). Set `COOKIE_SECURE=true`.
* **Never** publish PostgreSQL (5433) or the backend port, and never port-forward the app
  directly on your router.

## Operational recommendations

* Use a unique password; reset with `python -m app.cli reset-password <user>` if forgotten.
* Keep Windows, Docker Desktop and the images up to date (`docker compose build --pull`).
* Use `DOCUMENT_RETENTION_DAYS` if you do not want original statements kept indefinitely.
* Real statements must never be committed to git (`private/` and `.env` are ignored).

## Known limitations

* Login rate limiting is in-memory (resets on restart) and per client IP.
* There is one user; no roles. The schema keeps user ownership out of financial tables, so
  multi-user support would need tenant columns added.

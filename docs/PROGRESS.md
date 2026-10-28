# Progress checklist

Status as of 2026-10-28. ✅ implemented and tested · 🟡 implemented, limited · ⏳ waiting on input · ❌ not done

## Phase 1 — Foundation ✅
- ✅ Repository, git, `.gitignore` (secrets and `private/` excluded), `.env.example`
- ✅ FastAPI + SQLAlchemy 2 + Alembic; React + TypeScript + Vite + Tailwind
- ✅ PostgreSQL 16 in Docker Compose, loopback-only; separate `finance_test` / `finance_e2e` DBs
- ✅ Health check `/api/health` (DB + schema revision)

## Phase 2 — Accounts & ledger ✅
- ✅ All account types; masked identifiers (last 4 only); opening balance with source + verification
- ✅ Balances: calculated / statement-reported / reconciled / estimated; coverage dates and gaps
- ✅ Transactions with originals preserved, normalized/user values separate, audit history
- ✅ Search, filters, sort, pagination, bulk categorize, tags, notes, manual entries, CSV/XLSX export

## Phase 3 — Importer ✅
- ✅ CSV, XLSX, XLS, HTML-disguised XLS, digital PDF (ruled + unruled), password-protected PDF
- ✅ Local OCR for scanned PDFs (Tesseract in Docker image; verified on an image-only PDF)
- ✅ Parser registry, detection scoring, generic parsers, manual column mapping, saved formats
- ✅ Preview, row correction, include/exclude, statement metadata edit, validation, sign hints
- ✅ Duplicate protection (exact fingerprints + possible duplicates), repeat-file detection
- ✅ Transactional commit, idempotent commit, delete with impact check, controlled reprocess
- ✅ Layout/parser-version change warnings, document retention

## Phase 4 — Parsers from your statements ⏳
- ⏳ **Needs your sample statements.** No institution-specific parser exists yet; none is claimed.

## Phase 5 — Reconciliation ✅
- ✅ Transfer / card-payment / investment / loan / refund suggestions with reasons and scores
- ✅ Configurable window (default 5 days) and amount tolerance
- ✅ Approve, approve partial, reject (remembered), undo, manual links, split matches, over-allocation guard
- ✅ Mark committed duplicates; statement reconciliation with visible differences

## Phase 6 — Categorization & reporting ✅
- ✅ Default category tree with reporting types; editable
- ✅ Rules engine (priority, enable/disable, test preview, reapply), merchant aliases, rule suggestions
- ✅ Dashboard (cards, 6 charts with table views, freshness/coverage warnings, drill-down)
- ✅ Spending, income, merchants, MoM, largest, unusual, recurring candidates, cash flow, accounts, net worth (+ over time)

## Phase 7 — Investments 🟡
- ✅ Instruments, all transaction types, WAC cost basis, realized/unrealized, dividends/interest, splits, bonus
- ✅ Valuations (statement/import/manual with source note); unknown stays unknown; FDs with projected vs credited interest
- ✅ CSV/XLSX import of investment transactions and NAV/price files (dry-run preview, idempotent)
- 🟡 No PDF investment statement parsers (CAS/contract notes) — needs samples
- 🟡 TWR/MWR returns intentionally not computed (data completeness not guaranteed)

## Phase 8 — Budgets & exports ✅
- ✅ Monthly/default category budgets with projection; recurring detection → confirmed definitions (no fake ledger rows)
- ✅ CSV/Excel exports for transactions and 9 reports; print-to-PDF stylesheet
- ✅ Backup/restore (UI + CLI), checksums, single-transaction restore

## Phase 9 — Security & release 🟡
- ✅ Auth, sessions, rate limiting, CSRF, CSP, upload checks, non-root container, loopback binding
- ✅ Clean Docker deployment verified (`docker compose up -d --build`)
- 🟡 No encryption at rest by the app (documented: use BitLocker)

## Tests (last run 2026-10-28)

| Suite | Command | Result |
|---|---|---|
| Backend unit + integration + acceptance A–H | `cd backend; .\.venv\Scripts\python -m pytest` | 84 passed |
| Backend lint | `.\.venv\Scripts\ruff check app tests` | clean |
| Frontend unit | `cd frontend; npm test` | 5 passed |
| Frontend type check | `npm run typecheck` | clean |
| End-to-end (Playwright, Chromium) | `npm run e2e` | 1 workflow passed (setup → accounts → imports incl. overlap → category + rule → transfer & card-payment approval → dashboard figures → investments → report export → backup → restore → sign-in) |
| OCR in Docker | manual script (see conversation log) | image-only PDF parsed, balance chain passed |

## Known limitations
- Only generic parsers; real Indian bank/card/AMC layouts are untested until samples are provided.
- Classification is computed in Python per request — fine for tens of thousands of transactions; very large ledgers may need caching.
- Net-worth history uses current account definitions and the latest valuation on or before each month end.
- Login rate limiting is in-memory.
- Multi-currency: amounts carry a currency, but reports assume a single (INR) base without FX conversion.

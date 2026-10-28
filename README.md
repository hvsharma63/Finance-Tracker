# Finance Tracker

A private, self-hosted personal finance and wealth application for India (₹, Asia/Kolkata).
Everything is derived from bank, credit-card and investment statements **you import** —
CSV, Excel (XLSX/XLS, including HTML-disguised XLS), digital PDF, password-protected PDF and
scanned PDF via local OCR. There are **no bank APIs, no market-data APIs, no external AI and
no telemetry**. Your data stays on your machine.

## What it does

* **Accounts** — savings, current, cash, credit cards, FDs, brokerage/demat, mutual funds,
  loans, custom. Distinguishes statement-reported, calculated, reconciled and estimated balances,
  with the date coverage runs to.
* **Statement import** — upload → automatic format detection → preview with validation
  (running-balance chain, opening + movements = closing) → correct rows → confirm. Repeated and
  overlapping statements never double-count. Unknown formats can be column-mapped and saved as
  reusable formats.
* **Ledger** — integer paise, original statement values preserved, every edit audited; search,
  filter, sort, bulk categorize, tags, notes, CSV/Excel export.
* **Reconciliation** — suggested internal transfers, card repayments, investment flows and
  refunds with stated reasons; nothing counts until you approve; undo any time; partial and split
  matches.
* **Categorization** — editable categories with explicit reporting types, deterministic rules
  with priorities, merchant aliases, review queue, rule suggestions from your corrections.
* **Dashboard & reports** — income, net spending, savings, cash flow, categories, merchants,
  recurring and unusual payments, net worth over time; CSV/Excel export and print-to-PDF.
* **Investments** — instruments, buys/sells/dividends/splits/bonus/maturities, weighted average
  cost, realized/unrealized gains, FDs. Unknown valuations stay unknown.
* **Budgets**, **backups/restore**, single-user **authentication**.

Definitions of income, expenses, transfers, net worth and the sign convention:
[docs/CONVENTIONS.md](docs/CONVENTIONS.md).

## Quick start (Windows, Docker Desktop)

```powershell
cd "D:\Project Files\Finance Tracker"
copy .env.example .env          # then edit .env: set POSTGRES_PASSWORD and SECRET_KEY (see file)
docker compose up -d --build
```

Open <http://127.0.0.1:8420>, create your user, add accounts and import a statement.
Full instructions, the non-Docker path and upgrades: [docs/SETUP.md](docs/SETUP.md).

## Supported statement formats

| Parser | Formats | Status |
|---|---|---|
| `axis_savings_pdf` | Axis Bank savings e-statement (PDF) | Tested on a real statement (Sep 2026) |
| `sbi_savings_pdf` | SBI savings e-statement (PDF) | Tested on a real statement (Sep 2026) |
| `axis_credit_card_pdf` | Axis Bank credit cards — Visa Privilege, Neo RuPay (PDF) | Tested on 2 real statements (Oct 2026) |
| `idfc_first_credit_card_pdf` | IDFC FIRST Bank credit card — FIRST Select (PDF) | Tested on a real statement (Oct 2026) |
| `rbl_credit_card_pdf` | RBL Bank credit cards — IRCTC, BookMyShow Play (PDF) | Tested on 2 real statements (Oct 2026) |
| `generic_table` | CSV/XLSX/XLS with a recognisable header (Date, Narration/Particulars, Withdrawal/Debit, Deposit/Credit, Amount + Dr/Cr, Balance…) | Tested on synthetic statements |
| `generic_pdf` | Digital PDFs with ruled tables, unruled column layouts, or `date … amount balance` lines; scanned PDFs via Tesseract | Tested on synthetic statements |
| Saved formats | Any CSV/Excel layout you map once in the UI | Per your mapping |

Institution parsers are listed only for layouts validated row-by-row against real statements;
other variants of the same bank may differ. Password-protected PDFs open automatically with
saved passwords. To add another format see [docs/PARSERS.md](docs/PARSERS.md).

## Documentation

| Doc | Contents |
|---|---|
| [docs/SETUP.md](docs/SETUP.md) | Installation (Docker / without Docker), configuration, upgrades, migration to another machine |
| [docs/CONVENTIONS.md](docs/CONVENTIONS.md) | Money, signs, balances, reporting definitions |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Components, layers, import pipeline, risks |
| [docs/PARSERS.md](docs/PARSERS.md) | Parser library, adding a format, sample handling |
| [docs/SECURITY.md](docs/SECURITY.md) | Threat model, controls, remote access, encryption at rest |
| [docs/BACKUP.md](docs/BACKUP.md) | Backups, restore, scheduling |
| [docs/PROGRESS.md](docs/PROGRESS.md) | Implementation checklist, test results, known limitations |

API documentation (OpenAPI) is served at <http://127.0.0.1:8420/api/docs>.

## Development

```powershell
docker compose up -d db                 # PostgreSQL on 127.0.0.1:5433
.\scripts\dev.ps1                       # backend :8000 + frontend :5173 with hot reload
cd backend;  .\.venv\Scripts\python -m pytest      # backend tests (uses finance_test DB)
cd frontend; npm test; npm run typecheck; npm run e2e
```

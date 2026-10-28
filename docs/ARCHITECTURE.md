# Architecture

Modular monolith: one FastAPI backend, one React SPA, one PostgreSQL database, one private
file store. No external network calls for financial data, parsing, AI or market prices.

```
Browser ──► nginx (frontend container, :8080 on 127.0.0.1)
              ├── /        → React SPA (static files)
              └── /api/*   → FastAPI backend (:8000, internal only)
                                ├── PostgreSQL (volume pgdata)
                                └── private statement store (volume statements)
```

## Backend layers (`backend/app`)

| Layer | Path | Responsibility |
|---|---|---|
| API | `api/` | HTTP routing, request validation, auth dependency. No financial logic. |
| Core | `core/` | Settings, DB session, money/date primitives, security, errors. |
| Models | `models/` | SQLAlchemy ORM tables (schema is owned by Alembic migrations). |
| Schemas | `schemas/` | Pydantic request/response models. |
| Ledger | `services/ledger/` | Account balances, transaction edits, audit trail. |
| Imports | `services/imports/` | File storage, extraction, parser registry, normalization, validation, preview, commit. |
| Reconciliation | `services/reconciliation/` | Duplicate detection, match suggestions, approvals, statement reconciliation. |
| Categorization | `services/categorization/` | Deterministic rules engine, merchant aliases. |
| Investments | `services/investments/` | Holdings, weighted-average cost basis, valuations, FDs. |
| Reporting | `services/reporting/` | Classification of movements, dashboard, reports, exports. |
| Backup | `services/backup/` | Logical backup/restore of all tables plus statement files. |

Financial calculations live only in backend services and are covered by tests in
`backend/tests`. The frontend displays what the API returns; it does no money arithmetic
beyond formatting.

## Key conventions

See [CONVENTIONS.md](CONVENTIONS.md) for money, sign, balance and reporting definitions.

## Import pipeline

```
upload → size/type checks → SHA-256 hash → private storage
      → extraction (CSV / XLSX / XLS / PDF text+tables / OCR)
      → parser detection (registry scores every parser; best confidence wins)
      → parse → normalized candidate rows (+ source page/row references, raw values)
      → validation (row errors, running balance chain, opening+movements=closing, period)
      → duplicate detection against the ledger (fingerprints + fuzzy candidates)
      → PREVIEW (staged rows, editable; nothing in the ledger yet)
      → user corrections / column mapping / include-exclude decisions
      → COMMIT (single DB transaction: statement, transactions, balance snapshots,
                categorization rules, match suggestions)
```

A parser never writes to the ledger. Staged rows live in `import_rows` until committed.

## Technical risks

1. **PDF layouts** vary by bank and change over time. Mitigation: institution-specific
   parsers built from real samples, layout fingerprints, regression tests, and a
   generic fallback with user column mapping.
2. **Sign errors** (debit/credit, Dr/Cr suffixes, credit-card perspective). Mitigation: one
   holder-perspective sign convention, running-balance chain validation, never auto-flip.
3. **Double counting** of transfers and card repayments. Mitigation: explicit approved
   relationships plus "financial movement" category types, excluded from income/expense.
4. **Duplicates from overlapping statements**. Mitigation: per-row fingerprints with
   occurrence ordinals and running balances; fuzzy candidates require review.
5. **Valuations**. No market data: unknown values stay unknown and are labelled.

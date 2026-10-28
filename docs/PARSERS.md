# Statement parsers

## How parsing works

```
file → sniff real type → extract (CSV rows / sheets / PDF text, words with x/y, ruled tables / OCR words)
     → every registered parser scores the document (detect) → best parser parses
     → candidate rows (date, description, debit, credit, signed amount, balance, reference,
       raw source values, source page/row reference, errors, warnings)
     → validation → staged preview (nothing in the ledger)
```

Selection order: user-chosen parser → institution parser with confidence ≥ 0.5 → saved format
(header signature match) → generic parser.

Code: `backend/app/services/imports/`

| File | Role |
|---|---|
| `parser_registry.py` | `StatementParser` interface, `@register`, ranking |
| `extraction.py` | Type sniffing, CSV/XLSX/XLS/HTML-XLS, PDF (passwords), OCR |
| `table_mapping.py` | Header detection, column-role synonyms, row conversion, opening/closing rows, multi-line rows |
| `pdf_layout.py` | Positional parsing of unruled PDFs/OCR by header x-positions; balance-delta fallback |
| `metadata.py` | Period, masked account number, balances from text |
| `normalization.py` | UPI/NEFT/IMPS/ATM/POS detection, UTR/RRN extraction, merchant extraction |
| `validation.py` | Running-balance chain, opening + movements = closing, period checks, sign hints |
| `parsers/generic/` | `generic_table`, `generic_pdf` |
| `parsers/banks/`, `credit_cards/`, `investments/` | Institution-specific parsers (none yet) |

## Guarantees every parser must keep

* Output uses the holder-perspective sign convention (docs/CONVENTIONS.md).
* Unparseable rows are returned with errors, never dropped. Non-transaction lines (headers,
  totals, footers) are returned in `ignored_lines` and shown in the preview.
* Signs are never changed to make balances reconcile. A likely inverted file produces a hint.
* No database access.

## Current coverage — honest status

| Parser | Version | Tested against |
|---|---|---|
| generic_table | 1.0 | Synthetic CSV (preamble, opening/closing rows, separate debit/credit), XLSX (native dates/floats), HTML-as-XLS, card CSV with `Cr` suffix |
| generic_pdf | 1.0 | Synthetic multi-page PDFs (ruled and unruled, wrapped narrations, page footers, opening/closing lines), password-protected PDF, scanned image PDF via Tesseract (in the Docker image) |

No real bank, card or investment statement has been tested yet. **No institution is claimed as
supported.**

Known generic limitations:

* Wrapped narration lines are joined with a space unless the break is at `/ - @ _ . :`; a
  bank that wraps mid-word will show e.g. `GROC ERIES` until a dedicated parser joins correctly.
* Integers without decimals (`500`) are not treated as amounts in PDF text, to avoid confusing
  them with reference numbers.
* Day-first dates only; month-first dates are rejected rather than guessed.
* Credit-card statements with a single amount column and no Dr/Cr marker are assumed
  "positive = purchase" and flagged; confirm against a known payment.
* Investment PDFs (CAS, contract notes) need dedicated parsers; CSV/Excel exports work via
  **Investments → Import**.

## Adding a format from your sample

1. Put the sample in `sample-data/private/` (git-ignored). **Never commit real statements.**
2. Upload it in the app first: the preview shows exactly what generic parsing gets right/wrong.
3. Create `parsers/banks/<bank>_<product>_<filetype>.py`:

   ```python
   @register
   class HdfcSavingsPdf(StatementParser):
       name = "hdfc_savings_pdf"; version = "1.0"; institution = "HDFC Bank"
       statement_type = "bank"; file_types = frozenset({"pdf"})
       tested_variants = ("2024 e-statement layout, 4 samples",)
       def detect(self, doc): ...   # distinctive stable markers → ≥0.8
       def parse(self, doc, options): ...  # reuse pdf_layout / table_mapping helpers where possible
   ```
4. Build a **synthetic or redacted fixture** reproducing the layout (same headers, wrapping,
   page breaks, Dr/Cr style) in `backend/tests/fixtures/`, and a test that checks **every row**:
   count, dates, descriptions, signed amounts, balances, opening/closing, and malformed rows.
5. Compare against the original statement totals; document unresolved discrepancies.
6. Run `pytest` — all earlier parser tests must still pass. Bump `version` on any behaviour change;
   imports record the parser name/version and warn when an account's format or version changes.

## Sharing a sample for parser development

Best: the statement file as downloaded from net banking. Before sharing you may redact names,
addresses and full account numbers (keep the last 4), but keep the **layout, headers, dates,
amounts, Dr/Cr markers, balances and page breaks** — those are what the parser must handle.
One statement with several pages and some multi-line narrations is ideal; two months of the
same account show whether the layout is stable.

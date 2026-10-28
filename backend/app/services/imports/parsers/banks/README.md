# Institution-specific bank parsers

One module per institution and statement layout, e.g. `hdfc_savings_pdf.py`.
Each module defines a `StatementParser` subclass decorated with `@register`.

Rules:

* `detect()` must check for distinctive, stable markers (bank name, header labels) and return
  a high confidence (≥ 0.8) only when they are all present.
* `parse()` returns a `ParsedStatement` in the holder-perspective sign convention
  (docs/CONVENTIONS.md). Never flip signs to make balances chain.
* Bump `version` whenever parsing behaviour changes, and list tested layouts in
  `tested_variants`.
* Every parser needs a regression test in `backend/tests/parsers/` using a synthetic or
  redacted fixture. Real statements must never be committed.

No institution parsers exist yet: they are added only after testing against real samples.
See docs/PARSERS.md.

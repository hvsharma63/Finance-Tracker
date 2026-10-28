"""Helpers for regression tests against the user's real (private, never committed) statements.

Expectations live in sample-data/private/expectations.json (git-ignored). Regenerate them only
after manually verifying a parser's output against the original statement:

    python -m tests.parsers.real_samples --write
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from app.services.imports import extraction
from app.services.imports.candidates import ParseOptions
from app.services.imports.parser_registry import rank_parsers
from app.services.imports.validation import validate

PRIVATE = Path(__file__).resolve().parents[3] / "sample-data" / "private"
EXPECTATIONS = PRIVATE / "expectations.json"


def summarize(path: Path, password: str | None) -> dict:
    doc = extraction.extract(path.read_bytes(), path.name, path=path, password=password)
    best = rank_parsers(doc)[0]
    ps = best.parser.parse(doc, ParseOptions())
    rep = validate(ps)
    rows = [f"{r.txn_date}|{r.description}|{r.amount}|{r.balance}" for r in ps.rows]
    return {
        "parser": f"{best.parser.name}@{best.parser.version}",
        "rows": len(ps.rows),
        "error_rows": rep.error_rows,
        "total_debits": rep.total_debits,
        "total_credits": rep.total_credits,
        "opening": str(ps.opening_balance),
        "closing": str(ps.closing_balance),
        "period": [str(ps.period_start), str(ps.period_end)],
        "balance_check": rep.balance_check,
        "rows_sha256": hashlib.sha256("\n".join(rows).encode()).hexdigest(),
    }


def main(argv: list[str]) -> int:
    data = json.loads(EXPECTATIONS.read_text(encoding="utf-8"))
    for name, exp in data["files"].items():
        got = summarize(PRIVATE / name, exp.get("password"))
        if "--write" in argv:
            exp.update(got)
        print(name, json.dumps(got))
    if "--write" in argv:
        EXPECTATIONS.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

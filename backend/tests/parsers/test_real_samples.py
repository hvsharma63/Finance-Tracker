"""Regression against the user's real statements. Skipped when sample-data/private is absent."""

import json

import pytest

from tests.parsers.real_samples import EXPECTATIONS, PRIVATE, summarize

if not EXPECTATIONS.exists():
    pytest.skip("No private statement samples on this machine", allow_module_level=True)

CASES = json.loads(EXPECTATIONS.read_text(encoding="utf-8"))["files"]


@pytest.mark.parametrize("name", sorted(CASES))
def test_real_statement_unchanged(name):
    exp = CASES[name]
    path = PRIVATE / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    got = summarize(path, exp.get("password"))
    for key in ("parser", "rows", "error_rows", "total_debits", "total_credits", "opening", "closing", "period",
                "balance_check", "rows_sha256"):
        assert got[key] == exp[key], f"{name}: {key} changed ({exp[key]!r} -> {got[key]!r})"
    assert got["balance_check"] == "passed"

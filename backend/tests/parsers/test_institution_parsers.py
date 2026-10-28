"""Regression tests for institution-specific parsers using synthetic layout replicas (every row checked)."""

from datetime import date
from pathlib import Path

import pytest

from app.services.imports import extraction
from app.services.imports.candidates import ParseOptions
from app.services.imports.parser_registry import get_parser, rank_parsers
from app.services.imports.parsers.credit_cards.rbl_credit_card_pdf import colour_kind
from app.services.imports.validation import validate
from tests.fixtures import bank_layouts as bl


def _parse(tmp_path: Path, data: bytes, name="s.pdf"):
    p = tmp_path / name
    p.write_bytes(data)
    doc = extraction.extract(data, name, path=p)
    best = rank_parsers(doc)[0]
    return best, best.parser.parse(doc, ParseOptions())


def _d(s: str) -> date:
    for fmt in ("%d-%m-%Y", "%d-%m-%y", "%d/%m/%Y"):
        try:
            from datetime import datetime
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(s)


GENERATORS = [bl.axis_savings_pdf, bl.sbi_savings_pdf, bl.axis_credit_card_pdf, bl.idfc_credit_card_pdf,
              bl.rbl_credit_card_pdf]


@pytest.mark.parametrize("gen", GENERATORS, ids=lambda g: g.__name__)
def test_every_row_and_balances(tmp_path, gen):
    data, exp = gen()
    best, ps = _parse(tmp_path, data)
    assert best.parser.name == exp["parser"] and best.confidence >= 0.9
    got = [(r.txn_date, r.description, r.amount) for r in ps.rows]
    want = [(_d(d), desc, amt) for d, desc, amt in exp["rows"]]
    assert got == want
    assert all(not r.errors for r in ps.rows)
    assert ps.opening_balance == exp["opening"]
    assert ps.closing_balance == exp["closing"]
    assert ps.account_hint == exp["account_hint"]
    rep = validate(ps)
    assert rep.balance_check == "passed", rep.messages
    assert not [w for w in ps.warnings if "difference" in w], ps.warnings


def test_generic_parser_no_longer_wins_for_supported_layouts(tmp_path):
    for gen in GENERATORS:
        data, exp = gen()
        best, _ = _parse(tmp_path, data)
        assert not best.parser.is_generic, gen.__name__


def test_axis_card_ignores_example_table_and_keeps_merchant_category(tmp_path):
    data, _ = bl.axis_credit_card_pdf()
    _, ps = _parse(tmp_path, data)
    assert all(r.txn_date.year == 2026 and r.txn_date.month in (9, 10) for r in ps.rows)
    assert len(ps.rows) == len(bl.AXIS_CC_ROWS)  # page-2 "25/09/2026 Purchase Db" example not imported
    assert ps.rows[0].raw["merchant_category"] == "RETAIL STORES"
    assert any("Payments + credits" in c for c in ps.extra["summary_checks"])


def test_axis_savings_period_and_wrapped_narrations(tmp_path):
    data, _ = bl.axis_savings_pdf()
    _, ps = _parse(tmp_path, data)
    assert (ps.period_start, ps.period_end) == (date(2026, 9, 1), date(2026, 9, 30))
    assert ps.rows[3].description.endswith("CNA/TESTREF1/9100000000000000000")  # joined without space after "/"


def test_sbi_opening_closing_rows_are_metadata(tmp_path):
    data, _ = bl.sbi_savings_pdf()
    _, ps = _parse(tmp_path, data)
    reasons = {i["reason"] for i in ps.ignored_lines}
    assert {"opening balance", "closing balance"} <= reasons
    assert validate(ps).running_balance_check == "passed"
    assert (ps.period_start, ps.period_end) == (date(2026, 9, 1), date(2026, 9, 30))


def test_rbl_direction_comes_from_colour_and_is_cross_checked(tmp_path):
    data, _ = bl.rbl_credit_card_pdf()
    _, ps = _parse(tmp_path, data)
    assert any(i["reason"] == "zero-amount row" for i in ps.ignored_lines)
    assert any("rounded" in w for w in ps.warnings)
    # If credits were NOT coloured (layout change) the payment becomes a debit and the cross-check flags it
    data, _ = bl.rbl_credit_card_pdf(credit_colour=(0, 0, 0))
    _, ps = _parse(tmp_path, data, "b.pdf")
    pay = ps.rows[0]
    assert pay.amount < 0 and any("looks like a credit" in w for w in pay.warnings)
    assert any("Payments & credits" in w and "difference" in w for w in ps.warnings)
    assert validate(ps).balance_check == "failed"  # never silently "fixed"


def test_colour_classification():
    from app.services.imports.candidates import Word

    def w(c):
        return Word("1.00", 0, 1, 0, 1, color=c)
    assert colour_kind(w((0, 0.501, 0))) == "credit"
    assert colour_kind(w((0,))) == "debit"
    assert colour_kind(w((0.2, 0.2, 0.2))) == "debit"
    assert colour_kind(w((0.9, 0.1, 0.1))) == "unknown"
    assert colour_kind(w((0.8, 0.0, 0.9, 0.1))) == "credit"  # CMYK green


def test_layout_change_is_reported_not_guessed(tmp_path):
    data, _ = bl.idfc_credit_card_pdf()
    p = tmp_path / "x.pdf"
    p.write_bytes(data)
    doc = extraction.extract(data, "x.pdf", path=p)
    for page in doc.pages:  # simulate a redesigned header
        for wd in page.words:
            if wd.text == "Details":
                wd.text = "Narrative"
    ps = get_parser("idfc_first_credit_card_pdf").parse(doc, ParseOptions())
    assert ps.needs_mapping and not ps.rows and "layout may have changed" in ps.warnings[0]

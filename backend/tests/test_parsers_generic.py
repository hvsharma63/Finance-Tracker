"""Generic parser tests against complete synthetic statements (every row checked)."""

from decimal import Decimal
from pathlib import Path

import pytest

from app.services.imports import extraction
from app.services.imports.candidates import ParseOptions
from app.services.imports.parser_registry import rank_parsers
from app.services.imports.validation import validate
from tests.fixtures import synthetic as syn


def _expected_amounts():
    out = []
    for _, _, _, w, d in syn.BANK_ROWS:
        out.append(-Decimal(w.replace(",", "")) if w else Decimal(d.replace(",", "")))
    return out


def _parse(data: bytes, name: str, tmp_path: Path | None = None, **opts):
    path = None
    if tmp_path is not None:
        path = tmp_path / name
        path.write_bytes(data)
    doc = extraction.extract(data, name, path=path)
    best = rank_parsers(doc)[0]
    ps = best.parser.parse(doc, ParseOptions(**opts))
    return doc, best, ps


def _assert_bank_statement(ps, check_balances=True):
    assert [r.errors for r in ps.rows] == [[]] * len(syn.BANK_ROWS)
    assert len(ps.rows) == len(syn.BANK_ROWS)
    assert [r.amount for r in ps.rows] == _expected_amounts()
    assert [r.txn_date.strftime("%d/%m/%Y") for r in ps.rows] == [r[0] for r in syn.BANK_ROWS]
    assert [r.description for r in ps.rows] == [r[1] for r in syn.BANK_ROWS]
    rep = validate(ps)
    if check_balances:
        assert [r.balance for r in ps.rows] == syn.bank_balances()
        assert rep.running_balance_check == "passed"
        assert rep.balance_check == "passed"
        assert Decimal(rep.closing_balance_calculated) == syn.BANK_CLOSING
    return rep


def test_csv_with_preamble_opening_and_closing_rows():
    doc, best, ps = _parse(syn.bank_csv(), "stmt.csv")
    assert best.parser.name == "generic_table"
    _assert_bank_statement(ps)
    assert ps.opening_balance == syn.BANK_OPENING
    assert ps.closing_balance == syn.BANK_CLOSING
    assert ps.account_hint == "XX9876"
    assert str(ps.period_start) == "2026-04-01" and str(ps.period_end) == "2026-04-30"
    reasons = {i["reason"] for i in ps.ignored_lines}
    assert "opening balance row" in reasons and "summary/total row" in reasons
    assert ps.rows[0].transaction_type == "upi"
    assert ps.rows[0].reference == "412345678901"
    assert ps.rows[2].transaction_type == "atm"


def test_xlsx_native_dates_and_floats():
    _, best, ps = _parse(syn.bank_xlsx(), "stmt.xlsx")
    assert best.parser.name == "generic_table"
    rep = _assert_bank_statement(ps, check_balances=False)
    assert [r.balance for r in ps.rows] == syn.bank_balances()
    assert rep.running_balance_check == "passed"
    # no explicit opening balance: derived from first row
    assert Decimal(rep.opening_balance) == syn.BANK_OPENING


def test_html_disguised_as_xls():
    doc, _, ps = _parse(syn.bank_html_xls(), "stmt.xls")
    assert doc.file_type == "xls" and any("HTML" in w for w in doc.warnings)
    _assert_bank_statement(ps, check_balances=False)


@pytest.mark.parametrize("ruled", [False, True])
def test_pdf_multi_page_wrapped_rows(tmp_path, ruled):
    doc, best, ps = _parse(syn.bank_pdf(ruled=ruled, rows_per_page=5), "stmt.pdf", tmp_path)
    assert doc.file_type == "pdf" and len(doc.pages) == 3
    assert best.parser.name == "generic_pdf"
    _assert_bank_statement(ps)
    assert ps.opening_balance == syn.BANK_OPENING
    assert ps.closing_balance == syn.BANK_CLOSING
    assert any(i["reason"] == "page header/footer" for i in ps.ignored_lines)


def test_credit_card_csv_signs():
    _, _, ps = _parse(syn.card_csv(), "card.csv")
    assert ps.statement_type == "credit_card"
    assert [r.amount for r in ps.rows] == [
        Decimal("-12000.00"), Decimal("-1000.00"), Decimal("-12000.00"), Decimal("25000.00")
    ]
    assert any("single amount column" in w for w in ps.warnings)


def test_explicit_mapping_and_unrecognised_headers():
    data = b"When,What,Out,In\n01/04/2026,Coffee,120.00,\n02/04/2026,Refund,,20.00\n"
    _, _, ps = _parse(data, "odd.csv")
    assert ps.needs_mapping and not ps.rows
    _, _, ps = _parse(data, "odd.csv", column_mapping={"date": "When", "description": "What", "debit": "Out", "credit": "In"})
    assert [r.amount for r in ps.rows] == [Decimal("-120.00"), Decimal("20.00")]


def test_unparseable_rows_are_kept_as_errors_not_dropped():
    data = (b"Date,Narration,Withdrawal,Deposit,Balance\n"
            b"01/04/2026,Good row,100.00,,900.00\n"
            b"31/13/2026,Bad date,50.00,,850.00\n"
            b"02/04/2026,Bad amount,12x.00,,850.00\n")
    _, _, ps = _parse(data, "bad.csv")
    assert len(ps.rows) == 3
    assert ps.rows[0].errors == []
    assert "Could not read date" in ps.rows[1].errors[0]
    assert "Could not read debit amount" in ps.rows[2].errors[0]


def test_sign_inversion_is_hinted_never_applied():
    # Single signed amount column where the file uses positive = money out
    data = (b"Date,Description,Amount,Balance\n"
            b"01/04/2026,Shop,100.00,900.00\n"
            b"02/04/2026,Shop 2,50.00,850.00\n")
    _, _, ps = _parse(data, "inv.csv")
    assert [r.amount for r in ps.rows] == [Decimal("100.00"), Decimal("50.00")]
    rep = validate(ps)
    assert rep.running_balance_check == "failed"
    assert rep.sign_hint == "inverted"


def test_rejects_disguised_binary():
    with pytest.raises(extraction.ExtractionError):
        extraction.extract(b"MZ\x90\x00\x03\x00\x00\x00", "evil.csv")
    with pytest.raises(extraction.ExtractionError):
        extraction.extract(b"hello", "evil.exe")

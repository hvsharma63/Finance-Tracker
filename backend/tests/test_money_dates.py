from datetime import date
from decimal import Decimal

import pytest

from app.core.dates import DateParseError, parse_date
from app.core.money import MoneyParseError, format_inr, from_minor, parse_amount, to_minor


@pytest.mark.parametrize("raw,expected,direction", [
    ("1,23,456.78", Decimal("123456.78"), None),
    ("₹ 2,345.50", Decimal("2345.50"), None),
    ("Rs. 100", Decimal("100"), None),
    ("(500.00)", Decimal("-500.00"), None),
    ("500.00-", Decimal("-500.00"), None),
    ("-17.70", Decimal("-17.70"), None),
    ("25,000.00 Cr", Decimal("25000.00"), "CR"),
    ("1,000.00Dr", Decimal("1000.00"), "DR"),
    ("Dr 99.99", Decimal("99.99"), "DR"),
    ("", None, None),
    (None, None, None),
    (1234.5, Decimal("1234.5"), None),
    (0.1, Decimal("0.1"), None),
])
def test_parse_amount(raw, expected, direction):
    assert parse_amount(raw) == (expected, direction)


def test_parse_amount_rejects_text():
    with pytest.raises(MoneyParseError):
        parse_amount("12abc")


def test_minor_units_round_trip_no_float_error():
    assert to_minor(Decimal("0.1")) + to_minor(Decimal("0.2")) == to_minor(Decimal("0.3")) == 30
    assert to_minor("123456.785") == 12345679  # half-up
    assert from_minor(12345678) == Decimal("123456.78")
    assert format_inr(12345678) == "₹1,23,456.78"
    assert format_inr(-50000) == "-₹500.00"
    assert format_inr(10000000000) == "₹10,00,00,000.00"


@pytest.mark.parametrize("raw,expected", [
    ("05/04/2026", date(2026, 4, 5)),
    ("05-04-26", date(2026, 4, 5)),
    ("05 Apr 2026", date(2026, 4, 5)),
    ("05-Apr-2026", date(2026, 4, 5)),
    ("2026-04-05", date(2026, 4, 5)),
    ("05.04.2026", date(2026, 4, 5)),
])
def test_parse_date_day_first(raw, expected):
    assert parse_date(raw) == expected


def test_parse_date_never_month_first():
    # 13/04 is unambiguous day-first; 04/13 must fail rather than be guessed.
    assert parse_date("13/04/2026") == date(2026, 4, 13)
    with pytest.raises(DateParseError):
        parse_date("04/13/2026")

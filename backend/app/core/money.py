"""Decimal-safe money helpers. Amounts are integer minor units (paise for INR)."""

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

MINOR_UNITS = {"INR": 2, "USD": 2, "EUR": 2, "GBP": 2, "JPY": 0}


class MoneyParseError(ValueError):
    pass


def minor_factor(currency: str = "INR") -> int:
    return 10 ** MINOR_UNITS.get(currency.upper(), 2)


def to_minor(value: Decimal | int | str, currency: str = "INR") -> int:
    """Convert a major-unit Decimal to integer minor units, rounding half-up."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int((d * minor_factor(currency)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def from_minor(minor: int, currency: str = "INR") -> Decimal:
    places = MINOR_UNITS.get(currency.upper(), 2)
    return (Decimal(minor) / minor_factor(currency)).quantize(Decimal(1).scaleb(-places))


_CURRENCY_TOKENS = re.compile(r"(₹|rs\.?|inr|usd|\$|€|£)", re.IGNORECASE)


def parse_amount(raw) -> tuple[Decimal | None, str | None]:
    """Parse a statement amount string.

    Returns (absolute-or-signed Decimal, explicit_direction) where explicit_direction is
    "DR"/"CR" when the text carried a Dr/Cr marker, else None. Handles Indian digit grouping
    (1,23,456.78), parentheses negatives, trailing minus, currency symbols. Empty -> (None, None).
    Raises MoneyParseError for text that is not a number.
    """
    if raw is None:
        return None, None
    if isinstance(raw, (int, Decimal)):
        return Decimal(raw), None
    if isinstance(raw, float):
        if raw != raw:  # NaN from pandas
            return None, None
        # Spreadsheet floats: round-trip via repr to avoid binary artefacts
        return Decimal(repr(raw)).quantize(Decimal("0.0001")).normalize(), None
    s = str(raw).strip()
    if s in ("", "-", "--", "nan", "NaN", "None"):
        return None, None
    direction = None
    m = re.search(r"(?<![a-z])(dr|cr)\.?\s*$", s, re.IGNORECASE)
    if m:
        direction = m.group(1).upper()
        s = s[: m.start()].strip()
    else:
        m = re.match(r"^(dr|cr)\.?\s+", s, re.IGNORECASE)
        if m:
            direction = m.group(1).upper()
            s = s[m.end():].strip()
    s = _CURRENCY_TOKENS.sub("", s).replace(",", "").replace(" ", "").replace(" ", "")
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    if s.endswith("-"):
        negative, s = True, s[:-1]
    if s.startswith("+"):
        s = s[1:]
    if s.startswith("-"):
        negative, s = True, s[1:]
    if not re.fullmatch(r"\d+(\.\d+)?|\.\d+", s):
        raise MoneyParseError(f"Not a valid amount: {raw!r}")
    try:
        d = Decimal(s)
    except InvalidOperation as e:  # pragma: no cover - regex guards this
        raise MoneyParseError(f"Not a valid amount: {raw!r}") from e
    return (-d if negative else d), direction


def format_inr(minor: int) -> str:
    """Format paise as ₹ with Indian digit grouping, e.g. 12345678 -> ₹1,23,456.78."""
    neg = minor < 0
    d = from_minor(abs(minor))
    whole, frac = f"{d:.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{'-' if neg else ''}₹{whole}.{frac}"

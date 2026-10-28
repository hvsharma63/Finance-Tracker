"""Statement date parsing. Indian statements are day-first; we never guess month-first."""

import re
from datetime import date, datetime

_FORMATS = [
    "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d-%m-%y", "%d.%m.%Y", "%d.%m.%y",
    "%d %b %Y", "%d %b %y", "%d-%b-%Y", "%d-%b-%y", "%d/%b/%Y", "%d/%b/%y",
    "%d %B %Y", "%d-%B-%Y", "%d %b, %Y", "%b %d, %Y", "%d%b%Y", "%d%b%y",
    "%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M",
    "%d-%m-%Y %H:%M:%S", "%d-%b-%Y %H:%M:%S",
]


class DateParseError(ValueError):
    pass


def parse_date(raw, formats: list[str] | None = None) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if hasattr(raw, "to_pydatetime"):  # pandas Timestamp
        if str(raw) == "NaT":
            return None
        return raw.to_pydatetime().date()
    s = re.sub(r"\s+", " ", str(raw).strip())
    if s in ("", "nan", "NaT", "None"):
        return None
    for fmt in formats or _FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise DateParseError(f"Unrecognised date: {raw!r}")


def looks_like_date(raw) -> bool:
    try:
        return parse_date(raw) is not None
    except DateParseError:
        return False

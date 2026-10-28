"""Coordinate-based row building shared by institution-specific PDF parsers.

A statement table is described by a LayoutSpec: where dates, narrations and amounts sit
horizontally, where the table starts/ends, and whether wrapped narration lines sit below the
dated line ("top", e.g. Axis) or are vertically centred around it ("center", e.g. IDFC).
The engine returns AnchorRows (one per dated line) with the raw words of each amount column,
so each parser applies its own sign rules (Dr/Cr suffix, separate columns, text colour).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from app.core.dates import DateParseError, parse_date
from app.services.imports.candidates import ExtractedPage, Word
from app.services.imports.layout import group_lines, is_amount, merge_amount_suffixes
from app.services.imports.normalization import clean_text, join_continuation


@dataclass
class LayoutSpec:
    date_x: tuple[float, float]  # x-range in which the first date token starts
    desc_x: tuple[float, float]  # x-range for narration words
    amount_cols: dict[str, tuple[float, float]]  # name -> x-range containing the amount's right edge
    extra_cols: dict[str, tuple[float, float]] = field(default_factory=dict)  # other text columns
    date_formats: list[str] | None = None
    max_date_tokens: int = 3
    align: str = "top"  # top | center
    start: re.Pattern | None = None  # line that opens the transaction region (excluded)
    stop: re.Pattern | None = None  # line that closes it for the rest of the document
    page_end: re.Pattern | None = None  # line that closes the region on this page only
    skip: re.Pattern | None = None  # lines inside the region that are never narration
    skip_bold: bool = False  # bold lines are headings, not narration
    region_x: tuple[float, float] | None = None  # only words inside this x-range are considered
    restart_each_page: bool = True  # require the start marker again on every page
    max_gap: float = 30.0  # max vertical distance between a wrapped line and its row (top align)


@dataclass
class AnchorRow:
    page: int
    line_no: int
    top: float
    bottom: float
    txn_date: date
    desc_parts: list[tuple[float, str]] = field(default_factory=list)  # (top, text)
    amounts: dict[str, list[Word]] = field(default_factory=dict)
    extra: dict[str, list[str]] = field(default_factory=dict)
    line_text: str = ""

    @property
    def description(self) -> str:
        out = ""
        for _, t in sorted(self.desc_parts, key=lambda p: p[0]):
            out = join_continuation(out, t)
        return clean_text(out)

    @property
    def source_ref(self) -> str:
        return f"page:{self.page}:line:{self.line_no}"


@dataclass
class LayoutOutput:
    rows: list[AnchorRow] = field(default_factory=list)
    ignored: list[dict] = field(default_factory=list)
    region_lines: list[tuple[int, str]] = field(default_factory=list)


def _inside(x: float, rng: tuple[float, float]) -> bool:
    return rng[0] <= x <= rng[1]


def _leading_date(words: list[Word], spec: LayoutSpec) -> tuple[date | None, int]:
    if not words or not _inside(words[0].x0, spec.date_x):
        return None, 0
    for n in range(min(spec.max_date_tokens, len(words)), 0, -1):
        txt = " ".join(w.text for w in words[:n])
        try:
            d = parse_date(txt, spec.date_formats)
        except DateParseError:
            continue
        if d:
            return d, n
    return None, 0


def build_rows(pages: list[ExtractedPage], spec: LayoutSpec,
               line_filter: Callable[[str], bool] | None = None) -> LayoutOutput:
    out = LayoutOutput()
    active = spec.start is None
    stopped = False
    for page in pages:
        if stopped:
            break
        if spec.restart_each_page and spec.start is not None:
            active = False
        words = [w for w in page.words if spec.region_x is None or _inside(w.x0, spec.region_x)]
        lines = [merge_amount_suffixes(ln) for ln in group_lines(words)]
        page_rows: list[AnchorRow] = []
        pending: list[tuple[float, float, str, int]] = []  # (top, bottom, text, line_no) for center align
        for i, line in enumerate(lines, start=1):
            text = clean_text(" ".join(w.text for w in line))
            if not active:
                if spec.start is not None and spec.start.search(text):
                    active = True
                continue
            if spec.stop is not None and spec.stop.search(text):
                stopped = True
                break
            if spec.page_end is not None and spec.page_end.search(text):
                break
            if line_filter is not None and not line_filter(text):
                continue
            out.region_lines.append((page.number, text))
            d, n = _leading_date(line, spec)
            if d is None:
                if (spec.skip is not None and spec.skip.search(text)) or (spec.skip_bold and all(w.is_bold for w in line)):
                    out.ignored.append({"ref": f"page:{page.number}:line:{i}", "text": text[:200], "reason": "heading"})
                    continue
                desc = " ".join(w.text for w in line if _inside(w.x0, spec.desc_x))
                if not desc:
                    out.ignored.append({"ref": f"page:{page.number}:line:{i}", "text": text[:200], "reason": "no date"})
                    continue
                top = min(w.top for w in line)
                if spec.align == "top":
                    prev = page_rows[-1] if page_rows else None
                    if prev is not None and top - prev.bottom <= spec.max_gap:
                        prev.desc_parts.append((top, desc))
                        prev.bottom = max(w.bottom for w in line)
                    else:
                        out.ignored.append({"ref": f"page:{page.number}:line:{i}", "text": text[:200], "reason": "no date"})
                else:
                    pending.append((top, max(w.bottom for w in line), desc, i))
                continue
            row = AnchorRow(page=page.number, line_no=i, top=min(w.top for w in line),
                            bottom=max(w.bottom for w in line), txn_date=d, line_text=text)
            own_desc: list[str] = []
            for w in line[n:]:
                if is_amount(w.text):
                    col = next((name for name, rng in spec.amount_cols.items() if _inside(w.x1, rng)), None)
                    if col is not None:
                        row.amounts.setdefault(col, []).append(w)
                        continue
                ext = next((name for name, rng in spec.extra_cols.items() if _inside(w.x0, rng)), None)
                if ext is not None:
                    row.extra.setdefault(ext, []).append(w.text)
                elif _inside(w.x0, spec.desc_x):
                    own_desc.append(w.text)
            if own_desc:
                row.desc_parts.append((row.top, " ".join(own_desc)))
            page_rows.append(row)
        if spec.align == "center" and page_rows:
            for top, bottom, desc, i in pending:
                # nearest by vertical edge gap: a wrapped line belongs to the row it touches
                def gap(r, top=top, bottom=bottom):
                    return max(r.top - bottom, top - r.bottom, 0)
                nearest = min(page_rows, key=gap)
                if gap(nearest) <= spec.max_gap:
                    nearest.desc_parts.append((top, desc))
                else:
                    out.ignored.append({"ref": f"page:{page.number}:line:{i}", "text": desc[:200], "reason": "unassigned narration"})
        out.rows.extend(page_rows)
    return out


def header_positions(pages: list[ExtractedPage], labels: list[str]) -> dict[str, Word] | None:
    """Find the first line containing all labels (single words); return label -> word."""
    for page in pages:
        for line in group_lines(page.words):
            found = {}
            for w in line:
                for lab in labels:
                    if lab not in found and w.text.lower() == lab.lower():
                        found[lab] = w
            if len(found) == len(labels):
                return found
    return None


def first_match(pattern: str, text: str, flags=re.I) -> re.Match | None:
    return re.search(pattern, text, flags)

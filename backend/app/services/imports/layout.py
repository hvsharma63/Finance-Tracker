"""Helpers for positional (word-coordinate) parsing of PDF and OCR text."""

from __future__ import annotations

import re

from app.services.imports.candidates import Word

AMOUNT_TOKEN = re.compile(r"^\(?-?(₹|Rs\.?|INR)?\s?\d{1,3}(,\d{2,3})*(\.\d{1,2})?\)?(\s?(Dr|Cr|DR|CR)\.?)?-?$|^\(?-?\d+\.\d{1,2}\)?(Dr|Cr|DR|CR)?$")
DRCR_TOKEN = re.compile(r"^(Dr|Cr|DR|CR)\.?$")


def group_lines(words: list[Word], tolerance: float = 3.0) -> list[list[Word]]:
    """Group words into visual lines by vertical position, each line sorted left to right."""
    lines: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (round(w.top), w.x0)):
        if lines and abs(lines[-1][0].top - w.top) <= tolerance:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(line, key=lambda w: w.x0) for line in lines]


def merge_amount_suffixes(line: list[Word]) -> list[Word]:
    """Join an amount with a following standalone Dr/Cr token: ['1,000.00','Dr'] -> ['1,000.00 Dr']."""
    out: list[Word] = []
    for w in line:
        if out and DRCR_TOKEN.match(w.text) and AMOUNT_TOKEN.match(out[-1].text) and w.x0 - out[-1].x1 < 12:
            prev = out[-1]
            out[-1] = Word(f"{prev.text} {w.text}", prev.x0, w.x1, prev.top, max(prev.bottom, w.bottom))
        else:
            out.append(w)
    return out


def is_amount(text: str) -> bool:
    return bool(AMOUNT_TOKEN.match(text.strip()))

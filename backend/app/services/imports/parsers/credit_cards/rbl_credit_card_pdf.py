"""RBL Bank credit card statement (PDF). Covers IRCTC RBL and BookMyShow Play (same layout).

Layout (tested Oct 2026): two-column first page. Left column: ACCOUNT SUMMARY (Total Amount Due,
Last Bill Amount, - Payments & Credits, + New Debits, - Transferred to EMI, + Monthly EMI Debits,
+ Fees & Charges, + Goods & Services Tax, Statement Period dd-mm-yyyy to dd-mm-yyyy). Right
column: "Date | Description | Amount" with dates "28 Sep 2026".

IMPORTANT: amounts carry no Dr/Cr text. Credits (payments, refunds) are printed in GREEN; debits
in black. Direction is therefore read from the amount's fill colour and cross-checked against the
summary's "Payments & Credits" total. "Total Amount Due" is rounded up to the rupee, so the exact
closing balance is computed from the summary components.
"""

from __future__ import annotations

import re
from decimal import Decimal

from app.core.money import parse_amount
from app.services.imports.candidates import ExtractedDocument, ParsedStatement, ParseOptions, Word
from app.services.imports.layout import group_lines
from app.services.imports.parser_registry import StatementParser, register
from app.services.imports.parsers.helpers import AMT, candidate, cross_check, dec, find_dates
from app.services.imports.parsers.layout_engine import LayoutSpec, build_rows
from app.services.imports.table_mapping import header_signature

CREDIT_WORDS = re.compile(r"PAYMENT RECEIVED|REFUND|REVERSAL|CASHBACK|CREDIT ADJ", re.I)


def colour_kind(w: Word) -> str:
    """'credit' for green text, 'debit' for black/grey, 'unknown' otherwise."""
    c = [float(x) for x in (w.color or ())]
    if len(c) == 1 or (len(c) == 3 and max(c) - min(c) < 0.1):
        return "debit" if (c[0] if len(c) == 1 else sum(c) / 3) < 0.5 else "unknown"
    if len(c) == 3:
        r, g, b = c
        if g > r + 0.25 and g > b + 0.25:
            return "credit"
    if len(c) == 4:  # CMYK: green = high cyan + yellow, low magenta
        cy, m, y, k = c
        if cy > 0.5 and y > 0.5 and m < 0.3 and k < 0.6:
            return "credit"
        if k > 0.6 and cy < 0.3 and m < 0.3 and y < 0.3:
            return "debit"
    return "unknown"


def _header(doc: ExtractedDocument):
    for page in doc.pages:
        for line in group_lines(page.words):
            t = [w.text for w in line]
            if "Date" in t and "Description" in t and "Amount" in t:
                return {w.text: w for w in line if w.text in ("Date", "Description", "Amount")}, page.width
    return None, 0


def _summary(text: str, label: str) -> Decimal | None:
    m = re.search(rf"{label}\s+(?:PAY NOW\s+)?({AMT})", text)
    return dec(m.group(1)) if m else None


@register
class RblCreditCardPdf(StatementParser):
    name = "rbl_credit_card_pdf"
    version = "1.0"
    institution = "RBL Bank"
    statement_type = "credit_card"
    file_types = frozenset({"pdf"})
    description = "RBL Bank credit card PDF statement (IRCTC RBL, BookMyShow Play and same-layout cards)"
    tested_variants = ("IRCTC RBL, Oct 2026", "BookMyShow Play, Oct 2026")

    def detect(self, doc: ExtractedDocument) -> float:
        t = doc.text
        if "ACCOUNT SUMMARY (IN INR)" in t and "Last Bill Amount" in t and "rbl" in t.lower():
            return 0.95
        return 0.0

    def parse(self, doc: ExtractedDocument, options: ParseOptions) -> ParsedStatement:
        ps = ParsedStatement(parser_name=self.name, parser_version=self.version, statement_type="credit_card",
                             institution=self.institution)
        h, width = _header(doc)
        if h is None:
            ps.needs_mapping = True
            ps.warnings.append("RBL transaction header not found: the layout may have changed.")
            return ps
        spec = LayoutSpec(
            region_x=(h["Date"].x0 - 12, 10_000),
            date_x=(h["Date"].x0 - 12, h["Description"].x0 - 3),
            desc_x=(h["Description"].x0 - 3, h["Amount"].x0 - 25),
            amount_cols={"amount": (h["Amount"].x0 - 25, 10_000)},
            date_formats=["%d %b %Y"], max_date_tokens=3, align="top", max_gap=5,
            start=re.compile(r"^Date Description Amount"),
            page_end=re.compile(r"Get \d+% OFF|YOUR SPENDING|Look Out for|Scan and pay|Make payment"),
            skip=re.compile(r"^Eligible for EMI$"),
        )
        out = build_rows(doc.pages, spec)
        debits = credits = Decimal(0)
        idx = 0
        for a in out.rows:
            errors, warnings, amount = [], [], None
            toks = a.amounts.get("amount", [])
            if len(toks) != 1:
                errors.append(f"Expected one amount, found {[t.text for t in toks]}")
            else:
                v, marker = parse_amount(toks[0].text)
                if v == 0:
                    ps.ignored_lines.append({"ref": a.source_ref, "text": a.line_text[:200], "reason": "zero-amount row"})
                    continue
                kind = {"CR": "credit", "DR": "debit"}.get(marker or "", colour_kind(toks[0]))
                if kind == "credit":
                    amount, credits = abs(v), credits + abs(v)
                elif kind == "debit":
                    amount, debits = -abs(v), debits + abs(v)
                    if CREDIT_WORDS.search(a.description):
                        warnings.append("Printed as a debit but the description looks like a credit — verify")
                else:
                    errors.append(f"Cannot tell debit from credit (amount colour {toks[0].color})")
            ps.rows.append(candidate(idx, a, amount, errors=errors, warnings=warnings,
                                     raw={"amount_colour": str(toks[0].color) if toks else ""}))
            idx += 1
        ps.ignored_lines = out.ignored + ps.ignored_lines
        text = doc.text
        ps.period_start, ps.period_end = find_dates(r"Statement Period\s+(\d\d-\d\d-\d{4})\s+to\s+(\d\d-\d\d-\d{4})", text, ["%d-%m-%Y"])
        m = re.search(r"Card Number\s+X+(\d{2,4})\b", text)
        ps.account_hint = f"XX{m.group(1)}" if m else None
        last = _summary(text, "Last Bill Amount")
        pay = _summary(text, r"- Payments & Credits")
        new = _summary(text, r"\+ New Debits")
        to_emi = _summary(text, r"- Transferred to EMI") or Decimal(0)
        emi = _summary(text, r"\+ Monthly EMI Debits") or Decimal(0)
        fees = _summary(text, r"\+ Fees & Charges") or Decimal(0)
        gst = _summary(text, r"\+ Goods & Services Tax") or Decimal(0)
        total_due = _summary(text, "Total Amount Due")
        if last is not None and pay is not None and new is not None:
            ps.opening_balance = -last
            owed = last - pay + new - to_emi + emi + fees + gst
            ps.closing_balance = -owed
            if total_due is not None and total_due != owed:
                ps.warnings.append(f"Total Amount Due {total_due} is the rounded figure; the exact outstanding "
                                   f"from the summary components is {owed}.")
            cross_check(ps, "Payments & credits (green amounts)", pay, credits)
            cross_check(ps, "New debits + EMI + fees + GST", new + emi + fees + gst, debits)
            if to_emi:
                ps.warnings.append(f"{to_emi} was transferred to EMI this cycle; check the EMI rows.")
        else:
            ps.warnings.append("Account summary not found; opening/closing balances unknown.")
        ps.header_columns = ["Date", "Description", "Amount"]
        ps.layout_signature = header_signature(["rbl_cc", *ps.header_columns])
        return ps

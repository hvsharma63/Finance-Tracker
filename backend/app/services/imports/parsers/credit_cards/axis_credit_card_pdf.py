"""Axis Bank credit card statement (PDF). Covers Visa Privilege and Neo RuPay (same layout).

Layout (tested Oct 2026): PAYMENT SUMMARY with Statement Period "dd/mm/yyyy - dd/mm/yyyy";
summary line "Previous Balance - Payments - Credits + Purchase + Cash Advance + Other Debit&Charges
= Total Payment Due"; table "DATE | TRANSACTION DETAILS | MERCHANT CATEGORY | AMOUNT (Rs.)" with
"Dr"/"Cr" suffixes; table ends at "**** End of Statement ****". Page 2 holds an illustrative
charges table that must not be read as transactions.
"""

from __future__ import annotations

import re
from decimal import Decimal

from app.core.money import parse_amount
from app.services.imports.candidates import ExtractedDocument, ParsedStatement, ParseOptions
from app.services.imports.layout import group_lines
from app.services.imports.parser_registry import StatementParser, register
from app.services.imports.parsers.helpers import AMT, candidate, card_balance, cross_check, find_dates
from app.services.imports.parsers.layout_engine import LayoutSpec, build_rows
from app.services.imports.table_mapping import header_signature

SUMMARY = re.compile(
    rf"Previous Balance - Payments - Credits \+ Purchase.*?\n.*?({AMT})\s*(Dr|Cr)?\s+({AMT})\s+({AMT})\s+({AMT})\s+"
    rf"({AMT})\s+({AMT})\s+({AMT})\s*(Dr|Cr)?", re.S)


def _header(doc: ExtractedDocument):
    for page in doc.pages:
        for line in group_lines(page.words):
            texts = [w.text for w in line]
            if "DATE" in texts and "MERCHANT" in texts and "AMOUNT" in texts and "TRANSACTION" in texts:
                return {w.text: w for w in line}
    return None


@register
class AxisCreditCardPdf(StatementParser):
    name = "axis_credit_card_pdf"
    version = "1.0"
    institution = "Axis Bank"
    statement_type = "credit_card"
    file_types = frozenset({"pdf"})
    description = "Axis Bank credit card PDF statement (Visa Privilege, Neo RuPay and same-layout cards)"
    tested_variants = ("Visa Privilege, Oct 2026", "Neo RuPay, Oct 2026")

    def detect(self, doc: ExtractedDocument) -> float:
        t = doc.text
        if "PAYMENT SUMMARY" in t and "MERCHANT CATEGORY" in t and "End of Statement" in t and \
                ("Axis Bank" in t or "axis.bank.in" in t):
            return 0.95
        return 0.0

    def parse(self, doc: ExtractedDocument, options: ParseOptions) -> ParsedStatement:
        ps = ParsedStatement(parser_name=self.name, parser_version=self.version, statement_type="credit_card",
                             institution=self.institution)
        h = _header(doc)
        if h is None:
            ps.needs_mapping = True
            ps.warnings.append("Axis card transaction header not found: the layout may have changed.")
            return ps
        # Header labels are centred over their columns, so split at midpoints between labels.
        desc_cat = (h["DETAILS"].x1 + h["MERCHANT"].x0) / 2
        spec = LayoutSpec(
            date_x=(0, h["DATE"].x1 + 15),
            desc_x=(h["DATE"].x1 + 15, desc_cat),
            extra_cols={"merchant_category": (desc_cat, h["AMOUNT"].x0 - 40)},
            amount_cols={"amount": (h["AMOUNT"].x0 - 40, 10_000)},
            date_formats=["%d/%m/%Y"], max_date_tokens=1, align="top", max_gap=6,
            start=re.compile(r"^DATE TRANSACTION DETAILS MERCHANT CATEGORY"),
            stop=re.compile(r"\*+\s*End of Statement"), skip=re.compile(r"^Card No:"),
            restart_each_page=False,
        )
        out = build_rows(doc.pages, spec)
        debits = credits = Decimal(0)
        for i, a in enumerate(out.rows):
            errors, amount = [], None
            toks = a.amounts.get("amount", [])
            if len(toks) != 1:
                errors.append(f"Expected one amount, found {[t.text for t in toks]}")
            else:
                v, marker = parse_amount(toks[0].text)
                if marker == "DR":
                    amount = -abs(v)
                    debits += abs(v)
                elif marker == "CR":
                    amount = abs(v)
                    credits += abs(v)
                else:
                    errors.append(f"Amount {toks[0].text!r} has no Dr/Cr marker")
            cat = " ".join(a.extra.get("merchant_category", [])) or None
            ps.rows.append(candidate(i, a, amount, errors=errors, raw={"merchant_category": cat or ""}))
        ps.ignored_lines = out.ignored
        text = doc.text
        ps.period_start, ps.period_end = find_dates(r"(\d\d/\d\d/\d{4})\s*-\s*(\d\d/\d\d/\d{4})", text, ["%d/%m/%Y"])
        m = re.search(r"Card No:\s*\d{4,6}\*+(\d{4})", text) or re.search(r"\b\d{6}\*{6}(\d{4})\b", text)
        ps.account_hint = f"XX{m.group(1)}" if m else None
        s = SUMMARY.search(text)
        if s:
            prev, prev_m = Decimal(s.group(1).replace(",", "")), s.group(2)
            pay, cred, purch, cash, other = (Decimal(s.group(k).replace(",", "")) for k in (3, 4, 5, 6, 7))
            total, total_m = Decimal(s.group(8).replace(",", "")), s.group(9)
            ps.opening_balance = card_balance(prev, prev_m, ps, "Previous balance")
            ps.closing_balance = card_balance(total, total_m, ps, "Total payment due")
            cross_check(ps, "Purchases + cash advance + other charges", purch + cash + other, debits)
            cross_check(ps, "Payments + credits", pay + cred, credits)
        else:
            ps.warnings.append("Statement summary line not found; opening/closing balances unknown.")
        ps.header_columns = ["DATE", "TRANSACTION DETAILS", "MERCHANT CATEGORY", "AMOUNT (Rs.)"]
        ps.layout_signature = header_signature(["axis_cc", *ps.header_columns])
        return ps

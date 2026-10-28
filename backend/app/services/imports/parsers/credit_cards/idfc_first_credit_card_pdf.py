"""IDFC FIRST Bank credit card statement (PDF).

Layout (tested Oct 2026, FIRST Select): page 1 summary (Opening Balance, Purchases, EMI & Other
Debits, Payments & Refunds, Total Amount Due), "YOUR TRANSACTIONS" on page 2 with
"Transaction Date | Transaction Details | EMI Eligibility | FX Transactions | Amount (In INR)".
Dates "14 Oct 26"; amounts end in DR/CR; narrations are vertically centred, so wrapped lines sit
above and below the dated line; bold red section headings ("Purchases, EMIs & Other Debits").
The rupee sign is extracted as the letter "r" in summary figures.
"""

from __future__ import annotations

import re
from decimal import Decimal

from app.core.money import parse_amount
from app.services.imports.candidates import ExtractedDocument, ParsedStatement, ParseOptions
from app.services.imports.layout import group_lines
from app.services.imports.parser_registry import StatementParser, register
from app.services.imports.parsers.helpers import AMT, candidate, card_balance, cross_check, dec, find_dates
from app.services.imports.parsers.layout_engine import LayoutSpec, build_rows
from app.services.imports.table_mapping import header_signature

R = r"(?:r|₹|Rs\.?)?\s?"


def _header(doc: ExtractedDocument):
    for page in doc.pages:
        for line in group_lines(page.words):
            t = [w.text for w in line]
            if "Details" in t and "Amount" in t and "EMI" in t:
                details = next(w for w in line if w.text == "Details")
                trans = [w for w in line if w.text == "Transaction"]
                desc_word = max((w for w in trans if w.x1 < details.x0 + 1), key=lambda w: w.x0, default=details)
                return {"desc": desc_word, "emi": next(w for w in line if w.text == "EMI"),
                        "amount": next(w for w in line if w.text == "Amount"), "date": min(trans, key=lambda w: w.x0)}
    return None


@register
class IdfcFirstCreditCardPdf(StatementParser):
    name = "idfc_first_credit_card_pdf"
    version = "1.0"
    institution = "IDFC FIRST Bank"
    statement_type = "credit_card"
    file_types = frozenset({"pdf"})
    description = "IDFC FIRST Bank credit card PDF statement"
    tested_variants = ("FIRST Select, Oct 2026",)

    def detect(self, doc: ExtractedDocument) -> float:
        t = doc.text
        if "YOUR TRANSACTIONS" in t and "Credit Card Statement" in t and ("IDFC FIRST" in t or "idfcbank" in t):
            return 0.95
        return 0.0

    def parse(self, doc: ExtractedDocument, options: ParseOptions) -> ParsedStatement:
        ps = ParsedStatement(parser_name=self.name, parser_version=self.version, statement_type="credit_card",
                             institution=self.institution)
        h = _header(doc)
        if h is None:
            ps.needs_mapping = True
            ps.warnings.append("IDFC transaction header not found: the layout may have changed.")
            return ps
        spec = LayoutSpec(
            date_x=(0, h["desc"].x0 - 10),
            desc_x=(h["desc"].x0 - 10, h["emi"].x0 - 3),
            amount_cols={"amount": (h["amount"].x0 - 40, 10_000)},
            date_formats=["%d %b %y"], max_date_tokens=3, align="center", max_gap=14,
            start=re.compile(r"^YOUR TRANSACTIONS"),
            stop=re.compile(r"^ACTIVE EMI DETAILS|^REWARD POINTS|^SPECIAL BENEFITS|^Refer this Credit Card"),
            skip=re.compile(r"^(Transaction Transaction|Date Eligibility|Card Number:|Purchases, EMIs|Payments & Other Credits)"),
            skip_bold=True, restart_each_page=False,
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
                    amount, debits = -abs(v), debits + abs(v)
                elif marker == "CR":
                    amount, credits = abs(v), credits + abs(v)
                else:
                    errors.append(f"Amount {toks[0].text!r} has no DR/CR marker")
            ps.rows.append(candidate(i, a, amount, errors=errors))
        ps.ignored_lines = out.ignored
        text = doc.text
        ps.period_start, ps.period_end = find_dates(r"(\d\d/[A-Za-z]{3}/\d{4})\s*-\s*(\d\d/[A-Za-z]{3}/\d{4})", text, ["%d/%b/%Y"])
        m = re.search(r"\bXX(\d{4})\)", text) or re.search(r"Card Number:\s*X+\s*(\d{4})", text)
        ps.account_hint = f"XX{m.group(1)}" if m else None
        opening = re.search(rf"Opening Balance\s+{R}({AMT})\s*(DR|CR)?", text)
        total = re.search(rf"Total Amount Due\s*=\s*{R}({AMT})\s*(DR|CR)?", text)
        if opening:
            ps.opening_balance = card_balance(dec(opening.group(1)), opening.group(2) or "DR", ps, "Opening balance")
        if total:
            ps.closing_balance = card_balance(dec(total.group(1)), total.group(2), ps, "Total amount due")
        purchases = re.search(rf"Purchases\s*\+\s*{R}({AMT})", text)
        other = re.search(rf"EMI & Other Debits\s*\+\s*{R}({AMT})", text)
        payments = re.search(rf"Payments & Refunds\s*-\s*{R}({AMT})", text)
        if purchases and other:
            cross_check(ps, "Purchases + EMI & other debits", dec(purchases.group(1)) + dec(other.group(1)), debits)
        if payments:
            cross_check(ps, "Payments & refunds", dec(payments.group(1)), credits)
        if not (opening and total):
            ps.warnings.append("Opening balance or total amount due not found in the summary.")
        ps.header_columns = ["Transaction Date", "Transaction Details", "EMI Eligibility", "FX Transactions", "Amount (In INR)"]
        ps.layout_signature = header_signature(["idfc_cc", *ps.header_columns])
        return ps

"""Axis Bank savings account e-statement (PDF).

Layout (tested Sept 2026): "Detailed Statement for a/c no. XXXX between dd-mm-yyyy to dd-mm-yyyy",
table "Txn Date | Transaction Information | Withdrawals | Deposits | Balance" without ruling,
narrations wrap onto following lines, per-row balance usually blank, "Opening Balance" and
"Closing Balance" lines inside the table.
"""

from __future__ import annotations

import re

from app.services.imports.candidates import ExtractedDocument, ParsedStatement, ParseOptions
from app.services.imports.parser_registry import StatementParser, register
from app.services.imports.parsers.helpers import AMT, candidate, dec, find_amount, find_dates
from app.services.imports.parsers.layout_engine import LayoutSpec, build_rows, header_positions
from app.services.imports.table_mapping import header_signature


@register
class AxisSavingsPdf(StatementParser):
    name = "axis_savings_pdf"
    version = "1.0"
    institution = "Axis Bank"
    statement_type = "bank"
    file_types = frozenset({"pdf"})
    description = "Axis Bank savings account PDF e-statement"
    tested_variants = ("Savings e-statement, Sept 2026 layout (Txn Date | Transaction Information | Withdrawals | Deposits | Balance)",)

    def detect(self, doc: ExtractedDocument) -> float:
        t = doc.text
        markers = ["Detailed Statement for a/c no", "Txn Date", "Withdrawals", "Deposits", "Closing Balance"]
        if not all(m in t for m in markers):
            return 0.0
        return 0.95 if ("Axis Bank" in t or "UTIB" in t or "axis.bank.in" in t) else 0.5

    def parse(self, doc: ExtractedDocument, options: ParseOptions) -> ParsedStatement:
        ps = ParsedStatement(parser_name=self.name, parser_version=self.version, statement_type="bank",
                             institution=self.institution)
        hdr = header_positions(doc.pages, ["Txn", "Withdrawals", "Deposits", "Balance"])
        if hdr is None:
            ps.needs_mapping = True
            ps.warnings.append("Axis statement header not found: the layout may have changed. Use the generic parser.")
            return ps
        w, d, b = hdr["Withdrawals"], hdr["Deposits"], hdr["Balance"]
        wd_cut, db_cut = (w.x1 + d.x1) / 2, (d.x1 + b.x1) / 2
        spec = LayoutSpec(
            date_x=(0, hdr["Txn"].x0 + 15),
            desc_x=(hdr["Txn"].x1 + 5, w.x0 - 3),
            amount_cols={"withdrawal": (w.x0 - 80, wd_cut), "deposit": (wd_cut, db_cut), "balance": (db_cut, b.x1 + 80)},
            date_formats=["%d-%m-%Y"], max_date_tokens=1, align="top", max_gap=8,
            start=re.compile(r"\bTxn Date\b.*\bWithdrawals\b"), stop=re.compile(r"^Closing Balance\b"),
        )
        out = build_rows(doc.pages, spec)
        for i, a in enumerate(out.rows):
            errors = []
            wd = [x.text for x in a.amounts.get("withdrawal", [])]
            dp = [x.text for x in a.amounts.get("deposit", [])]
            if len(wd) + len(dp) != 1:
                errors.append(f"Expected exactly one withdrawal or deposit amount, found {wd + dp}")
                amount = None
            else:
                amount = -dec(wd[0]) if wd else dec(dp[0])
            bal = a.amounts.get("balance")
            ps.rows.append(candidate(i, a, amount, balance=dec(bal[-1].text) if bal else None, errors=errors))
        ps.ignored_lines = [x for x in out.ignored if not x["text"].startswith(("Information", "Other"))]
        text = doc.text
        ps.opening_balance = find_amount(rf"Opening Balance\s+({AMT})", text)
        ps.closing_balance = find_amount(rf"Closing Balance\s+({AMT})", text)
        ps.period_start, ps.period_end = find_dates(r"between\s+(\d\d-\d\d-\d{4})\s+to\s+(\d\d-\d\d-\d{4})", text, ["%d-%m-%Y"])
        m = re.search(r"a/c no\.?\s*(X*\d{3,})", text, re.I)
        ps.account_hint = m.group(1) if m else None
        ps.header_columns = ["Txn Date", "Transaction Information", "Withdrawals", "Deposits", "Balance"]
        ps.layout_signature = header_signature(["axis_savings", *ps.header_columns])
        if ps.opening_balance is None:
            ps.warnings.append("Opening balance line not found.")
        return ps

"""State Bank of India savings account statement (PDF, ruled tables).

Layout (tested Sept 2026 e-statement): "TRANSACTION OVERVIEW" tables with header
"Date | Transaction Reference | Ref.No./Chq.No. | Credit | Debit | Balance", dates dd-mm-yy,
empty amounts printed as "0", a (garbled) "Your Opening Balance on dd-mm-yy: X" first row and a
"Your Closing Balance on dd-mm-yy: X" last row. The header repeats on each page.
"""

from __future__ import annotations

import re

from app.core.dates import DateParseError, parse_date
from app.services.imports.candidates import CandidateRow, ExtractedDocument, ParsedStatement, ParseOptions
from app.services.imports.normalization import clean_text, detect_transaction_type, extract_reference, join_continuation
from app.services.imports.parser_registry import StatementParser, register
from app.services.imports.parsers.helpers import dec
from app.services.imports.table_mapping import header_signature, norm_header

NUM = re.compile(r"^-?\d[\d,]*\.\d{2}$")


def _find_cols(row: list) -> dict[str, int] | None:
    names = [norm_header(c) for c in row]
    want = {"date": "date", "transaction reference": "desc", "ref no chq no": "ref", "credit": "credit",
            "debit": "debit", "balance": "balance"}
    cols = {want[n]: i for i, n in enumerate(names) if n in want}
    return cols if {"date", "desc", "credit", "debit", "balance"} <= cols.keys() else None


@register
class SbiSavingsPdf(StatementParser):
    name = "sbi_savings_pdf"
    version = "1.0"
    institution = "State Bank of India"
    statement_type = "bank"
    file_types = frozenset({"pdf"})
    description = "SBI savings account PDF statement (Transaction Overview tables)"
    tested_variants = ("SBI e-statement, Sept 2026 layout (Date | Transaction Reference | Ref.No./Chq.No. | Credit | Debit | Balance)",)

    def detect(self, doc: ExtractedDocument) -> float:
        t = doc.text
        if "sbi.co.in" in t and "TRANSACTION OVERVIEW" in t and "Ref.No./Chq.No." in t:
            return 0.95
        return 0.0

    def parse(self, doc: ExtractedDocument, options: ParseOptions) -> ParsedStatement:
        ps = ParsedStatement(parser_name=self.name, parser_version=self.version, statement_type="bank",
                             institution=self.institution)
        idx = 0
        open_date = close_date = None
        found_header = False
        for table in doc.tables:
            cols = None
            for ri, row in enumerate(table.rows):
                cells = [clean_text(str(c)) if c is not None else "" for c in row]
                ref = f"{table.source}:row:{ri + 1}"
                hdr = _find_cols(row)
                if hdr:
                    cols, found_header = hdr, True
                    continue
                if cols is None:
                    continue
                joined = " ".join(c for c in cells if c)
                nums = [c for c in cells if NUM.match(c.replace(",", ""))]
                compact = re.sub(r"\s+", "", joined).lower()  # label may be split across cells
                if "closingbalanceon" in compact:
                    m = re.search(r"on (\d\d-\d\d-\d\d)", joined)
                    close_date = m.group(1) if m else close_date
                    ps.closing_balance = dec(nums[0]) if nums else None
                    ps.ignored_lines.append({"ref": ref, "text": joined[:200], "reason": "closing balance"})
                    continue
                date_txt = cells[cols["date"]] if cols["date"] < len(cells) else ""
                try:
                    d = parse_date(date_txt, ["%d-%m-%y"])
                except DateParseError:
                    d = None
                if d is None:
                    # "Your Opening Balance on dd-mm-yy: X" — the label text is garbled in the PDF
                    # ("Yourn Oupllening nBualllance"), so match its stable tail instead.
                    m = re.search(r"\bon (\d\d-\d\d-\d\d):", joined)
                    if m and nums and ps.opening_balance is None and not ps.rows:
                        open_date = m.group(1)
                        ps.opening_balance = dec(nums[0])
                        ps.ignored_lines.append({"ref": ref, "text": joined[:200], "reason": "opening balance"})
                    else:
                        ps.ignored_lines.append({"ref": ref, "text": joined[:200], "reason": "no date"})
                    continue
                end = cols.get("ref", cols["credit"])
                desc = ""
                for c in row[cols["desc"]:end]:
                    for part in str(c or "").split("\n"):
                        desc = join_continuation(desc, part)
                desc = clean_text(desc)
                refno = cells[cols["ref"]] if "ref" in cols else ""
                refno = None if refno in ("", "-", "null") else refno
                credit, debit = dec(cells[cols["credit"]]), dec(cells[cols["debit"]])
                credit = credit if credit else None
                debit = debit if debit else None
                errors = []
                if credit and debit:
                    errors.append("Row has both a credit and a debit amount")
                    amount = None
                elif credit is None and debit is None:
                    errors.append("No amount in credit or debit column")
                    amount = None
                else:
                    amount = credit if credit else -debit
                ps.rows.append(CandidateRow(
                    row_index=idx, source_ref=ref, txn_date=d, description=desc,
                    reference=refno or extract_reference(desc),
                    debit=debit, credit=credit, amount=amount, balance=dec(cells[cols["balance"]]),
                    transaction_type=detect_transaction_type(desc), errors=errors,
                    raw={"date": date_txt, "description": desc, "ref": refno or "", "credit": cells[cols["credit"]],
                         "debit": cells[cols["debit"]], "balance": cells[cols["balance"]]},
                ))
                idx += 1
        if not found_header:
            ps.needs_mapping = True
            ps.warnings.append("SBI transaction table header not found: the layout may have changed.")
        if open_date:
            ps.period_start = parse_date(open_date, ["%d-%m-%y"])
        if close_date:
            ps.period_end = parse_date(close_date, ["%d-%m-%y"])
        m = re.search(r"SAVING ACCOUNT\s+(X+\d{3,})", doc.text) or re.search(r"\b(X{4,}\d{4})\b", doc.text)
        ps.account_hint = m.group(1) if m else None
        ps.header_columns = ["Date", "Transaction Reference", "Ref.No./Chq.No.", "Credit", "Debit", "Balance"]
        ps.layout_signature = header_signature(["sbi_savings", *ps.header_columns])
        return ps

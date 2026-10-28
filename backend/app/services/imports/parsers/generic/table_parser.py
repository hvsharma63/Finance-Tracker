"""Generic CSV / Excel parser using header auto-detection or a user column mapping."""

from __future__ import annotations

from app.services.imports.candidates import ExtractedDocument, ParsedStatement, ParseOptions
from app.services.imports.parser_registry import StatementParser, register
from app.services.imports.parsers.generic.common import apply_text_metadata, guess_statement_type
from app.services.imports.table_mapping import (
    HeaderMatch,
    candidate_headers,
    find_header,
    header_signature,
    mapping_is_usable,
    parse_rows,
    resolve_mapping,
)


def parse_tabular(doc: ExtractedDocument, options: ParseOptions, name: str, version: str) -> ParsedStatement:
    stype = options.statement_type or guess_statement_type(doc)
    ps = ParsedStatement(parser_name=name, parser_version=version, statement_type=stype)
    ps.candidate_headers = [c["headers"] for c in candidate_headers(doc.tables)]
    header: HeaderMatch | None = None
    if options.column_mapping:
        ti = options.table_index or 0
        if options.header_row is not None and ti < len(doc.tables):
            hdrs = [str(c or "").strip() for c in doc.tables[ti].rows[options.header_row]]
            header = HeaderMatch(ti, options.header_row, hdrs, {}, 0)
        else:
            header = find_header(doc.tables)
            if header is None:
                # locate the header row containing the mapped column names
                wanted = {v for v in options.column_mapping.values() if v}
                for t_i, t in enumerate(doc.tables):
                    for r_i, row in enumerate(t.rows[:60]):
                        cells = {str(c or "").strip() for c in row}
                        if wanted <= cells:
                            header = HeaderMatch(t_i, r_i, [str(c or "").strip() for c in row], {}, 0)
                            break
                    if header:
                        break
        if header is None:
            ps.needs_mapping = True
            ps.warnings.append("Could not find a header row containing the mapped columns.")
            return ps
        mapping = resolve_mapping(header.headers, options.column_mapping)
    else:
        header = find_header(doc.tables)
        if header is None:
            ps.needs_mapping = True
            ps.warnings.append(
                "No transaction table header was recognised. Map the columns manually; the mapping can be saved."
            )
            return ps
        mapping = header.mapping
    if not mapping_is_usable(mapping):
        ps.needs_mapping = True
        ps.header_columns = header.headers
        ps.warnings.append("Column mapping needs date, description and either debit+credit or amount.")
        return ps
    sign_mode = options.sign_mode or ("inverted" if stype == "credit_card" and "amount" in mapping
                                      and "drcr" not in mapping else "signed")
    res = parse_rows(doc.tables, header, mapping, sign_mode=sign_mode, date_format=options.date_format)
    ps.rows = res.rows
    ps.opening_balance = res.opening_balance
    ps.closing_balance = res.closing_balance
    ps.ignored_lines = res.ignored_lines
    ps.warnings.extend(res.warnings)
    ps.header_columns = header.headers
    ps.mapping_used = {role: header.headers[i] for role, i in mapping.items()} | {"_sign_mode": sign_mode}
    ps.layout_signature = header_signature(header.headers)
    if stype == "credit_card" and "amount" in mapping and "drcr" not in mapping and not options.sign_mode:
        ps.warnings.append(
            "Credit-card file with a single amount column: assumed purchases are positive in the file "
            "(stored as money out). Verify a known purchase and a known payment."
        )
    apply_text_metadata(ps, doc)
    return ps


@register
class GenericTableParser(StatementParser):
    name = "generic_table"
    version = "1.0"
    statement_type = "bank"
    file_types = frozenset({"csv", "xlsx", "xls"})
    description = "Generic CSV/Excel import with header auto-detection and manual column mapping."
    is_generic = True

    def detect(self, doc: ExtractedDocument) -> float:
        return 0.2 if find_header(doc.tables) else 0.05

    def parse(self, doc: ExtractedDocument, options: ParseOptions) -> ParsedStatement:
        return parse_tabular(doc, options, self.name, self.version)

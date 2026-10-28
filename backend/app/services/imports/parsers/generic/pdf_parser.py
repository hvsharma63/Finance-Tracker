"""Generic digital/scanned PDF parser: ruled tables → positional columns → balance-delta fallback."""

from __future__ import annotations

from app.services.imports.candidates import ExtractedDocument, ParsedStatement, ParseOptions
from app.services.imports.parser_registry import StatementParser, register
from app.services.imports.parsers.generic.common import apply_text_metadata, guess_statement_type
from app.services.imports.parsers.generic.table_parser import parse_tabular
from app.services.imports.pdf_layout import parse_balance_delta, parse_pages
from app.services.imports.table_mapping import find_header, header_signature


@register
class GenericPdfParser(StatementParser):
    name = "generic_pdf"
    version = "1.0"
    statement_type = "bank"
    file_types = frozenset({"pdf"})
    description = (
        "Generic PDF extraction: ruled tables, then column positions from the header line, then "
        "running-balance inference. Uses local OCR for scanned PDFs when Tesseract is installed."
    )
    is_generic = True

    def detect(self, doc: ExtractedDocument) -> float:
        return 0.1 if doc.text.strip() else 0.02

    def parse(self, doc: ExtractedDocument, options: ParseOptions) -> ParsedStatement:
        stype = options.statement_type or guess_statement_type(doc)
        if not doc.text.strip():
            ps = ParsedStatement(parser_name=self.name, parser_version=self.version, statement_type=stype)
            ps.warnings.append("No text could be extracted from this PDF.")
            ps.needs_mapping = True
            return ps
        if options.column_mapping or (doc.tables and find_header(doc.tables)):
            ps = parse_tabular(doc, options, self.name, self.version)
            if ps.rows:
                ps.extra["pdf_mode"] = "tables"
                return ps
        ps = ParsedStatement(parser_name=self.name, parser_version=self.version, statement_type=stype)
        res = parse_pages(doc.pages)
        if not res.rows:
            fallback = parse_balance_delta(doc.pages, None)
            if fallback.rows:
                res = fallback
                ps.warnings.append(
                    "No column header recognised; rows were read as '<date> <description> <amount> <balance>' "
                    "and directions inferred from the running balance. Review every row."
                )
        ps.rows = res.rows
        ps.opening_balance = res.opening_balance
        ps.closing_balance = res.closing_balance
        ps.ignored_lines = res.ignored_lines
        ps.warnings.extend(res.warnings)
        ps.header_columns = res.header_labels
        ps.layout_signature = header_signature(res.header_labels) if res.header_labels else None
        ps.extra["pdf_mode"] = res.mode
        if not ps.rows:
            ps.needs_mapping = True
            ps.warnings.append(
                "No transactions could be read from this PDF. Options: provide the statement as CSV/Excel, "
                "enable OCR for scanned files, or share a redacted sample so a dedicated parser can be built."
            )
        apply_text_metadata(ps, doc)
        return ps

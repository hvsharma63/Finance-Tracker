"""Parser registry. Every statement parser implements StatementParser and registers itself.

Institution-specific parsers live in parsers/banks, parsers/credit_cards, parsers/investments.
Generic parsers live in parsers/generic and report low confidence so a dedicated parser wins.
"""

from __future__ import annotations

import importlib
import pkgutil
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.services.imports.candidates import ExtractedDocument, ParsedStatement, ParseOptions


class StatementParser(ABC):
    name: str = ""
    version: str = "0"
    institution: str | None = None
    statement_type: str = "bank"
    file_types: frozenset[str] = frozenset()
    description: str = ""
    # Exactly which format variants have been tested against real (redacted) samples.
    tested_variants: tuple[str, ...] = ()
    is_generic: bool = False

    def supports(self, doc: ExtractedDocument) -> bool:
        return doc.file_type in self.file_types

    @abstractmethod
    def detect(self, doc: ExtractedDocument) -> float:
        """Return confidence 0..1 that this parser handles the document."""

    @abstractmethod
    def parse(self, doc: ExtractedDocument, options: ParseOptions) -> ParsedStatement:
        """Extract candidate rows. Must not touch the database."""

    def describe(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "institution": self.institution,
            "statement_type": self.statement_type,
            "file_types": sorted(self.file_types),
            "description": self.description,
            "tested_variants": list(self.tested_variants),
            "is_generic": self.is_generic,
        }


_REGISTRY: dict[str, StatementParser] = {}
_LOADED = False


def register(cls: type[StatementParser]) -> type[StatementParser]:
    inst = cls()
    if not inst.name:
        raise ValueError(f"{cls.__name__} has no name")
    if inst.name in _REGISTRY:
        raise ValueError(f"Duplicate parser name {inst.name}")
    _REGISTRY[inst.name] = inst
    return cls


def _load_all() -> None:
    global _LOADED
    if _LOADED:
        return
    from app.services.imports import parsers

    for pkg in ("generic", "banks", "credit_cards", "investments"):
        mod = importlib.import_module(f"{parsers.__name__}.{pkg}")
        for info in pkgutil.iter_modules(mod.__path__):
            importlib.import_module(f"{mod.__name__}.{info.name}")
    _LOADED = True


def all_parsers() -> list[StatementParser]:
    _load_all()
    return list(_REGISTRY.values())


def get_parser(name: str) -> StatementParser | None:
    _load_all()
    return _REGISTRY.get(name)


@dataclass
class DetectionResult:
    parser: StatementParser
    confidence: float


def rank_parsers(doc: ExtractedDocument) -> list[DetectionResult]:
    results = []
    for p in all_parsers():
        if not p.supports(doc):
            continue
        try:
            c = float(p.detect(doc))
        except Exception:  # a broken detector must not block other parsers
            c = 0.0
        if c > 0:
            results.append(DetectionResult(p, min(c, 1.0)))
    results.sort(key=lambda r: (r.confidence, not r.parser.is_generic), reverse=True)
    return results

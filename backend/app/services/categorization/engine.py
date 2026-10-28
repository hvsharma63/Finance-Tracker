"""Deterministic categorization rules and merchant aliases.

Rule conditions (JSON):
    {"match": "all" | "any",
     "conditions": [{"field": "description", "op": "contains", "value": "SWIGGY"}, ...]}

Fields: description, merchant, reference, transaction_type, account_id, direction, amount, abs_amount
Ops:    contains, not_contains, equals, starts_with, regex, in, gt, gte, lt, lte, between
Amounts are integer minor units. Rules run in ascending priority; the first match wins.
User-set categories (category_source == 'user') are never overwritten by rules.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CategorizationRule, MerchantAlias, Transaction
from app.services.imports.normalization import extract_merchant

TEXT_FIELDS = {"description", "merchant", "reference", "transaction_type", "direction"}
NUM_FIELDS = {"amount", "abs_amount", "account_id"}
OPS = {"contains", "not_contains", "equals", "starts_with", "regex", "in", "gt", "gte", "lt", "lte", "between"}


class RuleError(ValueError):
    pass


def validate_conditions(cond: dict) -> dict:
    if not isinstance(cond, dict) or cond.get("match", "all") not in ("all", "any"):
        raise RuleError("conditions.match must be 'all' or 'any'")
    items = cond.get("conditions")
    if not isinstance(items, list) or not items:
        raise RuleError("At least one condition is required")
    for c in items:
        f, op = c.get("field"), c.get("op")
        if f not in TEXT_FIELDS | NUM_FIELDS:
            raise RuleError(f"Unknown field {f!r}")
        if op not in OPS:
            raise RuleError(f"Unknown operator {op!r}")
        if op == "regex":
            try:
                re.compile(str(c.get("value", "")))
            except re.error as e:
                raise RuleError(f"Invalid regex: {e}") from e
        if f in NUM_FIELDS and op in ("gt", "gte", "lt", "lte", "equals") and not isinstance(c.get("value"), int):
            raise RuleError(f"{f} comparisons need an integer value in minor units")
        if op == "between" and not (isinstance(c.get("value"), list) and len(c["value"]) == 2):
            raise RuleError("between needs [low, high]")
    return {"match": cond.get("match", "all"), "conditions": items}


def _value(t: Transaction, field: str):
    if field == "description":
        return t.normalized_description or ""
    if field == "abs_amount":
        return abs(t.amount_minor)
    if field == "amount":
        return t.amount_minor
    return getattr(t, field)


def condition_matches(t: Transaction, c: dict) -> bool:
    field, op, val = c["field"], c["op"], c.get("value")
    v = _value(t, field)
    if field in TEXT_FIELDS:
        s = (v or "").lower()
        if op == "contains":
            return str(val).lower() in s
        if op == "not_contains":
            return str(val).lower() not in s
        if op == "equals":
            return s == str(val).lower()
        if op == "starts_with":
            return s.startswith(str(val).lower())
        if op == "regex":
            return re.search(str(val), v or "", re.I) is not None
        if op == "in":
            return s in {str(x).lower() for x in (val or [])}
        return False
    if v is None:
        return False
    if op == "equals":
        return v == val
    if op == "in":
        return v in (val or [])
    if op == "gt":
        return v > val
    if op == "gte":
        return v >= val
    if op == "lt":
        return v < val
    if op == "lte":
        return v <= val
    if op == "between":
        return val[0] <= v <= val[1]
    return False


def rule_matches(t: Transaction, rule: CategorizationRule) -> bool:
    cond = rule.conditions or {}
    items = cond.get("conditions", [])
    if not items:
        return False
    results = (condition_matches(t, c) for c in items)
    return all(results) if cond.get("match", "all") == "all" else any(results)


def resolve_merchant(description: str | None, aliases: list[MerchantAlias]) -> str | None:
    d = description or ""
    for a in aliases:
        if a.match_type == "exact" and d.lower() == a.pattern.lower():
            return a.merchant_name
        if a.match_type == "contains" and a.pattern.lower() in d.lower():
            return a.merchant_name
        if a.match_type == "regex":
            try:
                if re.search(a.pattern, d, re.I):
                    return a.merchant_name
            except re.error:
                continue
    return None


def load_rules(db: Session) -> list[CategorizationRule]:
    return list(db.scalars(
        select(CategorizationRule).where(CategorizationRule.enabled.is_(True))
        .order_by(CategorizationRule.priority, CategorizationRule.id)
    ))


def load_aliases(db: Session) -> list[MerchantAlias]:
    return list(db.scalars(select(MerchantAlias).order_by(MerchantAlias.priority, MerchantAlias.id)))


def apply_rules(db: Session, txns: Iterable[Transaction], *, reapply: bool = False) -> int:
    """Set merchant and category on transactions. Returns number categorized."""
    rules = load_rules(db)
    aliases = load_aliases(db)
    n = 0
    for t in txns:
        alias = resolve_merchant(t.normalized_description, aliases)
        if alias:
            t.merchant = alias
        elif not t.merchant:
            t.merchant = extract_merchant(t.normalized_description)
        if t.category_source == "user":
            continue
        if t.category_id is not None and not reapply:
            continue
        for rule in rules:
            if rule_matches(t, rule):
                t.category_id, t.category_source, t.rule_id = rule.category_id, "rule", rule.id
                if rule.set_merchant:
                    t.merchant = rule.set_merchant
                n += 1
                break
        else:
            if reapply and t.category_source == "rule":
                t.category_id, t.category_source, t.rule_id = None, "none", None
    return n


def propose_rule(t: Transaction, category_id: int) -> dict:
    """Suggest a reusable rule from a user correction. The user must confirm it."""
    if t.merchant:
        cond = {"field": "merchant", "op": "equals", "value": t.merchant}
        name = f"{t.merchant}"
    else:
        words = [w for w in re.split(r"[^A-Za-z]+", t.normalized_description or "") if len(w) >= 4]
        token = max(words, key=len) if words else (t.normalized_description or "")[:20]
        cond = {"field": "description", "op": "contains", "value": token}
        name = token
    direction = {"field": "direction", "op": "equals", "value": t.direction}
    return {
        "name": f"{name} → category {category_id}",
        "conditions": {"match": "all", "conditions": [cond, direction]},
        "category_id": category_id,
        "priority": 100,
    }

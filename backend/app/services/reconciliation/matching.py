"""Transaction relationship suggestions and manual review.

Suggestions are only suggestions: nothing affects reports until the user approves it.
Each suggestion stores the reasons and differences that produced its score.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, NotFound
from app.core.money import format_inr
from app.models import Account, Transaction, TransactionRelationship
from app.models.ledger import INVESTMENT_TYPES, MOVEMENT_RELATIONSHIPS
from app.services.imports.normalization import match_key
from app.services.ledger import audit
from app.services.ledger.seed import get_setting

CARD_KEYWORDS = re.compile(r"credit card|cc payment|card payment|cc bill|bbps|card ?no|cred club|cred\b|autopay", re.I)
TRANSFER_KEYWORDS = re.compile(r"self|own a/?c|own account|transfer|trf|sweep|fund transfer|to a/?c", re.I)
INVEST_KEYWORDS = re.compile(r"zerodha|groww|upstox|kuvera|mutual fund|\bmf\b|nse clearing|bse|cams|kfin|"
                             r"karvy|sip|icclzerodha|indian clearing", re.I)
REFUND_KEYWORDS = re.compile(r"refund|reversal|\brev\b|chargeback|cashback|returned", re.I)
SUGGEST_THRESHOLD = 0.45


def relationship_type_for(src: Account, dst: Account) -> str:
    """Classify a money-out (src) → money-in (dst) pair by account types."""
    if dst.account_type == "credit_card":
        return "card_payment"
    if dst.account_type in ("loan",):
        return "loan_payment"
    if dst.account_type in INVESTMENT_TYPES and src.account_type not in INVESTMENT_TYPES:
        return "investment_contribution"
    if src.account_type in INVESTMENT_TYPES and dst.account_type not in INVESTMENT_TYPES:
        return "investment_withdrawal"
    return "transfer"


def _existing_pairs(db: Session, ids: set[int]) -> set[tuple[int, int]]:
    if not ids:
        return set()
    rels = db.scalars(select(TransactionRelationship).where(
        or_(TransactionRelationship.source_transaction_id.in_(ids),
            TransactionRelationship.related_transaction_id.in_(ids))))
    pairs = set()
    for r in rels:
        pairs.add((r.source_transaction_id, r.related_transaction_id))
        pairs.add((r.related_transaction_id, r.source_transaction_id))
    return pairs


def approved_matched_minor(db: Session, txn_id: int, types: set[str] | None = None) -> int:
    """Sum of approved matched amounts (magnitudes) already allocated for a transaction."""
    q = select(TransactionRelationship).where(
        TransactionRelationship.review_status == "approved",
        or_(TransactionRelationship.source_transaction_id == txn_id,
            TransactionRelationship.related_transaction_id == txn_id))
    total = 0
    for r in db.scalars(q):
        if types is None or r.relationship_type in types:
            total += abs(r.matched_amount_minor or 0)
    return total


def _score_pair(out: Transaction, inn: Transaction, src: Account, dst: Account, rtype: str,
                window: int, tolerance: int) -> tuple[float, dict] | None:
    diff_amount = abs(inn.amount_minor) - abs(out.amount_minor)
    if abs(diff_amount) > tolerance:
        return None
    days = abs((inn.transaction_date - out.transaction_date).days)
    if days > window:
        return None
    reasons: list[str] = []
    score = 0.0
    if diff_amount == 0:
        score += 0.4
        reasons.append(f"Exact amount {format_inr(abs(out.amount_minor))}")
    else:
        score += 0.25
        reasons.append(f"Amount within tolerance (difference {format_inr(abs(diff_amount))})")
    score += 0.25 * (1 - days / max(window, 1))
    reasons.append("Same date" if days == 0 else f"{days} day(s) apart (window {window})")
    if out.reference and inn.reference and out.reference == inn.reference:
        score += 0.35
        reasons.append(f"Same reference {out.reference}")
    text_out, text_in = out.normalized_description or "", inn.normalized_description or ""
    if dst.masked_identifier:
        last4 = re.sub(r"\D", "", dst.masked_identifier)[-4:]
        if last4 and last4 in text_out:
            score += 0.2
            reasons.append(f"Description mentions destination account ending {last4}")
    if src.masked_identifier:
        last4 = re.sub(r"\D", "", src.masked_identifier)[-4:]
        if last4 and last4 in text_in:
            score += 0.15
            reasons.append(f"Description mentions source account ending {last4}")
    if rtype == "card_payment" and (CARD_KEYWORDS.search(text_out) or out.transaction_type == "card_payment"):
        score += 0.15
        reasons.append("Bank narration looks like a card payment")
    if rtype == "card_payment" and inn.transaction_type == "card_payment":
        score += 0.1
        reasons.append("Card statement shows a payment received")
    if rtype == "transfer" and (TRANSFER_KEYWORDS.search(text_out) or TRANSFER_KEYWORDS.search(text_in)):
        score += 0.1
        reasons.append("Narration mentions a transfer")
    if rtype.startswith("investment") and (INVEST_KEYWORDS.search(text_out) or INVEST_KEYWORDS.search(text_in)):
        score += 0.15
        reasons.append("Narration mentions an investment platform")
    return min(score, 1.0), {
        "reasons": reasons,
        "amount_difference_minor": diff_amount,
        "days_apart": days,
        "source_account": src.name,
        "related_account": dst.name,
    }


def suggest_matches(db: Session, transaction_ids: list[int] | None = None) -> list[TransactionRelationship]:
    """Create 'suggested' relationships for transfers, card payments, investment flows and refunds."""
    window = int(get_setting(db, "matching_window_days", 5))
    tolerance = int(get_setting(db, "matching_amount_tolerance_minor", 0))
    accounts = {a.id: a for a in db.scalars(select(Account))}
    base = select(Transaction).where(Transaction.duplicate_status != "duplicate")
    targets = list(db.scalars(base.where(Transaction.id.in_(transaction_ids)))) if transaction_ids is not None \
        else list(db.scalars(base))
    if not targets:
        return []
    lo = min(t.transaction_date for t in targets) - timedelta(days=max(window, 90))
    hi = max(t.transaction_date for t in targets) + timedelta(days=window)
    pool = list(db.scalars(base.where(Transaction.transaction_date.between(lo, hi))))
    pairs = _existing_pairs(db, {t.id for t in pool})
    fully_matched = {t.id for t in pool
                     if approved_matched_minor(db, t.id, MOVEMENT_RELATIONSHIPS) >= abs(t.amount_minor)}
    created: list[TransactionRelationship] = []
    target_ids = {t.id for t in targets}

    # 1. Cross-account movements: best counterpart per money-out transaction
    outs = [t for t in pool if t.amount_minor < 0 and t.id not in fully_matched]
    ins = [t for t in pool if t.amount_minor > 0 and t.id not in fully_matched]
    claimed: set[int] = set()
    candidates = []
    for o in outs:
        for i in ins:
            if o.account_id == i.account_id or (o.id not in target_ids and i.id not in target_ids):
                continue
            if (o.id, i.id) in pairs:
                continue
            src, dst = accounts[o.account_id], accounts[i.account_id]
            rtype = relationship_type_for(src, dst)
            scored = _score_pair(o, i, src, dst, rtype, window, tolerance)
            if scored and scored[0] >= SUGGEST_THRESHOLD:
                candidates.append((scored[0], o, i, rtype, scored[1]))
    for score, o, i, rtype, reason in sorted(candidates, key=lambda c: -c[0]):
        if o.id in claimed or i.id in claimed:
            continue
        claimed.update({o.id, i.id})
        rel = TransactionRelationship(
            source_transaction_id=o.id, related_transaction_id=i.id, relationship_type=rtype,
            matched_amount_minor=min(abs(o.amount_minor), abs(i.amount_minor)),
            review_status="suggested", score=round(score, 3), matching_reason=reason,
        )
        db.add(rel)
        created.append(rel)
        pairs.update({(o.id, i.id), (i.id, o.id)})

    # 2. Refunds / reversals in the same account
    for r in [t for t in pool if t.amount_minor > 0 and t.id in target_ids]:
        if not REFUND_KEYWORDS.search(r.normalized_description or "") or r.id in claimed:
            continue
        rkey = set(re.findall(r"[a-z]{4,}", (r.merchant or r.normalized_description or "").lower())) - {"refund", "reversal"}
        best = None
        for p in pool:
            if p.account_id != r.account_id or p.amount_minor >= 0 or (r.id, p.id) in pairs:
                continue
            if not (timedelta(0) <= r.transaction_date - p.transaction_date <= timedelta(days=120)):
                continue
            if abs(p.amount_minor) < r.amount_minor:
                continue
            pkey = set(re.findall(r"[a-z]{4,}", (p.merchant or p.normalized_description or "").lower()))
            overlap = rkey & pkey
            if not overlap and match_key(p.merchant) != match_key(r.merchant):
                continue
            s = 0.5 + (0.3 if abs(p.amount_minor) == r.amount_minor else 0.1) + min(0.2, 0.05 * len(overlap))
            if best is None or s > best[0]:
                best = (s, p, overlap)
        if best:
            s, p, overlap = best
            reasons = ["Narration indicates a refund/reversal", f"Same account, {(r.transaction_date - p.transaction_date).days} day(s) after purchase"]
            if overlap:
                reasons.append("Shared merchant words: " + ", ".join(sorted(overlap)))
            reasons.append("Full refund" if abs(p.amount_minor) == r.amount_minor else
                           f"Partial refund {format_inr(r.amount_minor)} of {format_inr(abs(p.amount_minor))}")
            rel = TransactionRelationship(
                source_transaction_id=p.id, related_transaction_id=r.id, relationship_type="refund",
                matched_amount_minor=r.amount_minor, review_status="suggested", score=round(min(s, 1.0), 3),
                matching_reason={"reasons": reasons},
            )
            db.add(rel)
            created.append(rel)
            pairs.update({(p.id, r.id), (r.id, p.id)})
    db.flush()
    return created


def _check_capacity(db: Session, rel: TransactionRelationship) -> None:
    src, dst = db.get(Transaction, rel.source_transaction_id), db.get(Transaction, rel.related_transaction_id)
    amt = abs(rel.matched_amount_minor or min(abs(src.amount_minor), abs(dst.amount_minor)))
    rel.matched_amount_minor = amt
    if rel.relationship_type in MOVEMENT_RELATIONSHIPS or rel.relationship_type == "refund":
        types = MOVEMENT_RELATIONSHIPS | {"refund"}
        for t in (src, dst):
            used = approved_matched_minor(db, t.id, types)
            if used + amt > abs(t.amount_minor):
                raise Conflict(
                    f"Transaction {t.id} would be over-allocated: {format_inr(used)} already matched, "
                    f"{format_inr(amt)} more requested, amount is {format_inr(abs(t.amount_minor))}."
                )
    if rel.relationship_type in MOVEMENT_RELATIONSHIPS and src.account_id == dst.account_id:
        raise AppError("A transfer must link two different accounts")
    if rel.relationship_type in MOVEMENT_RELATIONSHIPS and (src.amount_minor > 0) == (dst.amount_minor > 0):
        raise AppError("A transfer links a money-out transaction with a money-in transaction")


def _refresh_recon_status(db: Session, txn_ids) -> None:
    for tid in txn_ids:
        t = db.get(Transaction, tid)
        t.reconciliation_status = "reconciled" if approved_matched_minor(db, tid) > 0 else "unreconciled"


def approve(db: Session, rel_id: int, matched_amount_minor: int | None = None) -> TransactionRelationship:
    rel = db.get(TransactionRelationship, rel_id, with_for_update=True)
    if rel is None:
        raise NotFound(f"Relationship {rel_id} not found")
    if rel.review_status == "approved":
        return rel
    if matched_amount_minor is not None:
        rel.matched_amount_minor = abs(matched_amount_minor)
    _check_capacity(db, rel)
    now = datetime.now(timezone.utc)
    rel.review_status, rel.reviewed_at, rel.approved_at = "approved", now, now
    if rel.relationship_type == "duplicate":
        dup = db.get(Transaction, rel.related_transaction_id)
        dup.duplicate_status = "duplicate"
    db.flush()
    _refresh_recon_status(db, [rel.source_transaction_id, rel.related_transaction_id])
    audit.record(db, "relationship", rel.id, "approved",
                 {"type": rel.relationship_type, "matched_amount_minor": rel.matched_amount_minor})
    return rel


def reject(db: Session, rel_id: int) -> TransactionRelationship:
    rel = db.get(TransactionRelationship, rel_id)
    if rel is None:
        raise NotFound(f"Relationship {rel_id} not found")
    if rel.review_status == "approved":
        raise Conflict("Undo the approval before rejecting")
    rel.review_status, rel.reviewed_at = "rejected", datetime.now(timezone.utc)
    audit.record(db, "relationship", rel.id, "rejected", {"type": rel.relationship_type})
    return rel


def undo(db: Session, rel_id: int) -> TransactionRelationship:
    rel = db.get(TransactionRelationship, rel_id)
    if rel is None:
        raise NotFound(f"Relationship {rel_id} not found")
    if rel.review_status != "approved":
        raise Conflict("Only approved relationships can be undone")
    rel.review_status, rel.reviewed_at, rel.approved_at = "undone", datetime.now(timezone.utc), None
    if rel.relationship_type == "duplicate":
        db.get(Transaction, rel.related_transaction_id).duplicate_status = "confirmed_unique"
    db.flush()
    _refresh_recon_status(db, [rel.source_transaction_id, rel.related_transaction_id])
    audit.record(db, "relationship", rel.id, "undone", {"type": rel.relationship_type})
    return rel


def create_manual(db: Session, source_id: int, related_id: int, rtype: str,
                  matched_amount_minor: int | None = None, notes: str | None = None) -> TransactionRelationship:
    for tid in (source_id, related_id):
        if db.get(Transaction, tid) is None:
            raise NotFound(f"Transaction {tid} not found")
    existing = db.scalar(select(TransactionRelationship).where(
        TransactionRelationship.source_transaction_id == source_id,
        TransactionRelationship.related_transaction_id == related_id,
        TransactionRelationship.relationship_type == rtype))
    rel = existing or TransactionRelationship(
        source_transaction_id=source_id, related_transaction_id=related_id, relationship_type=rtype,
        matching_reason={"reasons": ["Created manually"]}, notes=notes)
    rel.matched_amount_minor = matched_amount_minor
    rel.review_status = "suggested"
    if existing is None:
        db.add(rel)
    db.flush()
    return approve(db, rel.id)

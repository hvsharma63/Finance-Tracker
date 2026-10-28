from fastapi import Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import protected_router
from app.core.db import get_db
from app.core.errors import AppError, Conflict, get_or_404
from app.models import Budget, CategorizationRule, Category, MerchantAlias, Transaction
from app.models.ledger import REPORTING_TYPES
from app.services.categorization.engine import RuleError, apply_rules, rule_matches, validate_conditions
from app.services.ledger import audit

router = protected_router(tags=["categories"])


def _cat(c: Category, counts: dict | None = None) -> dict:
    return {"id": c.id, "name": c.name, "parent_id": c.parent_id, "reporting_type": c.reporting_type,
            "is_active": c.is_active, "is_system": c.is_system, "sort_order": c.sort_order,
            "transaction_count": (counts or {}).get(c.id, 0)}


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    parent_id: int | None = None
    reporting_type: str
    is_active: bool = True

    @field_validator("reporting_type")
    @classmethod
    def _rt(cls, v):
        if v not in REPORTING_TYPES:
            raise ValueError(f"reporting_type must be one of {REPORTING_TYPES}")
        return v


class CategoryPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    reporting_type: str | None = None
    is_active: bool | None = None
    parent_id: int | None = None


@router.get("/categories")
def list_categories(db: Session = Depends(get_db)):
    counts = dict(db.execute(select(Transaction.category_id, func.count()).group_by(Transaction.category_id)).all())
    return [_cat(c, counts) for c in db.scalars(select(Category).order_by(Category.parent_id.nulls_first(),
                                                                           Category.sort_order, Category.name))]


@router.post("/categories", status_code=201)
def create_category(body: CategoryIn, db: Session = Depends(get_db)):
    if body.parent_id:
        parent = get_or_404(db, Category, body.parent_id, "Category")
        if parent.parent_id is not None:
            raise AppError("Only two levels (category → subcategory) are supported")
    c = Category(**body.model_dump())
    db.add(c)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise Conflict("A category with that name already exists here")
    audit.record(db, "category", c.id, "created", body.model_dump())
    db.commit()
    return _cat(c)


@router.patch("/categories/{cid}")
def update_category(cid: int, body: CategoryPatch, db: Session = Depends(get_db)):
    c = get_or_404(db, Category, cid, "Category")
    data = body.model_dump(exclude_unset=True)
    if "reporting_type" in data and data["reporting_type"] not in REPORTING_TYPES:
        raise AppError("Invalid reporting_type")
    for k, v in data.items():
        setattr(c, k, v)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise Conflict("A category with that name already exists here")
    audit.record(db, "category", c.id, "updated", data)
    db.commit()
    return _cat(c)


@router.delete("/categories/{cid}")
def delete_category(cid: int, db: Session = Depends(get_db)):
    c = get_or_404(db, Category, cid, "Category")
    used = db.scalar(select(func.count()).select_from(Transaction).where(Transaction.category_id == cid))
    children = db.scalar(select(func.count()).select_from(Category).where(Category.parent_id == cid))
    rules = db.scalar(select(func.count()).select_from(CategorizationRule).where(CategorizationRule.category_id == cid))
    if used or children or rules:
        raise Conflict("Category is in use (transactions, subcategories or rules). Deactivate it instead.",
                       details={"transactions": used, "subcategories": children, "rules": rules})
    db.execute(Budget.__table__.delete().where(Budget.category_id == cid))
    db.delete(c)
    db.commit()
    return {"deleted": cid}


# ---------------------------------------------------------------- rules

class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    conditions: dict
    category_id: int
    set_merchant: str | None = Field(default=None, max_length=200)
    priority: int = 100
    enabled: bool = True
    apply_now: bool = True


class RulePatch(BaseModel):
    name: str | None = None
    conditions: dict | None = None
    category_id: int | None = None
    set_merchant: str | None = None
    priority: int | None = None
    enabled: bool | None = None


def _rule(r: CategorizationRule) -> dict:
    return {"id": r.id, "name": r.name, "conditions": r.conditions, "category_id": r.category_id,
            "set_merchant": r.set_merchant, "priority": r.priority, "enabled": r.enabled}


@router.get("/rules")
def list_rules(db: Session = Depends(get_db)):
    return [_rule(r) for r in db.scalars(select(CategorizationRule).order_by(CategorizationRule.priority, CategorizationRule.id))]


@router.post("/rules", status_code=201)
def create_rule(body: RuleIn, db: Session = Depends(get_db)):
    get_or_404(db, Category, body.category_id, "Category")
    try:
        cond = validate_conditions(body.conditions)
    except RuleError as e:
        raise AppError(str(e), code="invalid_rule")
    r = CategorizationRule(name=body.name, conditions=cond, category_id=body.category_id,
                           set_merchant=body.set_merchant, priority=body.priority, enabled=body.enabled)
    db.add(r)
    db.flush()
    applied = 0
    if body.apply_now and r.enabled:
        applied = apply_rules(db, db.scalars(select(Transaction).where(Transaction.category_id.is_(None))))
    audit.record(db, "rule", r.id, "created", {"name": r.name})
    db.commit()
    return _rule(r) | {"applied_to": applied}


@router.patch("/rules/{rid}")
def update_rule(rid: int, body: RulePatch, db: Session = Depends(get_db)):
    r = get_or_404(db, CategorizationRule, rid, "Rule")
    data = body.model_dump(exclude_unset=True)
    if "conditions" in data:
        try:
            data["conditions"] = validate_conditions(data["conditions"])
        except RuleError as e:
            raise AppError(str(e), code="invalid_rule")
    for k, v in data.items():
        setattr(r, k, v)
    audit.record(db, "rule", r.id, "updated", {k: v for k, v in data.items() if k != "conditions"})
    db.commit()
    return _rule(r)


@router.delete("/rules/{rid}")
def delete_rule(rid: int, db: Session = Depends(get_db)):
    r = get_or_404(db, CategorizationRule, rid, "Rule")
    db.delete(r)
    db.commit()
    return {"deleted": rid}


class RuleTest(BaseModel):
    conditions: dict
    limit: int = 50


@router.post("/rules/test")
def test_rule(body: RuleTest, db: Session = Depends(get_db)):
    """Preview which transactions a rule would match, without changing anything."""
    try:
        cond = validate_conditions(body.conditions)
    except RuleError as e:
        raise AppError(str(e), code="invalid_rule")
    probe = CategorizationRule(name="test", conditions=cond, category_id=0)
    hits = [t for t in db.scalars(select(Transaction).order_by(Transaction.transaction_date.desc()).limit(20000))
            if rule_matches(t, probe)]
    return {"match_count": len(hits), "sample": [{"id": t.id, "date": t.transaction_date.isoformat(),
                                                  "description": t.normalized_description, "amount_minor": t.amount_minor}
                                                 for t in hits[:body.limit]]}


@router.post("/rules/reapply")
def reapply_rules(db: Session = Depends(get_db)):
    """Re-run all rules on every transaction not categorized by the user."""
    n = apply_rules(db, db.scalars(select(Transaction).where(Transaction.category_source != "user")), reapply=True)
    db.commit()
    return {"categorized": n}


# ---------------------------------------------------------------- merchant aliases

class AliasIn(BaseModel):
    pattern: str = Field(min_length=1, max_length=200)
    match_type: str = Field(default="contains", pattern="^(contains|regex|exact)$")
    merchant_name: str = Field(min_length=1, max_length=200)
    priority: int = 100


@router.get("/merchant-aliases")
def list_aliases(db: Session = Depends(get_db)):
    return [{"id": a.id, "pattern": a.pattern, "match_type": a.match_type, "merchant_name": a.merchant_name,
             "priority": a.priority} for a in db.scalars(select(MerchantAlias).order_by(MerchantAlias.priority))]


@router.post("/merchant-aliases", status_code=201)
def create_alias(body: AliasIn, db: Session = Depends(get_db)):
    if body.match_type == "regex":
        import re
        try:
            re.compile(body.pattern)
        except re.error as e:
            raise AppError(f"Invalid regex: {e}")
    a = MerchantAlias(**body.model_dump())
    db.add(a)
    db.flush()
    apply_rules(db, db.scalars(select(Transaction)))
    db.commit()
    return {"id": a.id, **body.model_dump()}


@router.delete("/merchant-aliases/{aid}")
def delete_alias(aid: int, db: Session = Depends(get_db)):
    a = get_or_404(db, MerchantAlias, aid, "Alias")
    db.delete(a)
    db.commit()
    return {"deleted": aid}

"""Idempotent seeding of default categories and settings."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AppSetting, Category

DEFAULT_CATEGORIES: dict[tuple[str, str], list[tuple[str, str]]] = {
    ("Income", "income"): [
        ("Salary", "income"), ("Business income", "income"), ("Freelance income", "income"),
        ("Interest", "income"), ("Dividends", "income"), ("Rental income", "income"),
        ("Refunds and reimbursements", "refund"), ("Cashback", "refund"), ("Other income", "income"),
    ],
    ("Essential spending", "expense"): [
        ("Rent", "expense"), ("Utilities", "expense"), ("Groceries", "expense"), ("Healthcare", "expense"),
        ("Insurance", "expense"), ("Education", "expense"), ("Household expenses", "expense"),
        ("Transport", "expense"), ("Fuel", "expense"), ("Mobile and internet", "expense"),
    ],
    ("Lifestyle spending", "expense"): [
        ("Restaurants", "expense"), ("Food delivery", "expense"), ("Shopping", "expense"),
        ("Entertainment", "expense"), ("Travel", "expense"), ("Subscriptions", "expense"),
        ("Personal care", "expense"), ("Gifts", "expense"), ("Hobbies", "expense"), ("Other spending", "expense"),
    ],
    ("Financial costs", "expense"): [
        ("Bank charges", "expense"), ("Card fees and interest", "expense"), ("Loan interest", "expense"),
        ("Taxes", "expense"),
    ],
    ("Financial movements", "transfer"): [
        ("Internal transfers", "transfer"), ("Credit card repayments", "transfer"),
        ("Loan principal", "loan_principal"), ("Loan disbursement", "loan_principal"),
        ("Investment purchases", "investment"), ("Investment sales", "investment"),
        ("Cash withdrawals", "cash_withdrawal"), ("Reversals", "refund"), ("Refunds", "refund"),
        ("Excluded / ignore", "excluded"),
    ],
}

DEFAULT_SETTINGS = {
    "matching_window_days": 5,
    "matching_amount_tolerance_minor": 0,
    "possible_duplicate_window_days": 2,
    "base_currency": "INR",
    "timezone": "Asia/Kolkata",
}


def seed_defaults(db: Session) -> None:
    existing = {(c.parent_id, c.name): c for c in db.scalars(select(Category))}
    order = 0
    for (parent_name, parent_type), children in DEFAULT_CATEGORIES.items():
        order += 10
        parent = existing.get((None, parent_name))
        if parent is None:
            parent = Category(name=parent_name, reporting_type=parent_type, is_system=True, sort_order=order)
            db.add(parent)
            db.flush()
        for i, (child, rtype) in enumerate(children):
            if (parent.id, child) not in existing:
                db.add(Category(name=child, parent_id=parent.id, reporting_type=rtype, is_system=True, sort_order=i))
    for key, value in DEFAULT_SETTINGS.items():
        if db.get(AppSetting, key) is None:
            db.add(AppSetting(key=key, value=value))
    db.commit()


def get_setting(db: Session, key: str, default=None):
    s = db.get(AppSetting, key)
    return s.value if s is not None else DEFAULT_SETTINGS.get(key, default)


def category_by_path(db: Session, parent: str, child: str) -> Category | None:
    p = db.scalar(select(Category).where(Category.parent_id.is_(None), Category.name == parent))
    if p is None:
        return None
    return db.scalar(select(Category).where(Category.parent_id == p.id, Category.name == child))

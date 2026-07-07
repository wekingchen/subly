from sqlalchemy.orm import Session

from app.models import Category, Subscription


def is_carrier_category(category: Category | None) -> bool:
    if not category:
        return False
    name = category.name or ""
    lower = name.lower()
    return "carrier" in lower or "电信运营商" in name or "运营商" in name


def category_allows_keepalive(db: Session, category_id: int | None) -> bool:
    category = db.get(Category, category_id) if category_id else None
    return is_carrier_category(category)


def normalize_keepalive_data(data: dict, db: Session) -> None:
    if data.get("billing_type") != "recurring" or not category_allows_keepalive(db, data.get("category_id")):
        data["is_keepalive"] = False


def apply_keepalive_scope(db: Session, sub: Subscription) -> None:
    if sub.billing_type != "recurring" or not category_allows_keepalive(db, sub.category_id):
        sub.is_keepalive = False

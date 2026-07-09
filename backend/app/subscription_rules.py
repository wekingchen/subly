from sqlalchemy.orm import Session

from app.models import Bundle, Category, PaymentMethod, Subscription


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


def validate_subscription_refs(
    db: Session,
    user_id: int,
    *,
    category_id: int | None = None,
    payment_method_id: int | None = None,
    bundle_id: int | None = None,
) -> str | None:
    """校验订阅引用的分类 / 付款方式 / 套餐包归属当前用户。

    Category / PaymentMethod：系统级（is_system 或 user_id 为空）或属于本人；
    Bundle：用户私有，必须属于本人。返回首个不合法字段的中文名，全部合法返回 None。
    """
    if category_id is not None:
        cat = db.get(Category, category_id)
        if cat is None or not (cat.is_system or cat.user_id is None or cat.user_id == user_id):
            return "分类"
    if payment_method_id is not None:
        pm = db.get(PaymentMethod, payment_method_id)
        if pm is None or not (pm.is_system or pm.user_id is None or pm.user_id == user_id):
            return "付款方式"
    if bundle_id is not None:
        bundle = db.get(Bundle, bundle_id)
        if bundle is None or bundle.user_id != user_id:
            return "套餐包"
    return None

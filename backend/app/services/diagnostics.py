from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Bundle, Category, Currency, NotificationLog, PaymentMethod, Subscription, User
from app.services.scheduler import _parse_days
from app.subscription_rules import category_allows_keepalive

VALID_BILLING_TYPES = {"recurring", "one_time"}
VALID_CYCLES = {"day", "week", "month", "year"}


def _issue(
    issues: list[dict],
    *,
    severity: str,
    scope: str,
    code: str,
    title: str,
    detail: str,
    suggestion: str,
    user_id: int | None = None,
    username: str | None = None,
    subscription_id: int | None = None,
    subscription_name: str | None = None,
) -> None:
    issues.append({
        "severity": severity,
        "scope": scope,
        "code": code,
        "title": title,
        "detail": detail,
        "suggestion": suggestion,
        "user_id": user_id,
        "username": username,
        "subscription_id": subscription_id,
        "subscription_name": subscription_name,
    })


def run_data_diagnostics(db: Session, user_id: int | None = None) -> dict:
    """只读数据自诊断：发现明显脏数据、提醒配置缺口与近期通知失败。"""
    user_stmt = select(User)
    sub_stmt = select(Subscription)
    log_stmt = select(NotificationLog)
    if user_id is not None:
        user_stmt = user_stmt.where(User.id == user_id)
        sub_stmt = sub_stmt.where(Subscription.user_id == user_id)
        log_stmt = log_stmt.where(NotificationLog.user_id == user_id)

    users = db.scalars(user_stmt.order_by(User.id)).all()
    subs = db.scalars(sub_stmt.order_by(Subscription.id)).all()
    logs = db.scalars(log_stmt.order_by(NotificationLog.id)).all()
    user_ids = {u.id for u in users}
    all_user_ids = set(db.scalars(select(User.id)).all())
    category_ids = set(db.scalars(select(Category.id)).all())
    payment_ids = set(db.scalars(select(PaymentMethod.id)).all())
    bundle_ids = set(db.scalars(select(Bundle.id)).all())
    currency_codes = set(db.scalars(select(Currency.code)).all())
    sub_ids = set(db.scalars(select(Subscription.id)).all())

    issues: list[dict] = []

    active_sub_counts = {
        uid: db.scalar(
            select(func.count()).select_from(Subscription).where(
                Subscription.user_id == uid,
                Subscription.is_active.is_(True),
            )
        ) or 0
        for uid in user_ids
    }

    for user in users:
        if user.telegram_enabled and (not user.telegram_bot_token or not user.telegram_chat_id):
            _issue(
                issues,
                severity="warn",
                scope="user",
                code="telegram_config_incomplete",
                title="Telegram 通知配置不完整",
                detail=f"用户 {user.username} 已启用 Telegram，但 Bot Token 或 Chat ID 缺失。",
                suggestion="在系统设置中补齐 Bot Token 与 Chat ID，或关闭 Telegram 通知。",
                user_id=user.id,
                username=user.username,
            )
        if user.bark_enabled and not user.bark_device_key:
            _issue(
                issues,
                severity="warn",
                scope="user",
                code="bark_config_incomplete",
                title="Bark 通知配置不完整",
                detail=f"用户 {user.username} 已启用 Bark，但 Device Key 缺失。",
                suggestion="在系统设置中补齐 Bark Device Key，或关闭 Bark 通知。",
                user_id=user.id,
                username=user.username,
            )
        if not user.is_active and active_sub_counts.get(user.id, 0) > 0:
            _issue(
                issues,
                severity="info",
                scope="user",
                code="disabled_user_has_active_subscriptions",
                title="已禁用用户仍有生效订阅",
                detail=f"用户 {user.username} 已禁用，但仍有 {active_sub_counts[user.id]} 条生效订阅。",
                suggestion="确认这是保留历史数据，还是需要停用这些订阅。",
                user_id=user.id,
                username=user.username,
            )

    for sub in subs:
        user = db.get(User, sub.user_id)
        username = user.username if user else None
        common = {
            "user_id": sub.user_id,
            "username": username,
            "subscription_id": sub.id,
            "subscription_name": sub.name,
        }
        if sub.billing_type not in VALID_BILLING_TYPES:
            _issue(
                issues,
                severity="error",
                scope="subscription",
                code="invalid_billing_type",
                title="订阅计费类型异常",
                detail=f"订阅「{sub.name}」的 billing_type={sub.billing_type}，不是 recurring 或 one_time。",
                suggestion="编辑订阅并保存为周期订阅或一次性买断。",
                **common,
            )
        if sub.cycle not in VALID_CYCLES:
            _issue(
                issues,
                severity="error",
                scope="subscription",
                code="invalid_cycle",
                title="订阅周期异常",
                detail=f"订阅「{sub.name}」的 cycle={sub.cycle}，不是 day/week/month/year。",
                suggestion="编辑订阅并选择有效周期。",
                **common,
            )
        if (sub.cycle_count or 0) <= 0:
            _issue(
                issues,
                severity="error",
                scope="subscription",
                code="invalid_cycle_count",
                title="订阅周期数量异常",
                detail=f"订阅「{sub.name}」的周期数量为 {sub.cycle_count}。",
                suggestion="编辑订阅并把周期数量改为大于 0 的整数。",
                **common,
            )
        if (sub.amount or 0) < 0:
            _issue(
                issues,
                severity="warn",
                scope="subscription",
                code="negative_amount",
                title="订阅金额为负数",
                detail=f"订阅「{sub.name}」金额为 {sub.amount}。",
                suggestion="确认是否录入错误；通常订阅金额应为 0 或正数。",
                **common,
            )
        if not sub.currency or sub.currency not in currency_codes:
            _issue(
                issues,
                severity="warn",
                scope="subscription",
                code="currency_missing",
                title="订阅币种不存在",
                detail=f"订阅「{sub.name}」使用的币种 {sub.currency or '空'} 未在币种表中找到。",
                suggestion="在设置中补充自定义币种，或把订阅改为已有币种。",
                **common,
            )
        if sub.category_id and sub.category_id not in category_ids:
            _issue(
                issues,
                severity="warn",
                scope="subscription",
                code="category_missing",
                title="订阅分类引用不存在",
                detail=f"订阅「{sub.name}」引用的分类 id={sub.category_id} 不存在。",
                suggestion="编辑订阅并重新选择分类。",
                **common,
            )
        if sub.payment_method_id and sub.payment_method_id not in payment_ids:
            _issue(
                issues,
                severity="warn",
                scope="subscription",
                code="payment_method_missing",
                title="付款方式引用不存在",
                detail=f"订阅「{sub.name}」引用的付款方式 id={sub.payment_method_id} 不存在。",
                suggestion="编辑订阅并重新选择付款方式。",
                **common,
            )
        if sub.bundle_id and sub.bundle_id not in bundle_ids:
            _issue(
                issues,
                severity="warn",
                scope="subscription",
                code="bundle_missing",
                title="套餐包引用不存在",
                detail=f"订阅「{sub.name}」引用的套餐包 id={sub.bundle_id} 不存在。",
                suggestion="编辑订阅并重新选择套餐包，或移除套餐包归属。",
                **common,
            )
        if sub.is_active and sub.billing_type == "recurring" and sub.next_renewal_date is None:
            _issue(
                issues,
                severity="error",
                scope="subscription",
                code="subscription_missing_next_renewal",
                title="周期订阅缺少下次续费日",
                detail=f"订阅「{sub.name}」仍处于生效状态，但没有 next_renewal_date。",
                suggestion="编辑订阅并设置下次续费日，或改为一次性买断/停用。",
                **common,
            )
        if sub.billing_type == "recurring" and not _parse_days(sub.remind_days_before):
            _issue(
                issues,
                severity="warn",
                scope="subscription",
                code="invalid_remind_days",
                title="提醒天数无有效数字",
                detail=f"订阅「{sub.name}」的提前提醒配置为「{sub.remind_days_before}」。",
                suggestion="填写类似 7,1 的提前提醒天数。",
                **common,
            )
        if sub.is_keepalive and (sub.billing_type != "recurring" or not category_allows_keepalive(db, sub.category_id)):
            _issue(
                issues,
                severity="error",
                scope="subscription",
                code="keepalive_scope_invalid",
                title="短信保号标记超出适用范围",
                detail=f"订阅「{sub.name}」不是电信运营商分类的周期订阅，但 is_keepalive=true。",
                suggestion="编辑订阅并重新保存，或把分类改为电信运营商。",
                **common,
            )
        if sub.billing_type == "one_time" and (sub.next_renewal_date is not None or sub.auto_renew):
            _issue(
                issues,
                severity="warn",
                scope="subscription",
                code="one_time_has_recurring_fields",
                title="一次性买断残留周期字段",
                detail=f"订阅「{sub.name}」是一次性买断，但仍有下次续费日或自动续费标记。",
                suggestion="编辑订阅并保存一次，系统会按一次性买断规则清理周期字段。",
                **common,
            )

    since = datetime.utcnow() - timedelta(days=30)
    failed_30d = 0
    for log in logs:
        if log.status == "failed" and log.sent_at and log.sent_at >= since:
            failed_30d += 1
        if log.user_id and log.user_id not in all_user_ids:
            _issue(
                issues,
                severity="warn",
                scope="notification",
                code="notification_user_missing",
                title="通知日志引用的用户不存在",
                detail=f"通知日志 id={log.id} 引用的用户 id={log.user_id} 不存在。",
                suggestion="这通常来自历史数据，可在备份后清理孤儿通知日志。",
                user_id=log.user_id,
            )
        if log.subscription_id and log.subscription_id not in sub_ids:
            _issue(
                issues,
                severity="warn",
                scope="notification",
                code="notification_subscription_missing",
                title="通知日志引用的订阅不存在",
                detail=f"通知日志 id={log.id} 引用的订阅 id={log.subscription_id} 不存在。",
                suggestion="这通常来自历史数据，可在备份后清理孤儿通知日志。",
                subscription_id=log.subscription_id,
            )
    if failed_30d:
        _issue(
            issues,
            severity="warn",
            scope="notification",
            code="recent_notification_failures",
            title="近 30 天存在失败通知",
            detail=f"近 30 天共有 {failed_30d} 条通知发送失败。",
            suggestion="到通知中心查看失败原因，并检查 Telegram/Bark 配置。",
        )

    counts = {"error": 0, "warn": 0, "info": 0}
    for item in issues:
        counts[item["severity"]] = counts.get(item["severity"], 0) + 1

    active_recurring = sum(1 for s in subs if s.is_active and s.billing_type == "recurring")
    return {
        "summary": {
            "errors": counts.get("error", 0),
            "warnings": counts.get("warn", 0),
            "infos": counts.get("info", 0),
            "users": len(users),
            "subscriptions": len(subs),
            "active_recurring": active_recurring,
            "notification_failures_30d": failed_30d,
        },
        "issues": issues,
    }

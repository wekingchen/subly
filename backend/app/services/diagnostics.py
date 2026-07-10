from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.billing import compute_next_renewal
from app.models import Bundle, Category, Currency, NotificationLog, PaymentMethod, Subscription, User
from app.services.scheduler import _as_local_date, _local_today, _parse_days
from app.subscription_rules import apply_keepalive_scope, category_allows_keepalive, validate_subscription_refs

VALID_BILLING_TYPES = {"recurring", "one_time"}
VALID_CYCLES = {"day", "week", "month", "year"}

# A 类：有确定性正确目标值，admin 可一键修复。scope 必为 subscription 且 issue 带 subscription_id。
# B 类（需人工判断：通知配置缺口、负金额、非法周期、孤儿日志、失败统计等）不在此列。
REPAIRABLE_CODES = frozenset({
    "category_missing", "category_not_owned",
    "payment_method_missing", "payment_method_not_owned",
    "bundle_missing", "bundle_not_owned",
    "keepalive_scope_invalid",
    "one_time_has_recurring_fields",
    "invalid_remind_days",
    "subscription_missing_next_renewal",
})


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
        if sub.category_id:
            cat = db.get(Category, sub.category_id)
            if cat is None:
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
            elif not (cat.is_system or cat.user_id is None or cat.user_id == sub.user_id):
                _issue(
                    issues,
                    severity="error",
                    scope="subscription",
                    code="category_not_owned",
                    title="订阅分类不属于该用户",
                    detail=f"订阅「{sub.name}」引用的分类「{cat.name}」属于其他用户。",
                    suggestion="编辑订阅重新选择本人或系统分类。建议同时排查写入校验是否生效。",
                    **common,
                )
        if sub.payment_method_id:
            pm = db.get(PaymentMethod, sub.payment_method_id)
            if pm is None:
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
            elif not (pm.is_system or pm.user_id is None or pm.user_id == sub.user_id):
                _issue(
                    issues,
                    severity="error",
                    scope="subscription",
                    code="payment_method_not_owned",
                    title="付款方式不属于该用户",
                    detail=f"订阅「{sub.name}」引用的付款方式「{pm.name}」属于其他用户。",
                    suggestion="编辑订阅重新选择本人或系统付款方式。建议同时排查写入校验是否生效。",
                    **common,
                )
        if sub.bundle_id:
            bundle = db.get(Bundle, sub.bundle_id)
            if bundle is None:
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
            elif bundle.user_id != sub.user_id:
                _issue(
                    issues,
                    severity="error",
                    scope="subscription",
                    code="bundle_not_owned",
                    title="套餐包不属于该用户",
                    detail=f"订阅「{sub.name}」引用的套餐包「{bundle.name}」属于其他用户。",
                    suggestion="编辑订阅重新选择本人套餐包，或移除套餐包归属。建议同时排查写入校验是否生效。",
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

    # 近 30 天失败通知：按本地自然日统计，避免 UTC 偏移在午夜边界少算一天
    since_date = _local_today() - timedelta(days=30)
    failed_30d = 0
    for log in logs:
        sent_on = _as_local_date(log.sent_at)
        if log.status == "failed" and sent_on is not None and sent_on >= since_date:
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


def _subscription_issue_codes(db: Session, sub: Subscription) -> set[str]:
    """对单个订阅重跑诊断，返回当前命中的 code 集合（修复前重判，防过期状态）。

    复用 run_data_diagnostics（不重构大循环），过滤到该订阅。
    """
    out = run_data_diagnostics(db, user_id=sub.user_id)
    return {i["code"] for i in out["issues"] if i.get("subscription_id") == sub.id}


def repair_subscription_issue(db: Session, subscription_id: int, code: str) -> dict:
    """一键修复单个订阅的单个 A 类诊断项。

    流程：定位订阅 → 重判确认当前确有该 code → 执行修复 → 复核引用合法性 → 提交。
    返回 {fixed, code, subscription_id, detail}；失败抛 ValueError（路由层转 400/404/409）。
    """
    sub = db.get(Subscription, subscription_id)
    if sub is None:
        raise ValueError("订阅不存在")
    if code not in REPAIRABLE_CODES:
        raise ValueError(f"该问题类型「{code}」不支持一键修复")
    if code not in _subscription_issue_codes(db, sub):
        raise ValueError("该问题已不存在，请刷新诊断列表后再试")

    if code in ("category_missing", "category_not_owned"):
        sub.category_id = None
    elif code in ("payment_method_missing", "payment_method_not_owned"):
        sub.payment_method_id = None
    elif code in ("bundle_missing", "bundle_not_owned"):
        sub.bundle_id = None
    elif code == "keepalive_scope_invalid":
        apply_keepalive_scope(db, sub)
    elif code == "one_time_has_recurring_fields":
        sub.next_renewal_date = None
        sub.auto_renew = False
    elif code == "invalid_remind_days":
        sub.remind_days_before = "7,1"
    elif code == "subscription_missing_next_renewal":
        # 不臆造：缺 start_date 或周期无效时拒绝，提示先修周期字段
        if not sub.start_date:
            raise ValueError("订阅缺少 start_date，无法计算续费日，请先编辑订阅补齐起始日期")
        if sub.cycle not in VALID_CYCLES:
            raise ValueError(f"订阅 cycle={sub.cycle} 无效，请先编辑订阅修正周期")
        if not sub.cycle_count or sub.cycle_count < 1:
            raise ValueError(f"订阅 cycle_count={sub.cycle_count} 无效，请先编辑订阅修正周期数量")
        sub.next_renewal_date = compute_next_renewal(sub.start_date, sub.cycle, sub.cycle_count)

    # 清分类可能影响保号适用范围（与编辑保存路径行为一致）
    if code.startswith("category_"):
        apply_keepalive_scope(db, sub)

    # 防御性复核：清掉 FK 后引用必合法（None 通过校验），不通过说明逻辑有误，响亮失败
    bad = validate_subscription_refs(
        db, sub.user_id,
        category_id=sub.category_id, payment_method_id=sub.payment_method_id, bundle_id=sub.bundle_id,
    )
    if bad:
        raise ValueError(f"修复后引用复核仍不通过：{bad}")

    db.commit()
    db.refresh(sub)
    return {
        "fixed": True, "code": code, "subscription_id": sub.id,
        "detail": f"已修复订阅「{sub.name}」的「{code}」问题",
    }

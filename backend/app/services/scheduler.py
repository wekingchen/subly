"""定时任务：每日扫描即将到期的订阅，按用户开启的通道（Telegram / Bark）发送提醒。"""
from datetime import date, datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app import activity, database
from app.config import settings
from app.models import Category, NotificationLog, PaymentMethod, Subscription, User
from app.services import bark, exchange, telegram

_scheduler: BackgroundScheduler | None = None


def _parse_days(raw: str) -> list[int]:
    out = []
    for part in (raw or "").split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out


def _already_sent(db, sub_id: int, days_before: int, channel: str, on_day: date) -> bool:
    rows = db.scalars(
        select(NotificationLog).where(
            NotificationLog.subscription_id == sub_id,
            NotificationLog.days_before == days_before,
            NotificationLog.channel == channel,
            NotificationLog.status == "sent",
        )
    ).all()
    return any(r.sent_at and r.sent_at.date() == on_day for r in rows)


def _send_one(db, sub: Subscription, user: User, n: int, today: date, channel: str, send_fn) -> tuple[bool, str]:
    """发送单条提醒并记录日志。send_fn() 内部自行抛异常表示失败。返回 (是否发送, 状态)。"""
    if _already_sent(db, sub.id, n, channel, today):
        return False, "skip"
    log = NotificationLog(
        subscription_id=sub.id,
        user_id=user.id,
        days_before=n,
        channel=channel,
        status="sent",
    )
    try:
        message = send_fn()
        log.message = message
        ok = True
        activity.log(
            f"{channel}.reminder",
            f"已提醒「{sub.name}」（提前 {n} 天，{channel}）",
            user=user,
        )
    except Exception as e:  # noqa: BLE001
        log.status = "failed"
        log.message = f"{type(e).__name__}: {e}"
        ok = False
        activity.log(
            f"{channel}.reminder",
            f"提醒「{sub.name}」发送失败（{channel}）：{e}",
            user=user,
            level="error",
        )
    log.sent_at = datetime.utcnow()
    db.add(log)
    return ok, log.status


def run_reminder_scan() -> dict:
    """核心扫描逻辑（可被定时器或手动触发调用）。"""
    today = date.today()
    sent, failed = 0, 0
    if database.SessionLocal is None:
        return {"sent": 0, "failed": 0, "skipped": "数据库未配置"}
    db = database.SessionLocal()
    try:
        subs = db.scalars(
            select(Subscription).where(
                Subscription.is_active.is_(True),
                Subscription.billing_type == "recurring",
                Subscription.next_renewal_date.is_not(None),
            )
        ).all()
        for sub in subs:
            user = db.get(User, sub.user_id)
            if not user:
                continue
            tg_ready = user.telegram_enabled and user.telegram_bot_token and user.telegram_chat_id
            bark_ready = user.bark_enabled and user.bark_device_key
            if not tg_ready and not bark_ready:
                continue
            days_left = (sub.next_renewal_date - today).days
            for n in _parse_days(sub.remind_days_before):
                if days_left != n:
                    continue
                if tg_ready:
                    text = _build_telegram_text(db, sub, user, days_left)

                    def _do_telegram():
                        telegram.send_message(
                            user.telegram_chat_id, text,
                            token=user.telegram_bot_token,
                            api_base=user.telegram_api_base,
                            proxy=user.telegram_proxy,
                        )
                        return text

                    ok, _ = _send_one(db, sub, user, n, today, "telegram", _do_telegram)
                    sent += 1 if ok else 0
                    failed += 0 if ok else 1
                if bark_ready:
                    title, body = _build_bark_text(db, sub, user, days_left)

                    def _do_bark():
                        bark.send_push(
                            user.bark_device_key, title, body,
                            server=user.bark_server,
                            sound=user.bark_sound,
                            group=user.bark_group,
                        )
                        return f"{title}\n{body}"

                    ok, _ = _send_one(db, sub, user, n, today, "bark", _do_bark)
                    sent += 1 if ok else 0
                    failed += 0 if ok else 1
        db.commit()
    finally:
        db.close()
    return {"sent": sent, "failed": failed}


_CYCLE_CN = {"day": "天", "week": "周", "month": "个月", "year": "年"}


def _escape_md(text: str) -> str:
    """转义 Markdown 中可能破坏排版的下划线/星号，保证名称等原样显示。"""
    if not text:
        return ""
    for ch in ("_", "*", "`", "["):
        text = text.replace(ch, "\\" + ch)
    return text


def _renewal_facts(db, sub: Subscription, user: User, days_left: int):
    """提醒文案的共用要素，避免 Telegram / Bark 两份文案逻辑分叉走偏。"""
    amount = f"{sub.amount:.2f} {sub.currency}"
    in_base = exchange.convert(db, sub.amount, sub.currency, user.base_currency)
    base_str = ""
    if abs(in_base - sub.amount) > 1e-6 or sub.currency != user.base_currency:
        base_str = f"（≈ {in_base:.2f} {user.base_currency}）"
    cat = db.get(Category, sub.category_id) if sub.category_id else None
    pm = db.get(PaymentMethod, sub.payment_method_id) if sub.payment_method_id else None
    unit = _CYCLE_CN.get(sub.cycle, sub.cycle)
    cycle_str = f"每 {sub.cycle_count} {unit}" if (sub.cycle_count or 1) > 1 else f"每{unit}"
    title = sub.name + (f"（{sub.plan}）" if sub.plan else "")
    return {
        "amount": amount, "base_str": base_str, "cat": cat, "pm": pm,
        "cycle_str": cycle_str, "title": title,
    }


def _build_telegram_text(db, sub: Subscription, user: User, days_left: int) -> str:
    """构造一条信息完整、措辞友好的续费提醒（Telegram Markdown）。"""
    f = _renewal_facts(db, sub, user, days_left)
    if days_left <= 0:
        when = "⚠️ *今天到期*"
        head = "🔔 *续费提醒*｜今天就到期啦"
    else:
        when = f"还有 *{days_left}* 天"
        head = f"🔔 *续费提醒*｜还有 {days_left} 天到期"

    lines = [head, ""]
    title = _escape_md(f["title"])
    lines.append(f"📦 项目：*{title}*")
    if f["cat"]:
        lines.append(f"🗂️ 分类：{_escape_md(f['cat'].name)}")
    lines.append(f"📅 到期：*{sub.next_renewal_date}*（{when}）")
    lines.append(f"💰 金额：*{f['amount']}*{f['base_str']} · {f['cycle_str']}")
    if f["pm"]:
        lines.append(f"💳 付款：{_escape_md(f['pm'].name)}")
    lines.append(f"🔁 自动续费：{'开' if sub.auto_renew else '关'}")
    if sub.family_members:
        lines.append(f"👨‍👩‍👧 家庭成员：{_escape_md('、'.join(sub.family_members))}")
    if sub.remark:
        lines.append(f"📝 备注：{_escape_md(sub.remark)}")
    if sub.url:
        lines.append(f"🔗 官网：{sub.url}")

    lines.append("")
    if days_left <= 0:
        lines.append("👉 别忘了今天处理一下，保号 / 续费就万无一失～")
    else:
        lines.append("👉 早点安排续费，省心又安心，避免到期失效～")
    return "\n".join(lines)


def _build_bark_text(db, sub: Subscription, user: User, days_left: int) -> tuple[str, str]:
    """构造 Bark 推送的 (标题, 正文)。Bark 通知栏空间有限，正文保持简洁、不带 Markdown 符号。"""
    f = _renewal_facts(db, sub, user, days_left)
    if days_left <= 0:
        title = f"⚠️ 今天到期：{f['title']}"
    else:
        title = f"🔔 还有 {days_left} 天到期：{f['title']}"

    parts = [f"金额：{f['amount']}{f['base_str']} · {f['cycle_str']}", f"到期：{sub.next_renewal_date}"]
    if f["cat"]:
        parts.append(f"分类：{f['cat'].name}")
    if f["pm"]:
        parts.append(f"付款：{f['pm'].name}")
    if sub.remark:
        parts.append(f"备注：{sub.remark}")
    body = " · ".join(parts)
    return title, body


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    hour, minute = 9, 0
    try:
        hour, minute = (int(x) for x in settings.reminder_scan_time.split(":"))
    except Exception:  # noqa: BLE001
        pass

    _scheduler = BackgroundScheduler(timezone=settings.tz)
    _scheduler.add_job(
        run_reminder_scan,
        CronTrigger(hour=hour, minute=minute),
        id="daily_reminder_scan",
        replace_existing=True,
    )
    # 每天凌晨 4 点刷新汇率
    _scheduler.add_job(
        _refresh_rates_job,
        CronTrigger(hour=4, minute=0),
        id="daily_rate_refresh",
        replace_existing=True,
    )
    _scheduler.start()


def _refresh_rates_job() -> None:
    if database.SessionLocal is None:
        return
    db = database.SessionLocal()
    try:
        exchange.refresh_rates(db)
    except Exception:  # noqa: BLE001
        pass
    finally:
        db.close()


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None

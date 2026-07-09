"""定时任务：每日扫描即将到期的订阅，按用户开启的通道（Telegram / Bark）发送提醒。"""
import logging
from datetime import date, datetime, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - 仅缺 tzdata 的环境兜底
    ZoneInfo = None  # type: ignore[assignment]

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import activity, database
from app.config import settings
from app.models import Category, NotificationLog, PaymentMethod, Subscription, User
from app.services import bark, exchange, telegram

_scheduler: BackgroundScheduler | None = None
logger = logging.getLogger(__name__)


def _local_zone():
    """本地业务时区（来自 settings.tz）。

    ZoneInfo 不可用或 settings.tz 配置错误时退回 UTC 以保证扫描不崩溃，但会打 warning
    日志--按「失败要响亮」，静默退回 UTC 会让提醒按错误日期判日且难以定位。
    """
    if ZoneInfo is None:
        logger.warning("event=local_zone_fallback reason=zoneinfo_unavailable tz=%s -> UTC", settings.tz)
        return timezone.utc
    try:
        return ZoneInfo(settings.tz)
    except Exception as e:  # noqa: BLE001 - 配置错误的时区名不应让扫描崩溃
        logger.warning("event=local_zone_fallback reason=invalid_tz tz=%s error=%s -> UTC", settings.tz, e)
        return timezone.utc


def _local_today() -> date:
    """本地今天的日期。提醒去重以本地日历日为准，避免 UTC 偏移导致日期错位。"""
    return datetime.now(_local_zone()).date()


def _as_local_date(value) -> date | None:
    """把存储为 naive UTC 的 sent_at 转成本地日期；None / 非法值返回 None。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return aware.astimezone(_local_zone()).date()
    # 退化为 date 本身（如未来传入业务日期）
    return value if isinstance(value, date) else None


def _parse_days(raw: str) -> list[int]:
    out = []
    for part in (raw or "").split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out


def _unique_days(raw: str) -> list[int]:
    """去重后的提醒天数，保持首次出现顺序。生产扫描与 dry-run 共用，确保两者一致。"""
    return list(dict.fromkeys(_parse_days(raw)))


def _already_sent(db, sub_id: int, days_before: int, channel: str, on_day: date) -> bool:
    rows = db.scalars(
        select(NotificationLog).where(
            NotificationLog.subscription_id == sub_id,
            NotificationLog.days_before == days_before,
            NotificationLog.channel == channel,
            NotificationLog.status == "sent",
        )
    ).all()
    return any(_as_local_date(r.sent_at) == on_day for r in rows)


def _send_one(
    db, sub: Subscription, user: User, n: int, today: date, channel: str, send_fn, seen: set | None = None
) -> tuple[bool, str]:
    """发送单条提醒并记录日志。send_fn() 内部自行抛异常表示失败。返回 (是否发送, 状态)。

    seen 为本次扫描内已处理的 (订阅, 天数, 通道) 集合：生产 SessionLocal 为
    autoflush=False，未提交的 log 不可见，靠 DB 查询无法在同一次扫描内去重，故用
    内存集合兜底（不依赖 db.flush，避免外发期间长持 SQLite 写锁）。
    """
    key = (sub.id, n, channel)
    if seen is not None and key in seen:
        return False, "skip"
    if _already_sent(db, sub.id, n, channel, today):
        if seen is not None:
            seen.add(key)
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
        log.message = exchange.safe_error_message(e)
        ok = False
        activity.log(
            f"{channel}.reminder",
            f"提醒「{sub.name}」发送失败（{channel}）：{log.message}",
            user=user,
            level="error",
        )
    log.sent_at = datetime.utcnow()
    db.add(log)
    if seen is not None:
        seen.add(key)
    return ok, log.status


def run_reminder_scan() -> dict:
    """核心扫描逻辑（可被定时器或手动触发调用）。"""
    today = _local_today()
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
        seen: set[tuple[int, int, str]] = set()  # 同一次扫描内 (订阅, 天数, 通道) 去重
        for sub in subs:
            user = db.get(User, sub.user_id)
            if not user:
                continue
            if not user.is_active:
                continue  # 禁用用户不参与提醒扫描
            tg_ready = user.telegram_enabled and user.telegram_bot_token and user.telegram_chat_id
            bark_ready = user.bark_enabled and user.bark_device_key
            if not tg_ready and not bark_ready:
                continue
            days_left = (sub.next_renewal_date - today).days
            for n in _unique_days(sub.remind_days_before):
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

                    ok, _ = _send_one(db, sub, user, n, today, "telegram", _do_telegram, seen)
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
                            ttl=user.bark_ttl,
                            url=sub.url,
                        )
                        return f"{title}\n{body}"

                    ok, _ = _send_one(db, sub, user, n, today, "bark", _do_bark, seen)
                    sent += 1 if ok else 0
                    failed += 0 if ok else 1
        db.commit()
    finally:
        db.close()
    return {"sent": sent, "failed": failed}


_CYCLE_CN = {"day": "天", "week": "周", "month": "月", "year": "年"}


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
        base_str = f"（约 {in_base:.2f} {user.base_currency}）"
    cat = db.get(Category, sub.category_id) if sub.category_id else None
    pm = db.get(PaymentMethod, sub.payment_method_id) if sub.payment_method_id else None
    unit = _CYCLE_CN.get(sub.cycle, sub.cycle)
    cycle_str = f"每 {sub.cycle_count} {unit}" if (sub.cycle_count or 1) > 1 else f"每{unit}"
    title = sub.name + (f"（{sub.plan}）" if sub.plan else "")
    return {
        "amount": amount, "base_str": base_str, "cat": cat, "pm": pm,
        "cycle_str": cycle_str, "title": title, "is_keepalive": sub.is_keepalive,
    }


def _build_telegram_text(db, sub: Subscription, user: User, days_left: int) -> str:
    """构造一条信息完整、措辞友好的提醒（Telegram Markdown）。保号订阅切保号文案。"""
    f = _renewal_facts(db, sub, user, days_left)
    ka = f["is_keepalive"]
    if days_left <= 0:
        when = "⚠️ *今天需保号*" if ka else "⚠️ *今天到期*"
        head = "🔔 *保号提醒*｜今天该保号啦" if ka else "🔔 *续费提醒*｜今天就到期啦"
    else:
        when = f"还有 *{days_left}* 天"
        head = f"🔔 *保号提醒*｜还有 {days_left} 天需保号" if ka else f"🔔 *续费提醒*｜还有 {days_left} 天到期"

    lines = [head, ""]
    title = _escape_md(f["title"])
    lines.append(f"📦 项目：*{title}*")
    if f["cat"]:
        lines.append(f"🗂️ 分类：{_escape_md(f['cat'].name)}")
    date_label = "保号日" if ka else "到期"
    lines.append(f"📅 {date_label}：*{sub.next_renewal_date}*（{when}）")
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
    if ka:
        lines.append("👉 记得发条短信保号，避免停机失号～" if days_left > 0
                     else "👉 今天发一条短信就能保号，别拖到停机～")
    else:
        lines.append("👉 别忘了今天处理一下，保号 / 续费就万无一失～" if days_left <= 0
                     else "👉 早点安排续费，省心又安心，避免到期失效～")
    return "\n".join(lines)


def _cn_date(d) -> str:
    """date → 中文月日，如 7 月 14 日。"""
    return f"{d.month} 月 {d.day} 日"


def _is_cjk(ch: str) -> bool:
    return bool(ch) and '一' <= ch <= '鿿'


def _cn_join(a: str, b: str) -> str:
    """中文排版：a 末字符与 b 首字符若一中一非中文（英文/数字），插入一个空格；否则直接拼接。
    先规范化边界空白，避免用户输入带前后空格时产生双空格。"""
    if not a or not b:
        return (a + b).strip()
    a0, b0 = a.rstrip(), b.lstrip()
    if _is_cjk(a0[-1]) != _is_cjk(b0[0]):
        return f"{a0} {b0}"
    return a0 + b0


def _build_bark_text(db, sub: Subscription, user: User, days_left: int) -> tuple[str, str]:
    """构造 Bark 推送的 (标题, 正文)。保号订阅切保号文案。
    标题只留名称+天数；正文是一句完整的话，套餐/付款/备注/分类有才说。"""
    f = _renewal_facts(db, sub, user, days_left)
    ka = f["is_keepalive"]
    if days_left <= 0:
        title = f"⚠️ {sub.name} 今天该保号" if ka else f"⚠️ {sub.name} 今天到期"
        due_clause = "今天就需保号" if ka else "今天就到期"
    else:
        title = f"🔔 {sub.name} 还有 {days_left} 天需保号" if ka else f"🔔 {sub.name} 还有 {days_left} 天到期"
        verb = "需保号" if ka else "到期"
        due_clause = f"{_cn_date(sub.next_renewal_date)}{verb}"

    # 句子化正文：套餐起头 → 每月金额（折算） → 到期/保号 → 付款/备注/分类（有才带标签）
    parts = []
    if sub.plan:
        parts.append(_cn_join(sub.plan, "套餐"))
    parts.append(f"{f['cycle_str']} {f['amount']}{f['base_str']}")
    parts.append(due_clause)
    if f["pm"]:
        parts.append(_cn_join(_cn_join("由", f["pm"].name), "扣款"))
    if sub.remark:
        parts.append(f"备注：{sub.remark}")
    if f["cat"]:
        parts.append(f"分类：{f['cat'].name}")
    body = "，".join(parts) + "。"
    return title, body


def _simulation_channels(channel: str) -> list[str]:
    if channel == "telegram":
        return ["telegram"]
    if channel == "bark":
        return ["bark"]
    return ["telegram", "bark"]


def _append_simulation_item(items: list[dict], limit: int, item: dict) -> None:
    if len(items) < limit:
        items.append(item)


def simulate_reminder_scan(
    db: Session,
    as_of: date,
    user_id: int | None = None,
    subscription_id: int | None = None,
    channel: str = "all",
    include_skipped: bool = True,
    limit: int = 200,
) -> dict:
    """提醒 dry-run：复用真实提醒筛选与文案构造，不外发、不写 NotificationLog。"""
    stmt = select(Subscription).order_by(
        Subscription.next_renewal_date.is_(None),
        Subscription.next_renewal_date,
        Subscription.id,
    )
    if user_id is not None:
        stmt = stmt.where(Subscription.user_id == user_id)
    if subscription_id is not None:
        stmt = stmt.where(Subscription.id == subscription_id)
    subs = db.scalars(stmt).all()
    channels = _simulation_channels(channel)
    summary = {
        "scanned": len(subs),
        "would_send": 0,
        "skipped": 0,
        "telegram": 0,
        "bark": 0,
        "already_sent": 0,
        "channel_not_ready": 0,
        "invalid": 0,
        "returned": 0,
    }
    items: list[dict] = []

    def add(item: dict) -> None:
        if item["status"] == "would_send":
            summary["would_send"] += 1
            if item["channel"] in ("telegram", "bark"):
                summary[item["channel"]] += 1
        else:
            summary["skipped"] += 1
            if item["status"] == "already_sent":
                summary["already_sent"] += 1
            if item["status"] == "channel_not_ready":
                summary["channel_not_ready"] += 1
            if item["status"] in ("invalid_reminder_days", "missing_next_renewal", "inactive", "not_recurring"):
                summary["invalid"] += 1
        if include_skipped or item["status"] == "would_send":
            _append_simulation_item(items, limit, item)
            summary["returned"] = len(items)

    for sub in subs:
        user = db.get(User, sub.user_id)
        if not user:
            continue
        if not user.is_active:
            continue  # 与真实扫描一致：禁用用户不参与提醒
        base = {
            "user_id": user.id,
            "username": user.username,
            "subscription_id": sub.id,
            "subscription_name": sub.name,
            "is_keepalive": sub.is_keepalive,
            "next_renewal_date": sub.next_renewal_date,
            "days_left": None,
            "days_before": None,
            "title": None,
            "body": None,
            "preview": None,
        }
        if not sub.is_active:
            add({**base, "channel": "all", "status": "inactive", "reason": "订阅未启用，提醒扫描会跳过。"})
            continue
        if sub.billing_type != "recurring":
            add({**base, "channel": "all", "status": "not_recurring", "reason": "一次性买断订阅不参与提醒扫描。"})
            continue
        if not sub.next_renewal_date:
            add({**base, "channel": "all", "status": "missing_next_renewal", "reason": "周期订阅缺少下次续费日。"})
            continue
        reminder_days = _unique_days(sub.remind_days_before)
        if not reminder_days:
            add({**base, "channel": "all", "status": "invalid_reminder_days", "reason": "提前提醒配置中没有有效数字。"})
            continue
        days_left = (sub.next_renewal_date - as_of).days
        due_days = [n for n in reminder_days if n == days_left]
        if not due_days:
            add({**base, "days_left": days_left, "channel": "all", "status": "not_due", "reason": f"距离日期为 {days_left} 天，未命中提前提醒配置。"})
            continue
        for days_before in due_days:
            for ch in channels:
                tg_ready = user.telegram_enabled and user.telegram_bot_token and user.telegram_chat_id
                bark_ready = user.bark_enabled and user.bark_device_key
                ready = tg_ready if ch == "telegram" else bark_ready
                item = {**base, "days_left": days_left, "days_before": days_before, "channel": ch}
                if not ready:
                    add({**item, "status": "channel_not_ready", "reason": f"{ch} 通道未启用或配置不完整。"})
                    continue
                if _already_sent(db, sub.id, days_before, ch, as_of):
                    add({**item, "status": "already_sent", "reason": "同一天同通道已有成功提醒记录。"})
                    continue
                if ch == "telegram":
                    text = _build_telegram_text(db, sub, user, days_left)
                    add({**item, "status": "would_send", "reason": "模拟日期命中提醒规则，且通道配置完整。", "body": text, "preview": text})
                else:
                    title, body = _build_bark_text(db, sub, user, days_left)
                    add({**item, "status": "would_send", "reason": "模拟日期命中提醒规则，且通道配置完整。", "title": title, "body": body, "preview": f"{title}\n{body}"})

    return {"summary": summary, "items": items}


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    hour, minute = 9, 0
    try:
        hour, minute = (int(x) for x in settings.reminder_scan_time.split(":"))
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "event=scheduler_invalid_reminder_scan_time value=%s fallback=09:00 error_type=%s",
            settings.reminder_scan_time, type(e).__name__, exc_info=True,
        )

    # 统一用兜底后的业务时区：settings.tz 非法时 _local_zone() 会回退 UTC 并打 warning，
    # 若直接把原始字符串传给 BackgroundScheduler，APScheduler 构造期就会抛错导致进程启动失败。
    tz = _local_zone()
    _scheduler = BackgroundScheduler(timezone=tz)
    _scheduler.add_job(
        run_reminder_scan,
        CronTrigger(hour=hour, minute=minute, timezone=tz),
        id="daily_reminder_scan",
        replace_existing=True,
    )
    # 每天凌晨 4 点刷新汇率
    _scheduler.add_job(
        _refresh_rates_job,
        CronTrigger(hour=4, minute=0, timezone=tz),
        id="daily_rate_refresh",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(
        "event=scheduler_started reminder_scan_time=%02d:%02d timezone=%s",
        hour, minute, settings.tz,
    )


def _refresh_rates_job() -> None:
    if database.SessionLocal is None:
        return
    db = database.SessionLocal()
    try:
        count = exchange.refresh_rates(db)
        logger.info("event=exchange_refresh_job_done updated=%s", count)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "event=exchange_refresh_job_failed error_type=%s status_code=%s",
            type(e).__name__, exchange.error_status_code(e),
        )
    finally:
        db.close()


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        logger.info("event=scheduler_stopped")
        _scheduler = None

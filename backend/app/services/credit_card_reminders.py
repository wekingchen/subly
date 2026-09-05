"""信用卡计划还款提醒候选规划与文案。"""

import threading
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import database
from app.credit_card_rules import next_due_date_after
from app.models import CreditCard, CreditCardStatement, User
from app.services import credit_card_notification_outbox, notification_transport

_scan_lock = threading.Lock()
_CHANNELS = ("telegram", "bark", "webhook")


def _app_public_url() -> str | None:
    """读 APP_PUBLIC_URL 配置（Bark 图标绝对化用）；函数化便于测试 monkeypatch。"""
    from app.config import settings

    return settings.app_public_url or None


def _cn_date(value: date) -> str:
    return f"{value.month} 月 {value.day} 日"


def _escape_markdown(value: str) -> str:
    text = value
    for char in ("_", "*", "`", "["):
        text = text.replace(char, "\\" + char)
    return text


def _sanitize_label(value: str, last_four: str) -> str:
    """外发名称净化（卡片名与银行名同规则，复审 Low：完整逻辑收拢一处）：
    剥离与尾号完全相同的数字序列——且仅在实际发生剥离时做「剩余无实质
    字符则置空」判定（未发生剥离的「（）」这类纯标点输入保持原样，避免
    行为漂移）。不笼统禁所有 4 位数字，避免误伤年份等正常别名。
    """
    if last_four and last_four in value:
        value = value.replace(last_four, "").strip()
        value = " ".join(value.split())
        if not any(char.isalnum() for char in value):
            value = ""
    return value


def external_bank_label(card: CreditCard) -> str:
    """外发使用的银行名：与卡片标签同规则净化尾号（审核 Medium——用户可能
    把尾号写进 bank_name，如「招商银行 1234」；「（1234）」剥离后仅剩标点
    一并回退）。空值回退「信用卡」。"""
    bank = _sanitize_label(card.bank_name or "", (card.last_four or "").strip())
    return bank or "信用卡"


def external_card_label(card: CreditCard) -> str:
    """外发（iCal / 通知）使用的卡片标签：剥离与尾号相同的 4 位数字序列。

    用户可能把尾号写进 display_name（如「主卡 1234」）；last_four 本身虽不直接
    序列化，但名称会原样进入 iCal 与外部通知，等于间接泄露。这里在外部输出边界
    统一净化（_sanitize_label）；不笼统禁所有 4 位数字，避免误伤年份等正常别名。
    剥离后若只剩标点/空白等无实质内容（如「（1234）」→「（）」），回退为「信用卡」。
    """
    label = _sanitize_label(card.display_name or "", (card.last_four or "").strip())
    return label or "信用卡"


def latest_unrepaid_amount(db: Session, card: CreditCard) -> float | None:
    """该卡最新一期未标记还款的勾稽通过账单应还金额（与待还汇总同口径：
    最新账单为正即待还、为负即富余）。

    「最新」比较键与 outstanding_summary 一致：statement_date 优先、缺失
    回退 bill_period_end（coalesce）。两日期皆空的账单在汇总里不参与
    「最新」判定、保留逐期累加——提醒与之对齐：优先取有日期的最新账单
    金额；卡上只有双空账单时聚合全部已知金额之和（与汇总累加口径一致），
    全部金额未知时返回 None（文案回退「金额以银行账单为准」，不猜）。
    """
    dated = db.scalar(
        select(CreditCardStatement).where(
            CreditCardStatement.card_id == card.id,
            CreditCardStatement.is_repaid.is_(False),
            CreditCardStatement.verify_status == "ok",
            CreditCardStatement.statement_date.is_not(None)
            | CreditCardStatement.bill_period_end.is_not(None),
        ).order_by(
            func.coalesce(
                CreditCardStatement.statement_date, CreditCardStatement.bill_period_end
            ).desc(),
            CreditCardStatement.id.desc(),
        ).limit(1)
    )
    if dated is not None:
        return float(dated.total_due) if dated.total_due is not None else None
    # 全部账单双日期皆空：与汇总累加口径完全对齐（复审 Low）——
    # 聚合同卡全部未还勾稽通过账单的已知金额之和；全部金额未知时返回
    # None（不能把未知伪装成 0.00 元，复审 Low）
    rows = db.scalars(
        select(CreditCardStatement).where(
            CreditCardStatement.card_id == card.id,
            CreditCardStatement.is_repaid.is_(False),
            CreditCardStatement.verify_status == "ok",
        )
    ).all()
    if not rows:
        return None
    known = [float(s.total_due) for s in rows if s.total_due is not None]
    return round(sum(known), 2) if known else None


def _fmt_amount(amount: float) -> str:
    return f"{amount:,.2f}"


def _amount_phrase(amount: float | None) -> str:
    """金额短语：正数=应还；负数=富余（不参与还款，提示免忧）；None=未知。"""
    if amount is None:
        return "应还金额以银行账单为准"
    if amount < 0:
        return f"账上有富余 {_fmt_amount(-amount)} 元，本期无需还款"
    return f"应还 {_fmt_amount(amount)} 元"


def _bark_icon(card: CreditCard, app_public_url: str | None) -> str | None:
    """Bark 推送图标（用户确认口径）：收录银行的官方徽标（内置图标库，
    与日历事件/卡片徽标同源）；未收录银行回退 Subly logo。
    银行识别复用 match_bank.bank_matches_card（与账单关联/前端徽标同口径，
    审核 Low：不再自建第三套匹配规则）。app_public_url 未配置时返回 None
    （Bark 显示默认图标，推送不受影响）。"""
    from app.bank_senders import BANK_SENDER_DOMAINS, BANK_KEYS
    from app.icon_library import slug_for_domain
    from app.services import bark
    from app.services.match_bank import bank_matches_card

    bank_key = next(
        (k for k in BANK_KEYS if bank_matches_card(card.bank_name, k)), None
    )
    icon_path = (
        f"/api/icons/library/{slug_for_domain(BANK_SENDER_DOMAINS[bank_key]['domains'][0])}"
        if bank_key else "/pwa-192.png"
    )
    return bark.resolve_push_icon_url(icon_path, app_public_url)


def _build_payload(
    card: CreditCard, due_date: date, days_before: int, channel: str,
    amount: float | None = None,
    app_public_url: str | None = None,
) -> dict:
    """三通道提醒文案（用户确认口径：银行+卡名、金额、倒计时）。

    amount 由调用方查库传入（plan_reminder_candidates）；直接调用本函数的
    测试/工具未查库时为 None → 文案回退「金额以银行账单为准」。
    app_public_url 供 Bark 图标解析为设备可下载的绝对 URL；未配置时
    Bark 推送不带图标（显示默认图标，推送不受影响）。
    """
    safe_name = external_card_label(card)
    bank = external_bank_label(card)
    amount_phrase = _amount_phrase(amount)
    title = f"💳 {bank} · {safe_name} 还款提醒"
    day_word = "今天" if days_before == 0 else f"还有 {days_before} 天"
    body = (
        f"距还款日 {_cn_date(due_date)} {day_word}，{amount_phrase}。"
        "金额和处理状态以银行账单为准。"
    )
    if channel == "telegram":
        amount_line = {
            None: "ℹ️ 应还金额以银行账单为准。",
        }.get(amount) if amount is None else (
            f"💰 账上有富余 {_escape_markdown(_fmt_amount(-amount))} 元，本期无需还款。"
            if amount < 0 else
            f"💰 应还：*{_escape_markdown(_fmt_amount(amount))}* 元"
        )
        return {
            "text": "\n".join([
                f"🔔 *{_escape_markdown(title)}*",
                "",
                f"💳 卡片：{_escape_markdown(bank)} · {_escape_markdown(safe_name)}",
                f"📅 还款日：*{due_date}*（{day_word}）",
                amount_line,
                "ℹ️ 金额和处理状态以银行账单为准。",
            ])
        }
    if channel == "bark":
        return {"title": title, "body": body, "icon": _bark_icon(card, app_public_url)}
    return {
        "event": {
            "event": "credit_card.repayment.reminder",
            "version": 1,
            "credit_card_id": card.id,
            "name": safe_name,
            "bank_name": bank,
            "due_date": due_date.isoformat(),
            "days_before": days_before,
            "total_due": amount,
            "title": title,
            "body": body,
        }
    }


def plan_reminder_candidates(
    db: Session,
    as_of: date,
    *,
    user_id: int | None = None,
    credit_card_id: int | None = None,
    channel: str = "all",
    app_public_url: str | None = None,
) -> dict:
    """确定性规划信用卡提醒；不写库、不联网。

    app_public_url 供 Bark 推送图标解析（银行徽标/Subly logo → 绝对 URL）。
    """
    stmt = select(CreditCard).order_by(CreditCard.id)
    if user_id is not None:
        stmt = stmt.where(CreditCard.user_id == user_id)
    if credit_card_id is not None:
        stmt = stmt.where(CreditCard.id == credit_card_id)
    cards = db.scalars(stmt).all()
    selected_channels = [channel] if channel in _CHANNELS else list(_CHANNELS)
    candidates: list[dict] = []
    due_card_ids: set[int] = set()
    # 先筛出到期卡再查金额（避免为不提醒的卡查库）。
    # user 随卡片存入元组——第二轮若复用循环残留的局部变量会把 A 卡的
    # 提醒按 B 用户的通道配置入队（审核 High：多用户漏发/跨用户取消）
    due_cards: list[tuple[CreditCard, User, date, int]] = []
    for card in cards:
        user = db.get(User, card.user_id)
        if not user or not user.is_active or not card.is_active:
            continue
        # 已还款顺延：标记过的期次不再产生提醒候选（当期静默）
        due_date = next_due_date_after(
            as_of, card.due_day, repaid_through=card.repaid_through_due
        )
        days_left = (due_date - as_of).days
        reminder_days = card.remind_days_before or []
        if days_left not in reminder_days:
            continue
        due_cards.append((card, user, due_date, days_left))

    # 提醒文案金额（用户确认口径）：每张到期卡查一次最新未还账单应还
    amount_by_card: dict[int, float | None] = {
        card.id: latest_unrepaid_amount(db, card) for card, _, _, _ in due_cards
    }

    for card, user, due_date, days_left in due_cards:
        for selected_channel in selected_channels:
            state, _ = notification_transport.channel_config(user, selected_channel)
            if state != "ready":
                continue
            due_card_ids.add(card.id)
            # 提醒文案金额：查一次即可（三通道同额），N 通道共享
            amount = amount_by_card.get(card.id)
            candidates.append({
                "credit_card_id": card.id,
                "user_id": user.id,
                "business_date": as_of,
                "due_date": due_date,
                "days_before": days_left,
                "channel": selected_channel,
                "credit_card_name": external_card_label(card),
                "payload": _build_payload(
                card, due_date, days_left, selected_channel, amount,
                app_public_url=app_public_url,
            ),
            })
    return {
        "scanned": len(cards),
        "candidates": candidates,
        "due_credit_card_ids": due_card_ids,
    }


def run_reminder_scan(as_of: date) -> dict:
    """扫描信用卡提醒并原子写入独立 Outbox。"""
    if not _scan_lock.acquire(blocking=False):
        return {
            "scanned": 0,
            "enqueued": 0,
            "existing": 0,
            "skipped": "已有信用卡扫描在运行",
        }
    if database.SessionLocal is None:
        _scan_lock.release()
        return {
            "scanned": 0,
            "enqueued": 0,
            "existing": 0,
            "skipped": "数据库未配置",
        }
    db = database.SessionLocal()
    try:
        planned = plan_reminder_candidates(
            db, as_of, app_public_url=_app_public_url()
        )
        enqueued = credit_card_notification_outbox.enqueue_candidates(
            db, planned["candidates"]
        )
        credit_card_notification_outbox.mark_scan_completed(db, as_of)
        db.commit()
        candidate_count = len(planned["candidates"])
        return {
            "scanned": planned["scanned"],
            "enqueued": enqueued,
            "existing": candidate_count - enqueued,
            "skipped": planned["scanned"] - len(planned["due_credit_card_ids"]),
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
        _scan_lock.release()

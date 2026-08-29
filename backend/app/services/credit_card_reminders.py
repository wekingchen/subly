"""信用卡计划还款提醒候选规划与文案。"""

import threading
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import database
from app.credit_card_rules import next_due_date
from app.models import CreditCard, User
from app.services import credit_card_notification_outbox, notification_transport

_scan_lock = threading.Lock()
_CHANNELS = ("telegram", "bark", "webhook")


def _cn_date(value: date) -> str:
    return f"{value.month} 月 {value.day} 日"


def _escape_markdown(value: str) -> str:
    text = value
    for char in ("_", "*", "`", "["):
        text = text.replace(char, "\\" + char)
    return text


def external_card_label(card: CreditCard) -> str:
    """外发（iCal / 通知）使用的卡片标签：剥离与尾号相同的 4 位数字序列。

    用户可能把尾号写进 display_name（如「主卡 1234」）；last_four 本身虽不直接
    序列化，但名称会原样进入 iCal 与外部通知，等于间接泄露。这里在外部输出边界
    统一净化；不笼统禁所有 4 位数字，避免误伤年份等正常别名。
    剥离后若只剩标点/空白等无实质内容（如「（1234）」→「（）」），回退为「信用卡」。
    """
    label = card.display_name or ""
    last_four = (card.last_four or "").strip()
    if last_four and last_four in label:
        label = label.replace(last_four, "").strip()
        label = " ".join(label.split())
        if not any(char.isalnum() for char in label):
            label = ""
    return label or "信用卡"


def _build_payload(card: CreditCard, due_date: date, days_before: int, channel: str) -> dict:
    title = "信用卡计划还款提醒"
    safe_name = external_card_label(card)
    body = (
        f"{safe_name}的计划还款日是 {_cn_date(due_date)}。"
        "实际金额和处理状态请以银行账单为准。"
    )
    if channel == "telegram":
        return {
            "text": "\n".join([
                f"🔔 *{title}*",
                "",
                f"💳 卡片：{_escape_markdown(safe_name)}",
                f"📅 计划还款日：*{due_date}*",
                "ℹ️ 实际金额和处理状态请以银行账单为准。",
            ])
        }
    if channel == "bark":
        return {"title": title, "body": body}
    return {
        "event": {
            "event": "credit_card.repayment.reminder",
            "version": 1,
            "credit_card_id": card.id,
            "name": safe_name,
            "bank_name": card.bank_name,
            "due_date": due_date.isoformat(),
            "days_before": days_before,
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
) -> dict:
    """确定性规划信用卡提醒；不写库、不联网。"""
    stmt = select(CreditCard).order_by(CreditCard.id)
    if user_id is not None:
        stmt = stmt.where(CreditCard.user_id == user_id)
    if credit_card_id is not None:
        stmt = stmt.where(CreditCard.id == credit_card_id)
    cards = db.scalars(stmt).all()
    selected_channels = [channel] if channel in _CHANNELS else list(_CHANNELS)
    candidates: list[dict] = []
    due_card_ids: set[int] = set()

    for card in cards:
        user = db.get(User, card.user_id)
        if not user or not user.is_active or not card.is_active:
            continue
        due_date = next_due_date(as_of, card.due_day)
        days_left = (due_date - as_of).days
        reminder_days = card.remind_days_before or []
        if days_left not in reminder_days:
            continue
        for selected_channel in selected_channels:
            state, _ = notification_transport.channel_config(user, selected_channel)
            if state != "ready":
                continue
            due_card_ids.add(card.id)
            candidates.append({
                "credit_card_id": card.id,
                "user_id": user.id,
                "business_date": as_of,
                "due_date": due_date,
                "days_before": days_left,
                "channel": selected_channel,
                "credit_card_name": external_card_label(card),
                "payload": _build_payload(card, due_date, days_left, selected_channel),
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
        planned = plan_reminder_candidates(db, as_of)
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

"""数据备份与恢复：导出/导入数据。

应对场景：重新部署后数据丢失。用户可随时把自己的订阅及自定义分类/付款方式/
捆绑包/货币导出为一个 JSON 文件离线保存，重装后再导入恢复。
普通用户只能导出/导入自己的数据；管理员还可整站备份/恢复全部成员的数据。
"""
import math
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session

from app import activity
from app.billing import compute_next_renewal
from app.config import settings
from app.database import get_db
from app.deps import get_admin_user, get_current_user
from app.models import (
    Bundle,
    Category,
    CreditCard,
    CreditCardNotificationLog,
    CreditCardNotificationOutbox,
    CreditCardStatement,
    CreditCardStatementItem,
    CreditCardStatementPollRun,
    Currency,
    ImapAccount,
    ExchangeRate,
    NotificationLog,
    NotificationOutbox,
    PaymentMethod,
    RenewalHistory,
    Subscription,
    User,
)
from app.schemas import CreditCardIn, normalize_currency_code, sanitize_url
from app.services import (
    credit_card_notification_outbox,
    exchange,
    notification_outbox,
    scheduler,
)
from app.services.scheduler import utcnow
from app.security import hash_password
from app.subscription_rules import (
    apply_keepalive_scope,
    currency_allowed_for_user,
    custom_currency_has_rate,
)

router = APIRouter(prefix="/api/backup", tags=["backup"])

EXPORT_VERSION = 4


def _sub_dict(s: Subscription, history: list[RenewalHistory]) -> dict:
    return {
        "name": s.name,
        "plan": s.plan,
        "icon": s.icon,
        "url": s.url,
        "notes": s.notes,
        "remark": s.remark,
        "ipv4": s.ipv4,
        "ipv6": s.ipv6,
        "category_id": s.category_id,
        "payment_method_id": s.payment_method_id,
        "bundle_id": s.bundle_id,
        "amount": s.amount,
        "currency": s.currency,
        "billing_type": s.billing_type,
        "is_keepalive": s.is_keepalive,
        "cycle": s.cycle,
        "cycle_count": s.cycle_count,
        "start_date": s.start_date.isoformat() if s.start_date else None,
        "next_renewal_date": s.next_renewal_date.isoformat() if s.next_renewal_date else None,
        "end_date": s.end_date.isoformat() if s.end_date else None,
        "last_renewed_at": s.last_renewed_at.isoformat() if s.last_renewed_at else None,
        "is_active": s.is_active,
        "is_paused": s.is_paused,
        "auto_renew": s.auto_renew,
        "show_in_calendar": s.show_in_calendar,
        "sort": s.sort,
        "family_members": s.family_members,
        "remind_days_before": s.remind_days_before,
        # 续费历史快照：随订阅一起备份/恢复，灾难恢复后不丢失续费轨迹。
        "renewal_history": [
            {
                "renewed_at": r.renewed_at.isoformat() if r.renewed_at else None,
                "mode": r.mode,
                "prev_renewal_date": r.prev_renewal_date.isoformat() if r.prev_renewal_date else None,
                "next_renewal_date": r.next_renewal_date.isoformat() if r.next_renewal_date else None,
                "amount": r.amount,
                "currency": r.currency,
            }
            for r in history
        ],
    }


def _credit_card_dict(card: CreditCard) -> dict:
    return {
        "display_name": card.display_name,
        "bank_name": card.bank_name,
        "last_four": card.last_four,
        "statement_day": card.statement_day,
        "due_day": card.due_day,
        "remind_days_before": card.remind_days_before,
        "credit_limit": card.credit_limit,
        "is_active": card.is_active,
        "show_in_calendar": card.show_in_calendar,
        # 已还界线（名义还款日）：跨备份保留顺延/提醒静默状态
        "repaid_through_due": card.repaid_through_due,
        # 免年费配置（可空）：年费收取日锚定 + 刷 N 笔 / 满 M 元目标
        "fee_waiver_anchor_date": card.fee_waiver_anchor_date,
        "fee_waiver_target_count": card.fee_waiver_target_count,
        "fee_waiver_target_amount": card.fee_waiver_target_amount,
    }


def _statement_dict(s: CreditCardStatement, card_index: dict[int, int]) -> dict:
    return {
        # 备份内卡片局部 key = 该卡在备份 credit_cards 数组中的下标；
        # DB id 不能跨库使用，恢复端按下标映射到新建卡。
        "card_key": card_index.get(s.card_id) if s.card_id is not None else None,
        "bank_key": s.bank_key,
        "card_last_four": s.card_last_four,
        "match_status": s.match_status,
        "bill_period_start": s.bill_period_start,
        "bill_period_end": s.bill_period_end,
        "statement_date": s.statement_date,
        "due_date": s.due_date,
        "total_due": s.total_due,
        "min_due": s.min_due,
        "credit_limit": s.credit_limit,
        "message_id": s.message_id,
        "subject": s.subject,
        "verify_status": s.verify_status,
        # 还款标记：用户手动标记，跨备份保留（待还总额据此剔除）
        "is_repaid": s.is_repaid,
        "repaid_at": s.repaid_at,
        # 部分还款累计已还（多次还清；取消标记清零）
        "repaid_amount": s.repaid_amount,
        # 备份内来源局部 key：源邮箱地址（不含凭据）；恢复端映射到同邮箱账户
        "source_email": s.source_account.email if s.source_account else None,
        "items": [
            {
                "trans_date_raw": i.trans_date_raw,
                "trans_date": i.trans_date,
                "posted_date": i.posted_date,
                "description": i.description,
                "amount": i.amount,
                "tx_amount": i.tx_amount,
                "tx_currency": i.tx_currency,
                "tx_type": i.tx_type,
                "installment_note": i.installment_note,
            }
            for i in s.items
        ],
    }


def _validated_statements(data: dict) -> list[dict] | None:
    """校验 credit_card_statements；返回 None = 备份不含该字段（旧版备份）。"""
    if "credit_card_statements" not in data:
        return None
    stmts = data["credit_card_statements"]
    if not isinstance(stmts, list):
        raise ValueError("备份格式错误：credit_card_statements 不是数组")
    for index, s in enumerate(stmts, start=1):
        if not isinstance(s, dict):
            raise ValueError(f"备份 credit_card_statements 第 {index} 项必须是对象")
        for field in ("bank_key", "card_last_four", "message_id"):
            if not isinstance(s.get(field), str) or not s.get(field):
                raise ValueError(f"备份 credit_card_statements 第 {index} 项缺少 {field}")
        items = s.get("items")
        if items is not None and not isinstance(items, list):
            raise ValueError(f"备份 credit_card_statements 第 {index} 项 items 不是数组")
        # 还款标记字段（新版备份才有）：畸形值要响亮拒绝，不能静默翻转业务状态
        # （bool("false") is True——字符串 "false" 会被恢复成已还款，掩盖真实欠款）
        if "is_repaid" in s and not isinstance(s["is_repaid"], bool):
            raise ValueError(f"备份 credit_card_statements 第 {index} 项 is_repaid 必须是布尔值")
        # repaid_at 允许 datetime（进程内导出直传）或 ISO 字符串（JSON 备份文件），其余拒绝
        repaid_at = s.get("repaid_at")
        if repaid_at is not None and not isinstance(repaid_at, datetime):
            if not isinstance(repaid_at, str) or _parse_datetime(repaid_at) is None:
                raise ValueError(f"备份 credit_card_statements 第 {index} 项 repaid_at 非法")
        # 部分还款累计已还：必须是有限非负数（非 bool），且与 is_repaid 满足
        # 交叉不变量（三审 Medium 2——恢复矛盾态会让真实欠款被「已还清」隐藏，
        # 或剩余为零却仍未还）：
        # - is_repaid=True ⟹ repaid_amount == max(total_due, 0)（分精确相等；
        #   负数富余账单还清态恒 0）
        # - is_repaid=False ⟹ 0 ≤ repaid_amount < total_due（正应还时）；
        #   应还 NULL/负/零时必须为 0
        # 旧版备份缺字段仍按派生逻辑兼容（恢复端推导，不走此校验）
        if "repaid_amount" in s:
            ra = s["repaid_amount"]
            if isinstance(ra, bool) or not isinstance(ra, (int, float)) or ra != ra or ra in (float("inf"), float("-inf")) or ra < 0:
                raise ValueError(f"备份 credit_card_statements 第 {index} 项 repaid_amount 非法")
            # 分精度校验（六审 Low 6）：0.001 等亚分/三位小数经 round 会伪装成
            # 合法值写入，与 API 写入端（拒绝三位小数）不一致
            from decimal import Decimal
            try:
                ra_decimal = Decimal(repr(ra))
            except Exception:
                raise ValueError(f"备份 credit_card_statements 第 {index} 项 repaid_amount 非法")
            if not (isinstance(ra_decimal.as_tuple().exponent, int) and ra_decimal.as_tuple().exponent >= -2):
                raise ValueError(f"备份 credit_card_statements 第 {index} 项 repaid_amount 最多两位小数")
            total = s.get("total_due")
            is_repaid = s.get("is_repaid", False)
            total_cents = round(total * 100) if total is not None else None
            ra_cents = round(ra * 100)
            if is_repaid:
                expected = max(total_cents or 0, 0)
                if ra_cents != expected:
                    raise ValueError(
                        f"备份 credit_card_statements 第 {index} 项 repaid_amount 与已还状态不一致"
                    )
            else:
                if total_cents is not None and total_cents > 0 and ra_cents >= total_cents:
                    raise ValueError(
                        f"备份 credit_card_statements 第 {index} 项 repaid_amount 未还清时不得超过应还金额"
                    )
                if (total_cents is None or total_cents <= 0) and ra_cents != 0:
                    raise ValueError(
                        f"备份 credit_card_statements 第 {index} 项 repaid_amount 应为 0（账单无正待还）"
                    )
        for j, item in enumerate(items or [], start=1):
            if not isinstance(item, dict):
                raise ValueError(f"备份 credit_card_statements 第 {index} 项 items 第 {j} 条必须是对象")
            if not isinstance(item.get("description"), str):
                raise ValueError(f"备份 credit_card_statements 第 {index} 项 items 第 {j} 条缺 description")
            amount = item.get("amount")
            if not isinstance(amount, (int, float)) or isinstance(amount, bool):
                raise ValueError(f"备份 credit_card_statements 第 {index} 项 items 第 {j} 条 amount 非法")
    return stmts


def _collect_entities(db: Session, user: User) -> tuple[dict, list[Subscription]]:
    """汇总某用户的订阅及其依赖实体（分类/付款方式/捆绑包/自定义货币）。

    关键修复：订阅可能挂在「系统预置分类」（is_system=True, user_id=None）下，
    旧逻辑只导出 user_id == 当前用户 的分类，导致这些订阅在恢复时分类丢失。
    这里额外把订阅实际引用到的分类/付款方式（含系统预置的）一并导出，
    恢复端按名称匹配即可正确还原到重新种子化后的系统分类上。

    返回 (entities, subs)：subs 是生成 subscriptions 数组的同一份 ORM 列表
    （按 id 稳定排序，复审 Medium），供手动排序偏好的 ID→下标转换复用——
    偏好下标与导出数组必须指向同一份列表，两次独立查询在并发删除或无
    ORDER BY 时会错位。
    """
    subs = db.scalars(
        select(Subscription).where(Subscription.user_id == user.id).order_by(Subscription.id)
    ).all()
    statements = db.scalars(
        select(CreditCardStatement)
        .where(CreditCardStatement.user_id == user.id)
        .order_by(CreditCardStatement.id)
    ).all()
    # 一次性取本用户全部续费历史，按订阅分组，避免每条订阅单独查询。
    all_history = db.scalars(
        select(RenewalHistory)
        .where(RenewalHistory.user_id == user.id)
        .order_by(RenewalHistory.id)
    ).all()
    history_by_sub: dict[int, list[RenewalHistory]] = {}
    for r in all_history:
        history_by_sub.setdefault(r.subscription_id, []).append(r)

    used_cat_ids = {s.category_id for s in subs if s.category_id}
    used_pm_ids = {s.payment_method_id for s in subs if s.payment_method_id}

    cats = db.scalars(
        select(Category).where(
            or_(
                Category.user_id == user.id,
                and_(Category.id.in_(used_cat_ids), Category.is_system.is_(True)),
            )
        )
    ).all()
    pms = db.scalars(
        select(PaymentMethod).where(
            or_(
                PaymentMethod.user_id == user.id,
                and_(PaymentMethod.id.in_(used_pm_ids), PaymentMethod.is_system.is_(True)),
            )
        )
    ).all()
    bundles = db.scalars(select(Bundle).where(Bundle.user_id == user.id)).all()
    credit_cards = db.scalars(
        select(CreditCard).where(CreditCard.user_id == user.id).order_by(CreditCard.id)
    ).all()
    currencies = db.scalars(
        select(Currency).where(Currency.is_custom.is_(True), Currency.user_id == user.id)
    ).all()

    # 账单的备份内卡片 key = 卡片在 credit_cards 数组中的下标（与恢复端一致）
    card_index = {card.id: idx for idx, card in enumerate(credit_cards)}

    entities = {
        "categories": [
            {
                "id": c.id, "name": c.name, "icon": c.icon, "color": c.color,
                "sort": c.sort, "is_system": c.is_system,
            }
            for c in cats
        ],
        "payment_methods": [
            {"id": p.id, "name": p.name, "icon": p.icon, "is_system": p.is_system}
            for p in pms
        ],
        "bundles": [{"id": b.id, "name": b.name, "note": b.note} for b in bundles],
        "credit_cards": [_credit_card_dict(card) for card in credit_cards],
        "credit_card_statements": [_statement_dict(s, card_index) for s in statements],
        "currencies": [
            {
                "code": c.code,
                "name": c.name,
                "symbol": c.symbol,
                # 备份保存系统基准币报价，才能在用户基准币本身是该自定义币时精确恢复。
                "rate_to_base": exchange.system_quote_rate(
                    db, c.code, user_id=user.id
                ),
                "rate_base": (settings.exchange_api_base or "USD").upper(),
            }
            for c in currencies
        ],
        "subscriptions": [_sub_dict(s, history_by_sub.get(s.id, [])) for s in subs],
    }
    return entities, subs


def _parse_date(v):
    try:
        return date.fromisoformat(v) if v else None
    except (TypeError, ValueError):
        return None


def _parse_datetime(v):
    """备份里的时间戳（ISO 字符串）→ naive datetime；非法值静默为 None。"""
    try:
        return datetime.fromisoformat(v) if v else None
    except (TypeError, ValueError):
        return None


def _restore_currency_rate(
    db: Session, currency: Currency, payload: dict, user_base_currency: str
) -> None:
    if "rate_to_user_base" not in payload and "rate_to_base" not in payload:
        return
    if "rate_to_user_base" in payload:
        user_rate = payload.get("rate_to_user_base")
        stored_rate = (
            None
            if user_rate is None
            else exchange.stored_rate_from_user_base(
                db,
                user_rate,
                user_base_currency,
                user_id=currency.user_id,
            )
        )
        if user_rate is not None and stored_rate is None:
            raise ValueError(f"缺少基准币 {user_base_currency} 的系统汇率，无法恢复 {currency.code}")
    else:
        stored_rate = payload.get("rate_to_base")
        exported_base = str(
            payload.get("rate_base") or settings.exchange_api_base or "USD"
        ).strip().upper()
        current_base = (settings.exchange_api_base or "USD").upper()
        if stored_rate is not None and exported_base != current_base:
            cross_rate = exchange.system_quote_rate(db, exported_base)
            if cross_rate is None:
                raise ValueError(
                    f"缺少 {current_base} 到 {exported_base} 的交叉汇率，无法恢复 {currency.code}"
                )
            stored_rate *= cross_rate

    base = (settings.exchange_api_base or "USD").upper()
    row = db.scalar(
        select(ExchangeRate).where(
            ExchangeRate.base == base,
            ExchangeRate.quote == currency.code,
        )
    )
    if stored_rate is None:
        if row is not None:
            db.delete(row)
    elif row is None:
        db.add(
            ExchangeRate(
                base=base,
                quote=currency.code,
                rate=stored_rate,
                is_manual=True,
                user_id=currency.user_id,
            )
        )
    else:
        row.rate = stored_rate
        row.is_manual = True
        row.user_id = currency.user_id


def _validated_credit_cards(data: dict) -> list[dict] | None:
    if "credit_cards" not in data:
        return None
    cards = data["credit_cards"]
    if not isinstance(cards, list):
        raise ValueError("备份格式错误：credit_cards 不是数组")
    validated: list[dict] = []
    for index, card in enumerate(cards, start=1):
        if not isinstance(card, dict):
            raise ValueError(f"备份 credit_cards 第 {index} 项必须是对象")
        # 已还界线不在 CreditCardIn（表单 schema）：单独校验，旧备份缺省 None。
        # 允许 date 或 ISO 字符串（JSON 反序列化形态），其余响亮拒绝。
        # 拒绝 date.max：派生（next_due_date_after）需计算其后继日期，
        # date.max 会在读取卡片时溢出成 500；这里在写入前把关。
        repaid_through = card.get("repaid_through_due")
        if repaid_through is not None and not isinstance(repaid_through, date):
            if not isinstance(repaid_through, str) or _parse_date(repaid_through) is None:
                raise ValueError(f"备份 credit_cards 第 {index} 项 repaid_through_due 非法")
        if isinstance(repaid_through, date) and repaid_through >= date.max - timedelta(days=31):
            raise ValueError(f"备份 credit_cards 第 {index} 项 repaid_through_due 超出可用日期范围")
        try:
            # CreditCardIn 是 extra=forbid：剔除单独校验过的 repaid_through_due 再验。
            # fee_waiver_anchor_date 的类型/范围/未来日期校验都在 CreditCardIn 的
            # validator 里（JSON 字符串在此归一为 date 后统一把关，绕过进程内
            # 直接传 date 类型检查的漏洞）。
            validated.append(
                CreditCardIn.model_validate(
                    {k: v for k, v in card.items() if k != "repaid_through_due"}
                ).model_dump()
            )
        except ValueError as exc:
            raise ValueError(f"备份 credit_cards 第 {index} 项非法：{exc}") from exc
    return validated


def _validate_backup_payload(data: dict) -> None:
    """导入前校验：畸形备份（缺 name、非法日期、类型错误）直接抛错，避免 replace 先删后写丢数据。

    静默容错（缺 name 默认'导入订阅'、非法日期变 today）会让用户在'导入前清空'后
    丢掉原数据却收到成功响应，违背'失败要响亮'。这里在任何删除/写入前把关，
    覆盖后续构造 Subscription / compute_next_renewal 会用到的类型字段。
    """
    if not isinstance(data, dict):
        raise ValueError("备份格式错误：顶层不是对象")
    # user 字段（若有）必须是对象或 null（九审 Low 3）：真值非对象（如字符串）
    # 会让偏好应用分支被 isinstance 检查静默跳过——replace 已删旧数据而偏好
    # 残留陈旧 ID。缺失/null 归一化为 {}；其余响亮拒绝。
    if "user" in data:
        meta = data["user"]
        if meta is not None and not isinstance(meta, dict):
            raise ValueError("备份格式错误：user 字段必须是对象或 null")
    # subscriptions 必须存在且为数组：缺失 + replace 会静默清空用户现有订阅
    subs = data.get("subscriptions")
    if subs is None:
        raise ValueError("备份缺少 subscriptions 字段（如需清空请显式传空数组）")
    if not isinstance(subs, list):
        raise ValueError("备份格式错误：subscriptions 不是数组")
    _validated_credit_cards(data)
    _validated_statements(data)
    # 辅助集合必须是数组、元素必须是 dict，否则后续 .get() 抛 AttributeError 走成 500
    for key in ("categories", "payment_methods", "bundles", "currencies"):
        items = data.get(key)
        if items is None:
            continue
        if not isinstance(items, list):
            raise ValueError(f"备份格式错误：{key} 不是数组")
        for j, it in enumerate(items):
            if not isinstance(it, dict):
                raise ValueError(f"备份 {key} 第 {j + 1} 项必须是对象")
            if key == "currencies":
                try:
                    normalize_currency_code(it.get("code"))
                except ValueError as exc:
                    raise ValueError(
                        f"备份 currencies 第 {j + 1} 项 code 非法：{exc}"
                    ) from exc
                if "rate_to_base" in it and "rate_to_user_base" in it:
                    raise ValueError(
                        f"备份 currencies 第 {j + 1} 项不能同时包含 rate_to_base 与 rate_to_user_base"
                    )
                rate_base = it.get("rate_base")
                if rate_base is not None:
                    try:
                        normalize_currency_code(rate_base)
                    except ValueError as exc:
                        raise ValueError(
                            f"备份 currencies 第 {j + 1} 项 rate_base 非法：{exc}"
                        ) from exc
                for rate_field in ("rate_to_base", "rate_to_user_base"):
                    rate = it.get(rate_field)
                    if rate is not None and (
                        not isinstance(rate, (int, float))
                        or isinstance(rate, bool)
                        or not math.isfinite(rate)
                        or rate <= 0
                    ):
                        raise ValueError(
                            f"备份 currencies 第 {j + 1} 项 {rate_field} 必须是有限正数"
                        )
    for i, s in enumerate(subs):
        if not isinstance(s, dict):
            raise ValueError(f"第 {i + 1} 条订阅格式错误")
        if not (s.get("name") or "").strip():
            raise ValueError(f"第 {i + 1} 条订阅缺少 name")
        for field in ("start_date", "next_renewal_date", "end_date", "last_renewed_at"):
            v = s.get(field)
            if v not in (None, ""):
                try:
                    date.fromisoformat(v)
                except (TypeError, ValueError):
                    raise ValueError(f"第 {i + 1} 条订阅 {field} 日期非法：{v!r}")
        # 类型可转换校验：这些字段后续直接用于构造模型 / compute_next_renewal，
        # 类型错误会抛 TypeError 走成 500，必须在删旧数据前拦下。
        for field in ("cycle_count", "sort"):
            v = s.get(field)
            if v is not None and not isinstance(v, int):
                raise ValueError(f"第 {i + 1} 条订阅 {field} 必须是整数：{v!r}")
        # 布尔字段必须是真实 bool，避免字符串 "false" 等 truthy 值走成 500
        for field in ("is_active", "is_paused", "is_keepalive", "auto_renew", "show_in_calendar"):
            v = s.get(field)
            if v is not None and not isinstance(v, bool):
                raise ValueError(f"第 {i + 1} 条订阅 {field} 必须是布尔值：{v!r}")
        if "amount" in s and s["amount"] is not None:
            try:
                float(s["amount"])
            except (TypeError, ValueError):
                raise ValueError(f"第 {i + 1} 条订阅 amount 非法：{s['amount']!r}")
        bt = s.get("billing_type")
        if bt is not None and bt not in ("recurring", "one_time"):
            raise ValueError(f"第 {i + 1} 条订阅 billing_type 非法：{bt!r}")
        start_date = _parse_date(s.get("start_date"))
        end_date = _parse_date(s.get("end_date"))
        if bt != "one_time" and start_date and end_date and end_date < start_date:
            raise ValueError(f"第 {i + 1} 条订阅 end_date 不能早于 start_date")
        cy = s.get("cycle")
        if cy is not None and cy not in ("day", "week", "month", "year"):
            raise ValueError(f"第 {i + 1} 条订阅 cycle 非法：{cy!r}")
        rdb = s.get("remind_days_before")
        if rdb is not None and not isinstance(rdb, str):
            raise ValueError(f"第 {i + 1} 条订阅 remind_days_before 必须是字符串：{rdb!r}")
        fm = s.get("family_members")
        if fm is not None and not isinstance(fm, list):
            raise ValueError(f"第 {i + 1} 条订阅 family_members 必须是数组：{fm!r}")
        if fm is not None and any(not isinstance(m, str) for m in fm):
            raise ValueError(f"第 {i + 1} 条订阅 family_members 元素必须是字符串")


def _validate_restore_currency_refs(
    db: Session,
    user: User,
    data: dict,
    *,
    replace: bool,
) -> None:
    imported: dict[str, dict] = {}
    for item in data.get("currencies", []) or []:
        code = str(item.get("code") or "").strip().upper()
        if not code:
            continue
        existing = db.get(Currency, code)
        if existing is not None and existing.is_custom and existing.user_id != user.id:
            raise ValueError(f"自定义货币 {code} 已被其他用户占用")
        imported[code] = item

    meta = data.get("user") if isinstance(data.get("user"), dict) else {}
    backup_base = meta.get("base_currency")
    normalized_backup_base = str(backup_base or user.base_currency or "").strip().upper()

    def allowed(code) -> bool:
        normalized = str(code or "").strip().upper()
        return normalized in imported or currency_allowed_for_user(db, user.id, normalized)

    def has_rate(code) -> bool:
        normalized = str(code or "").strip().upper()
        currency = db.get(Currency, normalized)
        item = imported.get(normalized)
        if currency is not None and not currency.is_custom:
            return True
        if item is not None:
            if "rate_to_base" in item:
                return item.get("rate_to_base") is not None
            if "rate_to_user_base" in item:
                return (
                    item.get("rate_to_user_base") is not None
                    and normalized != normalized_backup_base
                )
        return custom_currency_has_rate(db, user.id, normalized)

    final_references = {normalized_backup_base}
    final_references.update(
        str(sub.get("currency") or normalized_backup_base).strip().upper()
        for sub in data.get("subscriptions", []) or []
    )
    if not replace:
        final_references.update(
            (sub.currency or "").strip().upper()
            for sub in db.scalars(
                select(Subscription).where(Subscription.user_id == user.id)
            ).all()
        )
    for code, item in imported.items():
        clears_rate = (
            ("rate_to_base" in item and item.get("rate_to_base") is None)
            or ("rate_to_user_base" in item and item.get("rate_to_user_base") is None)
        )
        if clears_rate and code in final_references:
            raise ValueError(f"自定义货币 {code} 仍被基准币或订阅引用，不能清空汇率")

    if backup_base and not allowed(backup_base):
        raise ValueError(f"备份基准货币 {str(backup_base).upper()} 不存在或不属于该用户")
    if backup_base and not has_rate(backup_base):
        raise ValueError(f"备份基准货币 {str(backup_base).upper()} 缺少可用汇率")
    for index, sub in enumerate(data.get("subscriptions", []) or [], start=1):
        code = sub.get("currency") or backup_base or user.base_currency
        if not allowed(code):
            raise ValueError(f"第 {index} 条订阅货币 {str(code).upper()} 不存在或不属于该用户")
        if not has_rate(code):
            raise ValueError(f"第 {index} 条订阅货币 {str(code).upper()} 缺少可用汇率")


def _restore_entities(
    db: Session,
    user: User,
    data: dict,
    replace: bool,
    *,
    export_version: int | None = None,
) -> tuple[int, dict[int, int], dict[str, str], list[Subscription]]:
    """把一份导出数据恢复到指定用户名下。

    返回 (导入订阅数, 导出数组下标 → 新订阅 ID 映射, 旧分类 key → 新分类 key
    映射, 新建订阅 ORM 列表)。两份映射供恢复手动拖拽排序偏好（subscription_order
    的订阅 ID 与分类 key 在新实例都会重新分配，审核 Medium）；ORM 列表供旧版
    备份（无 subscription_order 字段）按 sort 回填手动顺序（七审 Medium 1）。
    """
    subs_in = data.get("subscriptions") or []
    cards_in = _validated_credit_cards(data)
    statements_in = _validated_statements(data)
    replace_credit_cards = replace and cards_in is not None

    # 任何删除/写入前先校验，畸形或越权货币引用直接抛错，避免 replace 先删后写错数据。
    _validate_backup_payload(data)
    _validate_restore_currency_refs(db, user, data, replace=replace)
    if cards_in is not None:
        credit_card_notification_outbox.invalidate_scan_checkpoint(db)

    if replace_credit_cards:
        old_card_ids = [
            card.id
            for card in db.scalars(
                select(CreditCard).where(CreditCard.user_id == user.id)
            ).all()
        ]
        if old_card_ids:
            db.execute(
                delete(CreditCardNotificationLog).where(
                    CreditCardNotificationLog.credit_card_id.in_(old_card_ids)
                )
            )
            db.execute(
                delete(CreditCardNotificationOutbox).where(
                    CreditCardNotificationOutbox.credit_card_id.in_(old_card_ids)
                )
            )
            # 账单与明细随卡片一起替换（SQLite 无级联，显式清理）
            old_stmt_ids = list(db.scalars(
                select(CreditCardStatement.id).where(CreditCardStatement.user_id == user.id)
            ).all())
            if old_stmt_ids:
                db.execute(
                    delete(CreditCardStatementItem).where(
                        CreditCardStatementItem.statement_id.in_(old_stmt_ids)
                    )
                )
            db.execute(
                delete(CreditCardStatement).where(CreditCardStatement.user_id == user.id)
            )
            db.execute(
                delete(CreditCardStatementPollRun).where(
                    CreditCardStatementPollRun.user_id == user.id
                )
            )
            db.execute(delete(CreditCard).where(CreditCard.id.in_(old_card_ids)))
        db.flush()

    if replace:
        notification_outbox.invalidate_scan_checkpoint(db)
        # 覆盖恢复：先清本用户的续费历史与订阅，避免 SQLite 无 AUTOINCREMENT 时
        # 新订阅复用旧 ID 而继承错误历史，或留下孤儿历史行。
        old_sub_ids = [
            s.id for s in db.scalars(
                select(Subscription).where(Subscription.user_id == user.id)
            ).all()
        ]
        if old_sub_ids:
            db.execute(delete(NotificationLog).where(NotificationLog.subscription_id.in_(old_sub_ids)))
            db.execute(delete(NotificationOutbox).where(NotificationOutbox.subscription_id.in_(old_sub_ids)))
            db.execute(delete(RenewalHistory).where(RenewalHistory.subscription_id.in_(old_sub_ids)))
        for s in db.scalars(
            select(Subscription).where(Subscription.user_id == user.id)
        ).all():
            db.delete(s)
        db.flush()

    # 现有可用实体（当前用户的 + 系统预置的），按名称去重，避免重复创建。
    # 同名时优先复用当前用户自己的实体；只有用户侧不存在时才落到系统预置。
    existing_cats = {
        c.name: c
        for c in db.scalars(
            select(Category).where(Category.is_system.is_(True)).order_by(Category.id)
        ).all()
    }
    existing_cats.update({
        c.name: c
        for c in db.scalars(
            select(Category).where(Category.user_id == user.id).order_by(Category.id)
        ).all()
    })
    existing_pms = {
        p.name: p
        for p in db.scalars(
            select(PaymentMethod).where(PaymentMethod.is_system.is_(True)).order_by(PaymentMethod.id)
        ).all()
    }
    existing_pms.update({
        p.name: p
        for p in db.scalars(
            select(PaymentMethod).where(PaymentMethod.user_id == user.id).order_by(PaymentMethod.id)
        ).all()
    })
    existing_bundles = {
        b.name: b
        for b in db.scalars(select(Bundle).where(Bundle.user_id == user.id).order_by(Bundle.id)).all()
    }

    cat_map: dict[int, int] = {}
    pm_map: dict[int, int] = {}
    bundle_map: dict[int, int] = {}

    for c in data.get("categories", []) or []:
        name = c.get("name")
        if not name:
            continue
        target = existing_cats.get(name)
        if not target:
            target = Category(
                name=name, icon=c.get("icon"), color=c.get("color"),
                sort=c.get("sort", 0), user_id=user.id, is_system=False,
            )
            db.add(target)
            db.flush()
            existing_cats[name] = target
        if c.get("id") is not None:
            cat_map[c["id"]] = target.id

    for p in data.get("payment_methods", []) or []:
        name = p.get("name")
        if not name:
            continue
        target = existing_pms.get(name)
        if not target:
            target = PaymentMethod(name=name, icon=p.get("icon"), user_id=user.id, is_system=False)
            db.add(target)
            db.flush()
            existing_pms[name] = target
        if p.get("id") is not None:
            pm_map[p["id"]] = target.id

    for b in data.get("bundles", []) or []:
        name = b.get("name")
        if not name:
            continue
        target = existing_bundles.get(name)
        if not target:
            target = Bundle(name=name, note=b.get("note"), user_id=user.id)
            db.add(target)
            db.flush()
            existing_bundles[name] = target
        if b.get("id") is not None:
            bundle_map[b["id"]] = target.id

    meta = data.get("user") if isinstance(data.get("user"), dict) else {}
    backup_base_currency = user.base_currency
    if isinstance(meta.get("base_currency"), str) and meta["base_currency"].strip():
        backup_base_currency = meta["base_currency"].strip().upper()

    for cu in data.get("currencies", []) or []:
        code = (cu.get("code") or "").strip().upper()
        if not code:
            continue
        currency = db.get(Currency, code)
        if currency is None:
            currency = Currency(
                code=code,
                name=cu.get("name", code),
                symbol=cu.get("symbol", ""),
                is_custom=True,
                user_id=user.id,
            )
            db.add(currency)
            db.flush()
        elif not currency.is_custom or currency.user_id != user.id:
            continue
        else:
            currency.name = cu.get("name", currency.name)
            currency.symbol = cu.get("symbol", currency.symbol)
        _restore_currency_rate(db, currency, cu, backup_base_currency)
    db.flush()

    if isinstance(cards_in, list):
        # 备份内局部 key（卡片在备份 credit_cards 数组的下标）→ 新卡 id。
        # 尾号不唯一不可作关联键；账单的 card_key 指向导出时的卡片数组序。
        card_key_map: dict[int, int] = {}
        for idx, card in enumerate(cards_in):
            # repaid_through_due 已在 _validated_credit_cards 校验；
            # 原始 dict 取值（model_dump 后的 cards_in 不含该字段）
            raw_repaid_through = (data.get("credit_cards") or [])[idx].get("repaid_through_due")
            new_card = CreditCard(
                user_id=user.id,
                display_name=card["display_name"].strip(),
                bank_name=card["bank_name"],
                last_four=card["last_four"],
                statement_day=card["statement_day"],
                due_day=card["due_day"],
                remind_days_before=card["remind_days_before"],
                credit_limit=card.get("credit_limit"),
                is_active=card["is_active"],
                show_in_calendar=card["show_in_calendar"],
                repaid_through_due=(
                    raw_repaid_through
                    if isinstance(raw_repaid_through, date)
                    else _parse_date(raw_repaid_through)
                ),
                # 免年费三字段经 CreditCardIn 校验（model_dump 含，含默认 None）
                fee_waiver_anchor_date=card.get("fee_waiver_anchor_date"),
                fee_waiver_target_count=card.get("fee_waiver_target_count"),
                fee_waiver_target_amount=card.get("fee_waiver_target_amount"),
            )
            db.add(new_card)
            db.flush()
            card_key_map[idx] = new_card.id
        # 恢复账单与明细（v4+）：
        # - 仅 replace 清空现有账单；合并导入按 (source, message_id, card) 去重插入
        # - 来源按备份内 source_email 映射到当前用户同邮箱的 IMAP 账户；
        #   找不到则置 NULL（来源信息随账户删除/换库不可还原，不伪造 ID）
        if statements_in is not None:
            if replace:
                source_ids = list(db.scalars(
                    select(CreditCardStatement.id).where(CreditCardStatement.user_id == user.id)
                ).all())
                if source_ids:
                    db.execute(
                        delete(CreditCardStatementItem).where(
                            CreditCardStatementItem.statement_id.in_(source_ids)
                        )
                    )
                db.execute(
                    delete(CreditCardStatement).where(CreditCardStatement.user_id == user.id)
                )
            # 邮箱 → 当前用户账户（备份不含账户 ID；账户凭据不进备份）
            accounts_by_email = {
                a.email: a for a in db.scalars(
                    select(ImapAccount).where(ImapAccount.user_id == user.id)
                ).all()
            }
            # 合并模式下保留现有记录的键，避免重复插入
            existing_keys: set[tuple[int, str, str]] = set()
            if not replace:
                existing_keys = set(
                    db.execute(
                        select(
                            CreditCardStatement.source_account_id,
                            CreditCardStatement.message_id,
                            CreditCardStatement.card_last_four,
                        ).where(CreditCardStatement.user_id == user.id)
                    ).all()
                )
            for s in statements_in:
                card_key = s.get("card_key")
                if card_key is not None and (
                    not isinstance(card_key, int) or card_key not in card_key_map
                ):
                    raise ValueError("备份 credit_card_statements 的 card_key 超出范围")
                source_account = accounts_by_email.get(s.get("source_email"))
                key = (
                    source_account.id if source_account else -1,
                    s["message_id"],
                    s["card_last_four"],
                )
                if key in existing_keys:
                    continue  # 合并导入去重
                existing_keys.add(key)
                record = CreditCardStatement(
                    user_id=user.id,
                    card_id=card_key_map.get(card_key) if card_key is not None else None,
                    source_account_id=source_account.id if source_account else None,
                    bank_key=s["bank_key"],
                    card_last_four=s["card_last_four"],
                    match_status=s.get("match_status") or "unmatched",
                    bill_period_start=_parse_date(s.get("bill_period_start")),
                    bill_period_end=_parse_date(s.get("bill_period_end")),
                    statement_date=_parse_date(s.get("statement_date")),
                    due_date=_parse_date(s.get("due_date")),
                    total_due=s.get("total_due"),
                    min_due=s.get("min_due"),
                    credit_limit=s.get("credit_limit"),
                    message_id=s["message_id"],
                    subject=s.get("subject"),
                    verify_status=s.get("verify_status") or "ok",
                    # is_repaid/repaid_at：旧版备份无此字段，缺省为未还。
                    # repaid_at 已在 _validated_statements 校验（datetime 或 ISO 字符串）
                    is_repaid=bool(s.get("is_repaid") or False),
                    repaid_at=(
                        s["repaid_at"] if isinstance(s.get("repaid_at"), datetime)
                        else _parse_datetime(s.get("repaid_at"))
                    ),
                    # 部分还款累计已还：旧版备份缺字段时按归一化不变量派生
                    # （已还清 = max(total_due,0)；未还 = 0）——复审 Low 5：
                    # 固定 0 会让恢复后的已还账单显示「仍全额待还」
                    repaid_amount=(
                        float(s["repaid_amount"]) if s.get("repaid_amount") is not None
                        else (max(float(s["total_due"] or 0.0), 0.0) if s.get("is_repaid") else 0.0)
                    ),
                )
                db.add(record)
                db.flush()
                for line_no, item in enumerate(s.get("items") or [], start=1):
                    db.add(CreditCardStatementItem(
                        statement_id=record.id,
                        line_no=line_no,
                        trans_date_raw=item.get("trans_date_raw") or "",
                        trans_date=_parse_date(item.get("trans_date")),
                        posted_date=_parse_date(item.get("posted_date")),
                        description=item.get("description") or "",
                        amount=item.get("amount") or 0.0,
                        tx_amount=item.get("tx_amount"),
                        tx_currency=item.get("tx_currency"),
                        tx_type=item.get("tx_type") or "purchase",
                        installment_note=item.get("installment_note"),
                    ))
        db.flush()

    count = 0
    # 旧备份下标 -> 新订阅对象，用于恢复嵌套的续费历史。
    new_subs: list[Subscription] = []
    for s in subs_in:
        start = _parse_date(s.get("start_date")) or date.today()
        billing_type = s.get("billing_type", "recurring")
        sub = Subscription(
            user_id=user.id,
            name=s.get("name") or "导入订阅",
            plan=s.get("plan"),
            icon=s.get("icon"),
            url=sanitize_url(s.get("url")),
            notes=s.get("notes"),
            remark=s.get("remark"),
            ipv4=s.get("ipv4"),
            ipv6=s.get("ipv6"),
            category_id=cat_map.get(s.get("category_id")),
            payment_method_id=pm_map.get(s.get("payment_method_id")),
            bundle_id=bundle_map.get(s.get("bundle_id")),
            amount=s.get("amount", 0.0) or 0.0,
            currency=str(
                s.get("currency") or backup_base_currency or user.base_currency
            ).strip().upper(),
            billing_type=billing_type,
            is_keepalive=(s.get("is_keepalive", False) or False) if billing_type != "one_time" else False,
            cycle=s.get("cycle", "month"),
            cycle_count=s.get("cycle_count", 1) or 1,
            start_date=start,
            next_renewal_date=_parse_date(s.get("next_renewal_date")),
            end_date=_parse_date(s.get("end_date")),
            last_renewed_at=_parse_date(s.get("last_renewed_at")),
            is_active=s.get("is_active", True),
            is_paused=(s.get("is_paused", False) or False),
            auto_renew=s.get("auto_renew", True),
            show_in_calendar=s.get("show_in_calendar", True),
            sort=s.get("sort", 0) or 0,
            family_members=s.get("family_members"),
            remind_days_before=s.get("remind_days_before", "7,1") or "7,1",
        )
        if billing_type == "recurring" and not sub.next_renewal_date:
            sub.next_renewal_date = compute_next_renewal(start, sub.cycle, sub.cycle_count)
        if billing_type == "one_time":
            sub.next_renewal_date = None
            sub.end_date = None
            sub.auto_renew = False
        apply_keepalive_scope(db, sub)
        db.add(sub)
        db.flush()  # 拿到新 sub.id，供恢复历史关联
        new_subs.append(sub)
        count += 1

    # 恢复续费历史：按订阅在备份数组中的下标对应到新订阅；兼容不含历史的旧版备份。
    for idx, s in enumerate(subs_in):
        if idx >= len(new_subs):
            break
        hist_in = s.get("renewal_history")
        if not isinstance(hist_in, list):
            continue
        target_sub = new_subs[idx]
        for r in hist_in:
            if not isinstance(r, dict):
                continue
            try:
                amount = float(r.get("amount", 0) or 0)
            except (TypeError, ValueError):
                continue
            db.add(RenewalHistory(
                subscription_id=target_sub.id,
                user_id=user.id,
                renewed_at=_parse_date(r.get("renewed_at")) or date.today(),
                mode=str(r.get("mode") or "today"),
                prev_renewal_date=_parse_date(r.get("prev_renewal_date")),
                next_renewal_date=_parse_date(r.get("next_renewal_date")),
                amount=amount,
                currency=str(r.get("currency") or target_sub.currency),
            ))

    # 重映射表：导出数组下标 → 新订阅 ID；旧分类 key → 新分类 key
    # （供恢复手动排序偏好 subscription_order，审核 Medium）
    return count, {idx: sub.id for idx, sub in enumerate(new_subs)}, cat_map, new_subs



def _backfill_order_from_legacy_sort(subs: list[Subscription]) -> dict:
    """旧版备份的手动顺序推导（七审 Medium 1 / 八审 Medium）：备份不含
    subscription_order 字段时，恢复出的订阅仍带旧版 sort——按启动迁移相同的
    规则（同分类 ≥2 成员且存在非零 sort → 按 (sort, id)）推导偏好 dict。
    纯函数不直接写 user：合并恢复需按 key 并入目标现有偏好而非整体覆盖
    （八审 Medium）。备份里的 sort 是当时展示顺序的唯一记录，不回填就会
    永久丢失。"""
    by_cat: dict[str, list[Subscription]] = {}
    for s in subs:
        key = "none" if s.category_id is None else str(s.category_id)
        by_cat.setdefault(key, []).append(s)
    saved: dict = {}
    for key, members in by_cat.items():
        if len(members) < 2 or not any(m.sort for m in members):
            continue  # 全零 = 未拖拽过，保持默认日期排序
        ordered = sorted(members, key=lambda m: (m.sort, m.id))
        saved[key] = [m.id for m in ordered]
    return saved


def _apply_subscription_order(
    db: Session,
    user: User,
    meta: dict,
    sub_index_to_id: dict[int, int],
    cat_key_to_id: dict[str, str] | None = None,
    replace: bool = False,
    *,
    restored_subs: list[Subscription] | None = None,
) -> None:
    """恢复用户的手动拖拽排序偏好（subscription_order：分类 key → 有序下标）。

    备份里的两套引用都需要重映射（审核 Medium）：订阅 ID 按恢复时的「导出
    数组下标 → 新订阅 ID」转换；数字分类 key 按旧分类 ID → 新分类 ID 转换
    （"none" 保持不变）。指向不存在实体的条目剔除后剩余合法 ID 才写回。
    仅接受 dict[str, list[int]] 形状（type(idx) is int 排除 bool——八审 Low 2：
    isinstance 对 True 放行会映射到下标 1 的订阅）。restored_subs 传入本次
    恢复的订阅 ORM 列表，用于旧版备份（字段缺失而非显式 null）的 legacy
    sort 回填（七审 Medium 1）。"""
    has_field = "subscription_order" in meta
    saved = meta.get("subscription_order")
    if not has_field:
        # 旧版备份不含该字段：从恢复出的订阅按旧版 sort 推导手动顺序（该
        # 备份里 sort 是展示顺序的唯一记录）。replace 覆盖恢复直接采用推导
        # 结果（全零/单成员 → 无偏好）；合并恢复（八审 Medium）按 key 并入
        # 目标现有偏好——不丢无关分类，同名分类保留目标现有 ID 顺序、追加
        # 本次恢复的新成员（与展示端 normalize 的追加语义一致）。
        if restored_subs is None:
            if replace:
                user.subscription_order = None
            return
        derived = _backfill_order_from_legacy_sort(restored_subs)
        if replace:
            user.subscription_order = derived or None
            return
        merged = dict(user.subscription_order or {})
        for key, ids in derived.items():
            existing = list(merged.get(key) or [])
            combined = existing + [sid for sid in ids if sid not in existing]
            if combined:
                merged[key] = combined
        user.subscription_order = merged or None
        return
    if not isinstance(saved, dict):
        # 显式 null/非 dict：该备份明确没有手动顺序。覆盖恢复清空目标偏好；
        # 合并恢复视为「此次备份没有顺序可合并」，不动目标现有偏好
        # （八审 Medium：合并语义不得清除目标已有数据）
        if replace:
            user.subscription_order = None
        return
    cat_map = {str(k): str(v) for k, v in (cat_key_to_id or {}).items()}
    # replace 恢复会删除并重建订阅：旧偏好里的 ID 全部失效，必须从空开始
    # 合并（SQLite 可能复用已删 ID，保留旧偏好会错误应用到新订阅——复审 Medium）
    merged = {} if replace else dict(user.subscription_order or {})
    for cat_key, indexes in saved.items():
        if cat_key != "none" and not str(cat_key).isdigit():
            continue
        if not isinstance(indexes, list):
            continue
        new_key = cat_map.get(cat_key, cat_key) if cat_key != "none" else "none"
        # type(idx) is int：isinstance 会放行 bool（True==1 映射到下标 1 的
        # 订阅——八审 Low 2）；越界的陈旧下标仍按既有语义剔除
        remapped = [sub_index_to_id[idx] for idx in indexes if type(idx) is int and idx in sub_index_to_id]
        unique = list(dict.fromkeys(remapped))
        # 始终累加去重（十审 Medium）：备份内多个同名源分类会映射到同一目标
        # key——replace 时每轮置空会让后一个源 key 覆盖前一个的手动顺序，空
        # 条目还会误删已累计结果。统一「现有在前 + 新成员去重追加」：replace
        # 从空 merged 开始（不带恢复前的目标偏好），合并恢复带上目标现有顺序；
        # 两种模式下备份内部的碰撞语义一致。
        existing = list(merged.get(new_key) or [])
        merged[new_key] = existing + [sid for sid in unique if sid not in existing]
    # 累加后仍为空的 key 清掉（全下标失效的条目不留空数组——空数组语义由
    # 展示端 normalize 处理，持久化偏好里只保留有内容的 key）
    merged = {k: v for k, v in merged.items() if v}
    user.subscription_order = merged or None


def _apply_user_preferences(
    db: Session, user: User, meta: dict, *, label: str = ""
) -> None:
    """成对恢复基准货币与月预算，避免预算被按错误币种解释。"""
    prefix = f"用户 {label} 的 " if label else ""
    if "base_currency" in meta:
        currency = meta.get("base_currency")
        if not isinstance(currency, str) or not currency.strip() or len(currency.strip()) > 8:
            raise ValueError(f"{prefix}base_currency 必须是 1-8 位字符串")
        currency = currency.strip().upper()
        available = db.scalar(
            select(Currency).where(
                Currency.code == currency,
                or_(Currency.user_id.is_(None), Currency.user_id == user.id),
            )
        )
        if not available:
            raise ValueError(f"{prefix}base_currency 不存在或不属于该用户：{currency}")
        user.base_currency = currency
    if "monthly_budget" in meta:
        budget = meta.get("monthly_budget")
        if budget is not None:
            if (
                not isinstance(budget, (int, float))
                or isinstance(budget, bool)
                or budget != budget
                or budget in (float("inf"), float("-inf"))
            ):
                raise ValueError(f"{prefix}monthly_budget 必须是有限数：{budget!r}")
            if budget < 0:
                raise ValueError(f"{prefix}monthly_budget 不能为负：{budget!r}")
        user.monthly_budget = budget


# --------------------------------------------------------------------------- #
# 单用户：导出 / 导入自己的数据
# --------------------------------------------------------------------------- #
@router.get("/export")
def export_data(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """导出当前用户的全部数据为 JSON。"""
    entities, orm_subs = _collect_entities(db, user)
    return {
        "export_version": EXPORT_VERSION,
        "app": "Subly",
        "exported_at": utcnow().isoformat(timespec="seconds"),
        "user": {
            "username": user.username,
            "base_currency": user.base_currency,
            "monthly_budget": user.monthly_budget,
            "theme": user.theme,
            # 手动顺序里的订阅 ID 转成 subscriptions 数组下标——恢复时新实例
            # 的订阅 ID 会重新分配，只有下标是稳定引用（审核 Medium）。
            # 必须用生成导出数组的同一份 ORM 列表（复审 Medium：两次独立
            # 查询在并发删除或无 ORDER BY 时下标会错位）
            "subscription_order": _subscription_order_to_indexes(user, orm_subs),
        },
        **entities,
    }


class ImportIn(BaseModel):
    data: dict
    replace: bool = False  # True：导入前先清空当前用户的全部订阅


@router.post("/import")
def import_data(
    payload: ImportIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """从导出的 JSON 恢复数据。自定义分类/付款方式/捆绑包按名称匹配，缺失则新建。"""
    data = payload.data or {}
    if not isinstance(data.get("subscriptions"), list):
        raise HTTPException(400, "备份文件格式不正确：缺少 subscriptions")

    try:
        count, sub_index_to_id, cat_key_to_id, restored_subs = _restore_entities(
            db,
            user,
            data,
            payload.replace,
            export_version=data.get("export_version"),
        )
        # user 字段已在 _validate_backup_payload 前置校验（对象或 null，九审
        # Low 3）——这里无条件应用偏好，不再有被 isinstance 跳过的路径
        meta = data.get("user") or {}
        _apply_user_preferences(db, user, meta)
        _apply_subscription_order(db, user, meta, sub_index_to_id, cat_key_to_id, replace=payload.replace, restored_subs=restored_subs)
    except (ValueError, TypeError, AttributeError) as e:
        db.rollback()
        raise HTTPException(400, f"备份校验失败：{e}")
    db.commit()
    if payload.replace or "credit_cards" in data:
        scheduler.rescan_after_restore()
    activity.log("backup.import", f"导入恢复了 {count} 个订阅", user=user)
    return {"ok": True, "imported": count}


# --------------------------------------------------------------------------- #
# 管理员：整站备份 / 恢复全部成员的数据
# --------------------------------------------------------------------------- #
def _subscription_order_to_indexes(u: User, subs: list[Subscription]) -> dict | None:
    """手动顺序偏好导出转换：把有序订阅 ID 列表转成 subscriptions 数组下标。

    恢复时新实例的订阅 ID 会重新分配，只有导出数组下标是稳定引用（审核
    Medium）。ID 不在当前订阅集合（陈旧引用）的条目剔除。
    subs 是 ORM 订阅对象列表（审核 Medium：_collect_entities 的 dict 无 id
    字段，误用会 AttributeError 500）。"""
    saved = u.subscription_order
    if not isinstance(saved, dict):
        return None
    id_to_index = {s.id: i for i, s in enumerate(subs)}
    out = {}
    for key, ids in saved.items():
        if not isinstance(ids, list):
            continue
        indexes = [id_to_index[i] for i in ids if i in id_to_index]
        if indexes:
            out[key] = indexes
    return out or None


def _user_meta(u: User, subs: list[Subscription] | None = None) -> dict:
    """整站备份才导出账户信息（含密码哈希，便于完整还原账号）。仅管理员可访问。

    subs 传入手动排序偏好引用的订阅列表（用于把 ID 转成数组下标）。"""
    subscription_order = (
        _subscription_order_to_indexes(u, subs) if subs is not None else None
    )
    return {
        "username": u.username,
        "email": u.email,
        "password_hash": u.password_hash,
        "is_admin": u.is_admin,
        "is_active": u.is_active,
        "is_approved": u.is_approved,
        "email_verified": u.email_verified,
        "theme": u.theme,
        "base_currency": u.base_currency,
        "monthly_budget": u.monthly_budget,
        "category_order": u.category_order,
        # 已手动拖拽排序的分类 key → 订阅数组下标列表（恢复时按下标 → 新 ID 重映射）
        "subscription_order": subscription_order,
    }


@router.get("/export-all")
def export_all(admin: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    """管理员：导出全部成员的账户与数据（整站备份）。"""
    users = db.scalars(select(User).order_by(User.id)).all()
    payload_users = []
    for u in users:
        # 复用 _collect_entities 返回的同一份 ORM 订阅列表（复审 Medium：
        # 偏好下标必须与导出数组同源，独立二次查询会错位）
        block, orm_subs = _collect_entities(db, u)
        block["user"] = _user_meta(u, orm_subs)
        payload_users.append(block)
    activity.log(
        "backup.export_all", f"管理员导出整站备份（{len(payload_users)} 个用户）", user=admin
    )
    return {
        "export_version": EXPORT_VERSION,
        "app": "Subly",
        "scope": "all",
        "exported_at": utcnow().isoformat(timespec="seconds"),
        "users": payload_users,
    }


class ImportAllIn(BaseModel):
    data: dict
    replace: bool = False  # True：每个用户导入前先清空其现有订阅


@router.post("/import-all")
def import_all(
    payload: ImportAllIn,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """管理员：从整站备份恢复全部成员数据。

    按用户名匹配现有账户；账户不存在则用备份中的账户信息（含密码哈希）新建。
    """
    data = payload.data or {}
    users_in = data.get("users")
    if not isinstance(users_in, list):
        raise HTTPException(400, "备份文件格式不正确：缺少 users（请使用整站备份文件）")

    existing_users = {u.username: u for u in db.scalars(select(User)).all()}
    created_users = 0
    total_subs = 0

    try:
        for ub in users_in:
            if not isinstance(ub, dict):
                raise ValueError("整站备份的 users 项必须是对象")
            meta = ub.get("user") or {}
            if not isinstance(meta, dict):
                raise ValueError("整站备份的 user 字段必须是对象")
            username = meta.get("username")
            if not username:
                raise ValueError("整站备份存在缺少 username 的用户块")

            target = existing_users.get(username)
            if not target:
                # 新建账户：优先沿用备份的密码哈希，缺失则给一个需重置的占位密码
                pwd_hash = meta.get("password_hash") or hash_password(username + "@reset")
                target = User(
                    username=username,
                    email=meta.get("email") or f"{username}@example.com",
                    password_hash=pwd_hash,
                    is_admin=bool(meta.get("is_admin", False)),
                    is_active=bool(meta.get("is_active", True)),
                    is_approved=bool(meta.get("is_approved", True)),
                    email_verified=bool(meta.get("email_verified", True)),
                    theme=meta.get("theme", "light"),
                    # 偏好字段在恢复实体后统一校验并应用，避免原始畸形值先进入 flush。
                    base_currency="CNY",
                    monthly_budget=None,
                    category_order=meta.get("category_order"),
                )
                db.add(target)
                db.flush()
                existing_users[username] = target
                created_users += 1

            # 审核 Medium：累计各用户的导入数——元组赋值直接覆盖会把
            # total_subs 变成「最后一个用户」的数量，响应与活动日志失真
            # 审核 Medium：累计各用户的导入数——元组赋值直接覆盖会把
            # total_subs 变成「最后一个用户」的数量，响应与活动日志失真
            imported_count, sub_index_to_id, cat_key_to_id, restored_subs = _restore_entities(
                db,
                target,
                ub,
                payload.replace,
                export_version=data.get("export_version"),
            )
            total_subs += imported_count
            _apply_user_preferences(db, target, meta, label=username)
            _apply_subscription_order(db, target, meta, sub_index_to_id, cat_key_to_id, replace=payload.replace, restored_subs=restored_subs)
    except (ValueError, TypeError, AttributeError) as e:
        db.rollback()
        raise HTTPException(400, f"备份校验失败：{e}")

    db.commit()
    if payload.replace or any(
        isinstance(block, dict) and "credit_cards" in block for block in users_in
    ):
        scheduler.rescan_after_restore()
    activity.log(
        "backup.import_all",
        f"管理员恢复整站备份：新建 {created_users} 个用户，共导入 {total_subs} 个订阅",
        user=admin,
        level="warn",
    )
    return {"ok": True, "users": len(users_in), "created_users": created_users, "imported": total_subs}

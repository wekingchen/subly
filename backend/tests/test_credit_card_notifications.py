from datetime import date, datetime

from icalendar import Calendar
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (
    CreditCard,
    CreditCardNotificationLog,
    CreditCardNotificationOutbox,
    NotificationOutbox,
    SchedulerState,
    User,
)
from app.routers import notifications
from app.services import (
    calendar_feed,
    credit_card_notification_outbox,
    credit_card_reminders,
    notification_transport,
)


def make_db(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'credit-card-notifications.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(credit_card_reminders.database, "SessionLocal", Session)
    monkeypatch.setattr(
        credit_card_notification_outbox.database, "SessionLocal", Session
    )
    monkeypatch.setattr(
        credit_card_notification_outbox.activity, "log", lambda *args, **kwargs: None
    )
    return Session, engine


def add_card(db):
    user = User(
        username="alice",
        email="alice@example.com",
        password_hash="hash",
        webhook_enabled=True,
        webhook_url="https://hooks.example.com/subly",
        webhook_secret="webhook-secret-placeholder",
    )
    db.add(user)
    db.flush()
    card = CreditCard(
        user_id=user.id,
        display_name="日常消费主卡",
        bank_name="测试银行",
        last_four="1234",
        statement_day=25,
        due_day=5,
        remind_days_before=[7, 3, 1, 0],
    )
    db.add(card)
    db.commit()
    return user, card


def test_credit_card_scan_is_idempotent_and_payload_is_minimal(tmp_path, monkeypatch):
    Session, engine = make_db(tmp_path, monkeypatch)
    db = Session()
    try:
        user, card = add_card(db)
        as_of = date(2026, 8, 29)

        first = credit_card_reminders.run_reminder_scan(as_of)
        second = credit_card_reminders.run_reminder_scan(as_of)

        assert first == {"scanned": 1, "enqueued": 1, "existing": 0, "skipped": 0}
        assert second == {"scanned": 1, "enqueued": 0, "existing": 1, "skipped": 0}
        row = db.scalar(select(CreditCardNotificationOutbox))
        assert row.due_date == date(2026, 9, 5)
        assert row.days_before == 7
        assert row.status == "pending"
        assert db.get(
            SchedulerState, "credit_card_reminder_scan"
        ).last_completed_business_date == as_of
        rendered = str(row.payload)
        assert card.last_four not in rendered
        assert user.webhook_secret not in rendered
        assert user.webhook_url not in rendered
        assert "credit_card.repayment.reminder" in rendered
        assert "未还" not in rendered
        assert "逾期" not in rendered
    finally:
        db.close()
        engine.dispose()


def test_credit_card_dispatch_uses_stable_delivery_id_and_cancels_changed_rule(
    tmp_path, monkeypatch
):
    Session, engine = make_db(tmp_path, monkeypatch)
    db = Session()
    try:
        _, card = add_card(db)
        as_of = date(2026, 8, 29)
        credit_card_reminders.run_reminder_scan(as_of)
        captured = {}
        monkeypatch.setattr(
            notification_transport.webhook,
            "send_notification",
            lambda url, secret, payload, *, delivery_id=None: captured.update(
                {"payload": payload, "delivery_id": delivery_id, "secret": secret}
            ) or payload,
        )

        result = credit_card_notification_outbox.dispatch_due()

        assert result["sent"] == 1
        db.expire_all()
        row = db.scalar(select(CreditCardNotificationOutbox))
        log = db.scalar(select(CreditCardNotificationLog))
        assert row.status == "sent"
        assert log.credit_card_id == card.id
        assert captured["delivery_id"] == f"subly-{row.delivery_id}"
        assert captured["payload"]["credit_card_id"] == card.id
        assert "last_four" not in captured["payload"]

        card.remind_days_before = []
        db.add(
            CreditCardNotificationOutbox(
                delivery_id="f" * 32,
                credit_card_id=card.id,
                user_id=card.user_id,
                business_date=as_of,
                due_date=date(2026, 9, 5),
                days_before=7,
                channel="telegram",
                status="pending",
                credit_card_name=card.display_name,
                payload={"event": {}},
            )
        )
        db.commit()
        assert credit_card_notification_outbox.dispatch_due()["canceled"] == 1
    finally:
        db.close()
        engine.dispose()


def test_unified_delivery_cursor_is_stable_across_tables(tmp_path, monkeypatch):
    Session, engine = make_db(tmp_path, monkeypatch)
    db = Session()
    try:
        user, card = add_card(db)
        created_at = datetime(2026, 8, 29, 6, 0, 0)
        db.add_all([
            NotificationOutbox(
                delivery_id="a" * 32,
                subscription_id=100,
                user_id=user.id,
                business_date=date(2026, 8, 29),
                days_before=7,
                channel="webhook",
                status="sent",
                subscription_name="订阅 A",
                renewal_date=date(2026, 9, 5),
                payload={},
                created_at=created_at,
                updated_at=created_at,
            ),
            CreditCardNotificationOutbox(
                delivery_id="b" * 32,
                credit_card_id=card.id,
                user_id=user.id,
                business_date=date(2026, 8, 29),
                due_date=date(2026, 9, 5),
                days_before=7,
                channel="webhook",
                status="sent",
                credit_card_name=card.display_name,
                payload={},
                created_at=created_at,
                updated_at=created_at,
            ),
            NotificationOutbox(
                delivery_id="c" * 32,
                subscription_id=101,
                user_id=user.id,
                business_date=date(2026, 8, 28),
                days_before=7,
                channel="webhook",
                status="pending",
                subscription_name="订阅 B",
                renewal_date=date(2026, 9, 4),
                payload={},
                created_at=datetime(2026, 8, 28, 6, 0, 0),
                updated_at=datetime(2026, 8, 28, 6, 0, 0),
            ),
        ])
        db.commit()

        first = notifications.delivery_list(
            status=None,
            kind=None,
            limit=2,
            before_created_at=None,
            before_kind=None,
            before_id=None,
            user=user,
            db=db,
        )
        assert [item["kind"] for item in first["items"]] == [
            "credit_card",
            "subscription",
        ]
        assert first["has_more"] is True
        cursor = first["next_cursor"]
        second = notifications.delivery_list(
            status=None,
            kind=None,
            limit=2,
            before_created_at=cursor["created_at"],
            before_kind=cursor["kind"],
            before_id=cursor["id"],
            user=user,
            db=db,
        )
        assert [item["source_name"] for item in second["items"]] == ["订阅 B"]
        assert first["summary"]["total"] == 3
    finally:
        db.close()
        engine.dispose()


def test_private_calendar_includes_minimal_credit_card_events(tmp_path, monkeypatch):
    Session, engine = make_db(tmp_path, monkeypatch)
    db = Session()
    try:
        user, card = add_card(db)
        content = calendar_feed.build_calendar(
            db,
            user,
            today=date(2026, 8, 29),
            uid_namespace="feed-namespace",
        )
        parsed = Calendar.from_ical(content)
        events = [
            item
            for item in parsed.walk()
            if item.name == "VEVENT"
            and item.decoded("SUMMARY").startswith("计划还款：")
        ]
        assert events
        first = events[0]
        assert first.decoded("SUMMARY") == f"计划还款：{card.display_name}"
        assert first.decoded("UID").startswith(
            f"subly-credit-card-{user.id}-{card.id}-"
        )
        assert (first.decoded("DTEND") - first.decoded("DTSTART")).days == 1
        rendered = content.decode("utf-8")
        assert card.last_four not in rendered
        assert "webhook-secret-placeholder" not in rendered
        assert "以银行账单为准" in rendered
    finally:
        db.close()
        engine.dispose()


def test_external_outputs_strip_last_four_written_into_display_name(
    tmp_path, monkeypatch
):
    """尾号写进别名时，iCal 与三通道通知也不得外发该 4 位数字（隐私契约 WHY）。"""
    Session, engine = make_db(tmp_path, monkeypatch)
    db = Session()
    try:
        user = User(
            username="bob",
            email="bob@example.com",
            password_hash="hash",
            telegram_enabled=True,
            telegram_bot_token="telegram-token-placeholder",
            telegram_chat_id="123",
            bark_enabled=True,
            bark_device_key="bark-key-placeholder",
            webhook_enabled=True,
            webhook_url="https://hooks.example.com/subly",
            webhook_secret="webhook-secret-placeholder",
        )
        db.add(user)
        db.flush()
        card = CreditCard(
            user_id=user.id,
            display_name="招行主卡 1234",
            bank_name="招商银行",
            last_four="1234",
            statement_day=25,
            due_day=5,
            remind_days_before=[7],
        )
        db.add(card)
        db.commit()

        rendered = calendar_feed.build_calendar(
            db, user, today=date(2026, 8, 29), uid_namespace="ns"
        ).decode("utf-8")
        assert "1234" not in rendered
        assert "计划还款：招行主卡" in rendered

        payloads = {
            channel: credit_card_reminders._build_payload(
                card, date(2026, 9, 5), 7, channel
            )
            for channel in ("telegram", "bark", "webhook")
        }
        blob = str(payloads)
        assert "1234" not in blob
        assert "招行主卡" in blob
    finally:
        db.close()
        engine.dispose()


def test_subscription_scan_failure_does_not_block_credit_card_scan(
    tmp_path, monkeypatch
):
    """一类扫描抛错时另一类仍须执行（隔离 WHY）；失败结果要响亮记录。"""
    from app.services import scheduler

    engine = create_engine(
        f"sqlite:///{tmp_path / 'scan-isolation.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(scheduler.database, "SessionLocal", Session)
    monkeypatch.setattr(credit_card_reminders.database, "SessionLocal", Session)
    calls = []
    monkeypatch.setattr(
        scheduler, "run_reminder_scan",
        lambda: calls.append("subscription") or (_ for _ in ()).throw(
            RuntimeError("dirty subscription")
        ),
    )
    monkeypatch.setattr(
        scheduler, "run_credit_card_reminder_scan",
        lambda: calls.append("credit_card") or {"enqueued": 0},
    )

    result = scheduler.run_all_reminder_scans()

    assert calls == ["subscription", "credit_card"]
    assert result["credit_cards"] == {"enqueued": 0}
    assert result["subscriptions"] == {"error": "RuntimeError"}
    engine.dispose()


def test_external_label_falls_back_when_only_punctuation_remains(tmp_path):
    """名称剥离尾号后只剩标点/空白时，外发标签回退为「信用卡」而非残留括号。"""

    class _Card:
        display_name = "（1234）"
        last_four = "1234"

    assert credit_card_reminders.external_card_label(_Card()) == "信用卡"

    class _Wrapped:
        display_name = "招行 - 1234 - 尾号"
        last_four = "1234"

    wrapped_label = credit_card_reminders.external_card_label(_Wrapped())
    # 契约只要求尾号不外发且保留可读名称；分隔符如何收缩是实现细节。
    assert "1234" not in wrapped_label
    assert "招行" in wrapped_label and "尾号" in wrapped_label

    class _Normal:
        display_name = "主卡 1234"
        last_four = "1234"

    assert credit_card_reminders.external_card_label(_Normal()) == "主卡"

    class _NoLastFour:
        display_name = "（1234）"
        last_four = None

    # 未登记尾号时无从比对，名称保持原样（不误伤）。
    assert credit_card_reminders.external_card_label(_NoLastFour()) == "（1234）"


def test_credit_limit_never_reaches_external_outputs(tmp_path, monkeypatch):
    """额度是展示性数据：三通道 payload 与 iCal 渲染都不得包含 credit_limit 数值。"""
    Session, engine = make_db(tmp_path, monkeypatch)
    db = Session()
    try:
        user, card = add_card(db)
        card.credit_limit = 50000.0
        db.commit()

        rendered = calendar_feed.build_calendar(
            db, user, today=date(2026, 8, 29), uid_namespace="ns"
        ).decode("utf-8")
        assert "50000" not in rendered

        for channel in ("telegram", "bark", "webhook"):
            payload = credit_card_reminders._build_payload(
                card, date(2026, 9, 5), 7, channel
            )
            assert "50000" not in str(payload)
            assert "credit_limit" not in str(payload)
    finally:
        db.close()
        engine.dispose()


def test_external_outputs_never_render_credit_limit(tmp_path, monkeypatch):
    """额度是展示性数据：三通道 payload 与 iCal 均不得出现额度数值。"""
    Session, engine = make_db(tmp_path, monkeypatch)
    db = Session()
    try:
        user, card = add_card(db)
        card.credit_limit = 50000.0
        db.commit()

        rendered = calendar_feed.build_calendar(
            db, user, today=date(2026, 8, 29), uid_namespace="ns"
        ).decode("utf-8")
        assert "50000" not in rendered

        payloads = [
            credit_card_reminders._build_payload(card, date(2026, 9, 5), 7, channel)
            for channel in ("telegram", "bark", "webhook")
        ]
        blob = str(payloads)
        assert "50000" not in blob
        assert "credit_limit" not in blob
    finally:
        db.close()
        engine.dispose()


def test_repaid_card_produces_no_reminder_candidates(tmp_path, monkeypatch):
    """标记已还款后：提醒扫描按顺延派生，不再产生当期候选。"""
    Session, engine = make_db(tmp_path, monkeypatch)
    db = Session()
    try:
        user, card = add_card(db)  # due_day=5, remind [7,3,1,0]
        card.repaid_through_due = date(2026, 9, 5)  # 当期 9/5 已还
        db.commit()

        planned = credit_card_reminders.plan_reminder_candidates(db, date(2026, 8, 29))
        # 未标记时该卡应产生 9/5 提前 7 天的候选；标记后顺延到 10/5，8/29 距离 37 天不在提醒窗口
        assert planned["candidates"] == []
    finally:
        db.close()
        engine.dispose()


def test_repaid_card_cancels_already_enqueued_pending_reminders(tmp_path, monkeypatch):
    """已入队未投递的当期提醒：标记还款后在投递前复核中被自动取消。"""
    Session, engine = make_db(tmp_path, monkeypatch)
    db = Session()
    try:
        _, card = add_card(db)
        as_of = date(2026, 8, 29)
        credit_card_reminders.run_reminder_scan(as_of)
        assert db.scalar(select(CreditCardNotificationOutbox)).status == "pending"

        # 用户标记该期已还款 → 界线推进到 9/5
        card.repaid_through_due = date(2026, 9, 5)
        db.commit()

        result = credit_card_notification_outbox.dispatch_due()
        assert result["canceled"] == 1
        assert result["sent"] == 0
        db.expire_all()
        row = db.scalar(select(CreditCardNotificationOutbox))
        assert row.status == "canceled"
        assert row.canceled_at is not None
    finally:
        db.close()
        engine.dispose()


def test_ical_feed_excludes_repaid_period(tmp_path, monkeypatch):
    """iCal feed：已还界线覆盖的期次不再生成还款事件，之后期次保留。"""
    Session, engine = make_db(tmp_path, monkeypatch)
    db = Session()
    try:
        user, card = add_card(db)  # due_day=5
        card.repaid_through_due = date(2026, 9, 5)
        db.commit()

        data = calendar_feed.build_calendar(db, user, today=date(2026, 8, 29))
        dates = [
            c.decoded("dtstart")
            for c in Calendar.from_ical(data).walk("VEVENT")
            if "计划还款" in str(c["summary"])
        ]
        # 窗口含过去 31 天：8/5 与 9/5 两期已还 → 不出现；最早是 10/5
        assert all(d > date(2026, 9, 5) for d in dates)
        assert min(dates) == date(2026, 10, 5)
    finally:
        db.close()
        engine.dispose()


# ---------- 提醒文案：银行/卡名、金额、倒计时（用户确认口径） ----------

def test_bark_payload_includes_bank_amount_and_countdown(tmp_path, monkeypatch):
    """Bark 文案优化（用户需求）：标题带银行+卡名，正文带倒计时与应还金额。
    金额取该卡最新未还账单 total_due（与待还汇总同口径）。"""
    from app.models import CreditCardStatement

    Session, engine = make_db(tmp_path, monkeypatch)
    db = Session()
    try:
        user, card = add_card(db)
        db.commit()
        stmt = CreditCardStatement(
            user_id=user.id, card_id=card.id, bank_key="pab", card_last_four="1234",
            match_status="matched", statement_date=date(2026, 8, 13),
            due_date=date(2026, 9, 5), total_due=2546.50,
            message_id="amt-1", verify_status="ok", is_repaid=False,
        )
        db.add(stmt)
        db.commit()

        amount = credit_card_reminders.latest_unrepaid_amount(db, card)
        assert amount == 2546.50
        payload = credit_card_reminders._build_payload(
            card, date(2026, 9, 5), 3, "bark", amount)
        assert payload["title"] == "💳 测试银行 · 日常消费主卡 还款提醒"
        assert "还有 3 天" in payload["body"]
        assert "2,546.50" in payload["body"]
        assert "应还" in payload["body"]

        # Telegram 同口径
        tg = credit_card_reminders._build_payload(
            card, date(2026, 9, 5), 3, "telegram", amount)
        assert "测试银行 · 日常消费主卡" in tg["text"]
        assert "2,546.50" in tg["text"]

        # Webhook event 携带结构化金额
        wh = credit_card_reminders._build_payload(
            card, date(2026, 9, 5), 3, "webhook", amount)
        assert wh["event"]["total_due"] == 2546.50
        assert wh["event"]["days_before"] == 3
    finally:
        db.close()
        engine.dispose()


def test_reminder_amount_follows_latest_statement_semantics(tmp_path, monkeypatch):
    """金额口径与待还汇总一致：取最新一期未还账单；最新为负=富余（本期无需
    还款）；已标记还款的旧账单不参与。"""
    from app.models import CreditCardStatement

    Session, engine = make_db(tmp_path, monkeypatch)
    db = Session()
    try:
        user, card = add_card(db)
        db.commit()
        old = CreditCardStatement(
            user_id=user.id, card_id=card.id, bank_key="pab", card_last_four="1234",
            match_status="matched", statement_date=date(2026, 7, 13),
            due_date=date(2026, 8, 1), total_due=100.00,
            message_id="amt-old", verify_status="ok", is_repaid=True,  # 已标记
        )
        surplus = CreditCardStatement(
            user_id=user.id, card_id=card.id, bank_key="pab", card_last_four="1234",
            match_status="matched", statement_date=date(2026, 8, 13),
            due_date=date(2026, 9, 1), total_due=-500.00,
            message_id="amt-surplus", verify_status="ok", is_repaid=False,
        )
        db.add_all([old, surplus])
        db.commit()

        amount = credit_card_reminders.latest_unrepaid_amount(db, card)
        assert amount == -500.00  # 最新未还是富余账单
        payload = credit_card_reminders._build_payload(
            card, date(2026, 9, 5), 1, "bark", amount)
        assert "账上有富余 500.00 元" in payload["body"]
        assert "本期无需还款" in payload["body"]
    finally:
        db.close()
        engine.dispose()


def test_reminder_amount_falls_back_when_no_statement(tmp_path, monkeypatch):
    """无账单/金额未知：文案回退「金额以银行账单为准」，不显示 0 也不崩。"""
    Session, engine = make_db(tmp_path, monkeypatch)
    db = Session()
    try:
        user, card = add_card(db)
        db.commit()
        assert credit_card_reminders.latest_unrepaid_amount(db, card) is None
        payload = credit_card_reminders._build_payload(
            card, date(2026, 9, 5), 3, "bark", None)
        assert "应还金额以银行账单为准" in payload["body"]
        assert "0.00" not in payload["body"].replace("0.00 元", "X")  # 不出现猜测金额
        # 当天到期（days_before=0）显示「今天」
        today_payload = credit_card_reminders._build_payload(
            card, date(2026, 9, 5), 0, "bark", None)
        assert "今天" in today_payload["body"]
    finally:
        db.close()
        engine.dispose()


def test_multi_user_scan_uses_each_cards_own_user(tmp_path, monkeypatch):
    """审核 High 回归：两阶段重构后候选构造必须用每张卡自己的 user——
    用户 A（卡提醒、开 webhook）的卡 ID 小，用户 B（不在提醒窗口、不开
    webhook）的卡 ID 大；若复用循环残留的 user 变量，A 的提醒会按 B 的
    配置处理（跳过或跨用户入队被取消）。"""
    from app.models import CreditCard

    Session, engine = make_db(tmp_path, monkeypatch)
    db = Session()
    try:
        user_a = User(username="alice", email="a@example.com", password_hash="h",
                      webhook_enabled=True, webhook_url="https://hooks.example.com/a",
                      webhook_secret="s-a")
        db.add(user_a)
        db.flush()
        card_a = CreditCard(user_id=user_a.id, display_name="A卡", bank_name="测试银行",
                            last_four="1111", statement_day=25, due_day=12,
                            remind_days_before=[7])  # 9/5 → 9/12 还差 7 天，命中
        db.add(card_a)
        user_b = User(username="bob", email="b@example.com", password_hash="h",
                      webhook_enabled=False)  # B 无任何通道
        db.add(user_b)
        db.flush()
        card_b = CreditCard(user_id=user_b.id, display_name="B卡", bank_name="测试银行",
                            last_four="2222", statement_day=25, due_day=6,
                            remind_days_before=[7])  # due_day=6 → 9/6，不在 9/5 的窗口
        db.add(card_b)
        db.commit()

        planned = credit_card_reminders.plan_reminder_candidates(db, date(2026, 9, 5))
        # A 卡正常规划且归属 user_a（B 卡不在窗口不产生候选）
        assert [c["credit_card_id"] for c in planned["candidates"]] == [card_a.id]
        assert all(c["user_id"] == user_a.id for c in planned["candidates"])
    finally:
        db.close()
        engine.dispose()


def test_reminder_amount_falls_back_to_bill_period_end(tmp_path, monkeypatch):
    """审核 Medium 回归：statement_date 为空时「最新」判定回退
    bill_period_end（与 outstanding_summary 口径一致）——否则待还汇总显示
    500（8月期）而提醒发 100（7月期）。两日期皆空的账单不参与判定。"""
    from datetime import date as _date

    from app.models import CreditCardStatement

    Session, engine = make_db(tmp_path, monkeypatch)
    db = Session()
    try:
        user, card = add_card(db)
        db.commit()
        older = CreditCardStatement(
            user_id=user.id, card_id=card.id, bank_key="pab", card_last_four="1234",
            match_status="matched", statement_date=_date(2026, 7, 13),
            due_date=_date(2026, 8, 1), total_due=100.00,
            message_id="amt-jul", verify_status="ok", is_repaid=False,
        )
        newer_nodate = CreditCardStatement(
            user_id=user.id, card_id=card.id, bank_key="pab", card_last_four="1234",
            match_status="matched", statement_date=None,  # 仅 bill_period_end
            bill_period_end=_date(2026, 8, 31), due_date=_date(2026, 9, 1),
            total_due=500.00, message_id="amt-aug", verify_status="ok", is_repaid=False,
        )
        undated = CreditCardStatement(
            user_id=user.id, card_id=card.id, bank_key="pab", card_last_four="1234",
            match_status="matched", statement_date=None, bill_period_end=None,
            total_due=999.00, message_id="amt-nodate", verify_status="ok", is_repaid=False,
        )
        db.add_all([older, newer_nodate, undated])
        db.commit()

        # 8 月期（bill_period_end 更晚）胜出，两日期皆空的不参与「最新」判定
        amount = credit_card_reminders.latest_unrepaid_amount(db, card)
        assert amount == 500.00

        # 对照：只剩两日期皆空的账单 → 与汇总累加口径一致（复审 Low：
        # 汇总会累加这类账单，提醒取全部之和而非单笔，两条 999+200=1199）
        extra = CreditCardStatement(
            user_id=user.id, card_id=card.id, bank_key="pab", card_last_four="1234",
            match_status="matched", statement_date=None, bill_period_end=None,
            total_due=200.00, message_id="amt-nodate2", verify_status="ok", is_repaid=False,
        )
        db.add(extra)
        db.query(CreditCardStatement).filter(
            CreditCardStatement.message_id.in_(["amt-jul", "amt-aug"])
        ).delete(synchronize_session=False)
        db.commit()
        assert credit_card_reminders.latest_unrepaid_amount(db, card) == 1199.00

        # 全部金额 NULL → None（不能把未知伪装成 0.00 元；复审 Low）
        db.query(CreditCardStatement).filter(
            CreditCardStatement.message_id.in_(["amt-nodate", "amt-nodate2"])
        ).delete(synchronize_session=False)
        db.add(CreditCardStatement(
            user_id=user.id, card_id=card.id, bank_key="pab", card_last_four="1234",
            match_status="matched", statement_date=None, bill_period_end=None,
            total_due=None, message_id="amt-null", verify_status="ok", is_repaid=False,
        ))
        db.commit()
        assert credit_card_reminders.latest_unrepaid_amount(db, card) is None
    finally:
        db.close()
        engine.dispose()


def test_bank_name_with_last_four_is_sanitized_in_all_channels(tmp_path):
    """审核 Medium 回归：尾号写进银行名（如「招商银行 1234」）时，三通道
    payload 均不得包含尾号——银行名外发前与卡片标签同规则净化。"""
    class _Card:
        display_name = "主卡"
        bank_name = "招商银行 1234"
        last_four = "1234"
        id = 1

    card = _Card()
    for channel in ("telegram", "bark", "webhook"):
        payload = credit_card_reminders._build_payload(card, date(2026, 9, 5), 3, channel, 100.0)
        assert "1234" not in str(payload), f"{channel} 泄露尾号: {payload}"
    bark = credit_card_reminders._build_payload(card, date(2026, 9, 5), 3, "bark", 100.0)
    assert bark["title"] == "💳 招商银行 · 主卡 还款提醒"


def test_sanitize_label_edge_cases(tmp_path):
    """复审 Low 回归：净化规则的边界——未发生尾号剥离的纯标点输入保持
    原样（原 external_card_label 行为）；发生剥离后仅剩标点的银行名回退。"""

    class _Card:
        def __init__(self, display_name, bank_name="测试银行", last_four="1234"):
            self.display_name = display_name
            self.bank_name = bank_name
            self.last_four = last_four
            self.id = 1

    # 未剥离（尾号不在名称里）：「（）」保持原样不回退（行为与重构前一致）
    card = _Card("（）")
    assert credit_card_reminders.external_card_label(card) == "（）"
    # 未剥离时也不做空白压缩（「主  卡」原样保留——strip/压缩只发生在剥离分支）
    card_sp = _Card("主  卡")
    assert credit_card_reminders.external_card_label(card_sp) == "主  卡"
    # 剥离后仅剩标点：「（1234）」→「（）」→ 银行名回退「信用卡」
    card2 = _Card("主卡", bank_name="（1234）")
    assert credit_card_reminders.external_bank_label(card2) == "信用卡"
    # 剥离后仅剩标点的卡名同样回退（既有行为保持）
    card3 = _Card("（1234）")
    assert credit_card_reminders.external_card_label(card3) == "信用卡"

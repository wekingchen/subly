from datetime import date, datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Category, NotificationLog, PaymentMethod, Subscription, User
from app.services import scheduler


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session(), engine


def add_user(db, **overrides):
    base_currency = overrides.pop("base_currency", "CNY")
    user = User(
        username=overrides.pop("username", "alice"),
        email=overrides.pop("email", "alice@example.com"),
        password_hash="hash",
        base_currency=base_currency,
        **overrides,
    )
    db.add(user)
    db.flush()
    return user


def add_subscription(db, user, **overrides):
    sub = Subscription(
        user_id=user.id,
        name=overrides.pop("name", "Pro VPS"),
        plan=overrides.pop("plan", "基础版"),
        amount=overrides.pop("amount", 12.5),
        currency=overrides.pop("currency", "USD"),
        billing_type="recurring",
        cycle=overrides.pop("cycle", "month"),
        cycle_count=overrides.pop("cycle_count", 1),
        start_date=overrides.pop("start_date", date(2024, 1, 1)),
        next_renewal_date=overrides.pop("next_renewal_date", date(2024, 1, 8)),
        remind_days_before="7,1",
        auto_renew=overrides.pop("auto_renew", False),
        **overrides,
    )
    db.add(sub)
    db.flush()
    return sub


def test_parse_days_ignores_empty_and_non_numeric_values():
    assert scheduler._parse_days("7, 1, bad, ,0,-1") == [7, 1, 0]


def test_send_one_records_success_failure_and_duplicate_skip(monkeypatch):
    db, engine = make_db()
    try:
        monkeypatch.setattr(scheduler.activity, "log", lambda *args, **kwargs: None)
        user = add_user(db)
        sub = add_subscription(db, user)
        today = date.today()

        ok, status = scheduler._send_one(db, sub, user, 7, today, "telegram", lambda: "sent body")
        assert (ok, status) == (True, "sent")
        first_log = db.scalar(select(NotificationLog).where(NotificationLog.subscription_id == sub.id))
        assert first_log.message == "sent body"
        assert first_log.status == "sent"

        ok, status = scheduler._send_one(db, sub, user, 7, today, "telegram", lambda: "second body")
        assert (ok, status) == (False, "skip")
        assert db.scalars(select(NotificationLog).where(NotificationLog.subscription_id == sub.id)).all() == [first_log]

        def fail():
            raise RuntimeError("provider down")

        ok, status = scheduler._send_one(db, sub, user, 1, today, "bark", fail)
        assert (ok, status) == (False, "failed")
        failed = db.scalar(
            select(NotificationLog).where(
                NotificationLog.subscription_id == sub.id,
                NotificationLog.channel == "bark",
            )
        )
        assert failed.message == "RuntimeError"
    finally:
        db.close()
        engine.dispose()


def test_already_sent_only_matches_same_channel_day_and_sent_status():
    db, engine = make_db()
    try:
        user = add_user(db)
        sub = add_subscription(db, user)
        db.add_all([
            NotificationLog(
                subscription_id=sub.id,
                user_id=user.id,
                days_before=7,
                channel="telegram",
                status="failed",
                sent_at=datetime(2024, 1, 1, 8, 0, 0),
            ),
            NotificationLog(
                subscription_id=sub.id,
                user_id=user.id,
                days_before=7,
                channel="telegram",
                status="sent",
                sent_at=datetime(2024, 1, 2, 8, 0, 0),
            ),
        ])
        db.commit()

        assert scheduler._already_sent(db, sub.id, 7, "telegram", date(2024, 1, 1)) is False
        assert scheduler._already_sent(db, sub.id, 7, "telegram", date(2024, 1, 2)) is True
        assert scheduler._already_sent(db, sub.id, 7, "bark", date(2024, 1, 2)) is False
    finally:
        db.close()
        engine.dispose()


def test_send_one_sanitizes_provider_failure_messages(monkeypatch):
    db, engine = make_db()
    try:
        activity_details = []
        monkeypatch.setattr(scheduler.activity, "log", lambda action, detail="", **kwargs: activity_details.append(detail))
        user = add_user(db)
        sub = add_subscription(db, user)

        def fail_with_sensitive_url():
            raise RuntimeError("https://api.telegram.org/botsecret-token/sendMessage")

        ok, status = scheduler._send_one(db, sub, user, 3, date.today(), "telegram", fail_with_sensitive_url)

        assert (ok, status) == (False, "failed")
        failed = db.scalar(
            select(NotificationLog).where(
                NotificationLog.subscription_id == sub.id,
                NotificationLog.channel == "telegram",
            )
        )
        assert failed.message == "RuntimeError"
        assert "secret-token" not in activity_details[-1]
    finally:
        db.close()
        engine.dispose()


def test_reminder_text_includes_core_subscription_context(monkeypatch):
    db, engine = make_db()
    try:
        monkeypatch.setattr(scheduler.exchange, "convert", lambda db, amount, from_cur, to_cur: 88.88)
        user = add_user(db, base_currency="CNY")
        category = Category(user_id=user.id, name="云服务器", icon="", color="#00f")
        payment = PaymentMethod(user_id=user.id, name="Visa", icon="")
        db.add_all([category, payment])
        db.flush()
        sub = add_subscription(
            db,
            user,
            category_id=category.id,
            payment_method_id=payment.id,
            remark="生产节点",
            family_members=["主账号", "备用"],
            url="https://example.com",
        )

        telegram_text = scheduler._build_telegram_text(db, sub, user, 7)
        assert "Pro VPS" in telegram_text
        assert "基础版" in telegram_text
        assert "云服务器" in telegram_text
        assert "12.50 USD" in telegram_text
        assert "88.88 CNY" in telegram_text
        assert "Visa" in telegram_text
        assert "生产节点" in telegram_text
        assert "https://example.com" in telegram_text

        title, body = scheduler._build_bark_text(db, sub, user, 0)
        assert title == "⚠️ Pro VPS 今天到期"
        assert body == "基础版套餐，每月 12.50 USD（约 88.88 CNY），今天就到期，由 Visa 扣款，备注：生产节点，分类：云服务器。"
    finally:
        db.close()
        engine.dispose()


def test_bark_text_is_natural_and_omits_empty_fields(monkeypatch):
    """Bark 文案单行口语化；套餐/付款/备注「有才说」；外币才折算；周期用「月/年」。"""
    db, engine = make_db()
    try:
        monkeypatch.setattr(scheduler.exchange, "convert",
                            lambda db, amount, from_cur, to_cur: amount if from_cur == to_cur else 88.0)
        # 同币种：不折算；无套餐/付款/备注/分类：正文停在到期语句
        user_cny = add_user(db, username="cn", base_currency="CNY")
        sub_plain = add_subscription(db, user_cny, name="Netflix", amount=88.0, currency="CNY",
                                     plan=None, next_renewal_date=date(2024, 1, 9))
        title, body = scheduler._build_bark_text(db, sub_plain, user_cny, 3)
        assert title == "🔔 Netflix 还有 3 天到期"
        assert body == "每月 88.00 CNY，1 月 9 日到期。"

        # 多年周期用「每 2 年」
        sub_biennial = add_subscription(db, user_cny, name="域名", amount=120.0, currency="CNY",
                                        plan=None, cycle="year", cycle_count=2,
                                        next_renewal_date=date(2024, 1, 19))
        _, body_y = scheduler._build_bark_text(db, sub_biennial, user_cny, 10)
        assert body_y == "每 2 年 120.00 CNY，1 月 19 日到期。"

        # 外币才显示折算「（约 X）」
        user_usd = add_user(db, username="u", email="u@e.com", base_currency="CNY")
        sub_usd = add_subscription(db, user_usd, name="ChatGPT", amount=20.0, currency="USD",
                                   plan=None, next_renewal_date=date(2024, 1, 11))
        _, body_u = scheduler._build_bark_text(db, sub_usd, user_usd, 5)
        assert body_u == "每月 20.00 USD（约 88.00 CNY），1 月 11 日到期。"

        # 句子化：套餐起头 + 由…扣款 + 备注/分类带标签
        cat = Category(user_id=user_cny.id, name="流媒体", icon="", color="#00f")
        pm = PaymentMethod(user_id=user_cny.id, name="招行信用卡", icon="")
        db.add_all([cat, pm]); db.flush()
        sub_full = add_subscription(db, user_cny, name="Disney+", amount=35.0, currency="CNY",
                                    plan="标准版", category_id=cat.id, payment_method_id=pm.id,
                                    remark="家庭共享", next_renewal_date=date(2024, 1, 9))
        _, body_f = scheduler._build_bark_text(db, sub_full, user_cny, 3)
        assert body_f == "标准版套餐，每月 35.00 CNY，1 月 9 日到期，由招行信用卡扣款，备注：家庭共享，分类：流媒体。"
    finally:
        db.close()
        engine.dispose()


def test_cn_join_inserts_space_only_at_cjk_non_cjk_boundary():
    """中英文 token 交界加空格；中文-中文、英文-英文不加；空值安全。"""
    j = scheduler._cn_join
    assert j("基础版", "套餐") == "基础版套餐"      # 中+中 → 无空格
    assert j("Pro", "套餐") == "Pro 套餐"            # 英+中 → 空格
    assert j("由", "Visa") == "由 Visa"              # 中+英 → 空格
    assert j("Visa", "扣款") == "Visa 扣款"          # 英+中 → 空格
    assert j("PayPal", "Plus") == "PayPalPlus"       # 英+英 → 无空格（_cn_join 不处理英英边界）
    assert j("", "套餐") == "套餐"                   # 空值安全
    assert j("基础版", "") == "基础版"
    # 用户输入带前后空格时规范化为单一空格，不产生双空格
    assert j("Pro ", "套餐") == "Pro 套餐"
    assert j("由", " Visa") == "由 Visa"
    assert j(j("由", "Visa "), "扣款") == "由 Visa 扣款"


def test_bark_text_uses_keepalive_phrasing_when_flag_set(monkeypatch):
    """is_keepalive=True 的订阅，Bark/Telegram 提醒切保号文案。"""
    db, engine = make_db()
    try:
        monkeypatch.setattr(scheduler.exchange, "convert",
                            lambda db, amount, from_cur, to_cur: amount if from_cur == to_cur else 88.0)
        user = add_user(db, base_currency="CNY")
        sub = add_subscription(db, user, name="香港保号卡", amount=10.0, currency="CNY",
                               plan="保号", is_keepalive=True,
                               next_renewal_date=date(2024, 1, 9))
        title, body = scheduler._build_bark_text(db, sub, user, 3)
        assert "需保号" in title
        assert "1 月 9 日需保号" in body
        assert "保号" in body  # 套餐段「保号套餐」

        tg = scheduler._build_telegram_text(db, sub, user, 3)
        assert "保号提醒" in tg
        assert "保号日" in tg
        assert "发条短信保号" in tg
    finally:
        db.close()
        engine.dispose()


def test_unique_days_dedupes_and_keeps_first_seen_order():
    assert scheduler._unique_days("7,7,1,1,7") == [7, 1]
    assert scheduler._unique_days("") == []
    assert scheduler._unique_days("bad, 3, 3") == [3]


def make_db_autoflush_off():
    """复刻生产 SessionLocal：autoflush=False，使同事务内 db.add 的行默认不可见。"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    return Session(), engine


def test_send_one_dedupes_within_scan_under_production_autoflush(monkeypatch):
    """回归：生产 SessionLocal 为 autoflush=False，未提交的 log 对 DB 查询不可见。

    同一次扫描内对同一 (订阅, 天数, 通道) 再次调用 _send_one 时，靠传入的内存 seen
    集合去重，既不依赖 db.flush（避免外发期间长持 SQLite 写锁），也不会重发。
    """
    db, engine = make_db_autoflush_off()
    try:
        monkeypatch.setattr(scheduler.activity, "log", lambda *args, **kwargs: None)
        user = add_user(db)
        sub = add_subscription(db, user)
        today = scheduler._local_today()
        seen: set = set()

        ok1, s1 = scheduler._send_one(db, sub, user, 7, today, "telegram", lambda: "first", seen)
        ok2, s2 = scheduler._send_one(db, sub, user, 7, today, "telegram", lambda: "second", seen)

        assert (ok1, s1) == (True, "sent")
        assert (ok2, s2) == (False, "skip")
        db.flush()
        logs = db.scalars(select(NotificationLog).where(NotificationLog.subscription_id == sub.id)).all()
        assert len(logs) == 1
        assert logs[0].message == "first"
    finally:
        db.close()
        engine.dispose()


def test_already_sent_compares_local_calendar_date_not_utc(monkeypatch):
    """回归：去重以本地日历日为准。

    一条记录存为本地凌晨前的 UTC 时刻（例如本地 08:00 前一晚发的，对应 UTC 仍是
    前一天）。按本地日历日，它仍属于「今天」已发，不应因 UTC 跨日而重发。
    """
    db, engine = make_db()
    try:
        user = add_user(db)
        sub = add_subscription(db, user)
        # 本地 00:30 发送：在 +8 时区下对应 UTC 前一天 16:30
        local_now = datetime.now(scheduler._local_zone())
        sent_local = local_now.replace(hour=0, minute=30, second=0, microsecond=0)
        sent_utc = sent_local.astimezone(timezone.utc).replace(tzinfo=None)
        db.add(NotificationLog(
            subscription_id=sub.id, user_id=user.id, days_before=7,
            channel="telegram", status="sent", sent_at=sent_utc,
        ))
        db.commit()

        # 本地今天应判为「已发过」
        assert scheduler._already_sent(db, sub.id, 7, "telegram", scheduler._local_today()) is True
    finally:
        db.close()
        engine.dispose()


def test_local_zone_falls_back_to_utc_on_bad_tz_without_crashing(monkeypatch):
    """回归：settings.tz 配置错误时 _local_zone 退回 UTC 并打 warning，不抛异常。"""
    monkeypatch.setattr(scheduler.settings, "tz", "Not/A_Real/Zone")
    zone = scheduler._local_zone()
    assert zone == timezone.utc
    # _local_today 仍能返回日期，扫描不会因坏配置崩溃
    assert isinstance(scheduler._local_today(), date)


def test_start_scheduler_survives_bad_tz(monkeypatch):
    """回归：settings.tz 非法时 start_scheduler 不应在 BackgroundScheduler 构造期崩溃。

    若直接把原始 settings.tz 传给 APScheduler，非法时区会让进程启动失败；
    应先经 _local_zone() 兜底为 UTC，保证扫描触发时区与 _local_today 一致。
    """
    monkeypatch.setattr(scheduler.settings, "tz", "Not/A_Real/Zone")
    try:
        scheduler.start_scheduler()  # 不应抛异常
        assert scheduler._scheduler is not None
    finally:
        scheduler.shutdown_scheduler()
        # 清理全局，避免污染其它测试 / 后续启动判断
        scheduler._scheduler = None

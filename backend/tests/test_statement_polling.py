"""账单自动抓取轮询测试：run_poll 状态机（显式日期，免时钟）。

用户需求：账单日 D → D+1/2/3 的 23:50 各尝试一次，成功即停，
最多 3 次；停机错过窗口只补当天一次、不回放。
"""

import sys
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).parent))
from statement_fixtures import load_cmb  # noqa: E402

from app.database import Base  # noqa: E402
from app.models import (  # noqa: E402
    CreditCard,
    CreditCardStatementPollRun,
    ImapAccount,
    User,
)
from app.services import credit_card_statement_polling as polling  # noqa: E402
from app.services import imap_client  # noqa: E402


@pytest.fixture
def poll_env(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = Session()
    user = User(username="alice", email="alice@example.com", password_hash="hash")
    db.add(user)
    db.commit()
    account = ImapAccount(user_id=user.id, email="a@qq.com", password="x", provider="qq")
    db.add(account)
    db.commit()
    # run_poll/run_startup_catchup 内部从 app.database 取 SessionLocal，
    # 测试时指到内存库（对齐 test_scheduler 模式）
    import app.database as database
    monkeypatch.setattr(database, "SessionLocal", Session)
    try:
        yield db, user, account
    finally:
        db.close()
        engine.dispose()


def _mock_imap(monkeypatch, mails: list[bytes]):
    class FakeClient:
        def __init__(self, *a, **k): pass
        def login(self, *a): pass
        def xatom(self, *a): pass
        def list(self):
            return "OK", [b'(\\HasNoChildren) "/" "INBOX"']
        def select(self, *a, **k): return "OK", [b"1"]
        def uid(self, cmd, *a):
            if cmd == "search":
                return "OK", [" ".join(str(i) for i in range(1, len(mails) + 1)).encode()]
            target = a[0].decode() if isinstance(a[0], bytes) else str(a[0])
            uids_in_range = []
            for seg in target.split(","):
                if ":" in seg:
                    lo, hi = (int(x) for x in seg.split(":"))
                    uids_in_range.extend(str(u).encode() for u in range(lo, hi + 1))
                else:
                    uids_in_range.append(seg.encode())
            out_items = []
            for u in uids_in_range:
                idx = int(u) - 1
                if idx >= len(mails):
                    continue  # 无邮件
                raw = mails[idx]
                if "BODY.PEEK[]" in a[1]:
                    out_items.append((f"1 (UID {u.decode()} BODY[])".encode(), raw))
                    continue
                header = (raw or b"").split(b"\r\n\r\n")[0]
                out_items.append((f"1 (UID {u.decode()} RFC822.SIZE 500 BODY[HEADER] {len(header)})".encode(), header))
            out_items.append(b")")
            return "OK", out_items
        def logout(self): pass
        def shutdown(self): pass

    monkeypatch.setattr(imap_client.imaplib, "IMAP4_SSL", FakeClient)


def test_poll_attempts_d1_to_d3_then_exhausted(poll_env, monkeypatch):
    """D+1/2/3 无账单各消耗一次尝试，第 3 次后 exhausted，不再调用 IMAP。"""
    db, user, account = poll_env
    card = CreditCard(
        user_id=user.id, display_name="招行卡", bank_name="招商银行",
        last_four="6310", statement_day=15, due_day=3,
    )
    db.add(card)
    db.commit()

    _mock_imap(monkeypatch, [])  # 邮箱里没有账单
    calls = {"n": 0}
    real_core = polling.credit_card_statement_sync.sync_statements_core

    def counting_core(*a, **k):
        calls["n"] += 1
        return real_core(*a, **k)

    monkeypatch.setattr(polling.credit_card_statement_sync, "sync_statements_core", counting_core)

    polling.run_poll(date(2026, 9, 16))   # D+1
    polling.run_poll(date(2026, 9, 17))   # D+2
    polling.run_poll(date(2026, 9, 18))   # D+3
    run = db.query(CreditCardStatementPollRun).one()
    assert run.status == "exhausted"
    assert run.attempt_count == 3
    assert calls["n"] == 3

    # D+4：exhausted 进入兜底——当月内每日一次低频重试（银行侧账单日变更
    # 场景：新账单晚于原窗口到达仍能追上），同日只试一次
    polling.run_poll(date(2026, 9, 19))
    assert calls["n"] == 4
    polling.run_poll(date(2026, 9, 19))
    assert calls["n"] == 4  # 同日幂等


def test_poll_success_stops_retrying(poll_env, monkeypatch):
    """D+1 无账单、D+2 抓到 → succeeded，D+3 不再调用 IMAP。"""
    db, user, account = poll_env
    card = CreditCard(
        user_id=user.id, display_name="招行卡", bank_name="招商银行",
        last_four="6310", statement_day=15, due_day=3,
    )
    db.add(card)
    db.commit()

    _mock_imap(monkeypatch, [])  # D+1：邮箱暂无 8 月账单
    polling.run_poll(date(2026, 8, 16))
    run = db.query(CreditCardStatementPollRun).one()
    assert run.status == "pending"
    assert run.attempt_count == 1

    # D+2：邮箱里出现 8 月账单（statement_date 8/15 与 occurrence 同月 → 成功）
    _mock_imap(monkeypatch, [load_cmb()])
    polling.run_poll(date(2026, 8, 17))
    db.expire_all()
    run = db.query(CreditCardStatementPollRun).one()
    assert run.status == "succeeded"
    assert run.statement_id is not None

    calls = {"n": 0}
    real_core = polling.credit_card_statement_sync.sync_statements_core
    def counting_core(*a, **k):
        calls["n"] += 1
        return real_core(*a, **k)
    monkeypatch.setattr(polling.credit_card_statement_sync, "sync_statements_core", counting_core)
    polling.run_poll(date(2026, 8, 18))
    assert calls["n"] == 0  # 成功后不再抓取


def test_poll_same_day_idempotent(poll_env, monkeypatch):
    """同一天重复执行 run_poll 不重复消耗尝试（启动补偿+定时并发保护）。"""
    db, user, account = poll_env
    card = CreditCard(
        user_id=user.id, display_name="招行卡", bank_name="招商银行",
        last_four="6310", statement_day=15, due_day=3,
    )
    db.add(card)
    db.commit()
    _mock_imap(monkeypatch, [])
    polling.run_poll(date(2026, 9, 16))
    polling.run_poll(date(2026, 9, 16))
    run = db.query(CreditCardStatementPollRun).one()
    assert run.attempt_count == 1


def test_poll_month_end_anchor_cross_month(poll_env, monkeypatch):
    """名义 31 日在 2 月锚定 2/28 → 重试窗口 3/1-3/3（跨月）。"""
    db, user, account = poll_env
    card = CreditCard(
        user_id=user.id, display_name="招行卡", bank_name="招商银行",
        last_four="6310", statement_day=31, due_day=5,
    )
    db.add(card)
    db.commit()
    _mock_imap(monkeypatch, [])
    # 2026 平年 2 月锚 2/28，3/1 是 D+1
    polling.run_poll(date(2026, 3, 1))
    run = db.query(CreditCardStatementPollRun).one()
    assert run.statement_date == date(2026, 2, 28)
    assert run.attempt_count == 1


def test_poll_ignores_cards_outside_window(poll_env, monkeypatch):
    """账单日不在 D+1..D+3 的卡不产生 poll run、不调 IMAP。"""
    db, user, account = poll_env
    card = CreditCard(
        user_id=user.id, display_name="招行卡", bank_name="招商银行",
        last_four="6310", statement_day=5, due_day=25,  # 9/16 视角 D+11
    )
    db.add(card)
    db.commit()
    calls = {"n": 0}
    real_core = polling.credit_card_statement_sync.sync_statements_core
    def counting_core(*a, **k):
        calls["n"] += 1
        return real_core(*a, **k)
    monkeypatch.setattr(polling.credit_card_statement_sync, "sync_statements_core", counting_core)
    polling.run_poll(date(2026, 9, 16))
    assert db.query(CreditCardStatementPollRun).count() == 0
    assert calls["n"] == 0


def test_startup_catchup_compensates_once_within_window(poll_env, monkeypatch):
    """停机后启动：D+2 处于窗口内 → 补做一次当前尝试；不回放 D+1。"""
    db, user, account = poll_env
    card = CreditCard(
        user_id=user.id, display_name="招行卡", bank_name="招商银行",
        last_four="6310", statement_day=15, due_day=3,
    )
    db.add(card)
    db.commit()
    _mock_imap(monkeypatch, [])
    polling.run_poll(date(2026, 9, 16))  # D+1 尝试一次
    run = db.query(CreditCardStatementPollRun).one()
    assert run.attempt_count == 1

    # 服务重启（模拟 D+2 启动）
    polling.run_startup_catchup(date(2026, 9, 17))
    db.expire_all()
    run = db.query(CreditCardStatementPollRun).one()
    assert run.attempt_count == 2  # 只补当前一天
    assert run.last_attempt_date == date(2026, 9, 17)


def test_startup_catchup_marks_expired_beyond_window(poll_env, monkeypatch):
    """停机跨过整个窗口（D+4 及以后启动）→ 标 expired，不再追补。"""
    db, user, account = poll_env
    card = CreditCard(
        user_id=user.id, display_name="招行卡", bank_name="招商银行",
        last_four="6310", statement_day=15, due_day=3,
    )
    db.add(card)
    db.commit()
    _mock_imap(monkeypatch, [])
    polling.run_poll(date(2026, 9, 16))  # D+1 尝试一次
    run_before = db.query(CreditCardStatementPollRun).one()
    assert run_before.attempt_count == 1

    calls = {"n": 0}
    real_core = polling.credit_card_statement_sync.sync_statements_core
    def counting_core(*a, **k):
        calls["n"] += 1
        return real_core(*a, **k)
    monkeypatch.setattr(polling.credit_card_statement_sync, "sync_statements_core", counting_core)
    polling.run_startup_catchup(date(2026, 9, 21))  # D+6 启动
    db.expire_all()
    run = db.query(CreditCardStatementPollRun).one()
    assert run.status == "expired"
    assert run.attempt_count == 1  # 没有追补
    assert calls["n"] == 0


def test_poll_multiple_cards_one_account_single_sync(poll_env, monkeypatch):
    """同一账户服务多张到期卡 → 一轮只调用一次 sync core。"""
    db, user, account = poll_env
    for last4, day in (("6310", 15), ("1151", 15)):
        db.add(CreditCard(
            user_id=user.id, display_name=f"卡{last4}",
            bank_name="招商银行" if last4 == "6310" else "平安银行",
            last_four=last4, statement_day=day, due_day=3,
        ))
    db.commit()
    calls = {"n": 0}
    real_core = polling.credit_card_statement_sync.sync_statements_core
    def counting_core(*a, **k):
        calls["n"] += 1
        return real_core(*a, **k)
    monkeypatch.setattr(polling.credit_card_statement_sync, "sync_statements_core", counting_core)
    _mock_imap(monkeypatch, [load_cmb()])
    polling.run_poll(date(2026, 9, 16))
    # 招行卡用该账户尝试一次；平安卡无覆盖账户跳过（无第二个账户）
    assert calls["n"] == 1


# ---------- 审核修复回归 ----------

def test_imap_error_consumes_attempt_and_keeps_run(poll_env, monkeypatch):
    """审核 High-4 回归：IMAP 异常也消耗尝试并保留 run；3 次后 exhausted。"""
    db, user, account = poll_env
    card = CreditCard(
        user_id=user.id, display_name="招行卡", bank_name="招商银行",
        last_four="6310", statement_day=15, due_day=3,
    )
    db.add(card)
    db.commit()

    class ErrorClient:
        def __init__(self, *a, **k): pass
        def login(self, *a): raise imap_client.imaplib.IMAP4.error("login denied")
        def list(self): return "OK", []

    monkeypatch.setattr(imap_client.imaplib, "IMAP4_SSL", ErrorClient)
    polling.run_poll(date(2026, 9, 16))
    polling.run_poll(date(2026, 9, 17))
    polling.run_poll(date(2026, 9, 18))
    db.expire_all()
    run = db.query(CreditCardStatementPollRun).one()
    assert run.status == "exhausted"
    assert run.attempt_count == 3  # run 保留、有终态、有通知


def test_cold_start_creates_run_and_attempts(poll_env, monkeypatch):
    """审核 High-2 回归：停机期间从未建 run 的卡，D+2 冷启动 catchup
    也能创建 run 并尝试（不会整期漏抓）。"""
    db, user, account = poll_env
    card = CreditCard(
        user_id=user.id, display_name="招行卡", bank_name="招商银行",
        last_four="6310", statement_day=15, due_day=3,
    )
    db.add(card)
    db.commit()
    _mock_imap(monkeypatch, [])
    # 账单日 8/15；服务 8/14 前停机；8/17（D+2）冷启动
    polling.run_startup_catchup(date(2026, 8, 17))
    run = db.query(CreditCardStatementPollRun).one()
    assert run.statement_date == date(2026, 8, 15)
    assert run.attempt_count == 1  # 只补当天一次，不回放 8/16


def test_multi_card_one_account_all_progress(poll_env, monkeypatch):
    """审核 High-3 回归：一个全银行账户覆盖两张到期卡 → 两张卡都推进。"""
    db, user, account = poll_env
    for last4, bank in (("6310", "招商银行"), ("1151", "平安银行")):
        db.add(CreditCard(
            user_id=user.id, display_name=f"卡{last4}", bank_name=bank,
            last_four=last4, statement_day=15, due_day=3,
        ))
    db.commit()
    _mock_imap(monkeypatch, [])
    polling.run_poll(date(2026, 9, 16))
    runs = db.query(CreditCardStatementPollRun).all()
    assert len(runs) == 2
    assert all(r.attempt_count == 1 for r in runs), "两张卡都必须被尝试"


def test_poll_fallback_success_after_statement_day_change(poll_env, monkeypatch):
    """兜底场景（银行侧账单日变更）：D+1..D+3 扑空 exhausted 后，当月内
    兜底重试抓到晚到的新账单 → run 转 succeeded、卡片资料按新账单回写；
    外部通知不重复（失败通知已占用 UNIQUE，成功通知被 IGNORE）；跨月停止。"""
    from sqlalchemy import text

    db, user, account = poll_env
    card = CreditCard(
        user_id=user.id, display_name="招行卡", bank_name="招商银行",
        last_four="6310", statement_day=15, due_day=3,
    )
    db.add(card)
    db.commit()

    # D+1..D+3 邮箱无账单 → exhausted（含失败通知 3 channels）
    _mock_imap(monkeypatch, [])
    polling.run_poll(date(2026, 8, 16))
    polling.run_poll(date(2026, 8, 17))
    polling.run_poll(date(2026, 8, 18))
    db.expire_all()
    run = db.query(CreditCardStatementPollRun).one()
    assert run.status == "exhausted"

    def notify_count():
        return db.execute(
            text("SELECT COUNT(*) FROM bill_poll_notifications")
        ).scalar()

    assert notify_count() == 3  # 失败通知已发（telegram/bark/webhook）

    # D+4（8/19）兜底：邮箱出现 8/15 账单（新账单晚到——银行侧改了账单日），
    # statement_date 与 occurrence(8/15) 同月 → 兜底成功
    _mock_imap(monkeypatch, [load_cmb()])
    polling.run_poll(date(2026, 8, 19))
    db.expire_all()
    run = db.query(CreditCardStatementPollRun).one()
    assert run.status == "succeeded"
    assert run.statement_id is not None
    assert run.attempt_count == 4
    # 卡片资料按新账单回写（账单日/还款日/额度以最新邮件为准）
    db.expire_all()
    assert card.statement_day == 15
    assert card.credit_limit is not None
    # 通知不重复：失败通知占用 UNIQUE(poll_run_id, channel)，成功通知被 IGNORE
    assert notify_count() == 3

    # 成功后兜底自然退出：8/20 不再调用 IMAP
    calls = {"n": 0}
    real_core = polling.credit_card_statement_sync.sync_statements_core
    def counting_core(*a, **k):
        calls["n"] += 1
        return real_core(*a, **k)
    monkeypatch.setattr(polling.credit_card_statement_sync, "sync_statements_core", counting_core)
    polling.run_poll(date(2026, 8, 20))
    assert calls["n"] == 0


def test_poll_fallback_stops_next_month(poll_env, monkeypatch):
    """兜底只追「本期」：exhausted 后跨入下月，不再兜底（不无限回溯）。"""
    calls = {"n": 0}
    real_core = polling.credit_card_statement_sync.sync_statements_core
    def counting_core(*a, **k):
        calls["n"] += 1
        return real_core(*a, **k)

    db, user, account = poll_env
    card = CreditCard(
        user_id=user.id, display_name="招行卡", bank_name="招商银行",
        last_four="6310", statement_day=15, due_day=3,
    )
    db.add(card)
    db.commit()

    _mock_imap(monkeypatch, [])
    polling.run_poll(date(2026, 8, 16))
    polling.run_poll(date(2026, 8, 17))
    polling.run_poll(date(2026, 8, 18))   # exhausted
    db.expire_all()
    assert db.query(CreditCardStatementPollRun).one().status == "exhausted"

    # 8/31 仍兜底（当月内）
    monkeypatch.setattr(polling.credit_card_statement_sync, "sync_statements_core", counting_core)
    polling.run_poll(date(2026, 8, 31))
    assert calls["n"] == 1

    # 9/1 跨月：兜底条件（锚定月一致）不满足 → 不再尝试
    polling.run_poll(date(2026, 9, 1))
    polling.run_poll(date(2026, 9, 14))   # 9/14 也不在新窗口（day=15 的 D+1 是 9/16）
    assert calls["n"] == 1


def test_poll_fallback_real_day_change_no_duplicate_sync(poll_env, monkeypatch):
    """真实账单日变更（5→25）：兜底在新日期成功后，卡片资料回写 statement_day=25
    → 次日正常窗口命中新 occurrence(8/25) ——整期已由兜底完成，不得再同步
    （不重复 IMAP、新 run 静默标 succeeded 不重发通知）。"""
    calls = {"n": 0}
    real_core = polling.credit_card_statement_sync.sync_statements_core
    def counting_core(*a, **k):
        calls["n"] += 1
        return real_core(*a, **k)

    db, user, account = poll_env
    card = CreditCard(
        user_id=user.id, display_name="招行卡", bank_name="招商银行",
        last_four="6310", statement_day=5, due_day=3,
    )
    db.add(card)
    db.commit()

    from sqlalchemy import text
    def notify_count():
        return db.execute(text("SELECT COUNT(*) FROM bill_poll_notifications")).scalar()

    # 计数器从兜底抓取前装上（8/25 的成功与 8/26 的重复检测都靠它）
    monkeypatch.setattr(polling.credit_card_statement_sync, "sync_statements_core", counting_core)

    # 旧日期 8/5 的 D+1..D+3（8/6~8/8）扑空 → exhausted + 失败通知 3 条
    _mock_imap(monkeypatch, [])
    polling.run_poll(date(2026, 8, 6))
    polling.run_poll(date(2026, 8, 7))
    polling.run_poll(date(2026, 8, 8))
    db.expire_all()
    runs = db.query(CreditCardStatementPollRun).all()
    assert len(runs) == 1 and runs[0].status == "exhausted"
    assert notify_count() == 3

    # 8/25 银行按新账单日发信：兜底抓到 statement_date=8/25 的账单（同月 → 成功）
    _mock_imap(monkeypatch, [load_cmb(day=25)])
    polling.run_poll(date(2026, 8, 25))
    db.expire_all()
    assert calls["n"] == 4  # 扑空 3 次 + 兜底 1 次
    card = db.get(CreditCard, card.id)
    assert card.statement_day == 25  # 资料按新账单回写
    assert notify_count() == 3       # 兜底成功不发通知

    # 8/26 新日期的 D+1：正常窗口命中 occurrence 8/25——整期已由兜底完成，
    # 不得再同步（无 IMAP 调用、通知不增加）
    polling.run_poll(date(2026, 8, 26))
    assert calls["n"] == 4
    assert notify_count() == 3
    db.expire_all()
    runs = db.query(CreditCardStatementPollRun).all()
    assert len(runs) == 2  # 旧 8/5 run + 新 8/25 run（静默标 succeeded）
    assert all(r.status == "succeeded" for r in runs)

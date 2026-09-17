"""账单同步端到端测试：mock IMAP 返回完整 MIME → sync 落库 → 查询 → 清理。"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).parent))
from statement_fixtures import load_ccb, load_cmb  # noqa: E402

from app import main  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.deps import get_current_user  # noqa: E402
from app.models import (  # noqa: E402
    CreditCard,
    CreditCardStatement,
    CreditCardStatementItem,
    ImapAccount,
    User,
)
from app.services import credit_card_statement_sync, imap_client  # noqa: E402


@pytest.fixture
def sync_env():
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
    account = ImapAccount(
        user_id=user.id, email="a@qq.com", password="code", provider="qq"
    )
    db.add(account)
    db.commit()
    main.app.dependency_overrides[get_db] = lambda: db
    main.app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(main.app)
    try:
        yield client, db, user, account
    finally:
        main.app.dependency_overrides.pop(get_db, None)
        main.app.dependency_overrides.pop(get_current_user, None)
        db.close()
        engine.dispose()


def _mock_imap(monkeypatch, mails: list[bytes]):
    """mock IMAP4_SSL：search 返回固定 UID，fetch 逐封返回完整 MIME。"""

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def login(self, email, password):
            pass

        def xatom(self, name, arg):
            pass

        def select(self, folder, readonly=False):
            return "OK", [b"1"]

        def uid(self, command, *args):
            if command == "search":
                return "OK", [" ".join(str(i) for i in range(1, len(mails) + 1)).encode()]
            # 兼容两种 fetch 形态：逐封 UID 与批量头部（「lo:hi」区间，
            # 生产代码批量头部 FETCH 用；区间内每封返回头部+完整正文，
            # 解析层按需取字段）
            target = args[0].decode() if isinstance(args[0], bytes) else str(args[0])
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
                raw = mails[idx]
                if command == "fetch" and "BODY.PEEK[]" in args[1]:
                    out_items.append((f"1 (UID {u.decode()} BODY[])".encode(), raw))
                    continue
                header = raw.split(b"\r\n\r\n")[0]
                out_items.append((f"1 (UID {u.decode()} RFC822.SIZE {len(raw)} BODY[HEADER] {len(header)})".encode(), header))
            out_items.append(b")")
            return "OK", out_items

        def logout(self):
            pass

        def shutdown(self):
            pass

    monkeypatch.setattr(imap_client.imaplib, "IMAP4_SSL", FakeClient)


def test_sync_saves_statements_and_matches_cards(sync_env, monkeypatch):
    client, db, user, account = sync_env
    # 用户已有招行 6310 卡
    card = CreditCard(
        user_id=user.id, display_name="招行卡", bank_name="招商银行",
        last_four="6310", statement_day=15, due_day=3,
    )
    db.add(card)
    db.commit()

    _mock_imap(monkeypatch, [load_cmb()])
    resp = client.post(f"/api/imap/accounts/{account.id}/sync-statements", json={"days": 31})
    assert resp.status_code == 200
    body = resp.json()
    assert body["parsed"] == 1
    assert body["saved"] == 1
    assert body["skipped"] == 0
    assert body["unmatched"] == []
    assert body["mismatched"] == []

    # 落库验证：statement 关联到了卡，明细 5 条
    stmt = db.query(CreditCardStatement).one()
    assert stmt.card_id == card.id
    assert stmt.match_status == "matched"
    assert stmt.bank_key == "cmb"
    assert stmt.total_due == 1410.94
    assert len(stmt.items) == 5
    db.expire_all()
    items = db.query(CreditCardStatementItem).filter_by(statement_id=stmt.id).all()
    assert sum(i.amount for i in items if i.amount > 0) == pytest.approx(608.11)


def test_sync_is_idempotent_on_second_run(sync_env, monkeypatch):
    client, db, user, account = sync_env
    _mock_imap(monkeypatch, [load_cmb()])
    assert client.post(f"/api/imap/accounts/{account.id}/sync-statements").status_code == 200
    second = client.post(f"/api/imap/accounts/{account.id}/sync-statements")
    assert second.json()["skipped"] == 1
    assert second.json()["saved"] == 0
    assert db.query(CreditCardStatement).count() == 1


def test_sync_unmatched_card_reported(sync_env, monkeypatch):
    client, db, user, account = sync_env
    _mock_imap(monkeypatch, [load_ccb()])  # 3 张建行卡，用户一张都没有
    resp = client.post(f"/api/imap/accounts/{account.id}/sync-statements")
    body = resp.json()
    assert body["saved"] == 3
    assert {u["last_four"] for u in body["unmatched"]} == {"5468", "6714", "5561"}
    # unmatched statement 的 card_id 为空
    assert all(s.card_id is None for s in db.query(CreditCardStatement).all())


def test_sync_statements_query_endpoints(sync_env, monkeypatch):
    client, db, user, account = sync_env
    card = CreditCard(
        user_id=user.id, display_name="招行卡", bank_name="招商银行",
        last_four="6310", statement_day=15, due_day=3,
    )
    db.add(card)
    db.commit()
    _mock_imap(monkeypatch, [load_cmb()])
    client.post(f"/api/imap/accounts/{account.id}/sync-statements")

    lst = client.get(f"/api/credit-cards/{card.id}/statements")
    assert lst.status_code == 200
    stmts = lst.json()["statements"]
    assert len(stmts) == 1
    assert stmts[0]["verify_status"] == "ok"
    assert stmts[0]["item_count"] == 5

    items = client.get(f"/api/credit-cards/{card.id}/statements/{stmts[0]['id']}/items")
    assert items.status_code == 200
    body = items.json()
    assert body["count"] == 5
    assert all({"trans_date_raw", "description", "amount", "tx_type"} <= set(i) for i in body["items"])

    # 越权/不存在
    assert client.get("/api/credit-cards/9999/statements").status_code == 404
    assert client.get(f"/api/credit-cards/{card.id}/statements/9999/items").status_code == 404


def test_delete_card_preserves_statements(sync_env, monkeypatch):
    """删卡保留历史账单（用户需求）：解除关联而非删除。"""
    client, db, user, account = sync_env
    card = CreditCard(
        user_id=user.id, display_name="招行卡", bank_name="招商银行",
        last_four="6310", statement_day=15, due_day=3,
    )
    db.add(card)
    db.commit()
    _mock_imap(monkeypatch, [load_cmb()])
    client.post(f"/api/imap/accounts/{account.id}/sync-statements")
    assert db.query(CreditCardStatement).count() == 1

    assert client.delete(f"/api/credit-cards/{card.id}").json()["ok"] is True
    db.expire_all()
    stmt = db.query(CreditCardStatement).one()
    assert stmt.card_id is None  # 解除关联
    assert stmt.match_status == "unmatched"
    assert stmt.card_last_four == "6310"  # 冗余字段仍可辨识
    assert db.query(CreditCardStatementItem).count() == 5  # 明细保留


def test_sync_requires_ownership(sync_env, monkeypatch):
    client, db, user, account = sync_env
    other = User(username="bob", email="bob@example.com", password_hash="h")
    db.add(other)
    db.commit()
    other_account = ImapAccount(user_id=other.id, email="b@qq.com", password="p", provider="qq")
    db.add(other_account)
    db.commit()
    assert client.post(f"/api/imap/accounts/{other_account.id}/sync-statements").status_code == 404


# ---------- 备份 v4 往返（审核修复回归） ----------

def test_backup_v4_statement_roundtrip_with_card_mapping(sync_env):
    """card_key 导出为数组下标、恢复映射回正确的新卡（审核 High-1 回归）。"""
    from app.routers.backup import _collect_entities, _restore_entities

    client, db, user, account = sync_env
    card = CreditCard(
        user_id=user.id, display_name="招行卡", bank_name="招商银行",
        last_four="6310", statement_day=15, due_day=3,
    )
    db.add(card)
    db.commit()
    from app.services import imap_client as ic
    # 直接替换 IMAP4_SSL（复用 _mock_imap 逻辑）
    class FakeClient:
        def __init__(self, *a, **k): pass
        def login(self, *a): pass
        def xatom(self, *a): pass
        def select(self, *a, **k): return "OK", [b"1"]
        def uid(self, cmd, *a):
            if cmd == "search":
                return "OK", [b"1"]
            return "OK", [(b"1 (UID 1 BODY[])", load_cmb()), b")"]
        def logout(self): pass
        def shutdown(self): pass
    ic.imaplib.IMAP4_SSL = FakeClient
    client.post(f"/api/imap/accounts/{account.id}/sync-statements")

    exported, _subs = _collect_entities(db, user)
    assert exported["credit_card_statements"][0]["card_key"] == 0  # 数组下标而非 DB id
    assert exported["credit_card_statements"][0]["source_email"] == account.email

    # replace 恢复到新库（模拟重装）
    _restore_entities(db, user, exported, replace=True)
    db.expire_all()
    stmt = db.query(CreditCardStatement).one()
    assert stmt.card_id is not None, "card_key 必须映射回新卡"
    assert stmt.card.display_name == "招行卡"
    assert stmt.source_account_id == account.id, "source_email 应映射回同邮箱账户"


def test_backup_merge_does_not_delete_existing_statements(sync_env):
    """replace=false 合并导入不得删除现有账单（审核 High-2 回归）。"""
    from app.routers.backup import _restore_entities

    client, db, user, account = sync_env
    # 现有账单（较新）
    existing = CreditCardStatement(
        user_id=user.id, source_account_id=account.id, bank_key="cmb",
        card_last_four="9999", message_id="current-mail",
        match_status="unmatched", verify_status="ok",
    )
    db.add(existing)
    db.commit()
    # 旧备份：只含一条不同账单
    old_backup = {
        "subscriptions": [],
        "credit_cards": [],
        "credit_card_statements": [{
            "card_key": None, "bank_key": "pab", "card_last_four": "1151",
            "message_id": "old-mail", "verify_status": "ok",
            "source_email": None, "items": [],
        }],
    }
    _restore_entities(db, user, old_backup, replace=False)
    db.expire_all()
    msgs = {s.message_id for s in db.query(CreditCardStatement).all()}
    assert msgs == {"current-mail", "old-mail"}, "合并导入必须保留现有账单"


def test_backup_merge_dedupes_same_message(sync_env):
    """合并导入同一 (source, message_id, card) 时不重复插入。"""
    from app.routers.backup import _restore_entities

    client, db, user, account = sync_env
    existing = CreditCardStatement(
        user_id=user.id, source_account_id=account.id, bank_key="cmb",
        card_last_four="6310", message_id="dup-mail",
        match_status="unmatched", verify_status="ok",
    )
    db.add(existing)
    db.commit()
    backup = {
        "subscriptions": [],
        "credit_cards": [],
        "credit_card_statements": [{
            "card_key": None, "bank_key": "cmb", "card_last_four": "6310",
            "message_id": "dup-mail", "verify_status": "ok",
            "source_email": account.email, "items": [],
        }],
    }
    _restore_entities(db, user, backup, replace=False)
    db.expire_all()
    assert db.query(CreditCardStatement).count() == 1


def test_statements_endpoint_reports_unmatched_count(sync_env, monkeypatch):
    """未匹配账单不进详情列表，但 unmatched_count 让前端能给出准确提示。"""
    client, db, user, account = sync_env
    # 建尾号 6310 的卡（不同尾号的账单不会命中）
    card = CreditCard(
        user_id=user.id, display_name="招行卡", bank_name="招商银行",
        last_four="6310", statement_day=15, due_day=3,
    )
    db.add(card)
    db.commit()
    # 拉建行账单（3 尾号都 unmatched）
    _mock_imap(monkeypatch, [load_ccb()])
    client.post(f"/api/imap/accounts/{account.id}/sync-statements")

    lst = client.get(f"/api/credit-cards/{card.id}/statements")
    body = lst.json()
    assert body["statements"] == []
    assert body["unmatched_count"] == 0  # 建行尾号与招行卡不匹配 → 该卡视角 0\n

def test_sync_updates_card_fields_from_statement(sync_env, monkeypatch):
    """账单日/还款日/总额度以最新邮件为准覆盖卡片（用户需求）。"""
    client, db, user, account = sync_env
    # 卡片初始值与账单不同：账单日 15（邮件 8/15? 招行账单日=期末 8/15）、还款日 3（邮件 9/3）、额度 50000（邮件 60000）
    card = CreditCard(
        user_id=user.id, display_name="招行卡", bank_name="招商银行",
        last_four="6310", statement_day=10, due_day=20, credit_limit=50000.0,
    )
    db.add(card)
    db.commit()
    _mock_imap(monkeypatch, [load_cmb()])
    resp = client.post(f"/api/imap/accounts/{account.id}/sync-statements")
    body = resp.json()
    assert body["updated_cards"], "应有回写记录"
    upd = body["updated_cards"][0]
    assert upd["last_four"] == "6310"
    assert set(upd["fields"]) == {"statement_day", "due_day", "credit_limit"}

    db.expire_all()
    card = db.get(CreditCard, card.id)
    assert card.statement_day == 15   # 2026-08-15 → 15
    assert card.due_day == 3          # 2026-09-03 → 3
    assert card.credit_limit == 60000.0


def test_sync_does_not_overwrite_on_mismatch(sync_env, monkeypatch):
    """勾稽失败的账单不回写卡片（数据可信度存疑时不改手填值）。"""
    client, db, user, account = sync_env
    card = CreditCard(
        user_id=user.id, display_name="招行卡", bank_name="招商银行",
        last_four="6310", statement_day=10, due_day=20,
    )
    db.add(card)
    db.commit()
    # 篡改招行汇总金额 → mismatch
    raw = load_cmb().decode().replace("&yen; 608.11</DIV>", "&yen; 9,999.99</DIV>").encode()
    _mock_imap(monkeypatch, [raw])
    resp = client.post(f"/api/imap/accounts/{account.id}/sync-statements")
    assert resp.json()["mismatched"]
    db.expire_all()
    card = db.get(CreditCard, card.id)
    assert card.statement_day == 10  # 未被覆盖
    assert card.due_day == 20


def test_writeback_latest_statement_wins_regardless_of_order(sync_env, monkeypatch):
    """审核 High 回归：同卡两期账单，无论处理顺序，回写都用最新一期。

    招行账单日=期末：7/16-8/15 账单日 8/15，构造第二封「更旧」账单
    （statementCycle 6/16-7/15）改额度区分。
    """
    client, db, user, account = sync_env
    card = CreditCard(
        user_id=user.id, display_name="招行卡", bank_name="招商银行",
        last_four="6310", statement_day=10, due_day=20, credit_limit=1.0,
    )
    db.add(card)
    db.commit()

    newer = load_cmb()  # 账单日 2026-08-15，额度 60000
    older_src = load_cmb().decode()
    older = (older_src
             .replace("2026/07/16-2026/08/15", "2026/06/16-2026/07/15")
             .replace("<m-cmb-1>", "<m-cmb-old>")
             .replace("cmb-fix-1", "cmb-fix-old")
             .encode())

    # 顺序 1：新→旧（旧的后处理，旔回写不得胜出）
    _mock_imap(monkeypatch, [newer, older])
    client.post(f"/api/imap/accounts/{account.id}/sync-statements")
    db.expire_all()
    assert db.get(CreditCard, card.id).credit_limit == 60000.0

    # 顺序 2：旧→新（也应新账单胜出）
    client.delete(f"/api/credit-cards/{card.id}")
    card2 = CreditCard(
        user_id=user.id, display_name="招行卡", bank_name="招商银行",
        last_four="6310", statement_day=10, due_day=20, credit_limit=1.0,
    )
    db.add(card2)
    db.commit()
    _mock_imap(monkeypatch, [older, newer])
    client.post(f"/api/imap/accounts/{account.id}/sync-statements")
    db.expire_all()
    assert db.get(CreditCard, card2.id).credit_limit == 60000.0
    assert db.get(CreditCard, card2.id).statement_day == 15


def test_resync_repairs_null_total_due(sync_env, monkeypatch):
    """审核 Medium 回归：已入库记录（total_due=NULL 的旧版数据）重新解析
    同一封邮件时，汇总字段被刷新修复。"""
    client, db, user, account = sync_env
    from app.models import CreditCardStatement

    # 模拟旧版入库：金额为 NULL
    db.add(CreditCardStatement(
        user_id=user.id, source_account_id=account.id, bank_key="cmb",
        card_last_four="6310", message_id="cmb-fix-1",
        match_status="matched", verify_status="ok",
        total_due=None, min_due=None,
    ))
    db.commit()

    _mock_imap(monkeypatch, [load_cmb()])
    resp = client.post(f"/api/imap/accounts/{account.id}/sync-statements")
    assert resp.json()["skipped"] == 1
    db.expire_all()
    stmt = db.query(CreditCardStatement).one()
    assert stmt.total_due == 1410.94, "重新解析应修复旧记录的 NULL 金额"
    assert stmt.min_due == 389.07


def test_delete_account_preserves_statements(sync_env, monkeypatch):
    """删邮箱账户保留历史账单（解除来源关联而非删除）。"""
    client, db, user, account = sync_env
    card = CreditCard(
        user_id=user.id, display_name="招行卡", bank_name="招商银行",
        last_four="6310", statement_day=15, due_day=3,
    )
    db.add(card)
    db.commit()
    _mock_imap(monkeypatch, [load_cmb()])
    client.post(f"/api/imap/accounts/{account.id}/sync-statements")
    assert db.query(CreditCardStatement).count() == 1

    assert client.delete(f"/api/imap/accounts/{account.id}").json()["ok"] is True
    db.expire_all()
    stmt = db.query(CreditCardStatement).one()
    assert stmt.source_account_id is None  # 解除来源
    assert stmt.card_id == card.id  # 卡片关联保留
    assert db.query(CreditCardStatementItem).count() == 5  # 明细保留


def test_resync_claims_orphan_statement(sync_env, monkeypatch):
    """审核 M3 回归：删账户重加同邮箱再解析，认领孤立账单而非重复插入。"""
    client, db, user, account = sync_env
    card = CreditCard(
        user_id=user.id, display_name="招行卡", bank_name="招商银行",
        last_four="6310", statement_day=15, due_day=3,
    )
    db.add(card)
    db.commit()
    _mock_imap(monkeypatch, [load_cmb()])
    client.post(f"/api/imap/accounts/{account.id}/sync-statements")

    # 删账户 → 重新添加同邮箱 → 再解析
    client.delete(f"/api/imap/accounts/{account.id}")
    account2 = ImapAccount(user_id=user.id, email="a@qq.com", password="x", provider="qq")
    db.add(account2)
    db.commit()
    _mock_imap(monkeypatch, [load_cmb()])
    client.post(f"/api/imap/accounts/{account2.id}/sync-statements")
    db.expire_all()

    stmts = db.query(CreditCardStatement).all()
    assert len(stmts) == 1, "同邮件应认领孤立账单而非重复插入"
    assert stmts[0].source_account_id == account2.id
    assert stmts[0].card_id == card.id
    assert len(stmts[0].items) == 5  # 明细不重复追加

    # 详情接口无双份
    lst = client.get(f"/api/credit-cards/{card.id}/statements")
    assert len(lst.json()["statements"]) == 1


def test_all_statements_endpoint_includes_orphans(sync_env, monkeypatch):
    """审核 H1 回归：删卡后历史账单通过用户级接口仍可查询。"""
    client, db, user, account = sync_env
    card = CreditCard(
        user_id=user.id, display_name="招行卡", bank_name="招商银行",
        last_four="6310", statement_day=15, due_day=3,
    )
    db.add(card)
    db.commit()
    _mock_imap(monkeypatch, [load_cmb()])
    client.post(f"/api/imap/accounts/{account.id}/sync-statements")
    client.delete(f"/api/credit-cards/{card.id}")

    # 单卡接口 404（卡已删）
    assert client.get(f"/api/credit-cards/{card.id}/statements").status_code == 404
    # 用户级历史接口仍可查
    all_stmts = client.get("/api/credit-cards/statements/all")
    assert all_stmts.status_code == 200
    stmts = all_stmts.json()["statements"]
    assert len(stmts) == 1
    assert stmts[0]["card_last_four"] == "6310"
    assert stmts[0]["card_name"] is None  # 卡已删

    # 明细仍可查
    items = client.get(f"/api/credit-cards/statements/all/{stmts[0]['id']}/items")
    assert items.status_code == 200
    assert items.json()["count"] == 5

    # 越权隔离
    assert client.get("/api/credit-cards/statements/all/99999/items").status_code == 404


def test_resync_rebuilds_stale_items(sync_env, monkeypatch):
    """复核 High 回归：解析器修复（建行扫码行此前被丢弃）后重新解析同一封
    邮件——旧记录的交易明细必须重建补齐，且 verify 从 mismatch 转 ok；
    还款标记（is_repaid/repaid_at）不受明细重建影响。"""

    from statement_fixtures import load_ccb

    client, db, _, account = sync_env
    client.post("/api/credit-cards", json={
        "display_name": "建行卡", "bank_name": "建设银行", "last_four": "6714",
        "statement_day": 27, "due_day": 16, "remind_days_before": [3],
        "credit_limit": None, "is_active": True, "show_in_calendar": True,
    })
    account_id = account.id

    from app.services import imap_client as ic

    def fake_fetch(email, password, provider, days, predicate=None, **kwargs):
        return [{"uid": b"1", "from_address": "cc@ccb.com", "subject": "账单",
                 "raw": load_ccb()}]

    monkeypatch.setattr(ic, "fetch_full_mime", fake_fetch)

    orig_parse = credit_card_statement_sync.parse_email

    def old_parse(raw, from_address=""):
        r = orig_parse(raw, from_address=from_address)
        st = next(s for s in r.statements if s.card_last_four == "6714")
        st.items = [i for i in st.items if "税务" not in i.description]  # 旧解析器丢扫码行
        return r

    monkeypatch.setattr(credit_card_statement_sync, "parse_email", old_parse)
    assert client.post(f"/api/imap/accounts/{account_id}/sync-statements",
                       json={"days": 31}).status_code == 200
    stmt = db.query(CreditCardStatement).filter_by(card_last_four="6714").one()
    n_before = db.query(CreditCardStatementItem).filter_by(statement_id=stmt.id).count()
    # fixture 无「已收到上期还款」正文 → prev_period_settled=None → 勾稽跳过
    # （verify=ok 未验证默认）；明细重建回归的核心是笔数变化
    assert n_before == 3  # 旧解析器丢扫码行后的残缺明细

    # 用户标记还款（验证重建不覆盖用户状态）
    client.patch(f"/api/credit-cards/statements/{stmt.id}/repaid", json={"is_repaid": True})

    monkeypatch.setattr(credit_card_statement_sync, "parse_email", orig_parse)
    assert client.post(f"/api/imap/accounts/{account_id}/sync-statements",
                       json={"days": 31}).status_code == 200
    db.expire_all()
    stmt = db.get(CreditCardStatement, stmt.id)
    n_after = db.query(CreditCardStatementItem).filter_by(statement_id=stmt.id).count()
    assert n_after == n_before + 1  # 扫码明细补回
    assert db.query(CreditCardStatementItem).filter_by(
        statement_id=stmt.id, amount=1498.72).count() == 1
    assert stmt.verify_status == "ok"
    assert stmt.is_repaid is True  # 用户标记保留
    assert stmt.repaid_at is not None
    # 部分还款金额同样保留（同步层只刷新解析字段，不触碰用户状态）：
    # 先取消再部分还款，重新同步后累计已还不丢
    client.patch(f"/api/credit-cards/statements/{stmt.id}/repaid", json={"is_repaid": False})
    client.post(f"/api/credit-cards/statements/{stmt.id}/repay", json={"amount": 100})
    assert client.post(f"/api/imap/accounts/{account_id}/sync-statements",
                       json={"days": 31}).status_code == 200
    db.expire_all()
    stmt = db.get(CreditCardStatement, stmt.id)
    assert stmt.is_repaid is False
    assert stmt.repaid_amount == 100.0  # 部分还款金额保留


def test_resync_with_lower_amount_converges_partial_repay(sync_env, monkeypatch):
    """复审 Low 6 回归：部分还款（400/1000）后解析器修复使重新解析得到更小
    金额（300）——保留 repaid_amount 会留下负剩余（汇总误判富余）。确定性
    收敛：累计已还 ≥ 新应还 → 归一化为已还清（与超额还款语义一致）。"""
    from statement_fixtures import load_ccb

    client, db, _, account = sync_env
    client.post("/api/credit-cards", json={
        "display_name": "建行卡", "bank_name": "建设银行", "last_four": "6714",
        "statement_day": 27, "due_day": 16, "remind_days_before": [3],
        "credit_limit": None, "is_active": True, "show_in_calendar": True,
    })
    account_id = account.id

    from app.services import imap_client as ic

    def fake_fetch(email, password, provider, days, predicate=None, **kwargs):
        return [{"uid": b"1", "from_address": "cc@ccb.com", "subject": "账单",
                 "raw": load_ccb()}]

    monkeypatch.setattr(ic, "fetch_full_mime", fake_fetch)
    orig_parse = credit_card_statement_sync.parse_email

    def inflated_parse(raw, from_address=""):
        r = orig_parse(raw, from_address=from_address)
        st = next(s for s in r.statements if s.card_last_four == "6714")
        # 模拟旧解析器金额虚高（如账户级应还误复制给该卡）：追加一笔补足
        # 差额的调整明细使勾稽自洽（verify 保持 ok）
        st.total_due = 3000.0
        first = st.items[0]
        st.items = list(st.items) + [type(first)(
            trans_date_raw=first.trans_date_raw, trans_date=first.trans_date,
            posted_date=first.posted_date, description="账户调整",
            amount=3000.0 - sum(i.amount for i in st.items if i.tx_type != "payment"), tx_amount=None,
            tx_currency=None, tx_type="purchase", installment_note=None,
        )]
        return r

    monkeypatch.setattr(credit_card_statement_sync, "parse_email", inflated_parse)
    assert client.post(f"/api/imap/accounts/{account_id}/sync-statements",
                       json={"days": 31}).status_code == 200
    stmt = db.query(CreditCardStatement).filter_by(card_last_four="6714").one()

    # 部分还款 2600（虚高账面 3000）
    resp = client.post(f"/api/credit-cards/statements/{stmt.id}/repay", json={"amount": 2600})
    assert resp.status_code == 200, f"repay failed: {resp.status_code} {resp.text[:200]}"

    db.expire_all()
    stmt = db.get(CreditCardStatement, stmt.id)
    assert stmt.repaid_amount == 2600.0 and stmt.is_repaid is False

    # 解析器修复：重新解析得到正确金额（1658.72，明细勾稽自然成立）——
    # 累计 2600 ≥ 1658.72，必须收敛为已还清（不留负剩余被误判富余）
    monkeypatch.setattr(credit_card_statement_sync, "parse_email", orig_parse)
    assert client.post(f"/api/imap/accounts/{account_id}/sync-statements",
                       json={"days": 31}).status_code == 200
    db.expire_all()
    stmt = db.get(CreditCardStatement, stmt.id)
    assert stmt.is_repaid is True, "累计已还 ≥ 新应还应收敛为已还清（不留负剩余）"
    assert stmt.repaid_amount == stmt.total_due  # 归一化


def test_resync_amount_increase_downgrades_cleared_statement(sync_env, monkeypatch):
    """三审 Medium 1 回归：已还清账单重解析金额变大（原还清 → 银行更正上调）
    ——不得让新增欠款被已还状态隐藏。正确行为：降级为未还、保留实际已还、
    清 repaid_at；汇总可见新增欠款。"""
    from statement_fixtures import load_ccb

    client, db, _, account = sync_env
    client.post("/api/credit-cards", json={
        "display_name": "建行卡", "bank_name": "建设银行", "last_four": "6714",
        "statement_day": 27, "due_day": 16, "remind_days_before": [3],
        "credit_limit": None, "is_active": True, "show_in_calendar": True,
    })
    account_id = account.id

    from app.services import imap_client as ic

    def fake_fetch(email, password, provider, days, predicate=None, **kwargs):
        return [{"uid": b"1", "from_address": "cc@ccb.com", "subject": "账单",
                 "raw": load_ccb()}]

    monkeypatch.setattr(ic, "fetch_full_mime", fake_fetch)
    orig_parse = credit_card_statement_sync.parse_email

    def inflated_parse(raw, from_address=""):
        r = orig_parse(raw, from_address=from_address)
        st = next(s for s in r.statements if s.card_last_four == "6714")
        # 勾稽自洽的金额上调：追加一笔补足净额差额的 purchase 明细
        st.total_due = 3000.0
        first = st.items[0]
        st.items = list(st.items) + [type(first)(
            trans_date_raw=first.trans_date_raw, trans_date=first.trans_date,
            posted_date=first.posted_date, description="账单更正补录",
            amount=3000.0 - sum(i.amount for i in st.items if i.tx_type != "payment"),
            tx_amount=None, tx_currency=None, tx_type="purchase", installment_note=None,
        )]
        return r

    monkeypatch.setattr(credit_card_statement_sync, "parse_email", orig_parse)
    assert client.post(f"/api/imap/accounts/{account_id}/sync-statements",
                       json={"days": 31}).status_code == 200
    stmt = db.query(CreditCardStatement).filter_by(card_last_four="6714").one()

    # 用户全部还清
    original_due = stmt.total_due
    resp = client.post(f"/api/credit-cards/statements/{stmt.id}/repay", json={"amount": original_due})
    assert resp.status_code == 200, resp.text[:200]
    db.expire_all()
    stmt = db.get(CreditCardStatement, stmt.id)
    assert stmt.is_repaid is True

    # 银行更正账单：金额上调（重解析）
    monkeypatch.setattr(credit_card_statement_sync, "parse_email", inflated_parse)
    assert client.post(f"/api/imap/accounts/{account_id}/sync-statements",
                       json={"days": 31}).status_code == 200
    db.expire_all()
    stmt = db.get(CreditCardStatement, stmt.id)
    # 必须降级为未还清（新欠款可见），保留实际已还，清还清时间
    assert stmt.is_repaid is False, "金额上调后不得继续用已还状态隐藏新欠款"
    assert stmt.repaid_amount == original_due
    assert stmt.repaid_at is None

    # 汇总可见新增欠款（滚动余额口径：该卡最新账单剩余 = 3000 - 已还；
    # fixture 中另一张卡 5468 unmatched 进孤立组——断言本卡 per_card）
    summary = client.get("/api/credit-cards/outstanding/summary").json()
    entry = next(e for e in summary["per_card"] if e["card_id"] is not None)
    assert entry["total_due"] == round(3000.0 - original_due, 2)


def test_resync_keeps_unmarked_surplus_statement_unmarked(sync_env, monkeypatch):
    """四审 Medium 2 回归：未标记的负数富余账单（total_due=-200、repaid=0）
    重复解析不得被「0 >= -200」误判成已还清——用户从未操作过它；同样保护
    total_due=0 的账单。只有真实正数已还覆盖新应还才收敛。"""
    from statement_fixtures import load_ccb

    client, db, _, account = sync_env
    client.post("/api/credit-cards", json={
        "display_name": "建行卡", "bank_name": "建设银行", "last_four": "6714",
        "statement_day": 27, "due_day": 16, "remind_days_before": [3],
        "credit_limit": None, "is_active": True, "show_in_calendar": True,
    })
    account_id = account.id

    from app.services import imap_client as ic

    def fake_fetch(email, password, provider, days, predicate=None, **kwargs):
        return [{"uid": b"1", "from_address": "cc@ccb.com", "subject": "账单",
                 "raw": load_ccb()}]

    monkeypatch.setattr(ic, "fetch_full_mime", fake_fetch)
    orig_parse = credit_card_statement_sync.parse_email

    def surplus_parse(raw, from_address=""):
        r = orig_parse(raw, from_address=from_address)
        st = next(s for s in r.statements if s.card_last_four == "6714")
        st.total_due = -200.0
        return r

    monkeypatch.setattr(credit_card_statement_sync, "parse_email", surplus_parse)
    assert client.post(f"/api/imap/accounts/{account_id}/sync-statements",
                       json={"days": 31}).status_code == 200
    stmt = db.query(CreditCardStatement).filter_by(card_last_four="6714").one()

    # 首次落库：未标记富余
    assert stmt.is_repaid is False and stmt.repaid_amount == 0.0

    # 重复解析同一封邮件（模拟用户再点「解析账单」）
    assert client.post(f"/api/imap/accounts/{account_id}/sync-statements",
                       json={"days": 31}).status_code == 200
    db.expire_all()
    stmt = db.get(CreditCardStatement, stmt.id)
    assert stmt.is_repaid is False, "未操作的富余账单不得被自动标记已还清"
    assert stmt.repaid_amount == 0.0


def test_resync_cleared_statement_to_null_amount_keeps_restorable_state(sync_env, monkeypatch):
    """四审 Medium 4 回归：已还清账单重解析为金额未知（total_due=NULL）——
    保留旧可信 total_due 不覆盖（否则 is_repaid=True + repaid_amount=1000 +
    total_due=None 违反备份交叉不变量，应用产出无法恢复的备份）。"""
    from statement_fixtures import load_ccb

    client, db, _, account = sync_env
    client.post("/api/credit-cards", json={
        "display_name": "建行卡", "bank_name": "建设银行", "last_four": "6714",
        "statement_day": 27, "due_day": 16, "remind_days_before": [3],
        "credit_limit": None, "is_active": True, "show_in_calendar": True,
    })
    account_id = account.id

    from app.services import imap_client as ic

    def fake_fetch(email, password, provider, days, predicate=None, **kwargs):
        return [{"uid": b"1", "from_address": "cc@ccb.com", "subject": "账单",
                 "raw": load_ccb()}]

    monkeypatch.setattr(ic, "fetch_full_mime", fake_fetch)
    orig_parse = credit_card_statement_sync.parse_email

    def null_amount_parse(raw, from_address=""):
        r = orig_parse(raw, from_address=from_address)
        st = next(s for s in r.statements if s.card_last_four == "6714")
        st.total_due = None  # 银行模板变化：总额未提取到
        return r

    monkeypatch.setattr(credit_card_statement_sync, "parse_email", orig_parse)
    assert client.post(f"/api/imap/accounts/{account_id}/sync-statements",
                       json={"days": 31}).status_code == 200
    stmt = db.query(CreditCardStatement).filter_by(card_last_four="6714").one()
    original_total = stmt.total_due

    # 用户还清
    client.post(f"/api/credit-cards/statements/{stmt.id}/repay", json={"amount": original_total})
    db.expire_all()
    stmt = db.get(CreditCardStatement, stmt.id)
    assert stmt.is_repaid is True

    # 重解析金额未知化
    monkeypatch.setattr(credit_card_statement_sync, "parse_email", null_amount_parse)
    assert client.post(f"/api/imap/accounts/{account_id}/sync-statements",
                       json={"days": 31}).status_code == 200
    db.expire_all()
    stmt = db.get(CreditCardStatement, stmt.id)
    # 旧可信 total_due 保留（不覆盖为 None），还清状态与金额保持一致
    assert stmt.total_due == original_total
    assert stmt.is_repaid is True
    assert stmt.repaid_amount == original_total

    # 备份往返：导出可恢复（交叉不变量满足）
    from app.routers import backup as backup_router
    from app.models import User as _U
    owner = db.get(_U, stmt.user_id)
    entities, _subs = backup_router._collect_entities(db, owner)
    exported = {"export_version": 4, "user": {"username": owner.username}, **entities}
    backup_router._validate_backup_payload(exported)  # 不得抛「与已还状态不一致」


def test_resync_mismatch_keeps_repayment_tuple_intact(sync_env, monkeypatch):
    """五审 Medium 1 回归：部分还款后重解析因模板漂移得到 mismatch 金额——
    mismatch 金额不可信，还款四元组（total_due/repaid_amount/is_repaid/
    repaid_at）必须全部保留旧值；导出备份仍可通过恢复校验。"""
    from statement_fixtures import load_ccb

    client, db, _, account = sync_env
    client.post("/api/credit-cards", json={
        "display_name": "建行卡", "bank_name": "建设银行", "last_four": "6714",
        "statement_day": 27, "due_day": 16, "remind_days_before": [3],
        "credit_limit": None, "is_active": True, "show_in_calendar": True,
    })
    account_id = account.id

    from app.services import imap_client as ic

    def fake_fetch(email, password, provider, days, predicate=None, **kwargs):
        return [{"uid": b"1", "from_address": "cc@ccb.com", "subject": "账单",
                 "raw": load_ccb()}]

    monkeypatch.setattr(ic, "fetch_full_mime", fake_fetch)
    orig_parse = credit_card_statement_sync.parse_email

    def inflated_parse(raw, from_address=""):
        # 模板漂移：金额与明细净额不符 → verify=mismatch
        r = orig_parse(raw, from_address=from_address)
        st = next(s for s in r.statements if s.card_last_four == "6714")
        st.total_due = 300.0
        return r

    monkeypatch.setattr(credit_card_statement_sync, "parse_email", orig_parse)
    assert client.post(f"/api/imap/accounts/{account_id}/sync-statements",
                       json={"days": 31}).status_code == 200
    stmt = db.query(CreditCardStatement).filter_by(card_last_four="6714").one()

    client.post(f"/api/credit-cards/statements/{stmt.id}/repay", json={"amount": 400})
    db.expire_all()
    stmt = db.get(CreditCardStatement, stmt.id)
    snapshot = (stmt.total_due, stmt.repaid_amount, stmt.is_repaid, stmt.repaid_at)

    # 重解析 mismatch
    monkeypatch.setattr(credit_card_statement_sync, "parse_email", inflated_parse)
    assert client.post(f"/api/imap/accounts/{account_id}/sync-statements",
                       json={"days": 31}).status_code == 200
    db.expire_all()
    stmt = db.get(CreditCardStatement, stmt.id)
    assert (stmt.total_due, stmt.repaid_amount, stmt.is_repaid, stmt.repaid_at) == snapshot, (
        "mismatch 重解析不得改动还款四元组"
    )
    assert stmt.verify_status == "mismatch"  # mismatch 本身如实展示

    # 导出备份仍可通过恢复校验（无负剩余矛盾态）
    from app.routers import backup as backup_router
    from app.models import User as _U
    owner = db.get(_U, stmt.user_id)
    entities, _subs = backup_router._collect_entities(db, owner)
    exported = {"export_version": 4, "user": {"username": owner.username}, **entities}
    backup_router._validate_backup_payload(exported)


def test_downgrade_does_not_rollback_boundary_below_later_cleared(sync_env, monkeypatch):
    """五审 Medium 3 回归：8月账单先还清（界线=8/16）→ 更晚的 9月账单还清
    （界线=9/16）→ 8月账单重解析金额上调被 sync 降级为未还——界线重算不得
    低于 9月已还账单可证明的还款日（盲目回退让已还的 9月复活）。走真实
    sync 降级路径（fixture 邮件即 8月账单）。"""
    from statement_fixtures import load_ccb
    from app.models import CreditCardStatement, CreditCard
    from datetime import date, timedelta

    client, db, _, account = sync_env
    client.post("/api/credit-cards", json={
        "display_name": "建行卡", "bank_name": "建设银行", "last_four": "6714",
        "statement_day": 27, "due_day": 16, "remind_days_before": [3],
        "credit_limit": None, "is_active": True, "show_in_calendar": True,
    })
    account_id = account.id

    from app.services import imap_client as ic
    orig_parse = credit_card_statement_sync.parse_email
    card = db.query(CreditCard).filter_by(last_four="6714").one()
    today = date.today()
    aug_due = date(today.year, 8, 16)
    sep_due = date(today.year, 9, 16)

    # 更晚的 9月已还账单（独立邮件 m-sep，还清后可证明 9/16 已还）
    sep = CreditCardStatement(
        user_id=card.user_id, card_id=card.id, bank_key="ccb",
        card_last_four="6714", match_status="matched", due_date=sep_due,
        total_due=800.0, statement_date=sep_due - timedelta(days=11),
        source_account_id=account.id, message_id="m-sep",
        verify_status="ok", is_repaid=True, repaid_amount=800.0,
    )
    db.add(sep)
    db.commit()

    # 第一次同步：fixture 邮件（=8月账单，due=8/16 需 monkeypatch 改日期）
    def inflated_aug(raw, from_address=""):
        r = orig_parse(raw, from_address=from_address)
        st = next(s for s in r.statements if s.card_last_four == "6714")
        st.due_date = aug_due
        st.statement_date = aug_due - timedelta(days=11)
        return r

    def fetch_fixture(email, password, provider, days, predicate=None, **kwargs):
        return [{"uid": b"1", "from_address": "cc@ccb.com", "subject": "账单",
                 "raw": load_ccb()}]

    monkeypatch.setattr(ic, "fetch_full_mime", fetch_fixture)
    monkeypatch.setattr(credit_card_statement_sync, "parse_email", inflated_aug)
    assert client.post(f"/api/imap/accounts/{account_id}/sync-statements",
                       json={"days": 90}).status_code == 200
    aug = db.query(CreditCardStatement).filter_by(
        card_last_four="6714", message_id="ccb-fix-1").one()
    # 用户全额还清 8月账单（原始 total_due）→ 界线推进到 8/16
    client.post(f"/api/credit-cards/statements/{aug.id}/repay",
                json={"amount": aug.total_due})
    db.expire_all()
    card = db.get(CreditCard, card.id)
    assert card.repaid_through_due == aug_due
    # 手动补上 9月账单的界线证明（8月后还清的 9月账单把界线推进到 9/16）
    card.repaid_through_due = sep_due
    db.commit()

    # 重解析同一邮件：金额上调（勾稽自洽）→ 8月账单降级为未还
    def inflated_aug_v2(raw, from_address=""):
        r = inflated_aug(raw, from_address=from_address)
        st = next(s for s in r.statements if s.card_last_four == "6714")
        st.total_due = 3000.0
        first = st.items[0]
        st.items = list(st.items) + [type(first)(
            trans_date_raw=first.trans_date_raw, trans_date=first.trans_date,
            posted_date=first.posted_date, description="账单更正补录",
            amount=3000.0 - sum(i.amount for i in st.items if i.tx_type != "payment"),
            tx_amount=None, tx_currency=None, tx_type="purchase", installment_note=None,
        )]
        return r

    monkeypatch.setattr(credit_card_statement_sync, "parse_email", inflated_aug_v2)
    assert client.post(f"/api/imap/accounts/{account_id}/sync-statements",
                       json={"days": 90}).status_code == 200
    db.expire_all()

    # 8月账单降级为未还（金额上调、累计已还不足）
    aug = db.get(CreditCardStatement, aug.id)
    assert aug.is_repaid is False
    # 界线重算不得低于 9月已还账单可证明的还款日
    card = db.get(CreditCard, card.id)
    assert card.repaid_through_due is not None
    assert card.repaid_through_due >= sep_due, (
        f"界线 {card.repaid_through_due} 不得低于 9月已还账单还款日 {sep_due}"
    )
    # 9月账单保持已还
    assert db.get(CreditCardStatement, sep.id).is_repaid is True


def test_downgrade_restores_canceled_reminders(sync_env, monkeypatch):
    """五审 Medium 4 回归：还清后投递前复核把当期提醒置 canceled，重解析
    金额上调降级为未还——被取消的提醒必须恢复为 pending（唯一键不能永久
    压住新欠款的提醒），且绝不复活 sent 行。"""
    from statement_fixtures import load_ccb

    client, db, _, account = sync_env
    client.post("/api/credit-cards", json={
        "display_name": "建行卡", "bank_name": "建设银行", "last_four": "6714",
        "statement_day": 27, "due_day": 16, "remind_days_before": [3],
        "credit_limit": None, "is_active": True, "show_in_calendar": True,
    })
    account_id = account.id

    from app.services import imap_client as ic
    from app.models import CreditCardNotificationOutbox as _CCNO
    from app.services.scheduler import utcnow
    from datetime import timedelta

    orig_parse = credit_card_statement_sync.parse_email
    card = db.query(CreditCard).filter_by(last_four="6714").one()

    # 第一阶段：正常解析入库（9月账单）
    def fetch_fixture(email, password, provider, days, predicate=None, **kwargs):
        return [{"uid": b"1", "from_address": "cc@ccb.com", "subject": "账单",
                 "raw": load_ccb()}]

    monkeypatch.setattr(ic, "fetch_full_mime", fetch_fixture)
    assert client.post(f"/api/imap/accounts/{account_id}/sync-statements",
                       json={"days": 90}).status_code == 200
    stmt = db.query(CreditCardStatement).filter_by(card_last_four="6714").one()

    # 用户还清 → 界线推进（模拟投递前复核把当期提醒取消：手工造 canceled 行，
    # 与真实复核同一唯一键（卡+due+days+channel））
    client.post(f"/api/credit-cards/statements/{stmt.id}/repay", json={"amount": stmt.total_due})
    db.expire_all()
    stmt = db.get(CreditCardStatement, stmt.id)
    assert stmt.due_date is not None
    canceled = _CCNO(
        credit_card_id=card.id, user_id=card.user_id,
        business_date=stmt.due_date - timedelta(days=3),
        days_before=3, channel="telegram",
        status="canceled", credit_card_name="建行卡", due_date=stmt.due_date,
        payload={}, canceled_at=utcnow(),
    )
    db.add(canceled)
    card.repaid_through_due = stmt.due_date
    db.commit()

    # 重解析金额上调 → 降级为未还
    def inflated_parse(raw, from_address=""):
        r = orig_parse(raw, from_address=from_address)
        st = next(s for s in r.statements if s.card_last_four == "6714")
        st.total_due = 9999.0
        first = st.items[0]
        st.items = list(st.items) + [type(first)(
            trans_date_raw=first.trans_date_raw, trans_date=first.trans_date,
            posted_date=first.posted_date, description="账单更正补录",
            amount=9999.0 - sum(i.amount for i in st.items if i.tx_type != "payment"),
            tx_amount=None, tx_currency=None, tx_type="purchase", installment_note=None,
        )]
        return r

    monkeypatch.setattr(credit_card_statement_sync, "parse_email", inflated_parse)
    assert client.post(f"/api/imap/accounts/{account_id}/sync-statements",
                       json={"days": 90}).status_code == 200
    db.expire_all()

    stmt = db.get(CreditCardStatement, stmt.id)
    assert stmt.is_repaid is False  # 已降级
    # canceled 提醒恢复为 pending（新欠款的提醒不再被永久压住）
    db.expire_all()
    row = db.get(_CCNO, canceled.id)
    assert row.status == "pending", f"取消的提醒应恢复 pending，实际 {row.status}"


def test_downgrade_does_not_revive_sent_reminders(sync_env, monkeypatch):
    """五审 Medium 4 边界：sent 行绝不复活（已经发出去的不能重发）。"""
    from statement_fixtures import load_ccb

    client, db, _, account = sync_env
    client.post("/api/credit-cards", json={
        "display_name": "建行卡", "bank_name": "建设银行", "last_four": "6714",
        "statement_day": 27, "due_day": 16, "remind_days_before": [3],
        "credit_limit": None, "is_active": True, "show_in_calendar": True,
    })
    account_id = account.id

    from app.services import imap_client as ic
    from app.models import CreditCardNotificationOutbox as _CCNO
    from app.services.scheduler import utcnow
    from datetime import timedelta

    orig_parse = credit_card_statement_sync.parse_email
    card = db.query(CreditCard).filter_by(last_four="6714").one()

    monkeypatch.setattr(ic, "fetch_full_mime", lambda *a, **kw: [
        {"uid": b"1", "from_address": "cc@ccb.com", "subject": "账单", "raw": load_ccb()}])
    assert client.post(f"/api/imap/accounts/{account_id}/sync-statements",
                       json={"days": 90}).status_code == 200
    stmt = db.query(CreditCardStatement).filter_by(card_last_four="6714").one()
    client.post(f"/api/credit-cards/statements/{stmt.id}/repay", json={"amount": stmt.total_due})
    db.expire_all()
    stmt = db.get(CreditCardStatement, stmt.id)

    sent = _CCNO(
        credit_card_id=card.id, user_id=card.user_id,
        business_date=stmt.due_date - timedelta(days=3),
        days_before=3, channel="telegram",
        status="sent", credit_card_name="建行卡", due_date=stmt.due_date,
        payload={}, sent_at=utcnow(),
    )
    db.add(sent)
    card.repaid_through_due = stmt.due_date
    db.commit()

    def inflated_parse(raw, from_address=""):
        r = orig_parse(raw, from_address=from_address)
        st = next(s for s in r.statements if s.card_last_four == "6714")
        st.total_due = 9999.0
        first = st.items[0]
        st.items = list(st.items) + [type(first)(
            trans_date_raw=first.trans_date_raw, trans_date=first.trans_date,
            posted_date=first.posted_date, description="账单更正补录",
            amount=9999.0 - sum(i.amount for i in st.items if i.tx_type != "payment"),
            tx_amount=None, tx_currency=None, tx_type="purchase", installment_note=None,
        )]
        return r

    monkeypatch.setattr(credit_card_statement_sync, "parse_email", inflated_parse)
    assert client.post(f"/api/imap/accounts/{account_id}/sync-statements",
                       json={"days": 90}).status_code == 200
    db.expire_all()
    row = db.get(_CCNO, sent.id)
    assert row.status == "sent"  # sent 不复活


def test_downgrade_provable_boundary_includes_nominal_derived_others(sync_env, monkeypatch):
    """七审 Medium 2 回归：更晚的已还账单 due NULL 但出账日与名义日自证一致
    （可可靠推导还款日）——降级其他账单时界线重算必须把它计入 provable，
    不得误判「唯一依据」而回退（已还的它不得复活）。"""
    from statement_fixtures import load_ccb
    from app.models import CreditCardStatement, CreditCard
    from datetime import date

    client, db, _, account = sync_env
    client.post("/api/credit-cards", json={
        "display_name": "建行卡", "bank_name": "建设银行", "last_four": "6714",
        "statement_day": 27, "due_day": 16, "remind_days_before": [3],
        "credit_limit": None, "is_active": True, "show_in_calendar": True,
    })
    account_id = account.id

    from app.services import imap_client as ic
    orig_parse = credit_card_statement_sync.parse_email
    card = db.query(CreditCard).filter_by(last_four="6714").one()
    today = date.today()

    # 更晚的已还账单：due NULL、statement_date=当月16日？不——自证条件是
    # statement_date.day == card.statement_day(27)。造 9/27 出账、due NULL。
    sep_stmt = date(today.year, 9, 27)
    sep = CreditCardStatement(
        user_id=card.user_id, card_id=card.id, bank_key="ccb",
        card_last_four="6714", match_status="matched", due_date=None,
        total_due=800.0, statement_date=sep_stmt,
        source_account_id=account.id, message_id="m-sep",
        verify_status="ok", is_repaid=True, repaid_amount=800.0,
    )
    db.add(sep)
    # 界线已由该账单的还款（名义推导 10/16）推进
    from app.credit_card_rules import _next_month
    from app.credit_card_rules import anchor_month_day
    card.repaid_through_due = anchor_month_day(*_next_month(sep_stmt.year, sep_stmt.month), 16)
    db.commit()
    nominal_sep_due = card.repaid_through_due

    # 另一早账单（fixture 邮件=6714）已还、随后重解析金额上调 → 降级
    def fetch_fixture(email, password, provider, days, predicate=None, **kwargs):
        return [{"uid": b"1", "from_address": "cc@ccb.com", "subject": "账单",
                 "raw": load_ccb()}]

    monkeypatch.setattr(ic, "fetch_full_mime", fetch_fixture)
    assert client.post(f"/api/imap/accounts/{account_id}/sync-statements",
                       json={"days": 90}).status_code == 200
    aug = db.query(CreditCardStatement).filter_by(
        card_last_four="6714", message_id="ccb-fix-1").one()
    client.post(f"/api/credit-cards/statements/{aug.id}/repay", json={"amount": aug.total_due})
    db.expire_all()

    # 重解析金额上调 → 降级
    def inflated_parse(raw, from_address=""):
        r = orig_parse(raw, from_address=from_address)
        st = next(s for s in r.statements if s.card_last_four == "6714")
        st.total_due = 5000.0
        first = st.items[0]
        st.items = list(st.items) + [type(first)(
            trans_date_raw=first.trans_date_raw, trans_date=first.trans_date,
            posted_date=first.posted_date, description="账单更正补录",
            amount=5000.0 - sum(i.amount for i in st.items if i.tx_type != "payment"),
            tx_amount=None, tx_currency=None, tx_type="purchase", installment_note=None,
        )]
        return r

    monkeypatch.setattr(credit_card_statement_sync, "parse_email", inflated_parse)
    assert client.post(f"/api/imap/accounts/{account_id}/sync-statements",
                       json={"days": 90}).status_code == 200
    db.expire_all()

    aug = db.get(CreditCardStatement, aug.id)
    assert aug.is_repaid is False  # 已降级
    # 界线不得低于名义推导的 9月已还账单还款日（盲目回退会让它复活）
    card = db.get(CreditCard, card.id)
    assert card.repaid_through_due is not None
    assert card.repaid_through_due >= nominal_sep_due, (
        f"界线 {card.repaid_through_due} 不得低于名义推导的已还账单还款日 {nominal_sep_due}"
    )
    assert db.get(CreditCardStatement, sep.id).is_repaid is True


def test_downgrade_with_due_lost_uses_prior_due_for_boundary(sync_env, monkeypatch):
    """八审 Medium 3 回归：已还账单（due=9/16，界线已推进）重解析金额上调且
    due 丢成 NULL——降级协调用覆盖前保存的旧可信 due 兜底：界线回退正常计算、
    canceled 提醒按旧 due 恢复（否则永久静默）。"""
    from statement_fixtures import load_ccb

    client, db, _, account = sync_env
    client.post("/api/credit-cards", json={
        "display_name": "建行卡", "bank_name": "建设银行", "last_four": "6714",
        "statement_day": 27, "due_day": 16, "remind_days_before": [3],
        "credit_limit": None, "is_active": True, "show_in_calendar": True,
    })
    account_id = account.id

    from app.services import imap_client as ic
    from app.models import CreditCardNotificationOutbox as _CCNO
    from app.services.scheduler import utcnow
    from datetime import timedelta

    orig_parse = credit_card_statement_sync.parse_email
    card = db.query(CreditCard).filter_by(last_four="6714").one()

    # 第一阶段：正常解析（due 非空）入库
    monkeypatch.setattr(ic, "fetch_full_mime", lambda *a, **kw: [
        {"uid": b"1", "from_address": "cc@ccb.com", "subject": "账单", "raw": load_ccb()}])
    assert client.post(f"/api/imap/accounts/{account_id}/sync-statements",
                       json={"days": 90}).status_code == 200
    stmt = db.query(CreditCardStatement).filter_by(card_last_four="6714").one()
    original_due = stmt.due_date
    assert original_due is not None

    # 用户还清 + 界线推进 + 造 canceled 提醒
    client.post(f"/api/credit-cards/statements/{stmt.id}/repay", json={"amount": stmt.total_due})
    db.expire_all()
    stmt = db.get(CreditCardStatement, stmt.id)
    card = db.get(CreditCard, card.id)
    assert card.repaid_through_due == original_due
    canceled = _CCNO(
        credit_card_id=card.id, user_id=card.user_id,
        business_date=original_due - timedelta(days=3),
        days_before=3, channel="telegram",
        status="canceled", credit_card_name="建行卡", due_date=original_due,
        payload={}, canceled_at=utcnow(),
    )
    db.add(canceled)
    db.commit()

    # 重解析：金额上调 + due 丢失
    def inflated_null_due(raw, from_address=""):
        r = orig_parse(raw, from_address=from_address)
        st = next(s for s in r.statements if s.card_last_four == "6714")
        st.total_due = 9999.0
        st.due_date = None
        first = st.items[0]
        st.items = list(st.items) + [type(first)(
            trans_date_raw=first.trans_date_raw, trans_date=first.trans_date,
            posted_date=first.posted_date, description="账单更正补录",
            amount=9999.0 - sum(i.amount for i in st.items if i.tx_type != "payment"),
            tx_amount=None, tx_currency=None, tx_type="purchase", installment_note=None,
        )]
        return r

    monkeypatch.setattr(credit_card_statement_sync, "parse_email", inflated_null_due)
    assert client.post(f"/api/imap/accounts/{account_id}/sync-statements",
                       json={"days": 90}).status_code == 200
    db.expire_all()

    stmt = db.get(CreditCardStatement, stmt.id)
    assert stmt.is_repaid is False  # 已降级
    assert stmt.due_date is None  # 新解析确实没提取到 due
    # canceled 提醒按旧 due 恢复（否则该期提醒被永久静默）
    row = db.get(_CCNO, canceled.id)
    assert row.status == "pending", f"canceled 提醒应按旧 due 恢复，实际 {row.status}"


def test_cleared_side_effect_uses_fresh_card_profile(sync_env, monkeypatch):
    """九审 Medium 1 回归：金额下调收敛为已还清的同一次重解析同时更改了卡片
    账单日（回写）且 due 缺失——界线推导必须用**回写后**的新名义日（用旧
    名义日会自证失败、界线漏推进、当期提醒不静默）。"""
    from statement_fixtures import load_ccb

    client, db, _, account = sync_env
    client.post("/api/credit-cards", json={
        "display_name": "建行卡", "bank_name": "建设银行", "last_four": "6714",
        "statement_day": 15, "due_day": 25, "remind_days_before": [3],
        "credit_limit": None, "is_active": True, "show_in_calendar": True,
    })
    account_id = account.id

    from app.services import imap_client as ic
    from app.models import CreditCardStatement, CreditCard
    from datetime import date

    orig_parse = credit_card_statement_sync.parse_email
    card = db.query(CreditCard).filter_by(last_four="6714").one()
    today = date.today()

    # 初始账单：9月15日出账（与旧名义日一致）、1000、已部分还款 800
    sep15 = date(today.year, 9, 15)
    stmt = CreditCardStatement(
        user_id=card.user_id, card_id=card.id, bank_key="ccb",
        card_last_four="6714", match_status="matched", due_date=None,
        total_due=1000.0, statement_date=sep15,
        source_account_id=account.id, message_id="ccb-fix-1",
        verify_status="ok", is_repaid=False, repaid_amount=800.0,
    )
    db.add(stmt)
    db.commit()

    # 重解析：金额下调至 700（800 覆盖）+ 出账日改为 9月5日（回写新名义日 5）
    def corrected_parse(raw, from_address=""):
        r = orig_parse(raw, from_address=from_address)
        st = next(s for s in r.statements if s.card_last_four == "6714")
        st.statement_date = date(today.year, 9, 5)
        st.due_date = None  # due 缺失（界线推导只能走名义路径）
        # 金额下调需勾稽自洽：净额 1658.72 → 700，补一笔负调整（退款）
        st.total_due = 700.0
        first = st.items[0]
        st.items = list(st.items) + [type(first)(
            trans_date_raw=first.trans_date_raw, trans_date=first.trans_date,
            posted_date=first.posted_date, description="账单更正调减",
            amount=700.0 - sum(i.amount for i in st.items if i.tx_type != "payment"),
            tx_amount=None, tx_currency=None, tx_type="refund", installment_note=None,
        )]
        return r

    def fetch(email, password, provider, days, predicate=None, **kwargs):
        return [{"uid": b"1", "from_address": "cc@ccb.com", "subject": "账单",
                 "raw": load_ccb()}]

    monkeypatch.setattr(ic, "fetch_full_mime", fetch)
    monkeypatch.setattr(credit_card_statement_sync, "parse_email", corrected_parse)
    assert client.post(f"/api/imap/accounts/{account_id}/sync-statements",
                       json={"days": 90}).status_code == 200
    db.expire_all()

    stmt = db.get(CreditCardStatement, stmt.id)
    assert stmt.is_repaid is True  # 800 ≥ 700 收敛为已还清
    assert stmt.repaid_amount == 700.0
    # 卡片名义日已被回写为 5（本次同步的最终资料）
    card = db.get(CreditCard, card.id)
    assert card.statement_day == 5
    # 界线必须推进到新名义周期的还款日（9/25——9月5日出账、due_day 25 同月；
    # 若用旧名义日 15 自证失败，界线会是 None——漏推进且当期提醒不静默）
    assert card.repaid_through_due is not None, (
        "界线必须用回写后的新名义日推导（旧名义日 15 会自证失败漏推进）"
    )
    assert card.repaid_through_due == date(today.year, 9, 25)


def test_double_null_downgrade_restores_canceled_reminder_with_previous_boundary(
    sync_env, monkeypatch
):
    """十审 Medium 1 回归：三日期全空账单经卡片级全量标记还清（界线推进到
    名义锚定日、提醒被 canceled）→ 重解析金额上调降级为未还——界线清空前
    先快照，canceled 提醒用降级前界线恢复为 pending（否则该期提醒被唯一键
    永久压住，新增欠款永久无提醒）。"""
    from statement_fixtures import load_ccb

    client, db, _, account = sync_env
    client.post("/api/credit-cards", json={
        "display_name": "建行卡", "bank_name": "建设银行", "last_four": "6714",
        "statement_day": 27, "due_day": 16, "remind_days_before": [3],
        "credit_limit": None, "is_active": True, "show_in_calendar": True,
    })
    account_id = account.id

    from app.services import imap_client as ic
    from app.models import CreditCardNotificationOutbox as _CCNO
    from app.services.scheduler import utcnow
    from datetime import timedelta

    orig_parse = credit_card_statement_sync.parse_email
    card = db.query(CreditCard).filter_by(last_four="6714").one()

    # 双 NULL 日期账单（statement_date/bill_period_end/due_date 全空）
    def null_dates_parse(raw, from_address=""):
        r = orig_parse(raw, from_address=from_address)
        st = next(s for s in r.statements if s.card_last_four == "6714")
        st.statement_date = None
        st.bill_period_start = None
        st.bill_period_end = None
        st.due_date = None
        return r

    monkeypatch.setattr(ic, "fetch_full_mime", lambda *a, **kw: [
        {"uid": b"1", "from_address": "cc@ccb.com", "subject": "账单", "raw": load_ccb()}])
    monkeypatch.setattr(credit_card_statement_sync, "parse_email", null_dates_parse)
    assert client.post(f"/api/imap/accounts/{account_id}/sync-statements",
                       json={"days": 90}).status_code == 200
    stmt = db.query(CreditCardStatement).filter_by(card_last_four="6714").one()
    assert stmt.statement_date is None and stmt.due_date is None

    # 卡片级全量标记还清（mark-repaid 的锚定日兜底推进界线）+ 造 canceled 提醒
    client.post(f"/api/credit-cards/{card.id}/mark-repaid")
    db.expire_all()
    card = db.get(CreditCard, card.id)
    boundary = card.repaid_through_due
    assert boundary is not None  # mark-repaid 的锚定日兜底

    canceled = _CCNO(
        credit_card_id=card.id, user_id=card.user_id,
        business_date=boundary - timedelta(days=3),
        days_before=3, channel="telegram",
        status="canceled", credit_card_name="建行卡", due_date=boundary,
        payload={}, canceled_at=utcnow(),
    )
    db.add(canceled)
    db.commit()

    # 重解析金额上调（仍双 NULL 日期）→ 降级为未还。
    # 勾稽自洽：建行逐卡勾稽是「非还款净额 == total_due」，金额上调需补
    # purchase 调整明细（9999 − 1658.72），否则 verify=mismatch 会被门卫
    # 正确地保留原状（mismatch 金额不可信）
    def inflated_null_dates(raw, from_address=""):
        r = null_dates_parse(raw, from_address=from_address)
        st = next(s for s in r.statements if s.card_last_four == "6714")
        st.total_due = 9999.0
        first = st.items[0]
        st.items = list(st.items) + [type(first)(
            trans_date_raw=first.trans_date_raw, trans_date=first.trans_date,
            posted_date=first.posted_date, description="账单更正补录",
            amount=9999.0 - sum(i.amount for i in st.items if i.tx_type != "payment"),
            tx_amount=None, tx_currency=None, tx_type="purchase", installment_note=None,
        )]
        return r

    monkeypatch.setattr(credit_card_statement_sync, "parse_email", inflated_null_dates)
    assert client.post(f"/api/imap/accounts/{account_id}/sync-statements",
                       json={"days": 90}).status_code == 200
    db.expire_all()

    stmt = db.get(CreditCardStatement, stmt.id)
    assert stmt.is_repaid is False  # 已降级
    # 界线清空（无可证明依据，宁多提醒）
    card = db.get(CreditCard, card.id)
    assert card.repaid_through_due is None
    # canceled 提醒用降级前界线恢复为 pending（十审 M1 核心）
    row = db.get(_CCNO, canceled.id)
    assert row.status == "pending", f"canceled 提醒应用降级前界线恢复，实际 {row.status}"


def test_resync_null_amount_keeps_partial_repayment_intact(sync_env, monkeypatch):
    """十一审 Medium 2 回归：部分还款（400/1000）后重解析金额未知——保留旧
    total_due 与 repaid_amount（清零会永久丢失用户录入的真实还款）；后续
    解析恢复 1000 时剩余仍为 600。"""
    from statement_fixtures import load_ccb

    client, db, _, account = sync_env
    client.post("/api/credit-cards", json={
        "display_name": "建行卡", "bank_name": "建设银行", "last_four": "6714",
        "statement_day": 27, "due_day": 16, "remind_days_before": [3],
        "credit_limit": None, "is_active": True, "show_in_calendar": True,
    })
    account_id = account.id

    from app.services import imap_client as ic

    def fake_fetch(email, password, provider, days, predicate=None, **kwargs):
        return [{"uid": b"1", "from_address": "cc@ccb.com", "subject": "账单",
                 "raw": load_ccb()}]

    monkeypatch.setattr(ic, "fetch_full_mime", fake_fetch)
    orig_parse = credit_card_statement_sync.parse_email

    def null_amount_parse(raw, from_address=""):
        r = orig_parse(raw, from_address=from_address)
        st = next(s for s in r.statements if s.card_last_four == "6714")
        st.total_due = None
        return r

    # 第一次同步：inflated 解析（1000，勾稽自洽需补明细——直接用
    # self-consistent 方式构造）
    def inflated_parse(raw, from_address=""):
        r = orig_parse(raw, from_address=from_address)
        st = next(s for s in r.statements if s.card_last_four == "6714")
        st.total_due = 1000.0
        first = st.items[0]
        st.items = list(st.items) + [type(first)(
            trans_date_raw=first.trans_date_raw, trans_date=first.trans_date,
            posted_date=first.posted_date, description="账单更正补录",
            amount=1000.0 - sum(i.amount for i in st.items if i.tx_type != "payment"),
            tx_amount=None, tx_currency=None, tx_type="purchase", installment_note=None,
        )]
        return r

    monkeypatch.setattr(credit_card_statement_sync, "parse_email", inflated_parse)
    assert client.post(f"/api/imap/accounts/{account_id}/sync-statements",
                       json={"days": 31}).status_code == 200
    stmt = db.query(CreditCardStatement).filter_by(card_last_four="6714").one()
    assert stmt.total_due == 1000.0

    client.post(f"/api/credit-cards/statements/{stmt.id}/repay", json={"amount": 400})
    db.expire_all()
    stmt = db.get(CreditCardStatement, stmt.id)
    assert stmt.repaid_amount == 400.0

    # 重解析金额未知 → 保留旧 total_due=1000 与 repaid_amount=400
    monkeypatch.setattr(credit_card_statement_sync, "parse_email", null_amount_parse)
    assert client.post(f"/api/imap/accounts/{account_id}/sync-statements",
                       json={"days": 31}).status_code == 200
    db.expire_all()
    stmt = db.get(CreditCardStatement, stmt.id)
    assert stmt.total_due == 1000.0, "部分还款账单遇金额未知必须保留旧可信 total_due"
    assert stmt.repaid_amount == 400.0, "用户录入的还款不得被清零"
    assert stmt.is_repaid is False

    # 后续解析恢复 1000 → 剩余仍为 600
    monkeypatch.setattr(credit_card_statement_sync, "parse_email", inflated_parse)
    assert client.post(f"/api/imap/accounts/{account_id}/sync-statements",
                       json={"days": 31}).status_code == 200
    db.expire_all()
    stmt = db.get(CreditCardStatement, stmt.id)
    assert stmt.total_due == 1000.0 and stmt.repaid_amount == 400.0
    assert stmt.is_repaid is False


def test_apply_side_effects_skips_stale_signature(sync_env, monkeypatch):
    """十一审 Medium 3 回归（单元级）：repayment_events 携带状态签名——
    回滚后账单实际状态与事件期望不一致时，副作用必须跳过（不得补标/推进
    界线/静默提醒）。构造 stale cleared 事件（账单实际还是未还旧值）。"""
    from datetime import date, timedelta

    client, db, _, account = sync_env
    client.post("/api/credit-cards", json={
        "display_name": "建行卡", "bank_name": "建设银行", "last_four": "6714",
        "statement_day": 27, "due_day": 16, "remind_days_before": [3],
        "credit_limit": None, "is_active": True, "show_in_calendar": True,
    })
    card = db.query(CreditCard).filter_by(last_four="6714").one()
    today = date.today()
    due = date(today.year, 9, 16)

    # 数据库实际状态：未还（回滚后恢复的旧值）
    stmt = CreditCardStatement(
        user_id=card.user_id, card_id=card.id, bank_key="ccb",
        card_last_four="6714", match_status="matched", due_date=due,
        total_due=1000.0, statement_date=due - timedelta(days=11),
        message_id="m-x", verify_status="ok", is_repaid=False, repaid_amount=0.0,
    )
    db.add(stmt)
    card.repaid_through_due = None
    db.commit()

    # stale 事件：期望签名是回滚前的（True/1000/1000），实际 DB 是 False/0
    stale_event = {
        "statement_id": stmt.id,
        "cleared": True,
        "downgraded": False,
        "prior_due_date": None,
        "expect_total_cents": 100000,
        "expect_repaid_cents": 100000,
        "expect_is_repaid": True,
    }
    from app.services import credit_card_statement_sync as sync_mod
    sync_mod._apply_repayment_side_effects(db, [stale_event])
    db.expire_all()

    stmt = db.get(CreditCardStatement, stmt.id)
    assert stmt.is_repaid is False  # stale cleared 未执行（未补标任何状态）
    card = db.get(CreditCard, card.id)
    assert card.repaid_through_due is None  # 界线未被推进/静默


def test_multi_downgrade_side_effects_under_autoflush_false(sync_env, monkeypatch):
    """十二审 Medium 1 回归：生产会话 autoflush=False——同批两笔已还账单金额
    同时上调、都降级为未还时，副作用循环内第二个事件的 provable 查询必须
    看到第一个事件的最新状态（否则界线停留在「已还」期次，未还提醒被静默）。"""
    from app.models import CreditCardStatement, CreditCard
    from datetime import date, timedelta

    client, db, _, account = sync_env
    client.post("/api/credit-cards", json={
        "display_name": "建行卡", "bank_name": "建设银行", "last_four": "6714",
        "statement_day": 27, "due_day": 16, "remind_days_before": [3],
        "credit_limit": None, "is_active": True, "show_in_calendar": True,
    })
    from app.services import credit_card_statement_sync as sync_mod

    orig_parse = credit_card_statement_sync.parse_email
    card = db.query(CreditCard).filter_by(last_four="6714").one()
    today = date.today()

    # 用生产一致的 autoflush=False 会话执行协调（默认夹具 autoflush=True
    # 会掩盖生产行为——十二审 M1）
    SessionFalse = sessionmaker(bind=db.bind, expire_on_commit=False, autoflush=False)

    # 两笔已还账单（8/16、9/16 都已还，界线=9/16）
    aug_due = date(today.year, 8, 16)
    sep_due = date(today.year, 9, 16)
    aug = CreditCardStatement(
        user_id=card.user_id, card_id=card.id, bank_key="ccb",
        card_last_four="6714", match_status="matched", due_date=aug_due,
        total_due=500.0, statement_date=aug_due - timedelta(days=11),
        source_account_id=account.id, message_id="m-aug",
        verify_status="ok", is_repaid=True, repaid_amount=500.0,
    )
    sep = CreditCardStatement(
        user_id=card.user_id, card_id=card.id, bank_key="ccb",
        card_last_four="6714", match_status="matched", due_date=sep_due,
        total_due=800.0, statement_date=sep_due - timedelta(days=11),
        source_account_id=account.id, message_id="ccb-fix-1",
        verify_status="ok", is_repaid=True, repaid_amount=800.0,
    )
    db.add_all([aug, sep])
    card.repaid_through_due = sep_due
    db.commit()

    # 重解析两笔金额同时上调（各自勾稽自洽）→ 都降级
    def inflated_both(raw, from_address=""):
        r = orig_parse(raw, from_address=from_address)
        for st in r.statements:
            st.due_date = aug_due if st.card_last_four == "6714" and "zz" else st.due_date
        # 两封邮件场景由调用方控制——这里只处理单邮件；下方直接构造事件
        return r

    # 用生产一致的 autoflush=False 会话执行「协调修改 + 副作用」（真实
    # sync 流程：协调修改与副作用在同一未 flush 事务——flush 语义是本轮
    # 修复的核心）
    events = [
        {"statement_id": aug.id, "cleared": False, "downgraded": True,
         "prior_due_date": aug_due,
         "expect_total_cents": 50000, "expect_repaid_cents": 50000,
         "expect_is_repaid": False},
        {"statement_id": sep.id, "cleared": False, "downgraded": True,
         "prior_due_date": sep_due,
         "expect_total_cents": 80000, "expect_repaid_cents": 80000,
         "expect_is_repaid": False},
    ]
    fx = SessionFalse()
    try:
        aug_fx = fx.get(CreditCardStatement, aug.id)
        sep_fx = fx.get(CreditCardStatement, sep.id)
        # 协调修改（未 flush——autoflush=False 不会自动落库）
        aug_fx.is_repaid = False
        aug_fx.repaid_at = None
        sep_fx.is_repaid = False
        sep_fx.repaid_at = None
        sync_mod._apply_repayment_side_effects(fx, events)
        fx.commit()
    finally:
        fx.close()
    db.expire_all()

    card = db.get(CreditCard, card.id)
    # 两笔都未还 → 界线必须回退到最早未还账单的还款日之前（否则该期提醒
    # 仍被静默）；aug 是唯一界线依据 → 回退到它的前一期 7/16
    assert card.repaid_through_due is not None and card.repaid_through_due < aug_due, (
        f"双降级后界线必须早于最早未还账单的还款日 {aug_due}，实际 {card.repaid_through_due}"
    )
    assert db.get(CreditCardStatement, aug.id).is_repaid is False
    assert db.get(CreditCardStatement, sep.id).is_repaid is False

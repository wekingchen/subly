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
from app.services import imap_client  # noqa: E402


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
            idx = int(args[0]) - 1
            raw = mails[idx]
            return "OK", [(f"1 (UID {args[0]} BODY[])".encode(), raw), b")"]

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


def test_delete_card_removes_statements(sync_env, monkeypatch):
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
    assert db.query(CreditCardStatement).count() == 0
    assert db.query(CreditCardStatementItem).count() == 0


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

    exported = _collect_entities(db, user)
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
    assert body["unmatched_count"] == 0  # 建行尾号与招行卡不匹配 → 该卡视角 0

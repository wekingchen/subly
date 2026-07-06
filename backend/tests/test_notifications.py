import pytest

from app import models
from app.database import Base
from app.routers import notifications
from app.schemas import BarkTestIn
from app.security import hash_password
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session(), engine


def add_user(db, username="alice", device_key="key123"):
    user = models.User(
        username=username,
        email=f"{username}@example.com",
        password_hash=hash_password("x"),
        base_currency="CNY",
        bark_enabled=True,
        bark_device_key=device_key,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture(autouse=True)
def quiet_activity(monkeypatch):
    monkeypatch.setattr(notifications.activity, "log", lambda *a, **k: None)


def test_bark_test_passes_app_public_url_when_configured(monkeypatch):
    db, engine = make_db()
    try:
        user = add_user(db)
        captured = {}
        monkeypatch.setattr(notifications.bark, "send_push",
                            lambda *a, **kw: captured.update({"args": a, **kw}) or {})
        monkeypatch.setattr(notifications.settings, "app_public_url", "https://subly.example.com")

        notifications.bark_test(BarkTestIn(), user)

        # device_key/title/body 是位置参数
        assert captured["args"][1] == "✅ 连接成功！"
        assert captured["url"] == "https://subly.example.com"
    finally:
        db.close()
        engine.dispose()


def test_bark_test_omits_url_when_app_public_url_blank(monkeypatch):
    db, engine = make_db()
    try:
        user = add_user(db)
        captured = {}
        monkeypatch.setattr(notifications.bark, "send_push", lambda *a, **kw: captured.update(kw) or {})
        monkeypatch.setattr(notifications.settings, "app_public_url", "")

        notifications.bark_test(BarkTestIn(), user)

        # 空配置时 url=None，bark.send_push 内部不会把 url 放进 payload
        assert captured["url"] is None
    finally:
        db.close()
        engine.dispose()

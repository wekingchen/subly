"""SQLite 数据库引擎：零配置，启动时自动在 data/ 目录下创建/打开数据库文件。"""
import logging
import os

from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


logger = logging.getLogger(__name__)
engine = None
SessionLocal = None


def build_url() -> str:
    """根据配置的文件路径构建 SQLite SQLAlchemy URL，并确保父目录存在。"""
    path = settings.db_path
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return f"sqlite:///{path}"


def init_engine(url: str | None = None):
    """初始化全局引擎与会话工厂。不传 url 时使用默认 SQLite 文件。"""
    global engine, SessionLocal
    url = url or build_url()
    engine = create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False},
    )

    # 每个连接设置 busy_timeout，WAL 尝试启用但失败时保留可见告警
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _record):  # pragma: no cover
        cur = dbapi_conn.cursor()
        try:
            try:
                cur.execute("PRAGMA busy_timeout=5000")
            except Exception as e:  # noqa: BLE001
                logger.warning("event=sqlite_busy_timeout_failed error=%s", e)

            try:
                cur.execute("PRAGMA journal_mode=WAL")
            except Exception as e:  # noqa: BLE001
                logger.warning("event=sqlite_wal_failed error=%s", e)
        finally:
            cur.close()

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    logger.info("event=database_engine_initialized db_url=%s", url)
    return engine


def is_configured() -> bool:
    return SessionLocal is not None


def reset_engine():
    global engine, SessionLocal
    if engine is not None:
        engine.dispose()
    engine = None
    SessionLocal = None


def get_db():
    if SessionLocal is None:
        raise HTTPException(status_code=503, detail="数据库尚未初始化")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

"""SQLite 数据库引擎：零配置，启动时自动在 data/ 目录下创建/打开数据库文件。"""
import os

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


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
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
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

"""IMAP 邮件账户：一户多邮箱的增删改查、连接测试与最近邮件预览。

凭据只写不回显：授权码任何 API 永不返回；账户列表仅暴露 id/邮箱/服务商。
拉取仅返回邮件头部预览，不落库。
"""
import logging

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import activity
from app.database import get_db
from app.deps import get_current_user
from app.models import CreditCardStatement, CreditCardStatementItem, ImapAccount, User
from app.bank_senders import BANK_SENDER_DOMAINS, normalize_bank_keys, sender_matches_banks
from app.services import imap_client

router = APIRouter(prefix="/api/imap/accounts", tags=["imap"])
logger = logging.getLogger(__name__)

# 并发守卫移至 imap_client.IMAP_SEMAPHORE（手动路由与自动调度共享）

# 单用户账户数上限：防止无限增长
MAX_ACCOUNTS_PER_USER = 10


def _service_error(exc: Exception, action: str, user: User) -> HTTPException:
    # 响应只含泛化文案，不回显底层异常（防授权码/服务器细节泄漏）
    logger.warning(
        "event=imap_%s_failed user_id=%s error_type=%s", action, user.id, type(exc).__name__
    )
    return HTTPException(502, "IMAP 操作失败，请检查邮箱地址、授权码与网络连接")


def _account_for_user(user: User, account_id: int, db: Session) -> ImapAccount:
    """取本用户的指定账户；不存在返回 404（不区分他人账户，避免探测）。"""
    account = db.scalar(
        select(ImapAccount).where(
            ImapAccount.id == account_id,
            ImapAccount.user_id == user.id,
        )
    )
    if not account:
        raise HTTPException(404, "邮件账户不存在")
    return account


def _validate_provider(provider: str) -> str:
    if provider not in imap_client.IMAP_PROVIDERS:
        raise HTTPException(400, "不支持的邮箱服务商，目前仅支持 126 与 QQ 邮箱")
    return provider


def _validate_email(email: str | None) -> str:
    email = (email or "").strip()
    if not email or "@" not in email or len(email) > 255:
        raise HTTPException(400, "邮箱地址格式不正确")
    return email


class ImapAccountIn(BaseModel):
    email: str
    provider: str
    # 创建时必填；更新时 None/空串 = 不修改授权码
    password: str | None = None
    # 账单银行白名单（银行 key 数组）；None = 不修改（更新时）/全部银行（创建时默认）；
    # 空数组 = 全部银行。类型放宽为 Any 交由 normalize_bank_keys 统一校验，
    # 非法类型/元素/key 都返回 400（而非 Pydantic 的 422）。
    banks: Any | None = None


def _account_out(a: ImapAccount) -> dict:
    return {
        "id": a.id,
        "email": a.email,
        "provider": a.provider,
        "banks": a.banks or [],
    }


class ImapFetchIn(BaseModel):
    days: int = Field(default=30, ge=1, le=90)
    limit: int = Field(default=20, ge=1, le=50)


class ImapSyncIn(BaseModel):
    days: int = Field(default=31, ge=1, le=90)


@router.get("")
def list_accounts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    accounts = db.scalars(
        select(ImapAccount)
        .where(ImapAccount.user_id == user.id)
        .order_by(ImapAccount.id)
    ).all()
    return {"accounts": [_account_out(a) for a in accounts]}


@router.post("", status_code=201)
def create_account(
    payload: ImapAccountIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    email = _validate_email(payload.email)
    provider = _validate_provider(payload.provider)
    if not payload.password or not payload.password.strip():
        raise HTTPException(400, "请填写 IMAP 授权码")
    try:
        banks = normalize_bank_keys(payload.banks)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    existing = db.scalar(
        select(ImapAccount).where(
            ImapAccount.user_id == user.id, ImapAccount.email == email
        )
    )
    if existing:
        raise HTTPException(409, "该邮箱已存在，请直接编辑或测试")
    count = len(
        db.scalars(select(ImapAccount.id).where(ImapAccount.user_id == user.id)).all()
    )
    if count >= MAX_ACCOUNTS_PER_USER:
        raise HTTPException(400, f"最多可添加 {MAX_ACCOUNTS_PER_USER} 个邮件账户")
    account = ImapAccount(
        user_id=user.id,
        email=email,
        password=payload.password.strip(),
        provider=provider,
        banks=banks,  # None = 全部银行
    )
    db.add(account)
    # 并发下查重/计数可能同时通过，由唯一约束兜底；IntegrityError 转泛化 409，
    # 避免数据库异常（参数含授权码）进入全局 500 日志。
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        logger.warning(
            "event=imap_account_create_conflict user_id=%s error_type=%s",
            user.id, type(exc).__name__,
        )
        raise HTTPException(409, "该邮箱已存在或添加冲突，请刷新后重试")
    db.refresh(account)
    activity.log("imap.account_added", "新增邮件账户", user=user)
    return _account_out(account)


@router.patch("/{account_id}")
def update_account(
    account_id: int,
    payload: ImapAccountIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = _account_for_user(user, account_id, db)
    email = _validate_email(payload.email)
    provider = _validate_provider(payload.provider)
    try:
        banks = normalize_bank_keys(payload.banks)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    # 同用户下改邮箱时查重（排除自身）
    dup = db.scalar(
        select(ImapAccount).where(
            ImapAccount.user_id == user.id,
            ImapAccount.email == email,
            ImapAccount.id != account.id,
        )
    )
    if dup:
        raise HTTPException(409, "该邮箱已存在，请直接编辑或测试")
    account.email = email
    account.provider = provider
    # 授权码 None/空串 = 不修改
    if payload.password is not None and payload.password.strip():
        account.password = payload.password.strip()
    # banks None = 不修改（前端总是回传当前选择）；显式数组（含空=全部）则更新
    if payload.banks is not None:
        account.banks = banks
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        logger.warning(
            "event=imap_account_update_conflict user_id=%s error_type=%s",
            user.id, type(exc).__name__,
        )
        raise HTTPException(409, "该邮箱已存在或更新冲突，请刷新后重试")
    activity.log("imap.account_updated", "更新邮件账户", user=user)
    return _account_out(account)


@router.delete("/{account_id}")
def delete_account(
    account_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = _account_for_user(user, account_id, db)
    # 该账户解析出的账单与明细一并清理（来源已不存在，悬空引用会让
    # 重新添加同邮箱后重复导入；需要保留历史可先导出备份）。
    stmt_ids = db.scalars(
        select(CreditCardStatement.id).where(
            CreditCardStatement.source_account_id == account.id
        )
    ).all()
    if stmt_ids:
        db.execute(
            delete(CreditCardStatementItem).where(
                CreditCardStatementItem.statement_id.in_(stmt_ids)
            )
        )
        # 账单被删的 poll run 置空关联（防悬空 ID；已 succeeded 的历史不动）
        from app.models import CreditCardStatementPollRun

        db.execute(
            CreditCardStatementPollRun.__table__.update()
            .where(CreditCardStatementPollRun.statement_id.in_(stmt_ids))
            .values(statement_id=None)
        )
        db.execute(
            delete(CreditCardStatement).where(CreditCardStatement.id.in_(stmt_ids))
        )
    db.delete(account)
    db.commit()
    activity.log("imap.account_deleted", "删除邮件账户", user=user)
    return {"ok": True}


def _run_imap(action: str, user: User, run):
    """公共包裹：限并发 + 统一异常转 502 + activity 日志。run 返回 API 响应。"""
    if not imap_client.IMAP_SEMAPHORE.acquire(timeout=5):
        raise HTTPException(503, "IMAP 操作繁忙，请稍后再试")
    try:
        result = run()
    except (imap_client.ImapConnectionError, imap_client.ImapConfigError) as exc:
        raise _service_error(exc, action, user)
    finally:
        imap_client.IMAP_SEMAPHORE.release()
    return result


@router.post("/{account_id}/test")
def test_account(
    account_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = _account_for_user(user, account_id, db)
    result = _run_imap(
        "test",
        user,
        lambda: imap_client.test_connection(account.email, account.password, account.provider),
    )
    activity.log("imap.test", "IMAP 连接测试成功", user=user)
    return result


@router.post("/{account_id}/fetch")
def fetch_account(
    account_id: int,
    payload: ImapFetchIn | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = _account_for_user(user, account_id, db)
    body = payload or ImapFetchIn()
    # 银行白名单在拉取侧过滤：limit 指「命中白名单的邮件数上限」，
    # 扫描在 IMAP 会话内边取边匹配（受并发信号量保护），白名单邮件
    # 不会被无关邮件挤出截断窗口。白名单为空 = 不过滤、返回全部。
    predicate = None
    if account.banks:
        predicate = lambda name, addr: sender_matches_banks(addr, account.banks)  # noqa: E731
    messages = _run_imap(
        "fetch",
        user,
        lambda: imap_client.fetch_recent(
            account.email, account.password, account.provider, body.days, body.limit,
            predicate=predicate,
        ),
    )
    activity.log("imap.fetch", f"IMAP 拉取最近邮件 {len(messages)} 封", user=user)
    return {"messages": messages, "count": len(messages)}


@router.post("/{account_id}/sync-statements")
def sync_statements_endpoint(
    account_id: int,
    payload: ImapSyncIn | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """手动解析账单：拉白名单银行账单邮件正文 → 解析 → 按卡落库。

    IMAP 层异常转 502（同 test/fetch）；单封邮件解析失败不中断，
    计入 errors 返回。信号量与提交由 sync_statements 统一管理。
    """
    from app.services.credit_card_statement_sync import ImapBusyError, sync_statements

    account = _account_for_user(user, account_id, db)
    body = payload or ImapSyncIn()
    try:
        result = sync_statements(db, account, user, days=body.days)
    except ImapBusyError:
        # 本地并发饱和 ≠ 凭据/网络故障：503 + 明确文案（审核修复）
        raise HTTPException(503, "IMAP 操作繁忙，请稍后再试")
    except (imap_client.ImapConnectionError, imap_client.ImapConfigError) as exc:
        raise _service_error(exc, "sync", user)
    return result.as_dict()


@router.get("/banks")
def list_banks():
    """可选银行清单（key/名称/发件人域名），前端选择 UI 与解析层共用。"""
    return {
        "banks": [
            {"key": key, "name": info["name"], "domains": info["domains"]}
            for key, info in BANK_SENDER_DOMAINS.items()
        ]
    }

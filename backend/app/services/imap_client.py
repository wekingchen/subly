"""IMAP 邮件客户端：为信用卡账单邮件拉取提供连接测试与最近邮件预览。

仅支持内置预设服务商（126/qq），主机名不受用户配置控制，杜绝 SSRF 面。
标准库 imaplib 实现，用完即关（对齐 SMTP 出网先例），不做长连接/轮询。
"""
import email.header
import imaplib
import ssl
from email.utils import parseaddr

# 预设服务商：主机/端口固定，不暴露给用户配置
IMAP_PROVIDERS = {
    "126": {"host": "imap.126.com", "port": 993},
    "qq": {"host": "imap.qq.com", "port": 993},
}

IMAP_TIMEOUT_SECONDS = 20
MAX_SUBJECT_LENGTH = 120

# TLS 必须验证服务器证书与主机名：imaplib 默认 context 是 CERT_NONE，
# 不显式传入会把授权码暴露给中间人。
_SSL_CONTEXT = ssl.create_default_context()


class ImapConfigError(ValueError):
    """服务商预设不存在或配置不完整。"""


class ImapConnectionError(RuntimeError):
    """连接或登录失败（对外只暴露泛化信息）。"""


def provider_host(provider: str) -> str:
    """返回预设服务商的 IMAP 主机名；未知服务商抛配置错误。"""
    entry = IMAP_PROVIDERS.get(provider)
    if not entry:
        raise ImapConfigError("未知邮箱服务商")
    host = entry["host"]
    # 防御未来预设误配：主机不得是链路本地/元数据等危险字面量地址
    from app.schemas import _is_blocked_host

    if _is_blocked_host(host):
        raise ImapConfigError("预设主机不合法")
    return host


def _decode_header_value(raw) -> str:
    """解码 RFC2047 编码的邮件头（如 =?utf-8?B?...?=），超长截断。"""
    if not raw:
        return ""
    parts = email.header.decode_header(raw)
    decoded = []
    for data, charset in parts:
        if isinstance(data, bytes):
            try:
                decoded.append(data.decode(charset or "utf-8", errors="replace"))
            except LookupError:
                decoded.append(data.decode("utf-8", errors="replace"))
        else:
            decoded.append(data)
    text = "".join(decoded).replace("\r", " ").replace("\n", " ").strip()
    if len(text) > MAX_SUBJECT_LENGTH:
        text = text[:MAX_SUBJECT_LENGTH] + "…"
    return text


def _parse_from(raw) -> tuple[str, str]:
    """解析发件人头，返回 (显示名或地址, 地址)。"""
    name, address = parseaddr(_decode_header_value(raw))
    return (name or address, address)


def _ssl_context() -> ssl.SSLContext:
    """验证系统 CA 与主机名的 TLS context。

    imaplib 默认路径使用 _create_stdlib_context（CERT_NONE + 不校验主机名），
    会把授权码暴露给中间人；这里显式启用完整校验。
    """
    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def test_connection(email: str, password: str, provider: str) -> dict:
    """登录 IMAP 验证凭据；成功即断开返回。失败统一抛 ImapConnectionError。"""
    host = provider_host(provider)
    try:
        client = imaplib.IMAP4_SSL(
            host,
            IMAP_PROVIDERS[provider]["port"],
            ssl_context=_ssl_context(),
            timeout=IMAP_TIMEOUT_SECONDS,
        )
    except (OSError, imaplib.IMAP4.error) as exc:
        raise ImapConnectionError(type(exc).__name__) from exc
    try:
        try:
            client.login(email, password)
        except (imaplib.IMAP4.error, OSError, TimeoutError) as exc:
            # TLS 建立后的登录阶段也可能因服务端无响应抛 OSError/TimeoutError，
            # 统一转成不含底层细节的连接错误，避免 500 逃逸。
            raise ImapConnectionError("login-failed") from exc
        try:
            client.logout()
        except (imaplib.IMAP4.error, OSError):
            pass  # logout 失败不影响验证结论
    finally:
        try:
            client.shutdown()
        except (OSError, imaplib.IMAP4.error):
            pass
    return {"ok": True, "email": email, "provider": provider}


def fetch_recent(email: str, password: str, provider: str, days: int, limit: int) -> list[dict]:
    """拉取收件箱最近 N 天邮件头部（不取正文），按 UID 倒序截断 limit。

    只返回 uid/from/subject/date 预览字段，邮件内容不落库。
    """
    from datetime import date, timedelta

    host = provider_host(provider)
    since = (date.today() - timedelta(days=days)).strftime("%d-%b-%Y")
    try:
        client = imaplib.IMAP4_SSL(
            host,
            IMAP_PROVIDERS[provider]["port"],
            ssl_context=_ssl_context(),
            timeout=IMAP_TIMEOUT_SECONDS,
        )
    except (OSError, imaplib.IMAP4.error) as exc:
        raise ImapConnectionError(type(exc).__name__) from exc
    try:
        try:
            client.login(email, password)
        except (imaplib.IMAP4.error, OSError, TimeoutError) as exc:
            raise ImapConnectionError("login-failed") from exc
        try:
            status, _ = client.select("INBOX", readonly=True)
            if status != "OK":
                raise ImapConnectionError("select-failed")
            status, data = client.uid("search", None, f'(SINCE "{since}")')
            if status != "OK":
                raise ImapConnectionError("search-failed")
            uids = sorted((data[0] or b"").split(), key=lambda u: int(u), reverse=True)
            messages = []
            # 最新的 UID 数值最大：按数值降序取前 limit 封
            for uid in uids[:limit]:
                status, msg_data = client.uid("fetch", uid, "(BODY.PEEK[HEADER])")
                if status != "OK" or not msg_data or msg_data[0] is None:
                    continue
                import email

                msg = email.message_from_bytes(msg_data[0][1])
                sender_name, sender_addr = _parse_from(msg.get("From"))
                messages.append({
                    "uid": uid.decode("ascii", errors="replace"),
                    "from": sender_name,
                    "from_address": sender_addr,
                    "subject": _decode_header_value(msg.get("Subject")) or "（无主题）",
                    "date": _decode_header_value(msg.get("Date")),
                })
            return messages
        except (OSError, TimeoutError) as exc:
            # SELECT/SEARCH/FETCH 期间的网络异常统一转成连接错误
            raise ImapConnectionError(type(exc).__name__) from exc
    finally:
        try:
            client.logout()
        except (OSError, imaplib.IMAP4.error):
            pass
        try:
            client.shutdown()
        except (OSError, imaplib.IMAP4.error):
            pass

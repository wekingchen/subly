"""IMAP 邮件客户端：为信用卡账单邮件拉取提供连接测试与最近邮件预览。

仅支持内置预设服务商（126/qq），主机名不受用户配置控制，杜绝 SSRF 面。
标准库 imaplib 实现，用完即关（对齐 SMTP 出网先例），不做长连接/轮询。
"""
import email.header
import imaplib
import re
import ssl
from email.utils import parseaddr

# 预设服务商：主机/端口固定，不暴露给用户配置
IMAP_PROVIDERS = {
    "126": {"host": "imap.126.com", "port": 993},
    "qq": {"host": "imap.qq.com", "port": 993},
}

IMAP_TIMEOUT_SECONDS = 20
MAX_SUBJECT_LENGTH = 120

# 网易系 IMAP（126/163/网易企业邮）要求登录后先发 ID 命令自报客户端身份，
# 否则后续 SELECT/SEARCH 会被以 "Unsafe Login" 拒绝——表现为「测试连接成功
# 但拉取失败」。QQ 邮箱无此要求，发送 ID 亦无害。名称必须在白名单里：
# xatom 对不在 imaplib.Commands 的名字会动态注册，绕过状态机校验。
_ID_COMMAND_NAME = "ID"


def _client_session(client) -> None:
    """登录后发送 ID 握手（网易系必需）。失败不阻断流程。"""
    try:
        client.xatom(
            _ID_COMMAND_NAME,
            '("name" "Subly" "version" "1.0")',
        )
    except (imaplib.IMAP4.error, OSError, TimeoutError):
        pass  # 非网易服务商可能不支持 ID；忽略

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
        _client_session(client)
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


def fetch_recent(
    email: str,
    password: str,
    provider: str,
    days: int,
    limit: int,
    predicate=None,
    max_scan: int = 200,
) -> list[dict]:
    """拉取收件箱最近 N 天邮件头部（不取正文），按 UID 倒序返回最多 limit 封。

    predicate(from_name, from_address) -> bool：可选过滤器（如账单银行白名单）。
    limit 指过滤后的命中数上限：按 UID 倒序最多扫描 max_scan 封头部，
    命中累计到 limit 即停，避免白名单邮件被无关邮件挤出截断窗口而漏掉。
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
        _client_session(client)
        try:
            status, _ = client.select("INBOX", readonly=True)
            if status != "OK":
                raise ImapConnectionError("select-failed")
            status, data = client.uid("search", None, f'(SINCE "{since}")')
            if status != "OK":
                raise ImapConnectionError("search-failed")
            uids = sorted((data[0] or b"").split(), key=lambda u: int(u), reverse=True)
            messages = []
            # 最新的 UID 数值最大：倒序扫描，命中累计到 limit 即停。
            # max_scan 封顶防止大收件箱产生无界 IO；limit 未满时属正常
            # （指定时间窗内命中邮件就这么多），不视为错误。
            for uid in uids[:max_scan]:
                status, msg_data = client.uid("fetch", uid, "(BODY.PEEK[HEADER])")
                if status != "OK" or not msg_data or msg_data[0] is None:
                    continue
                import email

                msg = email.message_from_bytes(msg_data[0][1])
                sender_name, sender_addr = _parse_from(msg.get("From"))
                if predicate is not None and not predicate(sender_name, sender_addr):
                    continue
                messages.append({
                    "uid": uid.decode("ascii", errors="replace"),
                    "from": sender_name,
                    "from_address": sender_addr,
                    "subject": _decode_header_value(msg.get("Subject")) or "（无主题）",
                    "date": _decode_header_value(msg.get("Date")),
                })
                if len(messages) >= limit:
                    break
            return messages
        except (imaplib.IMAP4.error, OSError, TimeoutError) as exc:
            # SELECT/SEARCH/FETCH 期间的协议/网络异常（含网易 "Unsafe Login"
            # 拒绝等 IMAP4.error 子类）统一转成连接错误，避免 500 逃逸。
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


def fetch_full_mime(
    email: str,
    password: str,
    provider: str,
    days: int,
    predicate=None,
    max_scan: int = 200,
    max_message_bytes: int = 5 * 1024 * 1024,
) -> list[dict]:
    """拉取收件箱最近 N 天**完整邮件**（含正文），供账单解析。

    predicate(from_address) -> bool 过滤发件人（账单银行白名单）。
    返回 [{uid, from_address, subject, raw(bytes)}]；单封超过
    max_message_bytes 直接跳过（防止异常大邮件撑爆内存）。
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
        _client_session(client)
        try:
            status, _ = client.select("INBOX", readonly=True)
            if status != "OK":
                raise ImapConnectionError("select-failed")
            status, data = client.uid("search", None, f'(SINCE "{since}")')
            if status != "OK":
                raise ImapConnectionError("search-failed")
            uids = sorted((data[0] or b"").split(), key=lambda u: int(u), reverse=True)
            out: list[dict] = []
            # 两阶段拉取：先取头部+大小（发件人过滤与大小判断都不需要正文），
            # 只对通过筛选的邮件下载完整 BODY——避免把大附件/无关邮件整个
            # 拉进内存后才丢弃（审核修复：资源保护必须发生在下载之前）。
            for uid in uids[:max_scan]:
                status, head_data = client.uid("fetch", uid, "(BODY.PEEK[HEADER] RFC822.SIZE)")
                if status != "OK" or not head_data or head_data[0] is None:
                    continue
                if not isinstance(head_data[0], tuple):
                    continue
                meta_raw = head_data[0][1]
                size_raw = head_data[0][0] if isinstance(head_data[0][0], bytes) else b""
                msize = re.search(rb"RFC822.SIZE\s+(\d+)", size_raw)
                if msize and int(msize[1]) > max_message_bytes:
                    continue  # 超限：不下载正文
                import email as _email

                head_msg = _email.message_from_bytes(meta_raw)
                _, sender_addr = _parse_from(head_msg.get("From"))
                if predicate is not None and not predicate(sender_addr):
                    continue
                status, body_data = client.uid("fetch", uid, "(BODY.PEEK[])")
                if status != "OK" or not body_data or body_data[0] is None:
                    continue
                raw = body_data[0][1] if isinstance(body_data[0], tuple) else b""
                if not raw:
                    continue
                out.append({
                    "uid": uid.decode("ascii", errors="replace"),
                    "from_address": sender_addr,
                    "subject": _decode_header_value(head_msg.get("Subject")),
                    "raw": raw,
                })
            return out
        except (imaplib.IMAP4.error, OSError, TimeoutError) as exc:
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

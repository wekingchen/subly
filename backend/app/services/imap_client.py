"""IMAP 邮件客户端：为信用卡账单邮件拉取提供连接测试与最近邮件预览。

仅支持内置预设服务商（126/qq），主机名不受用户配置控制，杜绝 SSRF 面。
标准库 imaplib 实现，用完即关（对齐 SMTP 出网先例），不做长连接/轮询。
"""
import email.header
import imaplib
import logging
import re
import ssl
import threading
from email.utils import parseaddr

logger = logging.getLogger(__name__)

# 同步阻塞外部 IO：全局并发上限（手动路由与自动调度共用），
# 防止慢速 IMAP 占满工作线程池。
IMAP_SEMAPHORE = threading.Semaphore(2)

# 预设服务商：主机/端口固定，不暴露给用户配置
IMAP_PROVIDERS = {
    "126": {"host": "imap.126.com", "port": 993},
    "qq": {"host": "imap.qq.com", "port": 993},
}

IMAP_TIMEOUT_SECONDS = 20
MAX_SUBJECT_LENGTH = 120
# 多文件夹扫描资源预算：防止「命中文件夹数 × 每文件夹 200 封 × 单封 5MB」
# 的无上限内存累积（如 10 个归档类文件夹理论上可达数 GB）。
MAX_SCAN_FOLDERS = 5
MAX_TOTAL_BYTES = 50 * 1024 * 1024  # 全部正文合计上限 50MB

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


class ImapScanBudgetExceeded(RuntimeError):
    """候选邮件超过安全扫描预算，扫描不完整。

    不是连接失败（不继承 ImapConnectionError）：调用方应向用户报告
    「扫描不完整，请缩小范围」，而非伪装成「未找到」或连接故障。
    """


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


def _date_sort_key(date_str: str):
    """邮件 Date 头 → 可比较排序键（解析失败/缺失排最后）。"""
    from datetime import datetime, timezone
    from email.utils import parsedate_to_datetime

    try:
        dt = parsedate_to_datetime(date_str)
        if dt is None:
            return datetime.min.replace(tzinfo=timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)


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
    today=None,
) -> list[dict]:
    """拉取最近 N 天邮件头部（不取正文），按 UID 倒序返回最多 limit 封。

    扫描 INBOX 及归档/订阅类文件夹（银行账单常被 QQ 自动分拣出 INBOX）。
    predicate(from_name, from_address) -> bool：可选过滤器（如账单银行白名单）。
    limit 指过滤后的命中数上限：按 UID 倒序最多扫描 max_scan 封头部，
    命中累计到 limit 即停，避免白名单邮件被无关邮件挤出截断窗口而漏掉。
    只返回 uid/from/subject/date 预览字段，邮件内容不落库。
    """
    from datetime import date, timedelta

    host = provider_host(provider)
    if today is None:
        today = date.today()  # 业务日期可由调用方传入（自动轮询保持时区一致）
    since = (today - timedelta(days=days)).strftime("%d-%b-%Y")
    # SEARCH 条目不用外层括号：QQ 邮箱对 (SINCE "…" …) 括号形态静默忽略日期
    # 条件返回全量邮箱（生产实测 10551 封），无括号形态才生效（生产实测 33 封）。
    # imaplib 可变参数会按 IMAP 协议逐 token 拼接，效果即无括号多条件。
    search_args = ("SINCE", since)
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
            messages = []
            seen_keys: set[str] = set()  # 跨文件夹去重（folder+uid）
            scanned_any = False  # 至少一个文件夹完成 SELECT+SEARCH
            for folder in _list_scan_folders(client):
                try:
                    status, _ = client.select(f'"{folder}"', readonly=True)
                except (imaplib.IMAP4.error, OSError, TimeoutError) as exc:
                    raise ImapConnectionError(type(exc).__name__) from exc
                if status != "OK":
                    continue
                status, data = client.uid("search", None, *search_args)
                if status != "OK":
                    continue
                scanned_any = True
                uids = sorted((data[0] or b"").split(), key=lambda u: int(u), reverse=True)
                # 倒序扫描（文件夹内 UID 新的在前）。不在此处提前 return——
                # 先收集所有文件夹的候选再全局截断，否则 INBOX 旧邮件会把
                # 归档文件夹里的新账单挤掉（审核修复：全局「最近」语义）。
                for uid in uids[:max_scan]:
                    key = f"{folder}:{uid.decode('ascii', errors='replace')}"
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
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
                        "folder": folder,
                        "from": sender_name,
                        "from_address": sender_addr,
                        "subject": _decode_header_value(msg.get("Subject")) or "（无主题）",
                        "date": _decode_header_value(msg.get("Date")),
                    })
            if not scanned_any:
                # 失败要响亮：所有文件夹都无法 SELECT/SEARCH（如 Unsafe Login、
                # 权限拒绝）不能伪装成「成功但没有邮件」
                raise ImapConnectionError("select-failed")
            # 全局按邮件日期倒序（Date 头解析失败的排最后），再截断 limit
            messages.sort(key=lambda m: _date_sort_key(m["date"]), reverse=True)
            return messages[:limit]
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


def _imap_utf7_decode(s: str) -> str:
    """RFC 3501 修改 UTF-7 解码（'&...-' 段是替换 ','→'/' 的 Base64 UTF-16BE）。

    Python 标准库没有 imap4-utf-7 codec；QQ 等服务商的中文文件夹名用此编码。
    解码失败时原样返回（关键词匹配退化为 ASCII 名）。
    """
    import base64

    out: list[str] = []
    i = 0
    while i < len(s):
        if s[i] == "&":
            j = s.find("-", i)
            if j == -1:
                out.append(s[i:])
                break
            chunk = s[i + 1:j]
            if not chunk:
                out.append("&")
            else:
                b64 = chunk.replace(",", "/")
                b64 += "=" * (-len(b64) % 4)
                try:
                    out.append(base64.b64decode(b64).decode("utf-16-be"))
                except Exception:  # noqa: BLE001
                    out.append(s[i:j])
            i = j + 1
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def _list_scan_folders(client) -> list[str]:
    """发现应扫描的文件夹：INBOX + 名称含归档/订阅/广告/archive 的文件夹。

    QQ 邮箱会把银行账单自动分拣进「邮件归档」「订阅邮件」等分类文件夹，
    INBOX 里看不到。用 LIST 动态发现（各家命名不同，不硬编码），
    跳过垃圾箱/已发送/草稿。文件夹名按 RFC 3501 修改 UTF-7 解码后匹配。
    """
    folders = ["INBOX"]
    try:
        status, data = client.list()
        if status != "OK" or not data:
            return folders
        # LIST 行形如 b'(\\HasNoChildren) "/" "Other Users/邮件归档"'
        # 或 b'(\\HasNoChildren) "." &XfJT0ZAB-...' （修改 UTF-7 编码名）
        for line in data:
            if not isinstance(line, bytes):
                continue
            m = re.match(rb'^\((?:[^)]*)\)\s+"?([^"]+)"?\s+(.+)$', line)
            if not m:
                continue
            name = m[2].strip()
            if name.startswith(b'"') and name.endswith(b'"'):
                name = name[1:-1]
            raw_name = name.decode("utf-8", errors="replace")
            folder = _imap_utf7_decode(raw_name)
            if not folder or folder.upper() == "INBOX":
                continue
            upper = folder.upper()
            skip_words = ("TRASH", "DELETE", "SPAM", "JUNK", "SENT", "DRAFT", "垃圾", "已删除", "已发送", "草稿")
            if any(w in upper for w in skip_words):
                continue
            hit_words = ("归档", "订阅", "广告", "ARCHIVE", "SUBSCRIPTION", "PROMOTION")
            if any(w in folder.upper() or w in folder for w in hit_words):
                # SELECT 时用原始名（服务器认的是编码后的名字）
                folders.append(raw_name)
    except (imaplib.IMAP4.error, OSError, TimeoutError, AttributeError):
        pass  # LIST 失败退化为只扫 INBOX
    return folders


def fetch_full_mime(
    email: str,
    password: str,
    provider: str,
    days: int,
    predicate=None,
    max_scan: int = 200,
    max_message_bytes: int = 5 * 1024 * 1024,
    max_total_bytes: int = MAX_TOTAL_BYTES,
    today=None,
    before=None,
    max_header_scan: int = 2000,
) -> list[dict]:
    """拉取最近 N 天**完整邮件**（含正文），供账单解析。

    扫描 INBOX 及归档/订阅类文件夹（银行账单常被 QQ 自动分拣出 INBOX）。
    predicate(from_address) -> bool 过滤发件人（账单银行白名单）。
    before 传入日期时搜索区间收窄为 [today−days, before)——历史账单
    补拉按月分段用（只有 SINCE 下界时无法排除当前邮件占用扫描名额）。
    区间查询（before 有值）不受 max_scan 截断——生产实测（建行 2025-11
    历史补拉）收件箱邮件量远超 200 后，历史账单按 UID 倒序根本进不了
    扫描窗口，全部「未找到」；但头部扫描有 max_header_scan 上限兜底，
    超限抛 ImapScanBudgetExceeded（区间内营销/订阅邮件可适数千封，
    逐封头部 FETCH 不能无界），由调用方把「扫描不完整」响亮转达，
    不得伪装成「未找到」。
    返回 [{uid, from_address, subject, raw(bytes)}]；单封超过
    max_message_bytes 直接跳过（防止异常大邮件撑爆内存）。
    """
    from datetime import date, timedelta

    host = provider_host(provider)
    if today is None:
        today = date.today()  # 业务日期可由调用方传入（自动轮询保持时区一致）
    since = (today - timedelta(days=days)).strftime("%d-%b-%Y")
    # SEARCH 条目不用外层括号：QQ 邮箱对 (SINCE "…" BEFORE "…") 括号形态
    # 静默忽略日期条件、返回全量邮箱（生产实测 INBOX 10551 封），
    # 无括号形态才生效（同邮箱同窗口实测 33 封）。逐 token 传参由
    # imaplib 按协议拼接，即无括号多条件形态。
    search_args = ["SINCE", since]
    if before is not None:
        search_args += ["BEFORE", before.strftime("%d-%b-%Y")]
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
            out: list[dict] = []
            seen_message_ids: set[str] = set()
            scanned_any = False
            total_bytes = 0  # 全局正文字节预算（跨文件夹累计）
            # 头部扫描超限跨文件夹累计：早文件夹超限的状态不能被后续空文件夹覆盖（复核 Medium）
            truncated_any = False
            folders_scanned = _list_scan_folders(client)[:MAX_SCAN_FOLDERS]
            for folder in folders_scanned:
                try:
                    status, _ = client.select(f'"{folder}"', readonly=True)
                except (imaplib.IMAP4.error, OSError, TimeoutError) as exc:
                    raise ImapConnectionError(type(exc).__name__) from exc
                if status != "OK":
                    continue  # 文件夹打不开（权限/不存在）→ 跳过，不阻断其他文件夹
                status, data = client.uid("search", None, *search_args)
                if status != "OK":
                    continue
                scanned_any = True
                uids = sorted((data[0] or b"").split(), key=lambda u: int(u), reverse=True)
                # max_scan 只为「开放式最近搜索」设防：生产实测（建行 2025-11 历史补拉）
                # 收件箱邮件量早已超过 200，历史账单按 UID 倒序根本进不了扫描窗口，
                # 全部「未找到」。带 BEFORE 上界的区间查询候选量受区间本身限制，
                # 截断反而丢数据——有上界时不截断，改用 max_header_scan 兜底：
                # 区间内营销/订阅邮件可适数千封，逐封头部 FETCH 不能无界（复核 Medium）。
                # 开放式查询超 200 保持旧行为：安静扫描最新 200 封并返回。
                if before is not None:
                    scan_limit = max_header_scan
                    folder_truncated = len(uids) > scan_limit
                    if folder_truncated:
                        logger.warning(
                            "event=imap_header_scan_budget_exceeded total_uids=%d limit=%d folder=%s",
                            len(uids), scan_limit, folder,
                        )
                    truncated_any = truncated_any or folder_truncated
                else:
                    scan_limit = max_scan
                # 两阶段拉取：先取头部+大小（发件人过滤与大小判断都不需要正文），
                # 只对通过筛选的邮件下载完整 BODY——避免把大附件/无关邮件整个
                # 拉进内存后才丢弃（审核修复：资源保护必须发生在下载之前）。
                # 头部按批获取（逗号分隔的精确 UID 列表，一次往返最多 50 封）：
                # 逐封串行在数千封邮箱上会产生数千次网络往返（生产实测 QQ 邮箱
                # 8625 封补拉超时断连，且长期占用全局信号量令后续请求 503）。
                # 不用 lo:hi 区间——候选稀疏时区间会扩张成全量（候选 14000,1 的
                # 区间 1:14000 会拉回一万多封），恰好重新引入超时（复核 Medium）。
                import email as _email

                BATCH = 50
                FETCH_HEADS_MACRO = "(BODY.PEEK[HEADER] RFC822.SIZE)"
                scan_target = uids[:scan_limit] if scan_limit is not None else uids

                def _parse_fetch_uid(meta: bytes):
                    """从 FETCH 记录元数据提取 UID；UID 无论在 literal 前缀还是
                    后随 trailer 里都能命中（属性顺序服务器自定，复核 Medium）。"""
                    mu = re.search(rb"UID\s+(\d+)", meta)
                    return mu[1] if mu else None

                def _parse_batch_headers(head_batch) -> dict:
                    """批量 FETCH 响应 → {uid: (头部literal, RFC822.SIZE)}。
                    literal 前缀（tuple[0]）与紧随的 trailer 行（bytes 项）合并
                    后再解析，不假设 UID 出现在 literal 之前。"""
                    headers: dict[bytes, tuple[bytes, int]] = {}
                    items = head_batch or []
                    i = 0
                    while i < len(items):
                        item = items[i]
                        if not isinstance(item, tuple) or len(item) < 2:
                            i += 1
                            continue
                        trailer = b""
                        if i + 1 < len(items) and isinstance(items[i + 1], bytes):
                            trailer = items[i + 1]
                            i += 1
                        uid_b = _parse_fetch_uid(item[0] + trailer)
                        if uid_b is not None:
                            msize = re.search(rb"RFC822.SIZE\s+(\d+)", item[0] + trailer)
                            headers[uid_b] = (item[1], int(msize[1]) if msize else 0)
                        i += 1
                    return headers

                def _fetch_single_header(uid_b: bytes):
                    """逐封头部获取（批量 NO 的降级路径）。复用批量解析——
                    UID/SIZE 同样可能位于 literal 之后的 trailer（复核 Medium），
                    否则降级路径在合法响应排列下仍会丢信或漏判大小。"""
                    status, head_data = client.uid("fetch", uid_b, FETCH_HEADS_MACRO)
                    if status != "OK" or not head_data:
                        return None
                    parsed = _parse_batch_headers(head_data)
                    return parsed.get(uid_b)

                # 只保留解析后的小字段，不跨批缓存原始头部 literal——
                # 2000 封大头部全部驻留内存可致进程 OOM（复核 Medium）。
                head_info: dict[bytes, tuple[str, str, str, int]] = {}
                for i in range(0, len(scan_target), BATCH):
                    batch = scan_target[i:i + BATCH]
                    status, head_batch = client.uid("fetch", b",".join(batch), FETCH_HEADS_MACRO)
                    if status == "OK":
                        batch_headers = _parse_batch_headers(head_batch)
                    else:
                        # NO：响亮降级为逐封重试（旧版单封语义），不得把整批
                        # 50 封静默丢弃后伪装成「未找到」（复核 Medium；BAD
                        # 已由 imaplib 直接抛出，走外层连接错误转换）
                        logger.warning(
                            "event=imap_batch_fetch_degraded status=%s batch_size=%d",
                            status, len(batch),
                        )
                        batch_headers = {}
                        for uid_b in batch:
                            got = _fetch_single_header(uid_b)
                            if got is not None:
                                batch_headers[uid_b] = got
                    for uid_b, (literal, size_int) in batch_headers.items():
                        head_msg = _email.message_from_bytes(literal)
                        _, sender_addr = _parse_from(head_msg.get("From"))
                        mid = str(head_msg.get("Message-ID") or "").strip()
                        subject = _decode_header_value(head_msg.get("Subject"))
                        head_info[uid_b] = (sender_addr, mid, subject, size_int)
                for uid in scan_target:
                    if total_bytes >= max_total_bytes:
                        logger.warning(
                            "event=imap_fetch_budget_exhausted total_bytes=%d",
                            total_bytes,
                        )
                        if before is not None:
                            # 区间查询预算耗尽=扫描不完整：直接抛，不得伪装成
                            # 「未找到」（复核 Medium——置标记后 return 仍会被
                            # 上层当成完整结果）
                            raise ImapScanBudgetExceeded()
                        return out  # 开放式查询保持原行为：安静返回部分结果
                    info = head_info.get(uid)
                    if info is None:
                        continue
                    sender_addr, mid, subject, size_int = info
                    if size_int > max_message_bytes:
                        continue  # 超限：不下载正文
                    if predicate is not None and not predicate(sender_addr):
                        continue  # 发件人过滤（银行白名单/补拉目标银行）——
                        # 必须在正文下载之前：无关邮件既不该进结果，
                        # 也不该消耗正文预算（复核 High）
                    # 跨文件夹去重（同一封邮件可能被 QQ 复制进多个文件夹）：
                    # Message-ID 全局唯一，比 UID 稳定（UID 每文件夹独立编号）。
                    # 只在正文成功取得后才标记已见——首副本下载失败时仍可从
                    # 其他文件夹的副本补拉（审核修复：过早标记会漏掉唯一可用副本）。
                    if mid and mid in seen_message_ids:
                        continue
                    status, body_data = client.uid("fetch", uid, "(BODY.PEEK[])")
                    if status != "OK" or not body_data or body_data[0] is None:
                        continue
                    raw = body_data[0][1] if isinstance(body_data[0], tuple) else b""
                    if not raw:
                        continue
                    if mid:
                        seen_message_ids.add(mid)
                    total_bytes += len(raw)
                    out.append({
                        "uid": uid.decode("ascii", errors="replace"),
                        "from_address": sender_addr,
                        "subject": subject,
                        "raw": raw,
                    })
            if not scanned_any:
                # 失败要响亮：所有文件夹都无法 SELECT/SEARCH 不能伪装成
                # 「成功但没有邮件」（Unsafe Login / 权限拒绝等）
                raise ImapConnectionError("select-failed")
            if truncated_any:
                # 响亮：扫描不完整不能伪装成「未找到」（复核 Medium——
                # 调用方据此向用户报告「候选邮件过多，请缩小范围」）
                raise ImapScanBudgetExceeded()
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

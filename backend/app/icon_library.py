"""内置常见商家清单：用于服务名联想 + 图标库。

图标按需从公共 favicon 服务下载并缓存到本地 data/icons/library/，
之后由本地静态目录提供，不依赖外网。
"""
from sqlalchemy import func, select

# 分类 key -> 显示标签（用于「按分类浏览」服务库）
CATEGORY_LABELS = [
    ("streaming", "流媒体 / Streaming"),
    ("music", "音乐 / Music"),
    ("ai", "AI 服务 / AI"),
    ("gaming", "游戏 / Gaming"),
    ("vps", "VPS / 服务器"),
    ("carrier", "电信运营商 / Carrier"),
    ("cloud", "云存储 / Cloud"),
    ("software", "软件 / Software"),
    ("domain", "域名 / Domain"),
    ("education", "教育 / Education"),
    ("news", "新闻 / News"),
    ("fitness", "健身 / Fitness"),
    ("membership", "会员 / Membership"),
]

# (显示名, 域名, 分类key)
SERVICES = [
    # 流媒体 streaming
    ("Netflix", "netflix.com", "streaming"),
    ("Disney+", "disneyplus.com", "streaming"),
    ("YouTube Premium", "youtube.com", "streaming"),
    ("HBO Max", "max.com", "streaming"),
    ("Prime Video", "primevideo.com", "streaming"),
    ("Hulu", "hulu.com", "streaming"),
    ("Apple TV+", "tv.apple.com", "streaming"),
    ("Paramount+", "paramountplus.com", "streaming"),
    ("Peacock", "peacocktv.com", "streaming"),
    ("Crunchyroll", "crunchyroll.com", "streaming"),
    ("DAZN", "dazn.com", "streaming"),
    ("Viu", "viu.com", "streaming"),
    ("bilibili", "bilibili.com", "streaming"),
    ("爱奇艺 iQIYI", "iqiyi.com", "streaming"),
    ("腾讯视频", "v.qq.com", "streaming"),
    ("优酷 Youku", "youku.com", "streaming"),
    ("芒果TV", "mgtv.com", "streaming"),
    # 音乐 music
    ("Spotify", "spotify.com", "music"),
    ("Apple Music", "music.apple.com", "music"),
    ("YouTube Music", "music.youtube.com", "music"),
    ("Amazon Music", "music.amazon.com", "music"),
    ("Tidal", "tidal.com", "music"),
    ("Deezer", "deezer.com", "music"),
    ("Qobuz", "qobuz.com", "music"),
    ("SoundCloud", "soundcloud.com", "music"),
    ("网易云音乐", "music.163.com", "music"),
    ("QQ音乐", "y.qq.com", "music"),
    # AI
    ("ChatGPT", "openai.com", "ai"),
    ("Claude", "claude.ai", "ai"),
    ("Google Gemini", "gemini.google.com", "ai"),
    ("Perplexity", "perplexity.ai", "ai"),
    ("Midjourney", "midjourney.com", "ai"),
    ("GitHub Copilot", "github.com", "ai"),
    ("Cursor", "cursor.com", "ai"),
    ("Grok", "x.ai", "ai"),
    ("Poe", "poe.com", "ai"),
    ("Mistral AI", "mistral.ai", "ai"),
    ("DeepSeek", "deepseek.com", "ai"),
    ("Suno", "suno.com", "ai"),
    ("ElevenLabs", "elevenlabs.io", "ai"),
    ("Runway", "runwayml.com", "ai"),
    ("文心一言", "yiyan.baidu.com", "ai"),
    ("通义千问", "tongyi.aliyun.com", "ai"),
    ("Kimi", "kimi.moonshot.cn", "ai"),
    # 游戏 gaming
    ("Steam", "steampowered.com", "gaming"),
    ("Epic Games", "epicgames.com", "gaming"),
    ("PlayStation Plus", "playstation.com", "gaming"),
    ("Xbox Game Pass", "xbox.com", "gaming"),
    ("Nintendo Switch Online", "nintendo.com", "gaming"),
    ("EA Play", "ea.com", "gaming"),
    ("Ubisoft+", "ubisoft.com", "gaming"),
    ("GeForce NOW", "nvidia.com", "gaming"),
    ("Apple Arcade", "apple.com", "gaming"),
    # VPS / 云（含主流大厂与 LowEnd 低价商家）
    ("AWS", "aws.amazon.com", "vps"),
    ("Google Cloud", "cloud.google.com", "vps"),
    ("Microsoft Azure", "azure.microsoft.com", "vps"),
    ("Oracle Cloud", "oracle.com", "vps"),
    ("DigitalOcean", "digitalocean.com", "vps"),
    ("Vultr", "vultr.com", "vps"),
    ("Linode / Akamai", "linode.com", "vps"),
    ("Hetzner", "hetzner.com", "vps"),
    ("Contabo", "contabo.com", "vps"),
    ("OVHcloud", "ovhcloud.com", "vps"),
    ("Scaleway", "scaleway.com", "vps"),
    ("UpCloud", "upcloud.com", "vps"),
    ("Gcore", "gcore.com", "vps"),
    ("IONOS", "ionos.com", "vps"),
    ("Kamatera", "kamatera.com", "vps"),
    ("Fly.io", "fly.io", "vps"),
    ("Railway", "railway.app", "vps"),
    ("Render", "render.com", "vps"),
    ("Hostinger", "hostinger.com", "vps"),
    ("Hostwinds", "hostwinds.com", "vps"),
    # LowEnd / 低价 VPS 圈常见商家
    ("DMIT", "dmit.io", "vps"),
    ("RackNerd", "racknerd.com", "vps"),
    ("BandwagonHost 搬瓦工", "bandwagonhost.com", "vps"),
    ("BuyVM / Frantech", "buyvm.net", "vps"),
    ("CloudCone", "cloudcone.com", "vps"),
    ("GreenCloud", "greencloudvps.com", "vps"),
    ("HostHatch", "hosthatch.com", "vps"),
    ("Netcup", "netcup.de", "vps"),
    ("VirMach", "virmach.com", "vps"),
    ("HostDare", "hostdare.com", "vps"),
    ("Hostodo", "hostodo.com", "vps"),
    ("RamNode", "ramnode.com", "vps"),
    ("Spartan Host", "spartanhost.net", "vps"),
    ("AlphaVPS", "alphavps.com", "vps"),
    ("Servarica", "servarica.com", "vps"),
    ("Crunchbits", "crunchbits.com", "vps"),
    ("WebHorizon", "webhorizon.net", "vps"),
    ("Misaka", "misaka.io", "vps"),
    ("ZGOVPS", "zgovps.com", "vps"),
    ("V.PS", "v.ps", "vps"),
    ("LisaHost 丽萨主机", "lisahost.com", "vps"),
    ("Cloudie / 莱卡云", "lcayun.com", "vps"),
    ("雨云 RainYun", "rainyun.com", "vps"),
    ("阿里云", "aliyun.com", "vps"),
    ("腾讯云", "cloud.tencent.com", "vps"),
    ("华为云", "huaweicloud.com", "vps"),
    ("UCloud", "ucloud.cn", "vps"),
    # 电信运营商 carrier
    ("VOXI", "voxi.co.uk", "carrier"),
    ("Vodafone", "vodafone.com", "carrier"),
    ("giffgaff", "giffgaff.com", "carrier"),
    ("EE", "ee.co.uk", "carrier"),
    ("O2", "o2.co.uk", "carrier"),
    ("Three", "three.co.uk", "carrier"),
    ("SMARTY", "smarty.co.uk", "carrier"),
    ("Tesco Mobile", "tescomobile.com", "carrier"),
    ("iD Mobile", "idmobile.co.uk", "carrier"),
    ("1pMobile", "1pmobile.com", "carrier"),
    ("Lebara", "lebara.com", "carrier"),
    ("Lycamobile", "lycamobile.com", "carrier"),
    ("T-Mobile", "t-mobile.com", "carrier"),
    ("AT&T", "att.com", "carrier"),
    ("Verizon", "verizon.com", "carrier"),
    ("Mint Mobile", "mintmobile.com", "carrier"),
    ("Visible", "visible.com", "carrier"),
    ("US Mobile", "usmobile.com", "carrier"),
    ("Ultra Mobile", "ultramobile.com", "carrier"),
    ("Google Fi", "fi.google.com", "carrier"),
    ("中国移动", "10086.cn", "carrier"),
    ("中国联通", "10010.com", "carrier"),
    ("中国电信", "189.cn", "carrier"),
    # 云存储 cloud
    ("Google One", "one.google.com", "cloud"),
    ("iCloud+", "icloud.com", "cloud"),
    ("Dropbox", "dropbox.com", "cloud"),
    ("OneDrive", "onedrive.live.com", "cloud"),
    ("MEGA", "mega.nz", "cloud"),
    ("pCloud", "pcloud.com", "cloud"),
    ("Backblaze", "backblaze.com", "cloud"),
    ("Box", "box.com", "cloud"),
    ("百度网盘", "pan.baidu.com", "cloud"),
    # 软件 software
    ("Microsoft 365", "microsoft.com", "software"),
    ("Adobe Creative Cloud", "adobe.com", "software"),
    ("Notion", "notion.so", "software"),
    ("1Password", "1password.com", "software"),
    ("Bitwarden", "bitwarden.com", "software"),
    ("JetBrains", "jetbrains.com", "software"),
    ("Figma", "figma.com", "software"),
    ("Canva", "canva.com", "software"),
    ("Grammarly", "grammarly.com", "software"),
    ("Zoom", "zoom.us", "software"),
    ("Setapp", "setapp.com", "software"),
    ("Todoist", "todoist.com", "software"),
    # 域名 domain
    ("Cloudflare", "cloudflare.com", "domain"),
    ("Namecheap", "namecheap.com", "domain"),
    ("GoDaddy", "godaddy.com", "domain"),
    ("Porkbun", "porkbun.com", "domain"),
    ("Dynadot", "dynadot.com", "domain"),
    ("Gandi", "gandi.net", "domain"),
    # 教育 education
    ("Coursera", "coursera.org", "education"),
    ("Udemy", "udemy.com", "education"),
    ("Duolingo", "duolingo.com", "education"),
    ("MasterClass", "masterclass.com", "education"),
    ("Skillshare", "skillshare.com", "education"),
    ("Brilliant", "brilliant.org", "education"),
    ("LinkedIn Learning", "linkedin.com", "education"),
    # 新闻 news
    ("Medium", "medium.com", "news"),
    ("The New York Times", "nytimes.com", "news"),
    ("The Wall Street Journal", "wsj.com", "news"),
    ("The Economist", "economist.com", "news"),
    ("Bloomberg", "bloomberg.com", "news"),
    # 健身 fitness
    ("Strava", "strava.com", "fitness"),
    ("Peloton", "onepeloton.com", "fitness"),
    ("MyFitnessPal", "myfitnesspal.com", "fitness"),
    ("Whoop", "whoop.com", "fitness"),
    # 会员 membership
    ("Amazon Prime", "amazon.com", "membership"),
    ("Costco", "costco.com", "membership"),
    ("Patreon", "patreon.com", "membership"),
    ("Sam's Club", "samsclub.com", "membership"),
]


def _slug(domain: str) -> str:
    return domain.replace(".", "_").replace("/", "_")


def slug_for_domain(domain: str) -> str:
    """对外公开的 slug 生成规则（与 _slug 一致，供 seed/admin 复用）。"""
    return _slug(domain)


def _strip_icon_ext(slug: str) -> str:
    safe = (slug or "").strip()
    for ext in (".png", ".svg", ".ico", ".webp", ".jpg", ".jpeg"):
        if safe.endswith(ext):
            return safe[: -len(ext)]
    return safe


_CAT_LABEL_MAP = dict(CATEGORY_LABELS)


def categories() -> list[dict]:
    """返回服务库分类清单（用于「按分类浏览」服务）。"""
    return [{"key": k, "label": v} for k, v in CATEGORY_LABELS]


def category_label(key: str) -> str:
    return _CAT_LABEL_MAP.get(key, key)


def _row_to_manifest(row) -> dict:
    slug = row.slug
    return {
        "name": row.name,
        "domain": row.domain,
        "website": row.website or f"https://{row.domain}",
        "category": row.category,
        "category_label": _CAT_LABEL_MAP.get(row.category, row.category),
        "slug": slug,
        # 前端通过该地址取图标（首次访问会触发本地缓存）
        "icon": f"/api/icons/library/{slug}.png",
    }


def manifest(db) -> list[dict]:
    """返回图标库清单（仅启用项）。数据来源已迁移到 DB。"""
    from app.models import IconLibraryService

    rows = db.scalars(
        select(IconLibraryService)
        .where(IconLibraryService.is_active.is_(True))
        .order_by(IconLibraryService.sort, IconLibraryService.id)
    ).all()
    return [_row_to_manifest(r) for r in rows]


def website_for_name(db, name: str) -> str | None:
    """按服务名（精确/包含）匹配官方网站，用于创建订阅时自动补全。只查启用项。"""
    if not name:
        return None
    from app.models import IconLibraryService

    q = name.strip().lower()
    row = db.scalar(
        select(IconLibraryService)
        .where(IconLibraryService.is_active.is_(True))
        .where(func.lower(IconLibraryService.name) == q)
    )
    if row:
        return row.website or f"https://{row.domain}"
    rows = db.scalars(
        select(IconLibraryService)
        .where(IconLibraryService.is_active.is_(True))
        .order_by(IconLibraryService.sort, IconLibraryService.id)
    ).all()
    for r in rows:
        name_l = (r.name or "").lower()
        if q and (q in name_l or name_l in q):
            return r.website or f"https://{r.domain}"
    return None


def service_for_slug(db, slug: str, include_inactive: bool = True) -> dict | None:
    """按图标 slug 查找服务信息，供后端下载和 fallback 使用。

    默认包含停用项，确保旧订阅保存的图标 URL 仍能解析。
    """
    from app.models import IconLibraryService

    target = _strip_icon_ext(slug)
    stmt = select(IconLibraryService).where(IconLibraryService.slug == target)
    if not include_inactive:
        stmt = stmt.where(IconLibraryService.is_active.is_(True))
    row = db.scalar(stmt)
    if not row:
        return None
    return {
        "name": row.name,
        "domain": row.domain,
        "category": row.category,
        "slug": row.slug,
        "website": row.website or f"https://{row.domain}",
    }


def domain_for_slug(db, slug: str) -> str | None:
    service = service_for_slug(db, slug)
    return service["domain"] if service else None


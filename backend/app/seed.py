"""首次启动时写入系统预置数据：货币、分类、付款方式、管理员账户。"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import icon_library
from app.config import settings, validate_initial_admin_password
from app.models import Category, Currency, IconLibraryService, User
from app.security import hash_password

# 全球常用流通货币
CURRENCIES = [
    ("USD", "美元 US Dollar", "$"),
    ("CNY", "人民币 Chinese Yuan", "¥"),
    ("EUR", "欧元 Euro", "€"),
    ("GBP", "英镑 British Pound", "£"),
    ("JPY", "日元 Japanese Yen", "¥"),
    ("RUB", "卢布 Russian Ruble", "₽"),
    ("HKD", "港币 Hong Kong Dollar", "HK$"),
    ("TWD", "新台币 Taiwan Dollar", "NT$"),
    ("KRW", "韩元 Korean Won", "₩"),
    ("SGD", "新加坡元 Singapore Dollar", "S$"),
    ("AUD", "澳元 Australian Dollar", "A$"),
    ("CAD", "加元 Canadian Dollar", "C$"),
    ("CHF", "瑞士法郎 Swiss Franc", "Fr"),
    ("INR", "印度卢比 Indian Rupee", "₹"),
    ("BRL", "巴西雷亚尔 Brazilian Real", "R$"),
    ("THB", "泰铢 Thai Baht", "฿"),
    ("MYR", "马来西亚林吉特 Malaysian Ringgit", "RM"),
    ("PHP", "菲律宾比索 Philippine Peso", "₱"),
    ("IDR", "印尼盾 Indonesian Rupiah", "Rp"),
    ("TRY", "土耳其里拉 Turkish Lira", "₺"),
    ("AED", "阿联酋迪拉姆 UAE Dirham", "د.إ"),
]

# 订阅分类（流媒体 / AI / 游戏 / VPS 等）
CATEGORIES = [
    ("流媒体 / Streaming", "📺", "#e50914"),
    ("AI 服务 / AI", "🤖", "#10a37f"),
    ("游戏 / Gaming", "🎮", "#107c10"),
    ("VPS / 服务器", "🖥️", "#0078d4"),
    ("电信运营商 / Carrier (SIM 保号)", "📱", "#e60000"),
    ("软件 / Software", "🧩", "#5b6ee1"),
    ("音乐 / Music", "🎵", "#1db954"),
    ("云存储 / Cloud", "☁️", "#4285f4"),
    ("域名 / Domain", "🌐", "#f59e0b"),
    ("会员 / Membership", "💳", "#9333ea"),
    ("教育 / Education", "📚", "#0ea5e9"),
    ("新闻 / News", "📰", "#374151"),
    ("健身 / Fitness", "💪", "#ef4444"),
    ("其它 / Other", "📦", "#6b7280"),
]

# 付款方式
PAYMENT_METHODS = [
    ("信用卡 / Credit Card", "💳"),
    ("借记卡 / Debit Card", "🏦"),
    ("Apple Pay", "🍎"),
    ("Google Pay", "🅖"),
    ("支付宝 / Alipay", "🅰️"),
    ("微信支付 / WeChat Pay", "💬"),
    ("PayPal", "🅿️"),
    ("银行转账 / Bank Transfer", "🏛️"),
    ("加密货币 / Crypto", "₿"),
]


def seed_all(db: Session) -> None:
    if not db.scalar(select(Currency).limit(1)):
        for code, name, symbol in CURRENCIES:
            db.add(Currency(code=code, name=name, symbol=symbol, is_custom=False))

    existing_category_names = set(db.scalars(select(Category.name).where(Category.is_system.is_(True))).all())
    for i, (name, icon, color) in enumerate(CATEGORIES):
        if name not in existing_category_names:
            db.add(Category(name=name, icon=icon, color=color, is_system=True, sort=i))

    # 服务图标库：幂等导入内置服务（仅插入缺失 slug，不覆盖管理员改动）
    existing_slugs = set(db.scalars(select(IconLibraryService.slug)).all())
    for i, (name, domain, category_spec) in enumerate(icon_library.SERVICES):
        slug = icon_library.slug_for_domain(domain)
        if slug in existing_slugs:
            continue
        keys = icon_library.normalize_category_keys(category_spec)
        db.add(
            IconLibraryService(
                name=name,
                domain=domain,
                website=None,
                category=keys[0],
                category_keys=keys,
                slug=slug,
                is_active=True,
                sort=i,
                source="builtin",
            )
        )
    icon_library.backfill_builtin_category_keys(db)

    # 首个管理员：系统已有任意管理员时不再按环境变量补建，避免管理员改名后升级被阻断。
    admin_exists = db.scalar(select(User.id).where(User.is_admin.is_(True)).limit(1))
    if not admin_exists and settings.admin_username:
        username_exists = db.scalar(select(User.id).where(User.username == settings.admin_username))
        if username_exists:
            raise RuntimeError("ADMIN_USERNAME 已被非管理员账号占用，无法创建初始管理员")
        validate_initial_admin_password(settings.admin_password)
        db.add(
            User(
                username=settings.admin_username,
                email=settings.admin_email,
                password_hash=hash_password(settings.admin_password),
                is_admin=True,
            )
        )

    db.commit()

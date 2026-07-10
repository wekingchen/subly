# Changelog

所有项目的重要变更都会记录在此文件中。

项目采用 [Semantic Versioning](https://semver.org/lang/zh-CN/) 进行版本管理；当前 `main` 分支上的未发布整理统一记录在 `[Unreleased]`。

---

## [Unreleased]

### Added
- 新增发布前浏览器与静态检查基线：后端 Ruff 聚焦应用代码正确性，前端 ESLint 聚焦 JS/Vue 未定义与未使用符号；Chromium Playwright 针对构建后的 amd64 Docker 产物验证登录、HttpOnly Cookie 刷新恢复、旧 localStorage Token 一次性迁移、退出、CORS 与关键页面 CSP，任一失败都会阻断镜像发布。
- 新增管理员「数据诊断」页与 `/api/admin/diagnostics` 接口：可检查通知配置缺口、订阅脏数据、保号范围异常、一次性买断残留周期字段、孤儿通知日志和近 30 天失败通知；同时提供提醒 dry-run 模拟，复用 Bark / Telegram 文案构造但不真实外发、不写通知日志。
- 数据诊断新增一键修复（`POST /api/admin/diagnostics/repair`，仅管理员）：对有确定性正确目标值的问题（引用缺失 / 越权、保号越界、一次性买断残留周期字段、无效提醒天数、周期订阅缺续费日）支持点按钮直接修复，修复前重判防过期状态、修复后复核引用合法性；需人工判断的问题（通知配置缺口、负金额、非法周期、孤儿日志等）仍只报告。
- 订阅新增 `is_keepalive`（短信保号）标记：电信运营商分类下的周期订阅可标记为保号套餐，表单 / 续费弹窗 / Bark 与 Telegram 提醒 / 活动日志 / 卡片状态文案全链路按保号场景切换（保号日 / 已过保号日 / 今天保号 / 记得发条短信保号等）。续费推进日期、报表金额统计、提醒触发条件逻辑不变，仅切换文案；保号入口只在电信运营商分类显示，且必须 recurring（前端切一次性买断或切出电信运营商分类会自动清空 + 后端校验 recurring）。
- 订阅账本卡片重构为“信号卡 + 内联详情”：默认卡片聚焦服务身份 / 费用 / 到期风险与少量摘要 chip，点击卡片展开内联详情，分「身份与费用 / 风险与提醒 / 账务与归属」三块展示完整字段；同时只展开一张卡片，展开按钮支持键盘 Enter/Space。
- 订阅币种非基准货币时，卡片与详情显示 `amount_in_base` 的基准货币折合值，跨币种对账更直观。
- 内置服务库新增「智谱 GLM」（AI）与「火山引擎 / 豆包」（AI + VPS，因火山引擎同时提供豆包大模型与火山云服务器）。

### Fixed
- 修复发布镜像被 Starlette 高危 DoS 漏洞阻断：将 FastAPI 升级至 `0.133.1` 并显式固定已修复的 Starlette `1.3.1`，保留 Trivy 对可修复 High/Critical 项的发布硬门禁，不以忽略规则绕过；`pip-audit` 当前仅剩 ecdsa 无可用修复版本项。
- 浏览器会话与响应头安全收口：新前端不再把 Token 写入 `localStorage`，Access Token 仅驻留页面内存，Refresh Token 使用 `Path=/api/auth` 的 HttpOnly/SameSite Cookie，并以 `refresh_sessions.jti` 实现服务端一次性轮换：刷新原子消费旧 session，logout 撤销当前 session 后删除 Cookie，旧 token 重放返回 401；旧 localStorage Refresh Token 仅在 Cookie 401 后迁移一次（旧版无 jti token 用 SHA-256 指纹防重复消费），明确 401/403 才删除，网络/5xx 保留供下次重试；logout 网络失败时不清本地状态并提示重试，避免假退出。后端暂时保留 body/响应体 refresh token 兼容桥供旧页面迁移；移除 wildcard+credentials CORS，并为 SPA、API 文档和通用响应补 CSP、nosniff、Referrer、Frame、Permissions 安全头。
- 数据库结构迁移改为 fail-fast：旧库补必需列时若 DDL 失败，记录表/列上下文并终止启动，不再打印“跳过”后带着半迁移结构继续运行；缺表与已有列仍保持幂等跳过，历史数据回填/清理维持兼容告警策略。
- 认证安全闭环：登录、Refresh Token 与受保护接口统一检查邮箱验证、管理员审核和账号启用状态，撤销审核/禁用后旧 Access Token 与 Refresh Token 均立即失效；登录、注册和邮箱验证码入口新增线程安全的单进程滑动窗口限流并返回 `Retry-After`，默认 Caddy compose 信任其代理头以按真实客户端区分限流桶；启动时拒绝空值、占位值或过短的 `JWT_SECRET`，首次创建管理员时拒绝默认/弱密码（已有管理员不受环境变量旧值影响）；SMTP 验证码改为发送成功后再提交用户，失败不再留下占用用户名/邮箱的半注册账号，客户端错误不回显底层 SMTP 异常；验证码过期后可凭相同用户名、邮箱和原密码重新注册并签发新验证码，不再陷入唯一约束死锁。
- 提醒扫描并发互斥：`run_reminder_scan` 用非阻塞进程锁串行化，定时任务与手动 `/api/notifications/run-scan` 并发触发时，第二个直接返回 `skipped` 而非重复扫描；手动入口遇占用返回 409。此前两个扫描实例会因未提交日志互相不可见而重复外发通知。
- 图标与备份链路安全收口：`/api/icons/upload` 与 `/api/icons/from-url` 的 SVG 上传统一经白名单消毒（`_sanitize_svg_icon`，fail-closed），堵住同源 SVG 存储型 XSS 窃取 token；自定义服务 `domain` 写入前经 `_validate_icon_domain` 校验（接收原始输入，拒协议 / userinfo / 路径 / query / fragment，显式拒 `localhost`，字面 IP 与 DNS 解析后的地址都拦本机 / 私网 / 链路本地 / 元数据 / 非常规 IPv4 字面量）；favicon 与 `from-url` 抓取改为手动跟随重定向（`_safe_resolve`，`follow_redirects=False`），用 stream 只读响应头避免大文件在体积校验前被全量下载，每一跳 host 经 `resolves_to_internal` 校验字面 IP 与 DNS 解析结果后才发请求，堵住「公网 302 跳内网 / hostname 解析到内网」的 SSRF；`/api/icons/from-url` 最终下载也改为有界流式读取（`_read_limited`，超限即 400，不先缓冲全 body），防大文件内存 DoS；备份导出 `_collect_entities` 收紧为只导出本人或系统级分类 / 付款方式，不再把订阅越权引用到的他人私有元数据打包出去；备份导入在任何删除 / 写入前先做 `_validate_backup_payload` 全量校验（缺 `subscriptions`、缺 name、非法日期、`cycle_count`/`sort` 非整数、`amount` 非数字、`billing_type`/`cycle` 非法枚举、辅助集合元素非对象、`family_members` 元素非字符串均返回 400），整站恢复缺 `username` 的用户块改为报错而非静默跳过，避免「先清空再宽松导入」丢数据却返回成功。
- 出网 URL 校验收紧与 SSRF 收口：`validate_outbound_url` 禁止 query / fragment / userinfo（堵住 `telegram_api_base` 存成 `http://host?` 把 `/bot.../getMe` 拼进 query 的绕过），并归一化非常规 IPv4 字面量（十进制 `2852039166` / 十六进制等，socket 层会解析为 `169.254.169.254`）后再拦截链路本地与全零地址；path 仍允许以支持反代；`/api/icons/from-url`（可读型 SSRF：抓取任意 URL 并存成静态文件回读）改为仅管理员可用，前端订阅表单的「从 URL 导入图标」按钮同步仅管理员可见；启动迁移清理 `users` 表中历史的危险出网配置（不打印旧值，只记 user_id 与字段），不合法值置空并打告警；通知测试端点失败时 ActivityLog 不再写入含 Bot Token 的底层异常 URL，改记脱敏信息，`getMe` / `getUpdates` 失败补服务端日志。
- 通知路由收紧越权与 SSRF 风险：`/api/notifications/run-scan`（全站真实扫描 + 外发）改为仅管理员可触发，普通用户返回 403；Telegram / Bark 测试端点不再接受 `bot_token` / `server` 等 payload 覆盖，固定取用户已存配置，防止借后端做消息中继或 SSRF 探测内网；`/api/me` 写入 `telegram_api_base` / `telegram_proxy` / `bark_server` 时经 `validate_outbound_url` 校验，拦截链路本地（含云元数据 `169.254.169.254`）与危险协议（自托管本地代理 `127.0.0.1` 仍放行）；通知端点的 502 错误改为泛化提示，不再回显底层异常细节。
- 提醒扫描跳过禁用用户：`run_reminder_scan` 与提醒 dry-run 现在按 `User.is_active` 过滤，禁用用户的订阅即使到期、通道配置完整也不再收到提醒（此前扫描不检查用户启用状态）。
- 提醒扫描修复重复发送隐患：`run_reminder_scan` 与 dry-run 统一用 `_unique_days` 去重提醒天数；扫描内改用内存 `seen` 集合兜底去重（替代 `db.flush`，避免外发期间长持 SQLite 写锁拖垮其它写请求）。同日去重改为按本地日历日（`settings.tz` + `zoneinfo`）判定，避免 naive UTC 与本地日期混比导致凌晨跨日重复发送；诊断「近 30 天失败通知」统计同步改本地自然日。
- 订阅分类 / 付款方式 / 套餐包引用补归属校验：新增 `validate_subscription_refs`，创建与更新订阅时拒绝引用他人账户下的分类 / 付款方式 / 套餐包（系统级与本人引用仍放行）；更新时按最终值校验，历史脏数据借无关注册更新也无法继续存活。数据诊断相应新增 `category_not_owned` / `payment_method_not_owned` / `bundle_not_owned` 报告。
- `settings.tz` 配置非法时不再让进程启动崩溃：调度器初始化与触发统一经 `_local_zone()` 兜底为 UTC 并打 warning，而非直接把原始字符串传给 APScheduler。
- admin 路由守卫与登录刷新收敛清会话逻辑：网络抖动 / 5xx 不再强制登出（仅 401/403 才清退），首次导航失败重定向到 `/dashboard` 而非停在空白页；`refresh_token` 缺失或刷新失败时统一清退会话，避免 `access_token` 残留导致 `/login` ↔ `/dashboard` 跳转死循环。
- 数据诊断页提醒模拟运行期间禁用全部表单输入，避免结果与表单显示值不一致；诊断「提醒」筛选标签改为显式 code 白名单，不再按 scope 启发式误纳 / 漏报。
- 设置页汇率表的更新时间按容器 `TZ` / 系统时区显示：汇率接口现在返回带 UTC 标记的 `updated_at`，前端复用时区格式化工具显示完整日期时间。
- 全站弹窗（订阅页、内置服务管理新增/编辑/确认、用户管理新建/重置密码/删除确认）统一不再因点击遮罩而关闭：`AppModal` 默认 `persistent`，避免桌面端误触丢失输入；仍可经 ×、取消或确认按钮关闭。
- 续费日历按日 / 周 / 月 / 年周期展开续费事件，无 `end_date` 的订阅在后续月份持续出现；`end_date` 到期后停止；`show_in_calendar=false` 与一次性买断订阅不显示。
- 实时日志时间按容器 `TZ` / `settings.tz`（默认 `Asia/Shanghai`）显示：`/api/logs` 现在返回带 UTC 时区标记的 `created_at`，前端按系统时区格式化。

### Changed
- Docker 与发布链路加固：前端镜像构建只使用 `npm ci`，新增 `.dockerignore`，运行时切换为固定 UID/GID `10001` 的非 root 用户；PR 只运行后端/前端测试、lint、构建、Compose 与非阻塞依赖审计，main/tag/手动发布才构建 amd64/arm64 归档、执行 Trivy 可修复 High/Critical 门禁与 Chromium E2E；双架构发布归档只构建一次，扫描通过后直接推送同一批产物并组装 manifest，避免二次构建漂移；同一 ref 的旧发布会被并发取消以防旧构建回写 `latest`，手动发布仅允许从 `main` 运行；`v*` tag 必须指向 `main` 历史且只写版本 tag，不再用旧提交回滚 `latest`；pip/npm 审计失败改为 warning，避免成功 job 携带误导性的 error annotation；`actions/upload-artifact` 升至 v7、`actions/download-artifact` 升至 v8，清除旧 Action 的 Node.js 20 弃用告警。为遵守远端只保留 `main` 的仓库约束，移除 Dependabot 自动 version-update PR 配置，pip/npm/GitHub Actions/Docker 基础镜像升级统一人工规划，依赖风险继续由 audit 日志与发布产物 Trivy 覆盖。同步将 `python-jose` 升至 `3.5.0`、`python-multipart` 升至 `0.0.31`、`cryptography` 升至 `48.0.1`、FastAPI 升至 `0.133.1` 并固定 Starlette `1.3.1`。
- 图标抓取流式读取加 wall-clock deadline（单次读超时的 3 倍，下限 3 秒）：httpx 的 read timeout 只限单次读空闲，慢速分块响应可长期占住抓取并发，现超总时长即中止并记 provider failure 触发冷却（避免后续 slug 反复重试同一慢 provider）。
- 清理自有代码中已弃用的 `datetime.utcnow()`，改为 `datetime.now(timezone.utc)`（存 naive UTC 列时用 `.replace(tzinfo=None)` 保持一致），消除 DeprecationWarning；上游 jose / passlib 的弃用告警待其发版。
- README、Docker Hub、NAS 与技术文档统一项目名表述：正式名称使用 `Subly`，中文定位调整为“你的自托管续费雷达”。
- 桌面端订阅卡片动作区降权为更轻的续费雷达工具条，并补充「续费」仅更新记录与到期日、不触发付款的说明，避免误认为支付入口。
- 桌面端订阅卡片仅保留「续费」快捷操作，编辑与删除收进 `⋯` 菜单，降低低频 / 高危操作对卡片主体的干扰。
- 移动端 `⋯` 操作面板的续费入口改为「标记已续费」，并补充一行不触发付款的说明，避免误认为支付入口。
- 桌面端订阅卡片的 `⋯` 菜单改为靠近原卡片位置弹出（取代此前的全屏底部 sheet），移动端仍保留底部 sheet。
- 抽取共享周期日期工具 `utils/date.js`（`toISODate` / `addCycleDate`），订阅页与日历展开复用同一套周期推进逻辑，与后端 `billing.add_cycle` 语义对齐。
- 新增 `utils/recurrence.js` 与 `utils/time.js`：分别负责日历范围内的续费事件展开与按目标时区格式化时间。

---

## [2.1.0] - 2026-07-01（Subly）

> 在 2.0.0 内置 SQLite / Bark 双通道基础上，补齐多用户审核、管理页、备份恢复、实时日志、内置服务多分类与文档同步，并统一项目身份与版本号到 `2.1.0`。

### Added
- 新增 Bark 推送 TTL 设置：用户可在「设置 → Bark 配置」填写非负整数秒数，测试推送与定时提醒都会透传；留空继续使用 Bark 默认值，`0` 会被保留并显式发送。
- 新增注册审核与邮箱验证支持：可通过 `REQUIRE_ADMIN_APPROVAL` 控制新用户是否需要管理员审核；配置 `SMTP_*` 后注册流程可发送邮箱验证码。
- 新增管理员用户管理能力：审核注册用户、启用 / 禁用账号、授予 / 撤销管理员权限、重置密码、删除用户。
- 新增实时日志页与活动日志：普通用户查看自己的操作记录，管理员可查看全站活动；慢请求可通过 `SLOW_REQUEST_MS` 记录到 stdout。
- 新增单用户备份 / 导入与管理员整站备份 / 恢复能力。
- 新增订阅扩展字段与场景：套餐名、个性备注、VPS IPv4 / IPv6、套餐包、家庭成员、日历显示开关、同分类排序、最近续费日、每订阅自定义提醒天数。
- 新增内置服务管理能力：服务 CRUD、软删除 / 恢复、多分类 `category_keys`、服务图标预热任务。
- 新增内置服务多分类数据整理：YouTube Premium、GitHub Copilot、Namecheap、Amazon Prime 等服务可同时归属多个分类。
- Docker 镜像发布工作流支持手动运行时输入版本号（如 `2.1.0`），并校验 Docker tag 格式后同时发布 `latest` 与指定版本。

### Changed
- 统一项目身份与版本号：FastAPI 应用标题改为 `Subly API`，前端包名改为 `subly-frontend`，`main.py` / `system.py` / 前端版本号统一为 `2.1.0`。
- 内置图标库改为多来源 favicon 下载：优先直连站点 `favicon.ico`、首页 icon link，再尝试公共 provider，并支持 PNG / ICO / WEBP / JPEG / SVG 多格式缓存。
- 远端 SVG favicon 在缓存前严格消毒（移除脚本 / 事件属性 / 外链 / data URL 等风险内容），命中现代品牌站点的高清 SVG 图标。
- 图标下载新增可配置开关与限制：`ICON_FETCH_ENABLED`、`ICON_FETCH_GOOGLE_ENABLED`、`ICON_FETCH_TIMEOUT_S`、`ICON_FETCH_MAX_BYTES`、`ICON_FETCH_CONCURRENCY`、`ICON_FETCH_SVG_ENABLED`。
- 移除英文 / 俄文语言包，界面改为中文单语言，保留 `vue-i18n` 仅承载中文文案。
- 后端 `UserOut` / `UserUpdate` 不再暴露或接受 `locale`；备份导出 / 导入不再带 `locale`（数据库列保留，固定 `zh`）。
- 设置、通知中心、实时日志、用户管理等管理页统一到“续费雷达 / 深色控制台”视觉体系。
- 导航栏重组为“雷达工作台 / 通知与系统 / 管理员”分组，并移除非项目信息的联系方式露出。
- “图标库管理”调整为“服务管理 / 内置服务管理”语义，去除服务复制，分类编辑支持多选。
- 项目文档、配置示例与贡献模板按当前代码能力重新同步。

### Fixed
- 修复冷缓存、Google favicon 不可达或触发限流 / 熔断时，图标库返回透明 1x1 PNG 导致整库视觉空白的问题；失败时现在会显示稳定颜色和首字母的可见 fallback。
- 修复图标库冷启动时一次打开多个图标、因下载并发被限流而大面积显示首字母的问题：并发上限提升为可配置（默认 6），限流时短暂排队等待而非立即返回 fallback，且限流 fallback 标记为 `no-store` 不被浏览器缓存。
- 前端订阅页、仪表盘、日历和报表统一使用 `ServiceIcon`，可在图片加载失败或旧透明占位图场景下自动切换为可见 fallback。
- 修正文档中关于外部 MySQL、安装向导、`reminders` 表、SVG 缓存策略、前端脚本和 PR 模板格式等过时说明。

### Removed
- 移除当前文档入口中的旧品牌与错误联系方式残留；保留 Telegram 功能说明与 `@BotFather` 使用指引。

---

## [2.0.0] - 2026-06-28（Subly）

> Subly 进入自托管续费雷达方向：内置 SQLite、中文单语言、Bark 通道与更完整的订阅管理体验。

### Changed
- **数据库由外部 MySQL 8 改为内置 SQLite**：去掉网页安装向导，启动时零配置自动建库（`/app/data/subly.db`）。
- `migrate.py` 列迁移逻辑改用 SQLite `PRAGMA table_info`，不再依赖 `information_schema`。

### Added
- **新增 Bark（iOS）推送通道**：与 Telegram 可同时开启，各自独立发送、独立记录日志，互不影响。
  - 用户设置新增 `bark_enabled` / `bark_device_key` / `bark_server` / `bark_sound` / `bark_group`。
  - 新增 `app/services/bark.py`，新增 `/api/notifications/bark/test` 接口。
  - 通知日志（`/api/notifications/logs`）新增 `channel` 字段区分来源。

### Removed
- 移除 `app/bootstrap.py`、`app/routers/setup.py`、前端 `Setup.vue` 及对应路由（安装向导整体下线）。
- `requirements.txt` 移除 `pymysql`。

---

## [1.0.0] - 2026-06-19

### Added

#### 核心功能
- ✅ 多用户系统 - JWT 鉴权，管理员和普通用户。
- ✅ 订阅管理 - 支持创建、编辑、删除订阅。
- ✅ 周期设置 - 支持按日 / 周 / 月 / 年计费，支持一次性买断。
- ✅ 自动续费提醒 - APScheduler 定时任务 + Telegram 推送。
- ✅ 仪表盘 - 总览支出、即将到期项目、最近订阅。

#### 中文界面
- 中文界面与文案集中管理。

#### 多主题支持
- 5 个预设主题：浅色、深色、海洋、森林、紫罗兰。
- CSS 变量实现主题切换。

#### 货币管理
- 支持全球主流货币（USD、CNY、EUR 等）。
- 实时汇率更新（open.er-api.com）。
- 用户自定义货币功能。
- 日期缓存，避免频繁 API 调用。

#### 分类管理
- 预设分类：流媒体、AI、游戏、VPS、电信运营商等。
- 用户可自定义分类。
- 分类排序功能。

#### 付款方式
- 预设付款方式：信用卡、Apple Pay、支付宝、微信、PayPal 等。
- 用户可自定义付款方式。

#### 日历视图
- 苹果风格日历。
- 显示所有续费日期。
- 交互式日期选择。

#### 报表分析
- 支出洞察 - 总支出、平均支出、支出趋势。
- 分类排行 - 按分类统计支出。
- 永久购买统计。
- 即将续费提醒。
- 已过期订阅查看。
- 按月 / 年展示。

#### 自定义图标
- Emoji 选择。
- 图片上传功能。
- 本地图标库。

#### Telegram 通知
- 创建 Bot Token 验证。
- Chat ID 自动获取。
- 自定义提醒天数。
- 测试消息发送。
- 通知日志记录。

#### 数据库
- MySQL 8 支持。
- 网页安装向导配置连接。
- 自动建表和初始化。
- 数据库迁移支持。

#### 部署
- Docker Compose 一键部署。
- Dockerfile 多阶段构建。
- Caddy 反向代理 + 自动 HTTPS。
- NAS 部署支持（TrueNAS、fnOS、群晖等）。
- 环境变量配置。

### Changed
- 项目名称：「手机保号通知」→ 「省心订阅 Subly」。
- 数据库架构完全重设计，支持外部 MySQL。

### Fixed

### Removed

---

## 版本发布规则

- **主版本号**（Major）：不兼容的 API 更改。
- **次版本号**（Minor）：新增功能，向后兼容。
- **修订版本号**（Patch）：Bug 修复，向后兼容。

---

## 如何贡献更新日志

当你提交 PR 时，请同时更新 `CHANGELOG.md`：

1. 添加你的更改到 `[Unreleased]` 部分。
2. 使用对应的标签（Added / Changed / Fixed / Removed）。
3. 清晰描述你的更改。

---

## 版本历史

- **2.1.0** (2026-07-01) - 多用户审核、管理页、备份恢复、实时日志、内置服务多分类与文档同步，统一项目身份与版本号。
- **2.0.0** (2026-06-28) - Subly 转向内置 SQLite、自托管续费雷达与 Bark 双通道提醒。
- **1.0.0** (2026-06-19) - 初始版本发布。
- **开发中** (main 分支) - 开发版本。

---

**最后更新**：2026-07-01

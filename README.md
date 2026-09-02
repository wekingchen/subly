<div align="center">

# Subly

**你的自托管续费雷达 —— 管理订阅、域名、VPS、保号套餐与提醒通道。**

[![License](https://img.shields.io/badge/license-MIT-blue)](./LICENSE)

```bash
docker run -d --name subly -p 8842:8000 \
  -e JWT_SECRET="$(openssl rand -hex 32)" \
  -e ADMIN_USERNAME=admin -e ADMIN_PASSWORD='please-change-this-admin-password' -e ADMIN_EMAIL=admin@example.com \
  -e TZ=Asia/Shanghai \
  -v subly_data:/app/data <你的DockerHub用户名>/subly:latest
```

> Subly 面向个人与小团队，把订阅、域名、VPS、保号套餐、提醒通道与成员权限集中到一个本地 SQLite 账本中管理，并在续费前主动提醒。

</div>

---

## ✨ 功能特性

| | |
|---|---|
| 👥 **多用户与审核** | JWT 鉴权，管理员 / 普通用户分层，数据按用户隔离；支持注册、SMTP 邮箱验证码、管理员审核、用户启停与权限分配 |
| 💳 **订阅账本** | 周期订阅 + 一次性买断，支持名称 / 套餐 / 备注搜索、类型与续费风险组合筛选；支持套餐名、个性备注、URL、VPS IPv4 / IPv6、家庭成员、套餐包、日历开关、同分类排序与可选结束日期，高级字段通过“更多设置”渐进展开；结束日期当天仍有效，之后停止当前计费、预测与提醒；每次续费自动留痕，详情内可折叠查看完整续费历史；订阅可暂停（不计支出/不提醒/不进日历，账本可见可恢复） |
| 📬 **邮件账户（IMAP）** | 设置页可绑定多个 126 / QQ 邮箱（IMAP 授权码只写入不回显，任何 API 不返回），支持连接测试与手动拉取最近邮件预览（扫描收件箱及归档/订阅类文件夹——银行账单常被 QQ 自动分拣出收件箱），可按账户配置账单银行白名单（首期招 / 平 / 民 / 中信 / 建 5 家，按发件人域名过滤）；「解析账单」一键读取账单邮件正文，按卡拆分保存账单汇总与逐笔明细（含金额勾稽自校验），在信用卡详情页查看；账单中的账单日 / 还款日 / 总额度会以最新邮件为准自动更新到对应卡片（卡名、银行、尾号不会被改动）；账单日次日起每天 23:50 自动抓取最新账单（最多连续 3 天，成功即停；抓取结果不含任何账务数据）；原始邮件不落库 |
| 🏦 **信用卡还款提醒** | 集中管理多张信用卡的账单日与计划还款日：只登记银行名称、可选尾号、名义账单日 / 还款日与提醒天数，不存储卡号、CVV、有效期或网银凭据；尾号支持一次填多个（如 `1234,2234`）自动拆分创建多张卡；发卡银行匹配招商 / 平安 / 民生 / 中信 / 建设时自动显示官网抓取的官方徽标（本地缓存，失败回退字标）；可选记录总额度（仅展示，不进入提醒与日历）；账单按月份命名（「26年8月账单」）；逾期账单（未标记还款且过还款日）在卡片与明细红色标注「已逾期 n 天」；统计区实时汇总「待还款总额」（所有已出账单未标记还款的合计，勾稽异常不计入），卡片上一键标记已还款并从总额剔除，明细区可单期标记 / 取消；合计为负（溢缴款 / 多还）时按「账上有富余」绿色展示而非负数，纯富余卡无需标记操作，逾期只统计真实欠款（汇总与明细同口径）；标记已还款后卡片自动顺延到下个账单周期（还款日 / 倒计时 / 日历 / 提醒全部指向下一期），当期各提前提醒不再发送；卡片列表默认按计划还款日由近到远排序（停用卡沉底），标记还款后顺序自动刷新；卡片只呈现核心信息（周期轨道 + 待还金额），提醒天数 / 免息期 / 额度等细节在详情；可选配置免年费核卡日与「刷 N 笔 / 满 M 元」目标（满足其一即达标，分期计入、退款抵扣金额），按年费周期自动统计已解析账单的达成进度，达标显示「年费可豁免」，检测到年费入账或缺账单期时如实提示（以银行实际规则为准）；系统按月末锚定规则自动推导每期「账单日 → 计划还款日」周期（31 日在短月自动取月末），账单日至还款日的自然日间隔仅作展示、不等同于银行免息期；计划还款事件与订阅续费共享日历与 iCal，提醒走同一套 Telegram / Bark / Webhook 可靠投递，文案只提示计划日期并以银行账单为准 |
| 📱 **保号场景** | 针对电信运营商保号：续费后可从当前时间重新计算周期，也可按原到期日滚动 |
| 🔔 **Telegram 提醒** | 续费日前自动推送，每个订阅可配置提醒天数（支持负数=过期后第 N 天补提醒，如 `7,1,-1,-7`）；支持 Bot Token、Chat ID、TG API 反代与 HTTP 代理 |
| 🔔 **Bark 推送** | iOS 推送提醒，与 Telegram 可同时开启、各发各的；支持订阅图片图标、自建服务器、提示音、分组与可选 TTL |
| 🔗 **Webhook 通知** | 向自建自动化服务发送结构化 JSON，使用必填共享密钥对原始请求体生成 HMAC-SHA256 签名；可与 Telegram、Bark 同时启用并独立记录 |
| 📊 **雷达总览 & 报表** | 月化 / 年化成本、支出洞察、按月化成本排行、永久购买、即将续费、已过期、最近付款与分类明细；分类按稳定 ID 聚合并跨页面使用持久颜色；3 / 6 / 12 个月趋势提供金额轴、跨年标签、键盘 / 触摸 Tooltip 与等价数据表；雷达总览页每条订阅可直接点击查看详情并标记续费 / 编辑 / 删除；可设置月度预算，超支时雷达与报表预警；缺汇率时明确标记统计不完整，不把原币金额伪装成基准币 |
| 🗓️ **续费与还款日历** | 日历化查看续费日与信用卡计划还款日（桌面月历 + 移动端议程），来源以文字标签区分、可按订阅 / 信用卡设置是否显示；订阅续费事件可点击弹出详情并直接标记已续费/已保号、编辑或删除，信用卡事件展示计划日期与周期说明；设置页可生成只存哈希、可重置/撤销的私有 iCal 链接，把续费与计划还款一起订阅到系统或云日历 |
| 📲 **安全 PWA** | 生产构建支持安装到桌面或手机；Service Worker 只预缓存静态离线页与品牌图标，断网导航可安全回退，不缓存账户、订阅、API 或登录数据 |
| 💱 **多货币** | 全球主流货币 + 自定义货币；设置页可维护自定义名称、符号及「1 自定义币 = X 用户基准币」手动汇率，汇率缓存与每日自动刷新，按用户基准货币统计；自定义货币需先设置可用汇率才能用于订阅或基准币，使用中不能清空汇率 |
| 🗂️ **分类与套餐包** | 设置页可管理用户自定义分类与付款方式，系统预置项只读；删除使用中的自定义项会安全解除订阅引用；支持套餐包 / 组合订阅管理 |
| 🧭 **内置服务管理** | 100+ 常见服务，支持多分类 `category_keys`、服务 CRUD、软删除 / 恢复、图标预热；桌面表格与移动卡片共享筛选、状态、进度和操作能力 |
| 🖼️ **图标系统** | Emoji、上传图片、URL 导入；内置服务 favicon 按需下载、缓存、远端 SVG 消毒与可见 fallback |
| 📝 **可靠通知与日志** | 订阅与信用卡提醒先写入各自 Outbox 再独立投递，瞬时故障自动退避重试，失败耗尽进入 dead-letter；通知中心按「订阅 / 信用卡」来源统一展示六种状态、尝试历史与手动重发；实时日志页按权限查看活动日志 |
| 💾 **备份恢复** | 当前用户 JSON 备份 / 导入（v3 含信用卡配置，旧版本备份兼容导入）；管理员可整站备份 / 恢复全部成员数据 |
| ♿ **键盘与辅助技术** | 登录、订阅、设置、用户和服务管理使用原生表单语义；路由标题与主标题焦点同步，移动抽屉约束焦点并隔离背景，动态成功 / 错误反馈可由辅助技术读出，粗指针关键操作目标至少 44px |
| 🌈 **中文界面 / 多主题** | 中文单语言界面，保留 `vue-i18n` 集中文案，内置 5 套主题 |
| 🗄️ **内置 SQLite** | 零配置，开箱即用，无需准备外部数据库；数据持久化在 `/app/data` |

---

## 🚀 快速开始

> 内置 **SQLite**，零配置：首次启动自动在 `/app/data` 卷里创建数据库文件，无需准备任何外部数据库，也没有安装向导。

### 方式 A：拉取镜像运行（推荐）

请先把镜像名替换为你自己发布的 Docker Hub / GHCR 镜像。

```bash
docker run -d --name subly \
  -p 8842:8000 \
  -e JWT_SECRET="$(openssl rand -hex 32)" \
  -e ADMIN_USERNAME=admin \
  -e ADMIN_PASSWORD='please-change-this-admin-password' \
  -e ADMIN_EMAIL=admin@example.com \
  -e TZ=Asia/Shanghai \
  -v subly_data:/app/data \
  --restart unless-stopped \
  <你的DockerHub用户名>/subly:latest
```

或使用仓库内的 compose 文件：

```bash
docker compose -f docker-compose.hub.yml up -d
```

启动后访问 `http://<服务器IP>:8842`，直接用管理员账号登录即可（首次启动按环境变量自动创建）。

### 方式 B：从源码构建（自带 Caddy 自动 HTTPS）

```bash
git clone <你的仓库地址>
cd subly
cp .env.example .env          # 编辑 JWT_SECRET、ADMIN_*、SMTP_* 等
vi Caddyfile                  # 可选：把 your-domain.com 改成你的域名
docker compose up -d --build
```

`docker-compose.yml` 会构建本地镜像，并由 Caddy 在 `80/443` 反代到后端 `app:8000`。该 compose 中 app 端口只在容器内网暴露，并通过 `FORWARDED_ALLOW_IPS=*` 信任 Caddy 注入的真实客户端地址，使认证限流不会把所有用户聚合到代理容器 IP。若自行把 app 端口直接暴露到公网，不要使用 `*`，应只填写可信反向代理的 IP/CIDR。

### 🖥️ NAS 部署

群晖 Synology / 威联通 QNAP / 飞牛 fnOS / Unraid / TrueNAS 的图形界面分步教程，详见
**[各厂家 NAS 安装教程](./各厂家NAS安装教程.md)**。

---

## ⚙️ 环境变量

### 必填 / 常用

| 变量 | 必填 | 说明 |
|------|:---:|------|
| `JWT_SECRET` | ✅ | 登录令牌密钥，请用 `openssl rand -hex 32` 生成随机串；空值、占位值或少于 32 字符会拒绝启动 |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` / `ADMIN_EMAIL` | ✅ | 管理员账号；仅首次创建时要求密码至少 12 位且非默认值，已有管理员不会被环境变量重置 |
| `ALLOW_INSECURE_DEFAULTS` | | 默认 `false`；仅本地演示可显式设为 `true` 跳过上述保护，禁止公网使用 |
| `FORWARDED_ALLOW_IPS` | | Uvicorn 信任的反向代理 IP/CIDR；默认源码 compose 因 app 仅内网暴露而设为 `*`，直接公网暴露时必须收紧 |
| `TZ` | | 时区，如 `Asia/Shanghai` |
| `DB_PATH` | | SQLite 数据库文件路径，默认 `data/subly.db`，容器内一般不需要改 |
| `REMINDER_SCAN_TIME` | | 每天扫描到期订阅并写入可靠投递队列的时间，如 `09:00` |
| `REQUIRE_ADMIN_APPROVAL` | | 新用户注册是否需要管理员审核，默认 `true` |
| `APP_PUBLIC_URL` | | 对外可访问地址（如 `https://subly.example.com`）；用于生成公网日历服务可订阅的私有 iCal URL、Bark 测试推送跳转，以及把上传/内置订阅图标转换为设备可访问的绝对 URL；真实提醒点击地址仍取订阅 `url` |
| `TELEGRAM_BOT_TOKEN` | | 仅声明保留，当前不参与发送；Telegram Bot Token、Chat ID、代理、API 反代均在网页「设置」里按用户配置 |

### 注册邮件 / SMTP

配置 SMTP 后，注册流程可发送邮箱验证码；不配置时仍可使用管理员审核管理账号。邮件发送失败时不会创建半注册账号，用户名和邮箱可直接重试；验证码过期后可用相同用户名、邮箱和密码重新注册获取新验证码。

登录、注册和验证码入口带单进程内存限流；管理员撤销审核、关闭账号或邮箱未验证时，现有 Access Token 与 Refresh Token 都会被拒绝。限流适配默认单 worker 部署，进程重启会重置。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SMTP_HOST` | 空 | SMTP 主机 |
| `SMTP_PORT` | `587` | SMTP 端口 |
| `SMTP_USER` | 空 | SMTP 用户名 |
| `SMTP_PASSWORD` | 空 | SMTP 密码 |
| `SMTP_FROM` | 空 | 发件人地址；`SMTP_HOST` 与 `SMTP_FROM` 同时存在才视为 SMTP 已配置 |
| `SMTP_TLS` | `true` | `true` 使用 STARTTLS，`false` 使用 SMTP SSL |

### 汇率、日志与令牌

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `EXCHANGE_API_BASE` | `USD` | 汇率数据源基准货币 |
| `EXCHANGE_API_URL` | `https://open.er-api.com/v6/latest/` | 汇率 API 地址 |
| `EXCHANGE_API_KEY` | 空 | 可选汇率 API key |
| `LOG_LEVEL` | `INFO` | 后端日志级别，输出到 stdout，可用 `docker logs` 查看 |
| `SLOW_REQUEST_MS` | `1000` | 超过该毫秒数的请求额外记录 `slow_request` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | Access Token 有效期 |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `14` | Refresh Token 有效期 |
| `AUTH_COOKIE_NAME` | `subly_refresh` | HttpOnly Refresh Cookie 名称，一般无需修改 |
| `AUTH_COOKIE_SECURE` | `false` | HTTPS 部署设为 `true`；纯 HTTP 局域网访问保持 `false`，否则浏览器不会发送 Cookie |
| `AUTH_COOKIE_SAMESITE` | `lax` | Cookie SameSite 策略，可选 `lax` / `strict` / `none`；设 `none` 时必须同时启用 Secure |

### 图标库

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ICON_FETCH_ENABLED` | `true` | 是否允许内置图标库联网下载 favicon |
| `ICON_FETCH_GOOGLE_ENABLED` | `true` | 是否启用 Google favicon provider，网络不可达时可关闭 |
| `ICON_FETCH_TIMEOUT_S` | `2.0` | 单次图标下载超时秒数 |
| `ICON_FETCH_MAX_BYTES` | `262144` | 单个图标最大下载字节数 |
| `ICON_FETCH_CONCURRENCY` | `6` | 冷缓存时 favicon 下载并发数 |
| `ICON_FETCH_SVG_ENABLED` | `true` | 是否接受并消毒缓存远端 SVG favicon |

认证令牌由 PyJWT 签发与验证，算法在代码中固定为 HS256，不接受环境变量扩展允许列表。浏览器会话中，Access Token 只保存在当前页面内存，Refresh Token 使用 HttpOnly Cookie，并由服务端 `refresh_sessions` 一次性消费/轮换；刷新后的旧 Token 和 logout 后的当前 Token 都不能重放。旧版本 `localStorage` 中的 Refresh Token 会在首次加载时迁移一次并立即删除；服务端退出请求网络失败时保留当前登录态并提示重试，避免 Cookie 仍在却显示“已退出”。生产与开发均按同源部署，不再开放 wildcard CORS；SPA 响应带 CSP、`nosniff`、Referrer、Frame 与 Permissions 安全头。私有 iCal 原始 Token 只在生成/重置时显示一次，数据库仅保存 SHA-256；Feed、Token 管理接口、HTML 与 Service Worker 禁止持久缓存，Vite 哈希资源才使用长期 immutable 缓存。

Bark 推送的 Device Key、服务器、提示音、分组与 TTL 均在网页「设置」里按用户配置。iOS 15+ 可显示订阅图片图标：绝对 HTTP(S) 图标可直接使用；上传图标和内置图标需要配置 `APP_PUBLIC_URL`，且该地址必须能被接收 Bark 的设备访问。未配置或图标不可用时提醒仍会正常送达，只显示 Bark 默认图标；Emoji/普通文本不会作为 Bark 图标发送。真实提醒点击地址仍取订阅自身 `url`。完整示例见 [.env.example](./.env.example)。

---

## 🧰 技术栈

| 组件 | 技术 |
|------|------|
| 后端 | FastAPI · SQLAlchemy · APScheduler · Pydantic |
| 前端 | Vue 3 · Vite · Pinia · Vue Router · vue-i18n（仅中文） |
| 数据库 | SQLite（内置，零配置，文件持久化在 `/app/data`） |
| 部署 | Docker 多阶段构建 · Caddy 自动 HTTPS · amd64 / arm64 镜像发布 |

Dockerfile 使用 `node:20-alpine` + `npm ci` 按 lockfile 构建前端，再用 `python:3.12-slim` 运行后端；容器入口仅以 root 修复 `/app/data` 的历史卷权限，随后立即降权并以固定 UID/GID `10001` 启动 Uvicorn，由 FastAPI 托管 API、上传图标静态资源与前端 SPA。

数据持久化在容器的 `/app/data` 卷中：SQLite 数据库文件 + 上传图标 + 内置图标库缓存。新版会自动接管旧镜像留下的 root-owned 命名卷或 bind mount 内容；宿主文件系统仍需允许容器 root 调整 ownership。容器必须以默认入口运行（root 修复权限后降权到 `10001`），或显式 `user: "10001:10001"`；其他 UID 会在启动时被拒绝。

---

## 🧪 开发与测试

仓库内置最小测试基础，覆盖后端纯函数 / health smoke 与前端工具函数。

后端（需 Python 3.12）：

```bash
cd backend
python -m pip install -r requirements-dev.txt   # 包含运行时依赖、pytest、pip-audit
python -m pytest
python -m ruff check app                         # 低噪声正确性检查
python -m pip_audit --strict -r requirements.txt # 阻断式漏洞审计，必须零已知漏洞
```

前端：

```bash
cd frontend
npm ci
npm run lint
npm test          # vitest run
npm run build     # 构建校验
npm audit --audit-level=high
# 先启动构建后的 Subly 服务，再执行：npm run e2e
```

测试包含后端数据库/API 回归、前端 Vitest 工具与会话迁移单测，以及 Chromium Playwright smoke：真实验证登录、HttpOnly Cookie 刷新恢复、旧 `localStorage` Token 一次性迁移、退出、CORS 和关键页面 CSP。外网通知/图标 provider 仍以 stub 或专项运行验收为主。

GitHub Actions 对 PR 运行 Ruff、ESLint、后端测试、前端测试/构建、两份 compose 配置校验和阻断式依赖审计；`pip-audit --strict` 发现任何已知 Python 漏洞或依赖解析失败、`npm audit --audit-level=high` 发现 High/Critical 漏洞时，`verify` 立即失败。推送到 `main`、`v*` tag 或从 `main` 手动发布时，才分别构建 amd64/arm64 发布归档供 Trivy 扫描，并用通过门禁的 amd64 产物运行 Chromium E2E。门禁通过后直接发布同一批已扫描归档，不再二次重建；Trivy 继续负责最终镜像中存在修复版本的 High/Critical 系统包与运行时依赖漏洞。为保持仓库只存在 `main`，不启用 Dependabot 自动 version-update PR，Python、npm、GitHub Actions 与 Docker 基础镜像升级统一人工规划。手动镜像发布只允许从 `main` 分支运行；`v*` tag 必须指向 `main` 历史，只发布对应版本 tag，不回写 `latest`，避免未合并代码发布或旧提交回滚正式镜像。

---

## 📖 使用要点

- **第一次登录**：直接用启动环境变量设置的管理员账号登录，无需安装向导。
- **注册审核**：默认新用户注册后需要管理员审核；如果配置 SMTP，注册时还会要求邮箱验证码。
- **Telegram 提醒**：找 @BotFather `/newbot` 拿 Bot Token → 设置 → Telegram 配置 → 填 Token、验证机器人、获取 Chat ID、发送测试；需要时可设置 API 反代与 HTTP 代理。
- **Bark 推送**：iOS 上安装 [Bark](https://github.com/Finb/Bark) App，复制 Device Key → 设置 → Bark 配置 → 粘贴 Key、按需填写服务器、提示音、分组、TTL → 发送测试。
- **Webhook 通知**：设置 → Webhook 通知 → 填写接收 URL 与双方共享的签名密钥 → 保存并发送测试。请求体为 UTF-8 JSON，签名头为 `X-Subly-Signature: sha256=<hex>`，其中 `<hex>` 是对原始请求体计算的 HMAC-SHA256；正式提醒另带稳定的 `X-Subly-Delivery-ID`，接收端可据此幂等处理。
- **通知投递中心**：到期扫描只负责把任务写入 Outbox，不在扫描事务内联网。网络异常、HTTP 408/425/429 与 5xx 会按 1 分钟、5 分钟、15 分钟、1 小时、6 小时退避，最多 6 次；普通 4xx 或确定性供应商拒绝会停止自动重试。`dead` / `retry_wait` 可在通知中心手动重新入队，请注意系统提供的是 at-least-once 投递，接收端仍应使用 Delivery ID 去重。
- **续费规则**：续费后可按当前时间重新计算下次到期（保号场景），也可按原到期日累加周期。
- **服务管理**：管理员可维护内置服务列表、服务多分类、启停服务、恢复服务，并预热 favicon 缓存。
- **备份**：设置 → 数据备份，导出 / 导入当前用户 JSON；管理员可整站备份与恢复全部成员数据。为避免凭据与运行态扩散，JSON 不包含 Telegram Token、Bark Device Key、Webhook secret、Notification Outbox、SchedulerState、通知尝试日志或日历 Feed Token，恢复后需重新配置通知通道。
- **图标库**：内置服务图标会按需下载 favicon 并缓存到 `/app/data/icons/library`；远端 SVG 会消毒后缓存，失败时显示稳定颜色与首字母 fallback。
- **日志排障**：网页「实时日志」可看活动记录；容器 stdout 日志可用 `docker logs` 或 `docker compose logs -f app` 查看。
- **API 文档**：默认 Docker/NAS 部署访问 `http://<host>:8842/docs`；后端直跑或容器内端口为 `http://<host>:8000/docs`。

更多文档：[各厂家NAS安装教程](./各厂家NAS安装教程.md) · [技术方案](./技术方案.md)

---

## ❓ 常见问题

<details>
<summary><b>如何升级而不丢数据？</b></summary>

数据都在容器的 `/app/data` 卷里，升级只换镜像：
```bash
docker compose -f docker-compose.hub.yml pull
docker compose -f docker-compose.hub.yml up -d
```
建议升级前先在「设置 → 数据备份」导出一份，或直接备份整个 `/app/data` 卷。必需数据库结构迁移失败时应用会停止启动，不会带着半迁移结构继续运行；此时请保留数据卷并查看容器日志排障。
</details>

<details>
<summary><b>注册后为什么不能马上登录？</b></summary>

默认 `REQUIRE_ADMIN_APPROVAL=true`，新用户需要管理员在「用户管理」里审核通过；如果配置了 SMTP，注册时还需要邮箱验证码。管理员也可以在用户管理页启用 / 禁用账号、授予或撤销管理员权限。
</details>

<details>
<summary><b>Telegram / Bark / Webhook 收不到消息？</b></summary>

- Telegram：确认 Bot Token 正确、已和机器人对过话拿到 Chat ID；中国大陆网络环境可能需要在设置里配置代理或 API 反代。
- Bark：确认 Device Key 正确、iOS 上 Bark App 在线；自建 Bark 服务器需确认地址可从容器访问。TTL 只能填写非负整数秒数，留空表示使用 Bark 默认值。
- Webhook：先在设置页执行测试发送；确认 URL 可从 Subly 容器访问、接收端返回 2xx，并使用相同共享密钥对收到的原始字节计算 HMAC-SHA256 后比对 `X-Subly-Signature`。
</details>

<details>
<summary><b>图标库不显示真实图标怎么办？</b></summary>

内置图标库会优先从目标站点和公共 favicon provider 下载图标，下载失败时仍会显示可见 fallback。若部署环境无法访问 Google favicon provider，可设置 `ICON_FETCH_GOOGLE_ENABLED=false`；若完全不希望容器联网下载图标，可设置 `ICON_FETCH_ENABLED=false`。
</details>

<details>
<summary><b>支持 HTTPS 吗？</b></summary>

支持。方式 B 自带 Caddy 自动签发证书，编辑 `Caddyfile` 填域名并把 DNS 解析到服务器即可。本地无域名测试可把 Caddyfile 改为 `:80`。
</details>

---

## 🤝 贡献

欢迎 Issue 与 PR！Fork → 建分支 → 提交 → 发起 Pull Request，详见 [CONTRIBUTING.md](./CONTRIBUTING.md)。

> 如需发布自己的镜像，请在仓库 Secrets 中配置 Docker Hub / GHCR 凭据，并将镜像名替换为自己的命名空间。

## 📝 许可

[MIT License](./LICENSE)

## 🙏 致谢

感谢开源社区在自托管订阅管理、通知推送与 NAS 部署实践中的启发与基础贡献。

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
| 💳 **订阅账本** | 周期订阅 + 一次性买断，支持套餐名、个性备注、URL、VPS IPv4 / IPv6、家庭成员、套餐包、日历开关与同分类排序 |
| 📱 **保号场景** | 针对电信运营商保号：续费后可从当前时间重新计算周期，也可按原到期日滚动 |
| 🔔 **Telegram 提醒** | 续费日前自动推送，每个订阅可配置提醒天数；支持 Bot Token、Chat ID、TG API 反代与 HTTP 代理 |
| 🔔 **Bark 推送** | iOS 推送提醒，与 Telegram 可同时开启、各发各的；支持自建 Bark 服务器、提示音、分组与可选 TTL |
| 📊 **雷达总览 & 报表** | 月度 / 年度支出、支出洞察、排行、永久购买、即将续费、已过期、最近付款与分类明细 |
| 🗓️ **续费日历** | 日历化查看续费日，可按订阅设置是否显示 |
| 💱 **多货币** | 全球主流货币 + 自定义货币，汇率缓存与每日自动刷新，按用户基准货币统计 |
| 🗂️ **分类与套餐包** | 系统预置分类、用户自定义分类、付款方式、套餐包 / 组合订阅管理 |
| 🧭 **内置服务管理** | 100+ 常见服务，支持多分类 `category_keys`、服务 CRUD、软删除 / 恢复、图标预热 |
| 🖼️ **图标系统** | Emoji、上传图片、URL 导入；内置服务 favicon 按需下载、缓存、远端 SVG 消毒与可见 fallback |
| 📝 **通知与日志** | 通知中心记录 Telegram / Bark 发送结果；实时日志页按权限查看活动日志，慢请求写入 stdout |
| 💾 **备份恢复** | 当前用户 JSON 备份 / 导入；管理员可整站备份 / 恢复全部成员数据 |
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
| `REMINDER_SCAN_TIME` | | 每天扫描到期订阅、发送提醒的时间，如 `09:00` |
| `REQUIRE_ADMIN_APPROVAL` | | 新用户注册是否需要管理员审核，默认 `true` |
| `APP_PUBLIC_URL` | | 对外可访问地址（如 `https://subly.example.com`）；仅影响 Bark 测试推送的点击跳转，真实续费提醒点击地址取订阅 `url` |
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
| `JWT_ALGORITHM` | `HS256` | JWT 算法，一般不需要修改 |
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

浏览器会话中，Access Token 只保存在当前页面内存，Refresh Token 使用 HttpOnly Cookie，并由服务端 `refresh_sessions` 一次性消费/轮换；刷新后的旧 Token 和 logout 后的当前 Token 都不能重放。旧版本 `localStorage` 中的 Refresh Token 会在首次加载时迁移一次并立即删除；服务端退出请求网络失败时保留当前登录态并提示重试，避免 Cookie 仍在却显示“已退出”。生产与开发均按同源部署，不再开放 wildcard CORS；SPA 响应带 CSP、`nosniff`、Referrer、Frame 与 Permissions 安全头。

Bark 推送的 Device Key、服务器、提示音、分组与 TTL 均在网页「设置」里按用户配置，无对应环境变量；`APP_PUBLIC_URL` 仅影响 Bark 测试推送的点击跳转地址。完整示例见 [.env.example](./.env.example)。

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
python -m pip_audit -r requirements.txt          # 漏洞可见性检查，发现项需结合兼容性处理
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

GitHub Actions 对 PR 运行 Ruff、ESLint、后端测试、前端测试/构建、两份 compose 配置校验和非阻塞依赖审计；推送到 `main`、`v*` tag 或从 `main` 手动发布时，才分别构建 amd64/arm64 发布归档供 Trivy 扫描，并用通过门禁的 amd64 产物运行 Chromium E2E。门禁通过后直接发布同一批已扫描归档，不再二次重建；仅存在修复版本的 High/Critical 镜像漏洞阻断发布。`pip-audit` / `npm audit` 发现问题时保留日志并显示 warning；为保持仓库只存在 `main`，不启用 Dependabot 自动 version-update PR，Python、npm、GitHub Actions 与 Docker 基础镜像升级统一人工规划，发布产物继续由 Trivy 覆盖可修复的 High/Critical 漏洞。手动镜像发布只允许从 `main` 分支运行；`v*` tag 必须指向 `main` 历史，只发布对应版本 tag，不回写 `latest`，避免未合并代码发布或旧提交回滚正式镜像。

---

## 📖 使用要点

- **第一次登录**：直接用启动环境变量设置的管理员账号登录，无需安装向导。
- **注册审核**：默认新用户注册后需要管理员审核；如果配置 SMTP，注册时还会要求邮箱验证码。
- **Telegram 提醒**：找 @BotFather `/newbot` 拿 Bot Token → 设置 → Telegram 配置 → 填 Token、验证机器人、获取 Chat ID、发送测试；需要时可设置 API 反代与 HTTP 代理。
- **Bark 推送**：iOS 上安装 [Bark](https://github.com/Finb/Bark) App，复制 Device Key → 设置 → Bark 配置 → 粘贴 Key、按需填写服务器、提示音、分组、TTL → 发送测试。
- **续费规则**：续费后可按当前时间重新计算下次到期（保号场景），也可按原到期日累加周期。
- **服务管理**：管理员可维护内置服务列表、服务多分类、启停服务、恢复服务，并预热 favicon 缓存。
- **备份**：设置 → 数据备份，导出 / 导入当前用户 JSON；管理员可整站备份与恢复全部成员数据。
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
<summary><b>Telegram / Bark 收不到消息？</b></summary>

- Telegram：确认 Bot Token 正确、已和机器人对过话拿到 Chat ID；中国大陆网络环境可能需要在设置里配置代理或 API 反代。
- Bark：确认 Device Key 正确、iOS 上 Bark App 在线；自建 Bark 服务器需确认地址可从容器访问。TTL 只能填写非负整数秒数，留空表示使用 Bark 默认值。
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

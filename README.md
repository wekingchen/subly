<div align="center">

# 省心订阅 Subly

**自托管的订阅 / 续费 / 保号管理系统 —— 内置 SQLite 零配置，中文单语言，Telegram + Bark 双通道提醒。**

[![License](https://img.shields.io/badge/license-MIT-blue)](./LICENSE)

```bash
docker run -d -p 8842:8000 -v subly_data:/app/data <你的DockerHub用户名>/subly:latest
```

> Subly 面向个人与小团队的自托管续费雷达：把订阅、域名、VPS、保号套餐、提醒通道与成员权限集中到一个 SQLite 本地账本中管理。

</div>

---

## ✨ 功能特性

| | |
|---|---|
| 👥 **多用户与审核** | JWT 鉴权，管理员 / 普通用户分层，数据按用户隔离；支持注册、SMTP 邮箱验证码、管理员审核、用户启停与权限分配 |
| 💳 **订阅账本** | 周期订阅 + 一次性买断，支持套餐名、个性备注、URL、VPS IPv4 / IPv6、家庭成员、套餐包、日历开关与同分类排序 |
| 📱 **保号场景** | 针对电信运营商保号：续费后可从当前时间重新计算周期，也可按原到期日滚动 |
| 🔔 **Telegram 提醒** | 续费日前自动推送，每个订阅可配置提醒天数；支持 Bot Token、Chat ID、管理员 ID、TG API 反代与 HTTP 代理 |
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
  -e ADMIN_PASSWORD=admin123 \
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

`docker-compose.yml` 会构建本地镜像，并由 Caddy 在 `80/443` 反代到后端 `app:8000`。

### 🖥️ NAS 部署

群晖 Synology / 威联通 QNAP / 飞牛 fnOS / Unraid / TrueNAS 的图形界面分步教程，详见
**[各厂家 NAS 安装教程](./各厂家NAS安装教程.md)**。

---

## ⚙️ 环境变量

### 必填 / 常用

| 变量 | 必填 | 说明 |
|------|:---:|------|
| `JWT_SECRET` | ✅ | 登录令牌密钥，请用 `openssl rand -hex 32` 生成随机串 |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` / `ADMIN_EMAIL` | ✅ | 首次初始化创建的管理员账号；首次登录后建议修改密码 |
| `TZ` | | 时区，如 `Asia/Shanghai` |
| `DB_PATH` | | SQLite 数据库文件路径，默认 `data/subly.db`，容器内一般不需要改 |
| `REMINDER_SCAN_TIME` | | 每天扫描到期订阅、发送提醒的时间，如 `09:00` |
| `REQUIRE_ADMIN_APPROVAL` | | 新用户注册是否需要管理员审核，默认 `true` |
| `TELEGRAM_BOT_TOKEN` | | 可留空；Telegram 的 Chat ID、代理、API 反代等也可在网页「设置」里配置 |

### 注册邮件 / SMTP

配置 SMTP 后，注册流程可发送邮箱验证码；不配置时仍可使用管理员审核管理账号。

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

### 图标库

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ICON_FETCH_ENABLED` | `true` | 是否允许内置图标库联网下载 favicon |
| `ICON_FETCH_GOOGLE_ENABLED` | `true` | 是否启用 Google favicon provider，网络不可达时可关闭 |
| `ICON_FETCH_TIMEOUT_S` | `2.0` | 单次图标下载超时秒数 |
| `ICON_FETCH_MAX_BYTES` | `262144` | 单个图标最大下载字节数 |
| `ICON_FETCH_CONCURRENCY` | `6` | 冷缓存时 favicon 下载并发数 |
| `ICON_FETCH_SVG_ENABLED` | `true` | 是否接受并消毒缓存远端 SVG favicon |

Bark 推送无需环境变量，在网页「设置」里填 Device Key、服务器、提示音、分组与 TTL 即可。完整示例见 [.env.example](./.env.example)。

---

## 🧰 技术栈

| 组件 | 技术 |
|------|------|
| 后端 | FastAPI · SQLAlchemy · APScheduler · Pydantic |
| 前端 | Vue 3 · Vite · Pinia · Vue Router · vue-i18n（仅中文） |
| 数据库 | SQLite（内置，零配置，文件持久化在 `/app/data`） |
| 部署 | Docker 多阶段构建 · Caddy 自动 HTTPS · amd64 / arm64 镜像发布 |

Dockerfile 使用 `node:20-alpine` 构建前端，再用 `python:3.12-slim` 运行后端；最终由 FastAPI 托管 API、上传图标静态资源与前端 SPA。

数据持久化在容器的 `/app/data` 卷中：SQLite 数据库文件 + 上传图标 + 内置图标库缓存。

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
建议升级前先在「设置 → 数据备份」导出一份，或直接备份整个 `/app/data` 卷。
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

<div align="center">

# 省心订阅 Subly

**自托管的订阅 / 续费 / 保号管理系统 —— 内置 SQLite 零配置，Telegram + Bark 双通道提醒，再也不怕忘记续费。**

[![License](https://img.shields.io/badge/license-MIT-blue)](./LICENSE)

```bash
docker run -d -p 8842:8000 -v subly_data:/app/data yourname/subly:latest
```

> Subly 面向个人与小团队的自托管续费雷达：把订阅、域名、VPS、保号套餐与提醒通道集中到一个 SQLite 本地账本中管理。

</div>

---

## ✨ 功能特性

| | |
|---|---|
| 👥 **多用户** | JWT 鉴权，管理员 / 普通用户分层，数据按用户隔离，支持注册审核 |
| 💳 **订阅管理** | 周期订阅 + 一次性买断，自动计算下次续费日，到期 / 即将到期醒目提醒 |
| 📱 **保号场景** | 针对电信运营商保号：续费后从当前时间重新计算周期（无论提前还是过期续费） |
| 🔔 **Telegram 提醒** | 续费日前自动推送，提前天数可自定义，支持 TG API 反代 / HTTP 代理 |
| 🔔 **Bark 推送** | iOS 推送提醒，与 Telegram 可同时开启、各发各的，支持自建 Bark 服务器与可选 TTL |
| 📊 **仪表盘 & 报表** | 月度 / 年度支出、支出洞察与排行、永久购买、即将续费、分类明细 |
| 🗓️ **日历视图** | 苹果风格日历，订阅一目了然 |
| 💱 **多货币** | 全球主流货币 + 自定义货币，实时汇率自动更新 |
| 🗂️ **分类管理** | 流媒体 / AI / 游戏 / VPS / 运营商等预置分类，支持自定义与拖拽排序 |
| 💾 **备份恢复** | 单用户 JSON 备份；管理员可一键**整站备份 / 恢复**全部成员数据 |
| 🌈 **中文界面 / 多主题** | 中文界面，5 套主题 |
| 🖼️ **自定义图标** | Emoji、上传图片、URL，内置图标库支持 favicon 下载、缓存与可见 fallback |
| 🗄️ **内置 SQLite** | 零配置，开箱即用，无需准备外部数据库 |

---

## 🚀 快速开始

> 内置 **SQLite**，零配置：首次启动自动在 `/app/data` 卷里创建数据库文件，无需准备任何外部数据库。

### 方式 A：拉取镜像运行（推荐）

```bash
docker run -d --name subly \
  -p 8842:8000 \
  -e JWT_SECRET="$(openssl rand -hex 32)" \
  -e ADMIN_USERNAME=admin -e ADMIN_PASSWORD=admin123 \
  -e ADMIN_EMAIL=admin@example.com -e TZ=Asia/Shanghai \
  -v subly_data:/app/data \
  --restart unless-stopped \
  yourname/subly:latest
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
cp .env.example .env          # 编辑 JWT_SECRET、ADMIN_* 等
vi Caddyfile                  # 可选：把 your-domain.com 改成你的域名
docker compose up -d --build
```

### 🖥️ NAS 部署

群晖 Synology / 威联通 QNAP / 飞牛 fnOS / Unraid / TrueNAS 的图形界面分步教程，详见
**[各厂家 NAS 安装教程](./各厂家NAS安装教程.md)**。

---

## ⚙️ 环境变量

| 变量 | 必填 | 说明 |
|------|:---:|------|
| `JWT_SECRET` | ✅ | 登录令牌密钥，请用 `openssl rand -hex 32` 生成随机串 |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` / `ADMIN_EMAIL` | ✅ | 首次初始化创建的管理员账号 |
| `TZ` | | 时区，如 `Asia/Shanghai` |
| `DB_PATH` | | SQLite 数据库文件路径，默认 `data/subly.db`，一般不需要改 |
| `REMINDER_SCAN_TIME` | | 每天扫描到期订阅、发送提醒的时间，如 `09:00` |
| `TELEGRAM_BOT_TOKEN` | | 可留空，后续在网页「设置」里配置 |
| `EXCHANGE_API_BASE` / `EXCHANGE_API_URL` | | 汇率数据源（已给默认免费源） |
| `ICON_FETCH_ENABLED` | | 是否允许内置图标库联网下载 favicon，默认 `true` |
| `ICON_FETCH_GOOGLE_ENABLED` | | 是否启用 Google favicon provider，默认 `true`；网络不可达时可关闭 |
| `ICON_FETCH_TIMEOUT_S` | | 单次图标下载超时秒数，默认 `2.0` |
| `ICON_FETCH_MAX_BYTES` | | 单个图标最大下载字节数，默认 `262144` |
| `ICON_FETCH_CONCURRENCY` | | 冷缓存时 favicon 下载并发数，默认 `6` |
| `ICON_FETCH_SVG_ENABLED` | | 是否接受并消毒缓存远端 SVG favicon，默认 `true` |

Bark 推送无需环境变量，在网页「设置」里填 Device Key 即可；TTL 可留空使用 Bark 默认值，也可填写非负整数秒数。完整示例见 [.env.example](./.env.example)。

---

## 🧰 技术栈

| 组件 | 技术 |
|------|------|
| 后端 | FastAPI · SQLAlchemy · APScheduler |
| 前端 | Vue 3 · Vite · Pinia |
| 数据库 | SQLite（内置，零配置，文件持久化在 `/app/data`） |
| 部署 | Docker（多架构 amd64 / arm64）· Caddy 自动 HTTPS |

数据持久化在容器的 `/app/data` 卷中：SQLite 数据库文件 + 上传的图标 + 内置图标库缓存。

---

## 📖 使用要点

- **第一次登录**：直接用启动时环境变量设置的管理员账号登录即可，无需任何安装向导。
- **Telegram 提醒**：找 @BotFather `/newbot` 拿 Bot Token → 设置 → Telegram 配置 → 填 Token、验证机器人、获取 Chat ID、发送测试。
- **Bark 推送**：iOS 上安装 [Bark](https://github.com/Finb/Bark) App，打开复制 Device Key → 设置 → Bark 配置 → 粘贴 Key、按需填写 TTL（秒，非负整数，留空用 Bark 默认值）、发送测试。支持自建 Bark 服务器地址。两个通道可以同时开启，各发各的，互不影响。
- **续费规则**：点击续费后系统从当前时间重新计算下次到期（保号场景），循环订阅可选择按原到期日累加。
- **备份**：设置 → 数据备份，导出 / 导入 JSON；管理员可整站备份与恢复全部成员数据。
- **图标库**：内置服务图标会按需下载 favicon 并缓存到 `/app/data/icons/library`；网络不可达或 provider 失败时，会显示稳定颜色与首字母的可见 fallback，不再出现透明空白图标。
- **API 文档**：启动后访问 `http://<host>:8000/docs`（Swagger UI）。

更多文档：[各厂家NAS安装教程](./各厂家NAS安装教程.md) · [技术方案](./技术方案.md)

---

## ❓ 常见问题

<details>
<summary><b>如何升级而不丢数据？</b></summary>

数据都在容器的 `/app/data` 卷里（SQLite 文件），升级只换镜像：
```bash
docker compose -f docker-compose.hub.yml pull && docker compose -f docker-compose.hub.yml up -d
```
建议升级前先在「设置 → 数据备份」导出一份，或直接备份整个 `/app/data` 卷。
</details>

<details>
<summary><b>Telegram / Bark 收不到消息？</b></summary>

- Telegram：确认 Bot Token 正确、已和机器人对过话拿到 Chat ID；中国大陆需在设置里配置代理或 API 反代。
- Bark：确认 Device Key 正确、iOS 上 Bark App 在线；自建 Bark 服务器需确认地址可从容器访问。TTL 只能填写非负整数秒数，留空表示使用 Bark 默认值。
</details>

<details>
<summary><b>图标库不显示真实图标怎么办？</b></summary>

内置图标库会优先从目标站点和公共 favicon provider 下载图标，下载失败时仍会显示可见 fallback。若你的部署环境无法访问 Google favicon provider，可设置 `ICON_FETCH_GOOGLE_ENABLED=false`；若完全不希望容器联网下载图标，可设置 `ICON_FETCH_ENABLED=false`。
</details>

<details>
<summary><b>支持 HTTPS 吗？</b></summary>

支持。方式 B 自带 Caddy 自动签发证书，编辑 `Caddyfile` 填域名并把 DNS 解析到服务器即可。
</details>

---

## 🤝 贡献

欢迎 Issue 与 PR！Fork → 建分支 → 提交 → 发起 Pull Request，详见 [CONTRIBUTING.md](./CONTRIBUTING.md)。

> 如需发布自己的镜像，请在仓库 Secrets 中配置 Docker Hub / GHCR 凭据，并将镜像名替换为自己的命名空间。

## 📝 许可

[MIT License](./LICENSE)

## 🙏 致谢

感谢开源社区在自托管订阅管理、通知推送与 NAS 部署实践中的启发与基础贡献。

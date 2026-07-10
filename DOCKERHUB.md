# Subly · 你的自托管续费雷达

Self-hosted subscription / renewal radar with built-in **SQLite** (zero-config), Chinese UI, **Telegram + Bark** reminders, multi-user approval, service icon library, backups, and real-time logs.

你的自托管续费雷达：集中管理订阅、域名、VPS、保号套餐与提醒通道，内置 **SQLite** 零配置，支持 **Telegram + Bark** 双通道提醒、注册审核、服务图标库、备份恢复与实时日志。

- **Source / 源码**: `<your-repo-url>`
- **Image / 镜像**: `<your-dockerhub-namespace>/subly:latest` 或 `ghcr.io/<your-github-username>/subly:latest`

> Built-in SQLite, no external database needed. Persist `/app/data` to keep the SQLite DB, uploaded icons, and built-in icon-library cache.
> 内置 SQLite，无需外部数据库。请持久化 `/app/data`，其中包含 SQLite 数据库、上传图标和内置图标库缓存。

## Quick start / 快速开始

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
  <your-dockerhub-namespace>/subly:latest
```

Then open `http://<host>:8842` and log in with the initial admin account — no setup wizard needed.

启动后打开 `http://<host>:8842`，使用初始管理员账号登录即可，无需安装向导。

API docs / Swagger UI: `http://<host>:8842/docs`.

## docker-compose

```yaml
services:
  app:
    image: <your-dockerhub-namespace>/subly:latest
    container_name: subly
    restart: unless-stopped
    environment:
      JWT_SECRET: please-change-this-to-a-random-secret
      AUTH_COOKIE_SECURE: "false" # HTTPS reverse proxy: true; direct HTTP: false
      ALLOW_INSECURE_DEFAULTS: "false"
      TZ: Asia/Shanghai
      ADMIN_USERNAME: admin
      ADMIN_PASSWORD: please-change-this-admin-password
      ADMIN_EMAIL: admin@example.com
      REQUIRE_ADMIN_APPROVAL: "true"
      REMINDER_SCAN_TIME: "09:00"
      LOG_LEVEL: INFO
      SLOW_REQUEST_MS: "1000"
      EXCHANGE_API_BASE: USD
      EXCHANGE_API_URL: https://open.er-api.com/v6/latest/
      EXCHANGE_API_KEY: ""
      TELEGRAM_BOT_TOKEN: ""
      ICON_FETCH_ENABLED: "true"
      ICON_FETCH_GOOGLE_ENABLED: "true"
      ICON_FETCH_TIMEOUT_S: "2.0"
      ICON_FETCH_MAX_BYTES: "262144"
      ICON_FETCH_CONCURRENCY: "6"
      ICON_FETCH_SVG_ENABLED: "true"
      # Optional SMTP email verification / 可选注册邮箱验证：
      # SMTP_HOST: "smtp.example.com"
      # SMTP_PORT: "587"
      # SMTP_USER: ""
      # SMTP_PASSWORD: ""
      # SMTP_FROM: "noreply@example.com"
      # SMTP_TLS: "true"
    volumes:
      - subly_data:/app/data
    ports:
      - "8842:8000"
volumes:
  subly_data:
```

## Environment variables / 环境变量

| Var | Description |
|-----|-------------|
| `JWT_SECRET` | **Required.** Random secret for auth tokens. Empty, placeholder, or shorter than 32 characters is rejected at startup. |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` / `ADMIN_EMAIL` | Initial admin account created on first boot; the initial password must be at least 12 characters and not a known default. Existing admins are never reset from env. |
| `ALLOW_INSECURE_DEFAULTS` | Default `false`. Local demos only; never enable on an internet-facing deployment. |
| `FORWARDED_ALLOW_IPS` | Trusted reverse-proxy IP/CIDR for Uvicorn proxy headers. Never use `*` when the app port is directly exposed to untrusted clients. |
| `TZ` | Timezone, e.g. `Asia/Shanghai`. |
| `DB_PATH` | SQLite file path, default `data/subly.db`. Usually keep the default inside `/app/data`. |
| `REMINDER_SCAN_TIME` | Daily renewal scan time, e.g. `09:00`. |
| `REQUIRE_ADMIN_APPROVAL` | Whether new registrations require admin approval. Default `true`. |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM` / `SMTP_TLS` | Optional SMTP settings for registration email verification. |
| `TELEGRAM_BOT_TOKEN` | Declared but not used in sending; configure Telegram Bot Token, Chat ID, API reverse proxy, and HTTP proxy per user in the web Settings page. |
| `EXCHANGE_API_BASE` / `EXCHANGE_API_URL` / `EXCHANGE_API_KEY` | Exchange-rate source and optional API key. |
| `LOG_LEVEL` | Backend log level. Default `INFO`. Logs go to stdout / `docker logs`. |
| `SLOW_REQUEST_MS` | Requests slower than this threshold emit `slow_request` warnings. Default `1000`. |
| `JWT_ALGORITHM` | JWT algorithm. Default `HS256`. Usually leave unchanged. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access token lifetime. Default `60`. |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh token lifetime. Default `14`. |
| `AUTH_COOKIE_NAME` | HttpOnly refresh cookie name. Default `subly_refresh`. |
| `AUTH_COOKIE_SECURE` | Set `true` behind HTTPS; keep `false` for direct HTTP LAN access. |
| `AUTH_COOKIE_SAMESITE` | Refresh cookie SameSite policy. Default `lax`. |
| `ICON_FETCH_ENABLED` | Enable on-demand favicon downloads for the built-in icon library. Default `true`. |
| `ICON_FETCH_GOOGLE_ENABLED` | Enable Google favicon provider. Disable it if your network cannot reach Google. Default `true`. |
| `ICON_FETCH_TIMEOUT_S` | Per-attempt icon fetch timeout in seconds. Default `2.0`. |
| `ICON_FETCH_MAX_BYTES` | Maximum icon download size in bytes. Default `262144`. |
| `ICON_FETCH_CONCURRENCY` | Cold-cache favicon download concurrency. Default `6`. |
| `ICON_FETCH_SVG_ENABLED` | Accept and sanitize remote SVG favicons. Default `true`. |

Authentication endpoints use an in-memory rate limit for the default single-worker deployment. SMTP delivery failures do not leave a reserved username/email; expired pending registrations can restart with the same username, email, and password. Disabled, unapproved, or unverified users cannot continue with existing access/refresh tokens. Browser access tokens stay in memory, refresh tokens use an HttpOnly cookie backed by one-time server-side refresh sessions, replayed/ logged-out tokens are rejected, legacy localStorage tokens migrate once, wildcard CORS is removed, and HTML responses carry CSP/security headers.

认证入口按默认单 worker 部署使用内存限流；SMTP 发送失败不会占用用户名/邮箱，验证码过期后可用相同注册信息重新获取，禁用、未审核或未验证用户的现有 Access/Refresh Token 也会被拒绝。浏览器 Access Token 仅驻留内存，Refresh Token 使用 HttpOnly Cookie 与一次性服务端 session，刷新后的旧 token 和 logout 后 token 均不可重放；旧 localStorage Token 首次加载后自动迁移并删除。同源部署不开放 wildcard CORS，HTML 响应带 CSP 与通用安全头。

Bark needs no env var; `APP_PUBLIC_URL` only affects the click-through URL of Bark test pushes (real renewal reminders use the subscription's own `url`). — configure Device Key, server, sound, group, and optional non-negative TTL in the web Settings page.

Bark 无需环境变量，请在网页「设置」里配置 Device Key、服务器、提示音、分组与 TTL；`APP_PUBLIC_URL` 仅影响 Bark 测试推送的点击跳转（真实续费提醒用订阅自身 `url`）。

## Volumes / 数据卷

- `/app/data` — SQLite database file, uploaded icons, and built-in icon-library cache. **Persist this directory.** The container runs as non-root UID/GID `10001`; named volumes are recommended, while bind mounts must be writable by `10001:10001`.

Required schema migrations fail fast instead of starting with a partial database structure. Published images pass backend/frontend tests and Compose validation. CI builds amd64/arm64 release archives once, scans those exact artifacts with a Trivy gate for fixable High/Critical findings, then publishes the same artifacts; Python/npm audits remain visible, and Dependabot checks updates weekly.

必需结构迁移失败会直接停止启动，避免半迁移运行。CI 分别构建 amd64/arm64 发布归档，对同一批产物执行可修复 High/Critical 的 Trivy 门禁，通过后直接发布而不二次重建；Python/npm 审计持续可见，Dependabot 每周检查更新。

## Features / 功能

- Multi-user auth, registration, SMTP email verification, admin approval, account enable/disable, admin role management.
- Recurring and one-time subscriptions with plan, notes, remark, URL, VPS IP fields, bundles, family members, calendar visibility, sorting, and per-subscription reminder days.
- Telegram + Bark reminders running side by side, with notification logs and manual scan.
- Dashboard, calendar, reports, multi-currency, live FX refresh, Chinese UI, and 5 themes.
- Built-in service management with multi-category service library, favicon cache, SVG sanitization, visible fallback icons, and prewarm tasks.
- Per-user backup/restore and admin full-site backup/restore.
- Real-time activity logs and stdout request logs.
- Built-in SQLite, zero config, Docker/NAS friendly.

## License

MIT License

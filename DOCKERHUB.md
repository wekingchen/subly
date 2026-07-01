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
  -e ADMIN_PASSWORD=admin123 \
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
      JWT_SECRET: change-me-to-a-random-secret
      TZ: Asia/Shanghai
      ADMIN_USERNAME: admin
      ADMIN_PASSWORD: admin123
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
| `JWT_SECRET` | **Required.** Random secret for auth tokens. Production must change it. |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` / `ADMIN_EMAIL` | Initial admin account created on first boot. |
| `TZ` | Timezone, e.g. `Asia/Shanghai`. |
| `DB_PATH` | SQLite file path, default `data/subly.db`. Usually keep the default inside `/app/data`. |
| `REMINDER_SCAN_TIME` | Daily renewal scan time, e.g. `09:00`. |
| `REQUIRE_ADMIN_APPROVAL` | Whether new registrations require admin approval. Default `true`. |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM` / `SMTP_TLS` | Optional SMTP settings for registration email verification. |
| `TELEGRAM_BOT_TOKEN` | Optional global token; Telegram can also be configured per user in the web Settings page. |
| `EXCHANGE_API_BASE` / `EXCHANGE_API_URL` / `EXCHANGE_API_KEY` | Exchange-rate source and optional API key. |
| `LOG_LEVEL` | Backend log level. Default `INFO`. Logs go to stdout / `docker logs`. |
| `SLOW_REQUEST_MS` | Requests slower than this threshold emit `slow_request` warnings. Default `1000`. |
| `JWT_ALGORITHM` | JWT algorithm. Default `HS256`. Usually leave unchanged. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access token lifetime. Default `60`. |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh token lifetime. Default `14`. |
| `ICON_FETCH_ENABLED` | Enable on-demand favicon downloads for the built-in icon library. Default `true`. |
| `ICON_FETCH_GOOGLE_ENABLED` | Enable Google favicon provider. Disable it if your network cannot reach Google. Default `true`. |
| `ICON_FETCH_TIMEOUT_S` | Per-attempt icon fetch timeout in seconds. Default `2.0`. |
| `ICON_FETCH_MAX_BYTES` | Maximum icon download size in bytes. Default `262144`. |
| `ICON_FETCH_CONCURRENCY` | Cold-cache favicon download concurrency. Default `6`. |
| `ICON_FETCH_SVG_ENABLED` | Accept and sanitize remote SVG favicons. Default `true`. |

Bark needs no env var — configure Device Key, server, sound, group, and optional non-negative TTL in the web Settings page.

Bark 无需环境变量，请在网页「设置」里配置 Device Key、服务器、提示音、分组与 TTL。

## Volumes / 数据卷

- `/app/data` — SQLite database file, uploaded icons, and built-in icon-library cache. **Persist this directory.**

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

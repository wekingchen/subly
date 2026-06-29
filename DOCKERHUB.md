# Subly · 省心订阅

Self-hosted subscription / renewal manager with built-in **SQLite** (zero-config) and **Telegram + Bark** reminders so you never let a subscription (or a SIM-keepalive plan) expire.

自托管的订阅 / 续费 / 保号管理系统，内置 **SQLite** 零配置，**Telegram + Bark** 双通道提醒，防止忘记导致过期。

- **Source / 源码**: `<your-repo-url>` — based on [suyijun8182/easysub](https://github.com/suyijun8182/easysub) (MIT)

> Built-in SQLite, no external database needed. First boot auto-creates the DB file in `/app/data`.
> 内置 SQLite，无需外部数据库。首次启动自动在 `/app/data` 里建库。

## Quick start / 快速开始

```bash
docker run -d --name subly \
  -p 8842:8000 \
  -e JWT_SECRET="$(openssl rand -hex 32)" \
  -e ADMIN_USERNAME=admin \
  -e ADMIN_PASSWORD=admin123 \
  -e TZ=Asia/Shanghai \
  -v subly_data:/app/data \
  --restart unless-stopped \
  yourname/subly:latest
```

Then open `http://<host>:8842` and log in with the admin account — no setup wizard needed.

## docker-compose

```yaml
services:
  app:
    image: yourname/subly:latest
    container_name: subly
    restart: unless-stopped
    environment:
      JWT_SECRET: change-me-to-a-random-secret
      TZ: Asia/Shanghai
      ADMIN_USERNAME: admin
      ADMIN_PASSWORD: admin123
      ADMIN_EMAIL: admin@example.com
      ICON_FETCH_ENABLED: "true"
      ICON_FETCH_GOOGLE_ENABLED: "true"
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
| `JWT_SECRET` | **Required.** Random secret for auth tokens. |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` / `ADMIN_EMAIL` | Initial admin account created on first init. |
| `TZ` | Timezone, e.g. `Asia/Shanghai`. |
| `DB_PATH` | SQLite file path, default `data/subly.db`. Rarely needs changing. |
| `REMINDER_SCAN_TIME` | Daily scan time for reminders, e.g. `09:00`. |
| `TELEGRAM_BOT_TOKEN` | Optional; can also be set in the web UI. |
| `EXCHANGE_API_BASE` / `EXCHANGE_API_URL` | Exchange-rate source (defaults provided). |
| `ICON_FETCH_ENABLED` | Enable on-demand favicon downloads for the built-in icon library. Default `true`. |
| `ICON_FETCH_GOOGLE_ENABLED` | Enable Google favicon provider. Disable it if your network cannot reach Google. Default `true`. |
| `ICON_FETCH_TIMEOUT_S` | Per-attempt icon fetch timeout in seconds. Default `2.0`. |
| `ICON_FETCH_MAX_BYTES` | Maximum icon download size in bytes. Default `262144`. |
| `ICON_FETCH_CONCURRENCY` | Cold-cache favicon download concurrency. Default `6`. |
| `ICON_FETCH_SVG_ENABLED` | Accept and sanitize remote SVG favicons. Default `true`. |

Bark needs no env var — configure the Device Key and optional non-negative TTL seconds in the web Settings page.

## Volumes

- `/app/data` — SQLite database file + uploaded icons + built-in icon-library cache. Persist this.

## Features

Multi-user (JWT, admin/user roles) · recurring & one-time subscriptions · multi-language (中/EN/RU) · 5 themes · multi-currency with live FX · dashboard analytics · category management · Apple-style calendar · spending reports · **Telegram + Bark** notifications (run side by side, optional Bark TTL) · icon library with favicon cache and visible fallback · per-user & **admin full-site** backup/restore · built-in SQLite, zero config.

## License

MIT · Based on [suyijun8182/easysub](https://github.com/suyijun8182/easysub)

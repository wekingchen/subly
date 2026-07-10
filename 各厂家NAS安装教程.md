# 各厂家 NAS 安装教程（Subly）

> Subly 是你的自托管续费雷达，内置 **SQLite** 零配置：拉镜像、填环境变量、映射 `/app/data`、启动即可用，不需要另外准备数据库，也没有安装向导。

镜像地址（任选其一，记得换成你自己发布的镜像）：

| 来源 | 镜像名 |
|------|--------|
| Docker Hub | `<你的用户名>/subly:latest` |
| GHCR（GitHub） | `ghcr.io/<你的GitHub用户名>/subly:latest` |

> 国内拉取 Docker Hub 较慢时，建议先配置镜像加速，或改用 GHCR。

## 通用前置条件

1. NAS 已安装 **Docker / Container** 套件。
2. 准备一个持久化目录映射到容器内 `/app/data`。容器入口会自动修复旧版 root-owned 数据卷权限，再以非 root UID/GID `10001` 运行 Uvicorn；使用宿主机目录时需允许容器 root 调整 ownership。若 NAS 强制指定运行用户并跳过默认权限修复，需预先确保 `10001:10001` 可写。
3. 准备以下环境变量。

### 必填 / 常用环境变量

| 变量 | 说明 | 示例 |
|------|------|------|
| `JWT_SECRET` | 登录令牌密钥，**必须使用至少 32 字符的随机串**；占位值会拒绝启动 | `openssl rand -hex 32` 生成 |
| `ADMIN_USERNAME` | 管理员账号，启动时该用户名不存在则创建 | `admin` |
| `ADMIN_PASSWORD` | 首次管理员密码，至少 12 位且不能使用默认值；已有管理员不会被环境变量重置 | 自行生成强密码 |
| `ALLOW_INSECURE_DEFAULTS` | 默认 `false`；仅本地演示可设 `true`，公网部署禁止开启 | `false` |
| `FORWARDED_ALLOW_IPS` | 使用 NAS 反向代理时填写可信代理 IP/CIDR；app 端口直接对外时不要设 `*` | 代理容器或网关地址 |
| `AUTH_COOKIE_SECURE` | 通过 HTTPS 反向代理访问时设 `true`；直接 HTTP 局域网访问保持 `false` | `false` |
| `AUTH_COOKIE_SAMESITE` | Refresh Cookie SameSite 策略，一般保持默认 | `lax` |
| `ADMIN_EMAIL` | 管理员邮箱 | `admin@example.com` |
| `TZ` | 时区 | `Asia/Shanghai` |
| `REMINDER_SCAN_TIME` | 每天扫描到期订阅、发送提醒的时间 | `09:00` |
| `REQUIRE_ADMIN_APPROVAL` | 新用户注册后是否需要管理员审核 | `true` |
| `TELEGRAM_BOT_TOKEN` | 仅声明保留，当前不参与发送；Bot Token、Chat ID 等在网页「设置」里配置 | |

### 邮箱验证 / SMTP（可选）

配置 SMTP 后，注册流程可以发送邮箱验证码；不配置时仍可通过管理员审核来管理新用户。SMTP 发送失败不会创建半注册账号，用户名和邮箱可以直接重试；验证码过期后可用相同用户名、邮箱和密码重新注册获取新验证码。登录、注册和验证码入口使用适配默认单 worker 部署的内存限流。浏览器 Refresh Token 使用 HttpOnly Cookie；若 NAS 通过 HTTPS 反向代理访问，请设置 `AUTH_COOKIE_SECURE=true`，直接 HTTP 访问则保持 `false`。

| 变量 | 说明 | 示例 |
|------|------|------|
| `SMTP_HOST` | SMTP 主机 | `smtp.example.com` |
| `SMTP_PORT` | SMTP 端口 | `587` |
| `SMTP_USER` | SMTP 用户名 | `noreply@example.com` |
| `SMTP_PASSWORD` | SMTP 密码或授权码 | `请使用占位或自行填写` |
| `SMTP_FROM` | 发件人地址；`SMTP_HOST` 与 `SMTP_FROM` 同时存在才视为启用 SMTP | `noreply@example.com` |
| `SMTP_TLS` | `true` 使用 STARTTLS，`false` 使用 SMTP SSL | `true` |

### 汇率、日志与图标库（可选）

| 变量 | 说明 | 示例 |
|------|------|------|
| `EXCHANGE_API_BASE` | 汇率数据源基准货币 | `USD` |
| `EXCHANGE_API_URL` | 汇率 API 地址 | `https://open.er-api.com/v6/latest/` |
| `EXCHANGE_API_KEY` | 可选汇率 API key | 留空 |
| `LOG_LEVEL` | 后端日志级别，输出到 stdout / 容器日志 | `INFO` |
| `SLOW_REQUEST_MS` | 请求耗时超过该毫秒数时记录 `slow_request` | `1000` |
| `ICON_FETCH_ENABLED` | 是否允许内置图标库联网下载 favicon | `true` |
| `ICON_FETCH_GOOGLE_ENABLED` | 是否启用 Google favicon provider，网络不可达时可关 | `true` |
| `ICON_FETCH_TIMEOUT_S` | 单次图标下载超时秒数 | `2.0` |
| `ICON_FETCH_MAX_BYTES` | 单个图标最大下载字节数 | `262144` |
| `ICON_FETCH_CONCURRENCY` | 冷缓存时 favicon 下载并发数 | `6` |
| `ICON_FETCH_SVG_ENABLED` | 是否接受并消毒缓存远端 SVG favicon | `true` |

> Bark 推送的 Device Key、服务器、提示音、分组与 TTL 均在网页「设置」里按用户配置，无对应环境变量；`APP_PUBLIC_URL` 仅影响 Bark 测试推送的点击跳转（真实续费提醒用订阅自身 `url`）。Telegram 的 Chat ID、API 反代和 HTTP 代理也建议在网页「设置」里配置。

- **端口**：容器内部 `8000`，映射到宿主任意端口（本文统一用 `8842`）。
- **持久化目录**：把容器内 `/app/data` 映射到 NAS 的一个目录。这里保存 SQLite 数据库文件、上传图标和内置图标库缓存。**这个目录一定要持久化，否则重建容器会丢数据。**

完成创建后，浏览器访问 `http://<NAS局域网IP>:8842`，直接用环境变量设置的管理员账号登录即可。

API / Swagger 文档地址：`http://<NAS局域网IP>:8842/docs`。

---

## 1. 群晖 Synology（DSM 7 / Container Manager）

1. 打开 **Container Manager**（旧版叫 Docker）。
2. **注册表** → 搜索 `<你的用户名>/subly` → 下载 `latest` 标签。
3. **映像** → 选中镜像 → **运行**。
4. 在向导里设置：
   - **端口设置**：本地端口 `8842` → 容器端口 `8000`。
   - **存储空间**：添加文件夹，装载路径填 `/app/data`（如 `/docker/subly` → `/app/data`）。
   - **环境**：逐条添加上表的变量（`JWT_SECRET`、`ADMIN_*`、`TZ`、`REQUIRE_ADMIN_APPROVAL` 等）。
5. 启动后访问 `http://<群晖IP>:8842`，用管理员账号登录。

> 也可用「项目（Project）」功能：上传本仓库的 `docker-compose.hub.yml`，新建项目直接部署。

---

## 2. 威联通 QNAP（Container Station）

1. 打开 **Container Station**。
2. **创建** → **搜索镜像** → 输入 `<你的用户名>/subly` → 选 `latest` 创建。
3. **高级设置**：
   - **网络**：端口转发 `8842 → 8000`。
   - **存储空间**：挂载一个卷到 `/app/data`。
   - **环境变量**：添加上表变量。
4. 创建并启动，访问 `http://<威联通IP>:8842`，用管理员账号登录。

> Container Station 新版支持「**应用程序（Application）**」用 docker-compose：把 `docker-compose.hub.yml` 内容粘进去即可。

---

## 3. 飞牛 fnOS

1. 飞牛桌面 → **Docker** App → **设置 / 仓库** → 配置镜像加速（强烈建议）：
   ```
   https://docker.1ms.run
   https://docker.m.daocloud.io
   ```
2. **镜像** → 搜索并拉取 `<你的用户名>/subly:latest`。
3. **容器** → 用该镜像创建：
   - 端口 `8842 → 8000`；
   - 目录映射 `/app/data`；
   - 添加上表环境变量。
4. 或用 **项目 / Compose**：粘贴 `docker-compose.hub.yml` 内容创建项目（推荐，最省事）。
5. 访问 `http://<飞牛IP>:8842`，用管理员账号登录。

---

## 4. Unraid

1. **Apps / Community Applications** 里搜索，或用 **Docker → Add Container** 手动添加。
2. 手动添加时：
   - **Repository**：`<你的用户名>/subly:latest`
   - **Network Type**：Bridge
   - **Port**：`8842` → `8000`
   - **Path**：`/mnt/user/appdata/subly` → `/app/data`
   - **Variables**：逐条加上表环境变量。
3. Apply 启动，访问 `http://<Unraid IP>:8842`，用管理员账号登录。

---

## 5. TrueNAS SCALE（Custom App）

1. **Apps** → **Discover** → **Custom App**。
2. 填写：
   - **Image Repository**：`<你的用户名>/subly`，**Tag**：`latest`
   - **Container Port** `8000`，**Node Port** 选一个（如 `8842`）。
   - **Environment Variables**：加上表变量。
   - **Storage**：Host Path 或 ixVolume 挂到 `/app/data`。
3. 安装后访问 `http://<TrueNAS IP>:<NodePort>`，用管理员账号登录。

---

## 6. 任意支持 Docker 的设备（命令行）

```bash
docker run -d --name subly \
  -p 8842:8000 \
  -e JWT_SECRET="$(openssl rand -hex 32)" \
  -e ADMIN_USERNAME=admin \
  -e ADMIN_PASSWORD='please-change-this-admin-password' \
  -e ADMIN_EMAIL=admin@example.com \
  -e TZ=Asia/Shanghai \
  -e REQUIRE_ADMIN_APPROVAL=true \
  -v subly_data:/app/data \
  --restart unless-stopped \
  <你的用户名>/subly:latest
```

如果需要 SMTP、日志、汇率或图标库高级配置，建议使用仓库内 compose 示例：

```bash
docker compose -f docker-compose.hub.yml up -d
```

---

## 升级到新版本

数据都在容器的 `/app/data` 卷里，升级只换镜像，不会丢数据：

```bash
docker compose -f docker-compose.hub.yml pull
docker compose -f docker-compose.hub.yml up -d
```

NAS 图形界面：重新拉取 `latest`，再重建容器（保持 `/app/data` 映射不变）即可。

> 建议升级前，先在网页 **设置 → 数据备份** 里导出一份当前用户备份；管理员还可用 **整站备份** 导出全部成员数据。重要数据建议再额外备份一份 `/app/data` 整个目录。新版遇到必需结构迁移失败会停止启动，不会继续运行半迁移数据库；请保留原数据卷并查看容器日志。升级镜像会自动修复旧版 root-owned 数据卷；若仍提示权限错误，检查宿主文件系统是否禁止 chown，或手动将目录及内容授权给 `10001:10001`。

---

## 常见问题

**Q：端口被占用？**
- 把映射左边的 `8842` 改成别的端口（如 `9000`），访问就用新端口，例如 `http://<NAS局域网IP>:9000`。

**Q：数据存在哪？**
- 全部在容器的 `/app/data` 卷里：SQLite 数据库文件（`subly.db`）+ 上传图标 + 内置图标库缓存。只要这个目录做了持久化映射，重建 / 升级容器都不会丢数据。

**Q：注册后为什么不能马上登录？**
- 默认 `REQUIRE_ADMIN_APPROVAL=true`，新用户注册后需要管理员在「用户管理」里审核通过。
- 如果配置了 SMTP，注册时还需要完成邮箱验证码校验。
- 管理员也可以在「用户管理」里启用 / 禁用账号、授予或撤销管理员权限。

**Q：不想开放注册怎么办？**
- 当前文档只建议把部署入口放在可信网络或反向代理后，并保留 `REQUIRE_ADMIN_APPROVAL=true`。这样即使有人注册，也必须管理员审核后才能使用。

**Q：Telegram / Bark 收不到提醒？**
- Telegram：确认 Bot Token 正确、已和机器人对话过拿到 Chat ID；国内访问需要在设置里配 HTTP 代理或 Telegram API 反代。
- Bark：确认 Device Key 正确、iOS 上 Bark App 在线；自建 Bark 服务器要确认容器能访问到那个地址。TTL 只能填写非负整数秒数，留空表示使用 Bark 默认值。
- 两者可以同时开启，互不影响，建议先在「设置」页点「发送测试」确认通道本身是通的。
- 若自动提醒没有触发，检查订阅是否为启用状态、到期日与提前提醒天数是否匹配，以及 `REMINDER_SCAN_TIME` 与 `TZ` 是否符合预期。

**Q：图标库没有真实图标或加载很慢？**
- 内置图标库会按需下载 favicon 并缓存到 `/app/data/icons/library`；下载失败时会显示可见 fallback，不会显示透明空白图标。
- 如果 NAS 所在网络无法访问 Google favicon provider，可添加环境变量 `ICON_FETCH_GOOGLE_ENABLED=false`。
- 如果不希望容器联网下载图标，可添加环境变量 `ICON_FETCH_ENABLED=false`，系统会直接使用可见 fallback。
- 远端 SVG favicon 默认会经过消毒后缓存；如需禁用，可设置 `ICON_FETCH_SVG_ENABLED=false`。

**Q：在哪里查看日志排障？**
- 网页「实时日志」可查看当前账号相关的活动记录；管理员可查看全站活动。
- 容器日志可用 NAS 图形界面的日志页，或命令行查看：
  ```bash
  docker logs -f subly
  # 或 compose 部署：
  docker compose -f docker-compose.hub.yml logs -f app
  ```
- `SLOW_REQUEST_MS` 可帮助定位慢请求；后端日志会记录 method、path、status、duration、user_id、client 等请求概要，不记录请求体、密码、token 或 API key。

**Q：Swagger / API 文档在哪？**
- NAS / Docker 默认端口映射后访问 `http://<NAS局域网IP>:8842/docs`。
- 如果你自己改了宿主端口，请把 `8842` 替换成实际端口。

# 各厂家 NAS 安装教程（Subly 省心订阅）

> 内置 **SQLite**，零配置：拉镜像、填几个环境变量、启动即可用，不需要另外准备数据库，也没有安装向导。

镜像地址（任选其一，记得换成你自己发布的镜像）：

| 来源 | 镜像名 |
|------|--------|
| Docker Hub | `<你的用户名>/subly:latest` |
| GHCR（GitHub） | `ghcr.io/<你的GitHub用户名>/subly:latest` |

> 国内拉取 Docker Hub 较慢时，建议先配置镜像加速，或改用 GHCR。

## 通用前置条件

1. NAS 已安装 **Docker / Container** 套件。
2. 关键环境变量（创建容器时填）：

| 变量 | 说明 | 示例 |
|------|------|------|
| `JWT_SECRET` | 登录令牌密钥，**必须改成随机串** | `openssl rand -hex 32` 生成 |
| `ADMIN_USERNAME` | 初始管理员账号 | `admin` |
| `ADMIN_PASSWORD` | 初始管理员密码（首次初始化后请改） | `admin123` |
| `ADMIN_EMAIL` | 管理员邮箱 | `admin@example.com` |
| `TZ` | 时区 | `Asia/Shanghai` |
| `REMINDER_SCAN_TIME` | 每天提醒扫描时间 | `09:00` |
| `TELEGRAM_BOT_TOKEN` | 可留空，后续网页里配 | |

> Bark 推送无需环境变量，登录后在网页「设置」里填 Device Key 即可；Telegram 也可以留空在网页里配。

- **端口**：容器内部 `8000`，映射到宿主任意端口（本文统一用 `8842`）。
- **持久化目录**：把容器内 `/app/data` 映射到 NAS 的一个目录（存 SQLite 数据库文件 + 上传图标）。**这个目录一定要做持久化映射，否则重建容器会丢数据。**

完成创建后，浏览器访问 `http://<NAS局域网IP>:8842`，直接用上面设置的管理员账号登录即可。

---

## 1. 群晖 Synology（DSM 7 / Container Manager）

1. 打开 **Container Manager**（旧版叫 Docker）。
2. **注册表** → 搜索 `<你的用户名>/subly` → 下载 `latest` 标签。
3. **映像** → 选中镜像 → **运行**。
4. 在向导里设置：
   - **端口设置**：本地端口 `8842` → 容器端口 `8000`。
   - **存储空间**：添加文件夹，装载路径填 `/app/data`（如 `/docker/subly` → `/app/data`）。
   - **环境**：逐条添加上表的变量（`JWT_SECRET`、`ADMIN_*`、`TZ` 等）。
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
  -e ADMIN_PASSWORD=admin123 \
  -e ADMIN_EMAIL=admin@example.com \
  -e TZ=Asia/Shanghai \
  -v subly_data:/app/data \
  --restart unless-stopped \
  <你的用户名>/subly:latest
```

或使用仓库内 compose：

```bash
docker compose -f docker-compose.hub.yml up -d
```

---

## 升级到新版本

数据都在容器的 `/app/data` 卷里（SQLite 文件），升级只换镜像，不会丢数据：

```bash
docker compose -f docker-compose.hub.yml pull
docker compose -f docker-compose.hub.yml up -d
```

NAS 图形界面：重新拉取 `latest`，再重建容器（保持 `/app/data` 映射不变）即可。

> 建议升级前，先在网页 **设置 → 数据备份** 里导出一份备份；管理员还可用 **整站备份** 导出全部成员数据。重要数据建议再额外备份一份 `/app/data` 整个目录。

---

## 常见问题

**Q：端口被占用？**
- 把映射左边的 `8842` 改成别的端口（如 `9000`），访问就用新端口。

**Q：数据存在哪？**
- 全部在容器的 `/app/data` 卷里：SQLite 数据库文件（`subly.db`）+ 上传的图标。只要这个目录做了持久化映射，重建/升级容器都不会丢数据。

**Q：Telegram / Bark 收不到提醒？**
- Telegram：确认 Bot Token 正确、已和机器人对话过拿到 Chat ID；国内访问需要在设置里配代理或 API 反代。
- Bark：确认 Device Key 正确、iOS 上 Bark App 在线；自建 Bark 服务器要确认容器能访问到那个地址。
- 两者可以同时开启，互不影响，建议先在「设置」页点「发送测试」确认通道本身是通的。

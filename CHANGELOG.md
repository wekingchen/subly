# Changelog

所有项目的重要变更都会记录在此文件中。

项目采用 [Semantic Versioning](https://semver.org/lang/zh-CN/) 进行版本管理；当前 `main` 分支上的未发布整理统一记录在 `[Unreleased]`。

---

## [Unreleased]

_当前 `main` 分支上尚未发布的新整理将记录在此。_

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

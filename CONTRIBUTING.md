# 贡献指南

感谢你愿意改进 Subly！本项目欢迎 Bug 修复、文档补充、NAS 部署经验、UI/UX 建议和功能 PR。

> 当前项目界面只维护中文文案。修改用户可见功能时，请同步更新 `frontend/src/i18n/index.js` 中的 `zh` 文案。

---

## 如何贡献

### 报告 Bug

请在 GitHub Issues 中创建问题，并尽量包含：

- 清晰的标题。
- 问题描述、复现步骤、实际行为与预期行为。
- 部署方式（Docker run / docker-compose / NAS 图形界面 / 源码运行）。
- 运行环境（OS、Docker 版本、浏览器等）。
- 相关日志或截图。

排障日志可以来自：

```bash
docker logs subly
# 或 compose 部署：
docker compose -f docker-compose.hub.yml logs -f app
```

### 建议功能

请先说明：

- 使用场景和目标用户。
- 期望的交互或 API 行为。
- 是否影响数据模型、环境变量、部署方式或现有文档。

### 提交代码

1. Fork 项目并创建分支。
   ```bash
   git clone https://github.com/你的用户名/subly.git
   cd subly
   git checkout -b feature/your-feature-name
   # 或：git checkout -b fix/bug-fix-name
   ```

2. 修改代码并本地验证。

3. 提交更改。
   ```bash
   git add <需要提交的文件>
   git commit -m "feat: 添加功能描述"
   ```

4. 推送并创建 Pull Request。
   ```bash
   git push origin feature/your-feature-name
   ```

推荐使用 [Conventional Commits](https://www.conventionalcommits.org/)：

- `feat:` 新功能
- `fix:` 修复 Bug
- `docs:` 文档更新
- `style:` 代码格式（不改逻辑）
- `refactor:` 重构代码
- `perf:` 性能优化
- `test:` 添加或更新测试
- `chore:` 其他更改

---

## 本地开发

### 后端

```bash
cd backend
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# macOS / Linux:
# source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

后端默认读取项目根目录或当前工作目录下的 `.env`。可参考根目录 `.env.example` 配置 `JWT_SECRET`、`ADMIN_*`、SMTP、图标库和日志等变量。

可选开发工具：

```bash
pip install black flake8 pytest
black backend/
flake8 backend/
pytest
```

> 当前仓库没有强制提交这些开发工具配置；如果你的改动只涉及文档或前端，可以按实际影响选择验证命令。

### 前端

```bash
cd frontend
npm install
npm run dev
npm run build
```

当前 `frontend/package.json` 中只有以下脚本：

- `npm run dev`
- `npm run build`
- `npm run preview`

请不要在贡献说明或 PR 检查中要求运行尚未定义的 `npm run lint`、`npm run format` 或 `npm test`，除非对应脚本已经在同一个 PR 中新增。

### Docker / Compose 验证

修改 Dockerfile、compose 文件或环境变量示例时，建议至少运行：

```bash
docker compose -f docker-compose.yml config
docker compose -f docker-compose.hub.yml config
```

修改前端或全栈行为时，建议运行：

```bash
npm --prefix frontend run build
```

---

## 代码与文档风格

### 通用规则

- 写法要贴近周围代码：命名、注释密度、组件拆分和错误处理保持一致。
- 一次提交尽量只做一件事，PR 保持可审查。
- 不要把真实密码、Token、API key、Device Key、SMTP 授权码写入示例或测试数据。
- 新增用户可见文案时同步中文文案；项目不再维护英文 / 俄文语言包。
- 日期字符串 `YYYY-MM-DD` 相关逻辑需注意本地日期解析，避免 UTC 偏移。
- 金额展示优先使用已有工具与组件（如 `MoneyText`、金额工具函数），避免重复实现。

### 不要提交本地生成内容

提交前确认没有加入以下内容：

- `.claude/`
- `frontend/node_modules/`
- `frontend/dist/`
- `backend/data/`
- `__pycache__/`
- `.pytest_cache/`
- `.venv/`、`venv/`
- SQLite 数据库文件（如 `*.db`、`*.sqlite`、`*.sqlite3`）
- 上传图标、图标库缓存、备份文件
- `.env` 或包含真实密钥的配置文件

建议提交前检查：

```bash
git status --short
git diff --check
```

---

## 文档同步清单

如果 PR 改动了用户可见功能、部署配置、环境变量、数据模型、通知通道、图标库行为或权限逻辑，请同步检查以下文件：

- `README.md` — 项目介绍、功能特性、快速开始、环境变量、FAQ。
- `DOCKERHUB.md` — 镜像页说明、快速启动、compose 示例。
- `各厂家NAS安装教程.md` — NAS 用户可操作步骤、环境变量、排障 FAQ。
- `技术方案.md` — 架构、数据模型、外部 API、安全与隐私约束。
- `CHANGELOG.md` — 在 `[Unreleased]` 记录重要变更。
- `.env.example` — 以 `backend/app/config.py` 为准同步配置示例。
- `docker-compose.yml` / `docker-compose.hub.yml` — 注释和示例环境变量保持一致。
- `.github/pull_request_template.md` — 如果流程或检查项变化，更新模板。

文档中不要承诺尚未实现的功能；如果是计划项，请明确标注为计划，不要写成已支持。

---

## Pull Request 流程

提交 PR 前建议确认：

1. 工作区只包含本次需要提交的文件。
2. 没有提交本地生成目录、数据库、缓存或密钥。
3. 相关文档与 `.env.example` 已同步。
4. 已运行与你的改动相关的验证命令，并在 PR 中写清楚结果。
5. 如果修改数据模型，已考虑旧 SQLite 数据库的迁移路径。
6. 如果修改通知、图标下载、备份恢复或用户权限，已检查失败路径和敏感信息日志。

维护者合并前会审查代码、文档、部署影响与安全影响；需要修改时请根据审查意见继续提交到同一分支。

### 维护者发布流程

- `main` 分支推送后会触发 Docker 镜像构建与发布。
- 需要手动发布指定镜像版本时，在 GitHub Actions 中运行 **Build and Publish Docker image**，填写版本号（如 `1.0.0`）。工作流会校验 Docker tag 格式，并同时推送 `latest` 与指定版本。
- 发布前确认工作区没有 `.claude/`、`frontend/node_modules/`、`frontend/dist/`、`backend/data/`、`__pycache__/` 等本地生成内容。

---

## 设计与体验贡献

改进 UI/UX 时，请尽量遵循当前“续费雷达 / 深色控制台”的视觉语言：

- 信息层级清晰，优先突出到期风险、支出金额和提醒状态。
- 操作入口按使用频率排序，避免把管理动作压过日常账本操作。
- 管理类页面保持雷达卡片、状态标签、信号点、分段控件等既有组件风格。
- 视觉调整不应破坏移动端布局。

---

## 许可

通过贡献代码或文档，你同意将你的贡献放在项目的 [MIT License](./LICENSE) 下。

感谢每一个改进，无论大小。

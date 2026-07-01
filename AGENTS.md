# AGENTS.md — Subly 接手工作规范

> 本文件是 Subly 项目所有 AI 编程工具（Claude Code、Cursor、Copilot、Gemini、Aider 等）与人类贡献者在接手开发时必须遵守的权威规范。`CLAUDE.md` 指向本文件，不重复内容。

## 项目简介

Subly（省心订阅）是自托管的订阅 / 续费 / 保号管理系统：内置 SQLite 零配置，中文单语言界面，Telegram + Bark 双通道提醒，多用户审核，备份恢复，实时日志。部署形态为单 Docker 镜像（前端构建产物由 FastAPI 静态托管）。

## 技术栈

| 层 | 选型 |
|----|------|
| 后端 | Python 3.12 · FastAPI · SQLAlchemy · APScheduler · pydantic-settings · SQLite |
| 前端 | Vue 3（`<script setup>`）· Vite · Pinia · Vue Router · vue-i18n（仅中文 `zh`） |
| 部署 | Docker 多阶段构建（`node:20-alpine` → `python:3.12-slim`）· 可选 Caddy |
| 测试 | 后端 pytest · 前端 Vitest |

前端无路径别名，统一用相对路径导入。

## 工作流程

整体节奏：**理解 → 探索 → 设计 → 实现 → 验证 → 审核 → 提交**。每一步都要能描述清楚自己做了什么，不静默跳过任何环节。

### 1. 理解需求
- 明确假设，不确定就问；存在歧义时呈现多种解读让用户选择。
- 先定义成功标准（做完什么算"成了"），再动手。
- 判断规模：trivial 直接做；非平凡任务先进 plan mode，探索后给计划。

### 2. 探索代码
- **先读再写**：动代码前看清导出、调用方、共享工具，"看起来正交"很危险。
- 改动前主动查找可复用的现有函数 / 组件 / 工具，避免重复实现。Subly 已抽取：`utils/date.js`、`utils/money.js`、`utils/renewal.js`、`ServiceIcon.vue`、`MoneyText.vue`、`StatusChip.vue`、`RadarBars.vue`、`AppModal.vue`，以及后端 `icon_library.normalize_category_keys`、`billing.compute_next_renewal` 等。
- 节约上下文：窄读文件范围，限制日志/diff，不做全量快照。

### 3. 设计
- **简单优先**：最小可行代码，不做投机性抽象。问自己"资深工程师会觉得过度复杂吗"。
- 发现两种冲突的写法，挑一个（更近期 / 更经过验证的），另一个标记待清理，不要混用。

### 4. 实现
- **外科手术式改动**：只动必须动的，不顺手"改进"相邻代码、注释或格式；匹配现有风格。
- 多步任务用任务清单跟踪，开始前置 in_progress，完成后置 completed。

### 5. 验证（按改动范围跑相应命令，loop until verified）

| 改动类型 | 验证命令 |
|---------|---------|
| 后端逻辑 | `cd backend && python -m pytest`（必要时 `python -m compileall app`）|
| 前端逻辑 | `cd frontend && npm test` |
| 前端构建 | `cd frontend && npm run build` |
| 全栈 / 格式 | `git diff --check` |
| Docker 配置 | `docker compose -f docker-compose.yml config` |

- 跳过的测试、没跑的命令都要明说，不能假装"完成"或"测试通过"。
- 新增测试要能因业务逻辑改变而失败，而不是只复述实现。

### 6. 审核
- 非平凡改动提交前做 code review（多角度审查 → 验证 → sweep），发现问题修复后复审到无确认问题。
- 同步文档：动了用户可见功能 / 环境变量 / 数据模型 / 部署方式 / 通知通道 / 图标库行为 / 权限逻辑时，按下方「文档同步清单」同步相关文件。
- 清理本轮生成的临时产物：`__pycache__/`、`.pytest_cache/`、`frontend/dist/`。

### 7. 提交推送
- 用 Conventional Commits：`feat:` / `fix:` / `docs:` / `chore:` / `test:` / `refactor:` / `perf:`。
- 末尾加 `Co-Authored-By: Claude <noreply@anthropic.com>`（若使用 Claude）。
- 提交前确认 `git status --short` 只含应提交文件；用显式 `git add <具体文件>`，不要 `git add .`，避免误纳生成目录。
- **本仓库直接推 `main`，不开功能分支、不走 PR**（除非用户另行要求）。

## 项目特有硬约束

1. **直接推 main**：用户说"推送到 GitHub"即发布到 `main`。
2. **绝不提交本地生成目录**：`.claude/`、`frontend/node_modules/`、`frontend/dist/`、`backend/data/`、`__pycache__/`、`.pytest_cache/`、`.venv/`、`*.db` / `*.sqlite`、上传图标、图标缓存、备份文件、`.env`。
3. **中文单语言**：界面只维护 `frontend/src/i18n/index.js` 中的 `zh` 文案，不引入英文 / 俄文。
4. **代码完成后先审核再推送**：用户习惯先 code review，再提交。
5. **不泄露敏感信息**：不要把真实密码 / Token / API key / Device Key / SMTP 授权码写进示例、测试或文档；示例只用占位值。
6. **日期字符串 `YYYY-MM-DD`** 一律按本地日期解析，避免 UTC 偏移导致日期错位一天。
7. **金额展示**优先复用 `MoneyText` 与金额工具函数，避免重复实现。

## 提交规范

单个语义提交，正文说明做了什么 / 为什么 / 如何验证：

```
<type>: <一句话摘要>

- 要点1
- 要点2

Validated with <命令>; code-review ([]).
Co-Authored-By: Claude <noreply@anthropic.com>
```

## 文档同步清单

改动影响以下面时，同步对应文件（以 `backend/app/config.py` / `models.py` 为代码事实源头）：

- 用户可见功能 / 快速开始 / 环境变量 / FAQ → `README.md`
- 镜像页 / compose 示例 → `DOCKERHUB.md`
- NAS 操作步骤 / 排障 → `各厂家NAS安装教程.md`
- 架构 / 数据模型 / 外部 API / 安全约束 → `技术方案.md`
- 重要变更 → `CHANGELOG.md`（`[Unreleased]`）
- 配置示例 → `.env.example`
- compose 注释 / 示例变量 → `docker-compose.yml`、`docker-compose.hub.yml`
- 流程 / 检查项变化 → `.github/pull_request_template.md`

文档不承诺尚未实现的功能；计划项要明确标注为计划。

## 核心原则（精简版）

1. **想清楚再写**：不确定就问，给多种解读，遇到更简单的方案要顶回去。
2. **简单优先**：最小代码解决问题，无投机抽象。
3. **外科手术式改动**：只动该动的，清理只清自己的。
4. **目标驱动**：定义成功标准，loop until verified。
5. **判断用模型，确定性用代码**：路由 / 重试 / 确定性转换不要塞给 LLM。
6. **主动节约上下文**：窄读、限日志、必要时压缩 checkpoint。
7. **冲突要选一个**，不要平均，另一个标待清理。
8. **先读再写**："看起来正交"很危险，不懂为什么这样写就问。
9. **测试验证意图**：测 WHY，不是只测 WHAT。
10. **每完成一步就 checkpoint**：说不清当前状态就停下重述。
11. **遵守约定**：conformance > taste；觉得有害就提出来，不静默 fork。
12. **失败要响亮**：跳过的、没验证的都要说出来。

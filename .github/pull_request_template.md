## 变更说明

请简要说明这个 PR 做了什么、为什么需要这个改动。

## 相关 Issue

Closes #

## 变更类型

- [ ] Bug 修复
- [ ] 新功能
- [ ] 文档更新
- [ ] 代码重构
- [ ] 性能优化
- [ ] 部署 / CI 调整
- [ ] 其他：

## 测试与验证

请列出你实际运行过的验证命令和结果。

- [ ] `cd backend && python -m pytest`
- [ ] `cd backend && python -m ruff check app`
- [ ] `npm --prefix frontend run lint`
- [ ] `npm --prefix frontend test`
- [ ] `npm --prefix frontend run build`
- [ ] `python -m pip_audit -r backend/requirements.txt`（如有告警已记录）
- [ ] `npm --prefix frontend audit --audit-level=high`
- [ ] `npm --prefix frontend run e2e`（已启动构建后的服务）
- [ ] `docker compose -f docker-compose.yml config`
- [ ] `docker compose -f docker-compose.hub.yml config`
- [ ] `git diff --check`
- [ ] 其他：

## 文档同步检查

如果改动影响用户可见功能、环境变量、数据模型、部署方式、通知通道、图标库或权限逻辑，请勾选已同步的文档。

- [ ] `README.md`
- [ ] `DOCKERHUB.md`
- [ ] `各厂家NAS安装教程.md`
- [ ] `技术方案.md`
- [ ] `CHANGELOG.md`
- [ ] `.env.example`
- [ ] 不涉及文档同步

## 配置 / 部署影响

- [ ] 新增或修改环境变量
- [ ] 需要数据库迁移或兼容旧数据
- [ ] 影响 Dockerfile / compose / 端口 / 数据卷
- [ ] 影响通知、图标下载、备份恢复或用户权限
- [ ] 不涉及配置或部署影响

说明：

## 安全与隐私检查

- [ ] 没有提交真实密码、Token、API key、Device Key、SMTP 授权码或 `.env`
- [ ] 日志没有新增敏感信息输出
- [ ] 备份、导入、通知或外部请求相关改动已检查失败路径
- [ ] 不涉及安全或隐私影响

## 本地生成内容检查

- [ ] 未提交 `.claude/`
- [ ] 未提交 `frontend/node_modules/`
- [ ] 未提交 `frontend/dist/`
- [ ] 未提交 `backend/data/`
- [ ] 未提交 `__pycache__/`、`.pytest_cache/`、`.venv/` 等缓存或虚拟环境
- [ ] 未提交数据库文件、上传图标、图标缓存或备份文件
- [ ] Docker build context 已由 `.dockerignore` 排除上述本地产物

## 截图 / 录屏（如涉及 UI）

请在此处附上前后对比截图或录屏。

## 备注

还有什么审查者需要特别注意？

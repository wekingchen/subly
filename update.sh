#!/usr/bin/env bash
# 省心订阅 Subly —— 增量升级脚本（不会清空数据）
#
# 用法：在项目目录执行  ./update.sh
# 作用：拉取最新代码 → 仅重建 app 镜像（复用未变更的层）→ 重启 app 容器 → 清理悬空镜像
# 数据安全：你的订阅数据在【外部 MySQL】，连接配置与图标在命名卷 app_data 中，
#          本脚本不使用 `down -v`，不会触碰这些数据。
set -e

cd "$(dirname "$0")"

echo "==> 1/4 拉取最新代码 (git pull)"
if [ -d .git ]; then
  git pull --ff-only
else
  echo "    跳过：当前目录不是 git 仓库（请手动覆盖最新代码后再运行）"
fi

echo "==> 2/4 重建并启动 app（自动复用缓存层，依赖未变则很快）"
docker compose up -d --build app

echo "==> 3/4 等待健康检查"
sleep 3
docker compose ps

echo "==> 4/4 清理悬空镜像，释放磁盘"
docker image prune -f >/dev/null 2>&1 || true

echo "✅ 升级完成。数据与数据库连接均已保留。"
echo "   查看日志： docker compose logs -f app"

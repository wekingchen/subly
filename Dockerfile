# ---------- 阶段 1：构建前端 ----------
FROM node:20-alpine AS frontend
WORKDIR /fe
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---------- 阶段 2：后端运行时 ----------
FROM python:3.12-slim AS backend
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

COPY backend/ ./
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
# 把前端构建产物放到 FastAPI 静态目录（单服务托管）
COPY --from=frontend /fe/dist ./frontend_dist

RUN groupadd --system --gid 10001 subly \
    && useradd --system --uid 10001 --gid subly --home-dir /app --shell /usr/sbin/nologin subly \
    && mkdir -p data/icons/library \
    && chown -R subly:subly /app \
    && chmod 0755 /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import database, migrate
from app.config import settings
from app.routers import (
    admin,
    admin_diagnostics,
    auth,
    backup,
    bundles,
    categories,
    currencies,
    dashboard,
    icons,
    icon_admin,
    logs,
    notifications,
    payment_methods,
    reports,
    subscriptions,
    system,
    users,
)
from app.seed import seed_all
from app.services import scheduler

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
    stream=sys.stdout,
    force=True,
)
# httpx 的 INFO 日志会包含完整请求 URL/query；避免 EXCHANGE_API_KEY 等敏感参数进入 docker logs。
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 内置 SQLite，零配置：直接建库 / 建表 / 跑迁移 / 写预置数据 / 启动定时任务
    database.init_engine()
    database.Base.metadata.create_all(bind=database.engine)
    migrate.run_migrations(database.engine)
    db = database.SessionLocal()
    try:
        seed_all(db)
    finally:
        db.close()
    scheduler.start_scheduler()
    logger.info("event=startup db_url=%s", database.build_url())
    yield
    scheduler.shutdown_scheduler()


app = FastAPI(title="Subly API", version="2.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _client_host(request: Request) -> str:
    return request.client.host if request.client else "-"


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """记录请求耗时、慢请求与未处理异常；不记录 body/query/header。"""
    request_id = uuid4().hex[:12]
    request.state.request_id = request_id
    path = request.url.path
    start = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception as e:  # noqa: BLE001
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.exception(
            "event=request_exception request_id=%s method=%s path=%s duration_ms=%s "
            "user_id=%s client=%s error_type=%s",
            request_id,
            request.method,
            path,
            duration_ms,
            getattr(request.state, "user_id", "-"),
            _client_host(request),
            type(e).__name__,
        )
        raise

    response.headers["X-Request-ID"] = request_id
    duration_ms = int((time.perf_counter() - start) * 1000)
    if path == "/api/health":
        logger.debug(
            "event=request_done request_id=%s method=%s path=%s status_code=%s "
            "duration_ms=%s user_id=%s client=%s",
            request_id,
            request.method,
            path,
            response.status_code,
            duration_ms,
            getattr(request.state, "user_id", "-"),
            _client_host(request),
        )
        return response

    level = logging.ERROR if response.status_code >= 500 else logging.INFO
    logger.log(
        level,
        "event=request_done request_id=%s method=%s path=%s status_code=%s "
        "duration_ms=%s user_id=%s client=%s",
        request_id,
        request.method,
        path,
        response.status_code,
        duration_ms,
        getattr(request.state, "user_id", "-"),
        _client_host(request),
    )
    if duration_ms >= settings.slow_request_ms:
        logger.warning(
            "event=slow_request request_id=%s method=%s path=%s status_code=%s "
            "duration_ms=%s threshold_ms=%s user_id=%s client=%s",
            request_id,
            request.method,
            path,
            response.status_code,
            duration_ms,
            settings.slow_request_ms,
            getattr(request.state, "user_id", "-"),
            _client_host(request),
        )
    return response


for r in (
    auth.router,
    users.router,
    categories.router,
    payment_methods.router,
    currencies.router,
    subscriptions.router,
    bundles.router,
    dashboard.router,
    reports.router,
    notifications.router,
    icons.router,
    icon_admin.router,
    admin.router,
    admin_diagnostics.router,
    logs.router,
    system.router,
    backup.router,
):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"status": "ok", "configured": database.is_configured()}


# 静态资源（上传的图标）
os.makedirs(os.path.join("data", "icons"), exist_ok=True)
app.mount("/static/icons", StaticFiles(directory=os.path.join("data", "icons")), name="icons")

# 前端构建产物（若存在则托管，实现单服务部署 + SPA history 路由兜底）
_frontend_dist = os.path.join("frontend_dist")
if os.path.isdir(_frontend_dist):
    _assets = os.path.join(_frontend_dist, "assets")
    if os.path.isdir(_assets):
        app.mount("/assets", StaticFiles(directory=_assets), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        candidate = os.path.join(_frontend_dist, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_frontend_dist, "index.html"))

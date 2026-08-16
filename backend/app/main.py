from __future__ import annotations

import asyncio
import sqlite3
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.app.api import (
    accounts,
    ai,
    alerts,
    analytics,
    auth,
    content,
    customers,
    dashboard,
    gifts,
    logs,
    model_configs,
    monitoring,
    profile,
    products,
    promotions,
    stores,
    tasks,
)
from backend.app.api.auth import get_current_user, require_admin, require_module
from backend.app.api.promotions import sync_promo_items_realtime_all, sync_promo_realtime_all
from backend.app.api.stores import run_inspect_once, sync_all_stores, sync_hourly_all, sync_items_realtime_all
from backend.app.core.db import DB_PATH, init_db
from backend.app.core.modules import get_modules


async def _inspect_loop() -> None:
    """店铺自动巡检：每 5 分钟检查一次授权与健康状态。"""
    while True:
        try:
            run_inspect_once()
        except Exception:
            pass
        await asyncio.sleep(300)


def _run_sycm_sync() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        sync_all_stores(conn)
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def _run_realtime_sync() -> None:
    """每 3 分钟全量同步：店铺日数据 + 分时（今日/昨日）+ 推广实时分时 + 商品实时 + 商品级实时推广。"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        sync_all_stores(conn)
        sync_hourly_all(conn)
        sync_promo_realtime_all(conn)
        sync_items_realtime_all(conn)
        sync_promo_items_realtime_all(conn)
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


async def _realtime_sync_loop() -> None:
    """数据自动同步：每 3 分钟同步一次所有数据，保持页面实时刷新。"""
    await asyncio.sleep(30)  # 启动后先等服务就绪，避免开机即抢占资源
    while True:
        try:
            await asyncio.to_thread(_run_realtime_sync)
        except Exception:
            pass
        await asyncio.sleep(180)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_inspect_loop())
    realtime_task = asyncio.create_task(_realtime_sync_loop())
    yield
    task.cancel()
    realtime_task.cancel()


def create_app() -> FastAPI:
    app = FastAPI(title="淘宝运营工作台 API", version="0.1.0", lifespan=lifespan)
    init_db()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:5174",
            "http://127.0.0.1:5174",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/", tags=["info"])
    def root() -> dict:
        """服务根路径：打开后端地址时展示基本信息，而不是 404。"""
        return {
            "service": "淘宝运营工作台 API",
            "version": app.version,
            "docs": "/docs",
            "health": "/api/health",
            "modules": "/api/modules",
            "auth": "/api/auth",
            "module_ids": [m["id"] for m in get_modules()],
        }

    @app.get("/api/health", tags=["health"])
    def health() -> dict:
        return {"status": "ok", "service": "taobao-workbench"}

    @app.get("/api/modules", tags=["modules"])
    def modules(user: dict = Depends(get_current_user)) -> dict:
        all_modules = get_modules()
        if user["role"] in ("admin", "super_admin"):
            return {"items": all_modules}
        allowed = user["allowed_modules"]
        if allowed is None:
            return {"items": [m for m in all_modules if m["id"] not in ("accounts", "logs")]}
        ids = set(allowed) | {"dashboard", "profile"}
        return {
            "items": [m for m in all_modules if m["id"] in ids and m["id"] not in ("accounts", "logs")]
        }

    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(
        alerts.router,
        prefix="/api/alerts",
        tags=["alerts"],
        dependencies=[Depends(get_current_user)],
    )
    app.include_router(
        profile.router,
        prefix="/api/profile",
        tags=["profile"],
        dependencies=[Depends(get_current_user)],
    )
    app.include_router(
        accounts.router,
        prefix="/api/accounts",
        tags=["accounts"],
        dependencies=[Depends(require_admin)],
    )
    app.include_router(
        logs.router,
        prefix="/api/logs",
        tags=["logs"],
        dependencies=[Depends(require_admin)],
    )
    avatar_dir = DB_PATH.parent / "avatars"
    avatar_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/api/avatars", StaticFiles(directory=str(avatar_dir)), name="avatars")
    qr_dir = DB_PATH.parent / "images"
    qr_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/api/images", StaticFiles(directory=str(qr_dir)), name="images")

    protected = [
        (dashboard.router, "/api/dashboard", "dashboard"),
        (stores.router, "/api/stores", "stores"),
        (products.router, "/api/products", "products"),
        (gifts.router, "/api/gifts", "gifts"),
        (customers.router, "/api/customers", "customers"),
        (analytics.router, "/api/analytics", "analytics"),
        (promotions.router, "/api/promotions", "promotions"),
        (content.router, "/api/content", "content"),
        (monitoring.router, "/api/monitoring", "monitoring"),
        (tasks.router, "/api/tasks", "tasks"),
        (model_configs.router, "/api/model-configs", "model-configs"),
        (ai.router, "/api/ai", "ai"),
    ]
    for router, prefix, tag in protected:
        app.include_router(
            router,
            prefix=prefix,
            tags=[tag],
            dependencies=[Depends(require_module(tag))],
        )

    return app


app = create_app()

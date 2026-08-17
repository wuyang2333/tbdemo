from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

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
    settings,
    stores,
    system,
    tasks,
)
from backend.app.api.auth import get_current_user, require_admin, require_module
from backend.app.api.promotions import (
    sync_promo_daily_all,
    sync_promo_items_realtime_all,
    sync_promo_realtime_all,
)
from backend.app.api.stores import (
    run_inspect_once,
    sync_all_stores,
    sync_hourly_all,
    sync_items_daily_all,
    sync_items_realtime_all,
)
from backend.app.core import loops
from backend.app.core.db import DB_PATH, connect_db, init_db
from backend.app.core.modules import get_modules


async def _inspect_loop() -> None:
    """店铺自动巡检：每 5 分钟检查一次授权与健康状态。"""
    while True:
        _start = time.monotonic()
        try:
            run_inspect_once()
            loops.record_success("inspect", time.monotonic() - _start)
        except Exception as _e:
            loops.record_error("inspect", _e, time.monotonic() - _start)
        await asyncio.sleep(300)


def _run_sycm_sync() -> None:
    conn = connect_db()
    try:
        sync_all_stores(conn)
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def _run_realtime_sync() -> None:
    """每 3 分钟全量同步：店铺日数据 + 分时（今日/昨日）+ 推广实时分时 + 商品实时 + 商品级实时推广。

    单点隔离：5 类数据各自 try/commit，单个失败不影响其他 4 类。
    """
    conn = connect_db()
    steps = [
        ("店铺日数据", lambda: sync_all_stores(conn)),
        ("分时数据", lambda: sync_hourly_all(conn)),
        ("推广实时分时", lambda: sync_promo_realtime_all(conn)),
        ("商品实时", lambda: sync_items_realtime_all(conn)),
        ("商品级推广", lambda: sync_promo_items_realtime_all(conn)),
    ]
    errors: list[str] = []
    for step_name, fn in steps:
        try:
            fn()
            conn.commit()
        except Exception as e:
            errors.append(f"{step_name}: {e}")
            try:
                conn.rollback()
            except Exception:
                pass
    conn.close()
    if errors:
        raise RuntimeError("; ".join(errors)[:300])


async def _realtime_sync_loop() -> None:
    """数据自动同步：每 3 分钟同步一次所有数据，保持页面实时刷新。"""
    await asyncio.sleep(30)  # 启动后先等服务就绪，避免开机即抢占资源
    while True:
        _start = time.monotonic()
        try:
            await asyncio.to_thread(_run_realtime_sync)
            loops.record_success("realtime_sync", time.monotonic() - _start)
        except Exception as _e:
            loops.record_error("realtime_sync", _e, time.monotonic() - _start)
        await asyncio.sleep(180)


def _run_report_push_once() -> None:
    """定时推送经营日报：到点且已启用推送时，生成日报文本发到群机器人。异常向上抛给循环层记录。"""
    conn = connect_db()
    try:
        from datetime import datetime

        from backend.app.api.analytics import (
            _report_push_config,
            _report_text_lines,
            daily_report,
            send_report_webhook,
        )

        cfg = _report_push_config(conn)
        if not cfg.get("enabled") or not cfg.get("webhook"):
            return
        now = datetime.now()
        if now.hour == int(cfg.get("hour") or 0) and now.minute == int(cfg.get("minute") or 0):
            report = daily_report(date="", store_id=None, user=None, db=conn)
            text = "\n".join(_report_text_lines(report))
            send_report_webhook(cfg["webhook"], text)
            loops.log_event("report_push", f"已推送经营日报（{now:%Y-%m-%d %H:%M}）")
    finally:
        conn.close()


async def _report_push_loop() -> None:
    """日报推送循环：每分钟检查一次是否到点。"""
    await asyncio.sleep(25)
    while True:
        _start = time.monotonic()
        try:
            await asyncio.to_thread(_run_report_push_once)
            loops.record_success("report_push", time.monotonic() - _start)
        except Exception as _e:
            loops.record_error("report_push", _e, time.monotonic() - _start)
        await asyncio.sleep(60)


def _run_hourly_push_once() -> None:
    """小时异常推送：检查上个小时数据，触发规则则推送到微信（pushplus）。异常向上抛给循环层记录。"""
    conn = connect_db()
    try:
        from backend.app.api.alerts import _hourly_push_config, check_hourly_rules, send_hourly_push

        cfg = _hourly_push_config(conn)
        if not cfg.get("enabled") or not cfg.get("token"):
            return
        messages = check_hourly_rules(conn, cfg)
        if messages:
            sent = send_hourly_push(cfg, "店铺小时异常提醒", "\n".join(messages))
            if sent:
                loops.log_event(
                    "hourly_push",
                    f"已推送小时异常提醒（{' + '.join(sent)}，{len(messages)} 条规则触发）",
                )
            else:
                loops.log_event(
                    "hourly_push",
                    f"未发送小时异常提醒：推送渠道未配置完整（{len(messages)} 条规则触发）",
                )
    finally:
        conn.close()


async def _hourly_push_loop() -> None:
    """小时异常检查循环：每个整点过 5 分检查一次上个小时。"""
    await asyncio.sleep(40)
    last_key = ""
    while True:
        try:
            from datetime import datetime

            now = datetime.now()
            key = now.strftime("%Y-%m-%d %H")
            if now.minute >= 5 and last_key != key:
                last_key = key
                _start = time.monotonic()
                try:
                    await asyncio.to_thread(_run_hourly_push_once)
                    loops.record_success("hourly_push", time.monotonic() - _start)
                except Exception as _e:
                    loops.record_error("hourly_push", _e, time.monotonic() - _start)
        except Exception as _e:
            loops.record_error("hourly_push", _e, 0.0)
        await asyncio.sleep(60)


def _run_promo_daily_once() -> None:
    """每日补数：推广按天（日报推广数据）+ 商品按天（日报 TOP 商品），各同步近 7 天。"""
    conn = connect_db()
    try:
        sync_promo_daily_all(conn, days=7)
        conn.commit()
        sync_items_daily_all(conn, days=7)
        conn.commit()
    finally:
        conn.close()


async def _promo_daily_loop() -> None:
    """按天数据每日同步：启动后先补一次近 7 天，之后每天早上 9:00 再跑一次。

    覆盖场景：日报的推广/商品按天数据此前无自动同步，只靠手动 sync 才写入。
    """
    # 延后到 90 秒：避开启动后实时同步（30s）的首轮窗口，减少并发写库冲突
    await asyncio.sleep(90)
    last_key = ""
    while True:
        now = datetime.now()
        key = now.strftime("%Y-%m-%d")
        should_run = (now.hour == 9) or not last_key
        if should_run and last_key != key:
            last_key = key
            _start = time.monotonic()
            loops.mark_running("promo_daily")
            loops.log_event("promo_daily", "开始补数（近 7 天推广 + 商品按天）")
            try:
                await asyncio.to_thread(_run_promo_daily_once)
                loops.record_success("promo_daily", time.monotonic() - _start)
            except Exception as _e:
                loops.record_error("promo_daily", _e, time.monotonic() - _start)
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    for _name in ("inspect", "realtime_sync", "report_push", "hourly_push", "promo_daily"):
        loops.register(_name)
    task = asyncio.create_task(_inspect_loop())
    realtime_task = asyncio.create_task(_realtime_sync_loop())
    push_task = asyncio.create_task(_report_push_loop())
    hourly_push_task = asyncio.create_task(_hourly_push_loop())
    promo_task = asyncio.create_task(_promo_daily_loop())
    yield
    task.cancel()
    realtime_task.cancel()
    push_task.cancel()
    hourly_push_task.cancel()
    promo_task.cancel()


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

    @app.get("/api", tags=["info"])
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
            return {
                "items": [m for m in all_modules if m["id"] not in ("accounts", "logs", "settings")]
            }
        ids = set(allowed) | {"dashboard", "profile"}
        return {
            "items": [
                m for m in all_modules if m["id"] in ids and m["id"] not in ("accounts", "logs", "settings")
            ]
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
        system.router,
        prefix="/api/system",
        tags=["system"],
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
    app.include_router(
        settings.router,
        prefix="/api/settings",
        tags=["settings"],
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


# ---- 生产模式：托管前端构建产物（frontend/dist 存在时）----
# 开发模式（vite dev :5173）不受影响；打包分发时用单端口 8000 访问页面。
_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    from fastapi.responses import FileResponse, JSONResponse

    @app.get("/{full_path:path}", include_in_schema=False)
    def _serve_frontend(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = _FRONTEND_DIST / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        # SPA fallback：深路径（如 /stores）刷新时回退到 index.html
        return FileResponse(_FRONTEND_DIST / "index.html")

"""SQLite 数据层：账号、令牌持久化。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "taobao.db"


def get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """老库补列 + 兜底：没有管理员时，最早的账号自动成为管理员。"""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
    if "role" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'member'")
    if "status" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
    if "allowed_modules" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN allowed_modules TEXT")
    if "avatar_url" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN avatar_url TEXT")
    if "current_store_id" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN current_store_id INTEGER")
    if "allowed_store_ids" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN allowed_store_ids TEXT")
    conn.commit()

    super_admin = conn.execute("SELECT id FROM users WHERE role = 'super_admin' LIMIT 1").fetchone()
    if not super_admin:
        first = conn.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1").fetchone()
        if first:
            conn.execute("UPDATE users SET role = 'super_admin' WHERE id = ?", (first["id"],))
            conn.commit()

    # 模块更名迁移：旧权限里的 "orders" 同步为 "gifts"
    conn.execute("UPDATE users SET allowed_modules = REPLACE(allowed_modules, ?, ?)", ('"orders"', '"gifts"'))
    conn.commit()


def _seed_stores(conn: sqlite3.Connection) -> None:
    """首次运行时写入几家演示店铺，方便查看健康状态效果。"""
    count = conn.execute("SELECT COUNT(*) AS c FROM stores").fetchone()["c"]
    if count > 0:
        return
    now = datetime.now(timezone.utc)
    demo = [
        (
            "淘品甄选旗舰店", "林晓", "女装", "天猫旗舰店", "浙江·杭州",
            4.9, 4.8, 4.9, "active", (now + timedelta(days=90)).isoformat(),
        ),
        (
            "美妆优选专营店", "陈默", "美妆", "皇冠店", "广东·广州",
            4.7, 4.6, 4.8, "active", (now + timedelta(days=9)).isoformat(),
        ),
        (
            "零食星球集市店", "周舟", "食品", "五钻店", "四川·成都",
            4.8, 4.7, 4.9, "stopped", (now - timedelta(days=10)).isoformat(),
        ),
        (
            "家居生活体验店", "苏晴", "家居", "四钻店", "江苏·苏州",
            4.6, 4.5, 4.7, "active", (now - timedelta(days=3)).isoformat(),
        ),
    ]
    conn.executemany(
        """
        INSERT INTO stores (name, owner, category, level, location, dsr_desc, dsr_service, dsr_logistics, status, auth_expires_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [(*item, now.isoformat()) for item in demo],
    )
    conn.commit()


def _migrate_logs(conn: sqlite3.Connection) -> None:
    """把旧的店铺日志迁移进统一操作日志表。"""
    count = conn.execute("SELECT COUNT(*) AS c FROM op_logs").fetchone()["c"]
    if count == 0:
        conn.execute(
            """
            INSERT INTO op_logs (module, user_id, username, action, target_name, detail, created_at)
            SELECT 'stores', user_id, username, action, target_name, detail, created_at FROM store_logs
            """
        )
        conn.commit()


def _seed_gifts(conn: sqlite3.Connection) -> None:
    """首次运行时给每家演示店铺写入几笔礼品单。"""
    count = conn.execute("SELECT COUNT(*) AS c FROM gifts").fetchone()["c"]
    if count > 0:
        return
    now = datetime.now(timezone.utc)
    sample = [
        (1, "中秋伴手礼盒", "张小雅", 2, 168.0, "pending", 1),
        (1, "联名保温杯", "李明远", 1, 89.0, "shipped", 3),
        (1, "定制丝巾", "王芳", 3, 129.0, "delivered", 8),
        (2, "精华旅行装", "陈乐乐", 5, 59.0, "shipped", 2),
        (2, "口红礼盒", "赵婷", 2, 199.0, "pending", 0),
        (3, "坚果大礼包", "周舟", 4, 138.0, "delivered", 12),
        (4, "香薰蜡烛套装", "苏晴", 2, 99.0, "refunded", 1),
        (4, "乳胶枕", "刘阿姨", 1, 259.0, "pending", 1),
    ]
    rows = []
    for idx, (store_id, gift_name, recipient, quantity, price, status, days_ago) in enumerate(sample, start=1):
        created = (now - timedelta(days=days_ago)).isoformat()
        rows.append(
            (
                store_id,
                f"G{now.strftime('%y%m%d')}{idx:03d}",
                recipient,
                gift_name,
                quantity,
                price,
                status,
                created,
            )
        )
    conn.executemany(
        """
        INSERT INTO gifts (store_id, order_no, recipient, gift_name, quantity, price, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                nickname TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'member',
                status TEXT NOT NULL DEFAULT 'active',
                allowed_modules TEXT,
                avatar_url TEXT,
                current_store_id INTEGER,
                allowed_store_ids TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tokens (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                owner TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                level TEXT NOT NULL DEFAULT '',
                location TEXT NOT NULL DEFAULT '',
                dsr_desc REAL NOT NULL DEFAULT 0,
                dsr_service REAL NOT NULL DEFAULT 0,
                dsr_logistics REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                auth_expires_at TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS store_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                action TEXT NOT NULL,
                target_name TEXT NOT NULL DEFAULT '',
                detail TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS op_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                module TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                action TEXT NOT NULL,
                target_name TEXT NOT NULL DEFAULT '',
                detail TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS gifts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_id INTEGER NOT NULL,
                order_no TEXT NOT NULL,
                recipient TEXT NOT NULL DEFAULT '',
                gift_name TEXT NOT NULL DEFAULT '',
                quantity INTEGER NOT NULL DEFAULT 1,
                price REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS model_configs (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                provider TEXT NOT NULL DEFAULT 'openai',
                base_url TEXT NOT NULL DEFAULT '',
                api_key TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                temperature REAL NOT NULL DEFAULT 0.7,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
        _migrate(conn)
        _seed_stores(conn)
        _migrate_logs(conn)
        _seed_gifts(conn)
    finally:
        conn.close()

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


def _migrate_model_configs(conn: sqlite3.Connection) -> None:
    """老版本单行 model_configs 表 → 多模型列表（带名称与默认标记）。"""
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(model_configs)")}
    except sqlite3.OperationalError:
        return
    if "name" in cols:
        return
    conn.execute("ALTER TABLE model_configs RENAME TO model_configs_old")
    conn.execute(
        """
        CREATE TABLE model_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL DEFAULT '默认模型',
            provider TEXT NOT NULL DEFAULT 'openai',
            base_url TEXT NOT NULL DEFAULT '',
            api_key TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            temperature REAL NOT NULL DEFAULT 0.7,
            is_default INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO model_configs (name, provider, base_url, api_key, model, temperature, is_default, created_at, updated_at)
        SELECT '默认模型', provider, base_url, api_key, model, temperature, 1, ?, ?
        FROM model_configs_old
        """,
        (now, now),
    )
    conn.execute("DROP TABLE model_configs_old")
    conn.commit()



def _migrate_gifts(conn: sqlite3.Connection) -> None:
    """礼品单台账化：补充关键词、规格、佣金、旺旺号、评论/结款状态、下单时间。"""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(gifts)")}
    if "keyword" not in cols:
        conn.execute("ALTER TABLE gifts ADD COLUMN keyword TEXT NOT NULL DEFAULT ''")
    if "spec" not in cols:
        conn.execute("ALTER TABLE gifts ADD COLUMN spec TEXT NOT NULL DEFAULT ''")
    if "commission" not in cols:
        conn.execute("ALTER TABLE gifts ADD COLUMN commission REAL NOT NULL DEFAULT 0")
    if "wangwang" not in cols:
        conn.execute("ALTER TABLE gifts ADD COLUMN wangwang TEXT NOT NULL DEFAULT ''")
    if "review_status" not in cols:
        conn.execute("ALTER TABLE gifts ADD COLUMN review_status TEXT NOT NULL DEFAULT 'none'")
    if "settle_status" not in cols:
        conn.execute("ALTER TABLE gifts ADD COLUMN settle_status TEXT NOT NULL DEFAULT 'unsettled'")
    if "order_time" not in cols:
        conn.execute("ALTER TABLE gifts ADD COLUMN order_time TEXT")
    if "qr_code" not in cols:
        conn.execute("ALTER TABLE gifts ADD COLUMN qr_code TEXT NOT NULL DEFAULT ''")
    if "image" not in cols:
        conn.execute("ALTER TABLE gifts ADD COLUMN image TEXT NOT NULL DEFAULT ''")
    if "store_name" not in cols:
        conn.execute("ALTER TABLE gifts ADD COLUMN store_name TEXT NOT NULL DEFAULT ''")
    conn.execute("UPDATE gifts SET order_time = created_at WHERE order_time IS NULL OR order_time = ''")
    conn.execute("UPDATE gifts SET wangwang = recipient WHERE wangwang = '' AND recipient != ''")
    conn.execute("UPDATE gifts SET image = qr_code WHERE image = '' AND qr_code != ''")
    conn.execute("UPDATE gifts SET keyword = gift_name WHERE keyword = '' AND gift_name != ''")
    conn.commit()


def _migrate_analytics(conn: sqlite3.Connection) -> None:
    """数据洞察扩展字段：新老客占比 / 复购，以及分时数据表。"""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(store_daily_data)")}
    if "repeat_rate" not in cols:
        conn.execute("ALTER TABLE store_daily_data ADD COLUMN repeat_rate REAL NOT NULL DEFAULT 0")
    if "old_buyer_cnt" not in cols:
        conn.execute("ALTER TABLE store_daily_data ADD COLUMN old_buyer_cnt INTEGER NOT NULL DEFAULT 0")
    if "repeat_sales" not in cols:
        conn.execute("ALTER TABLE store_daily_data ADD COLUMN repeat_sales REAL NOT NULL DEFAULT 0")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS store_hourly_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER NOT NULL,
            data_date TEXT NOT NULL,
            hour TEXT NOT NULL,
            visitors INTEGER NOT NULL DEFAULT 0,
            pv INTEGER NOT NULL DEFAULT 0,
            sales REAL NOT NULL DEFAULT 0,
            orders INTEGER NOT NULL DEFAULT 0,
            buyers INTEGER NOT NULL DEFAULT 0,
            conversion_rate REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            UNIQUE(store_id, data_date, hour)
        )
        """
    )
    conn.commit()


def _migrate_sycm(conn: sqlite3.Connection) -> None:
    """店铺生意参谋凭证字段：账号、密码、登录凭证 Cookie。"""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(stores)")}
    if "sycm_username" not in cols:
        conn.execute("ALTER TABLE stores ADD COLUMN sycm_username TEXT NOT NULL DEFAULT ''")
    if "sycm_password" not in cols:
        conn.execute("ALTER TABLE stores ADD COLUMN sycm_password TEXT NOT NULL DEFAULT ''")
    if "sycm_cookie" not in cols:
        conn.execute("ALTER TABLE stores ADD COLUMN sycm_cookie TEXT NOT NULL DEFAULT ''")
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


def _migrate_item_daily(conn: sqlite3.Connection) -> None:
    """商品每日数据补充商品排行指标列（访客/浏览/转化/加购/退款/图片）。"""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(store_item_daily)")}
    additions = {
        "visitors": "INTEGER NOT NULL DEFAULT 0",
        "pv": "INTEGER NOT NULL DEFAULT 0",
        "conversion_rate": "REAL NOT NULL DEFAULT 0",
        "add_cart": "INTEGER NOT NULL DEFAULT 0",
        "refund_amount": "REAL NOT NULL DEFAULT 0",
        "image": "TEXT NOT NULL DEFAULT ''",
    }
    for col, typ in additions.items():
        if col not in cols:
            conn.execute(f"ALTER TABLE store_item_daily ADD COLUMN {col} {typ}")
    conn.commit()


def _migrate_products_realtime(conn: sqlite3.Connection) -> None:
    """商品分析：实时商品排行数据表（今日实时快照）。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS store_item_realtime (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER NOT NULL,
            item_id TEXT NOT NULL,
            item_title TEXT NOT NULL DEFAULT '',
            image TEXT NOT NULL DEFAULT '',
            visitors INTEGER NOT NULL DEFAULT 0,
            pv INTEGER NOT NULL DEFAULT 0,
            buyers INTEGER NOT NULL DEFAULT 0,
            orders INTEGER NOT NULL DEFAULT 0,
            sales REAL NOT NULL DEFAULT 0,
            conversion_rate REAL NOT NULL DEFAULT 0,
            add_cart INTEGER NOT NULL DEFAULT 0,
            refund_amount REAL NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            UNIQUE(store_id, item_id)
        )
        """
    )
    cols = {row[1] for row in conn.execute("PRAGMA table_info(store_item_realtime)")}
    if "add_cart" not in cols:
        conn.execute("ALTER TABLE store_item_realtime ADD COLUMN add_cart INTEGER NOT NULL DEFAULT 0")
    if "refund_amount" not in cols:
        conn.execute("ALTER TABLE store_item_realtime ADD COLUMN refund_amount REAL NOT NULL DEFAULT 0")
    for col in ("visitors_cycle", "pv_cycle", "buyers_cycle", "orders_cycle", "sales_cycle", "conversion_cycle", "add_cart_cycle"):
        if col not in cols:
            conn.execute(f"ALTER TABLE store_item_realtime ADD COLUMN {col} REAL NOT NULL DEFAULT 0")
    conn.commit()


def _migrate_products(conn: sqlite3.Connection) -> None:
    """商品分析：单品每日销售数据表。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS store_item_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER NOT NULL,
            item_id TEXT NOT NULL,
            item_title TEXT NOT NULL DEFAULT '',
            data_date TEXT NOT NULL,
            sales REAL NOT NULL DEFAULT 0,
            orders INTEGER NOT NULL DEFAULT 0,
            buyers INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            UNIQUE(store_id, item_id, data_date)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_item_daily ON store_item_daily(store_id, data_date)
        """
    )
    conn.commit()


def _migrate_promo_realtime(conn: sqlite3.Connection) -> None:
    """老版 promo_realtime 无 scene 字段（无法分场景），检测到就重建（仅存当天临时数据）。"""
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(promo_realtime)")}
    except sqlite3.OperationalError:
        return
    if "scene" not in cols:
        conn.execute("DROP TABLE promo_realtime")
        conn.execute(
            """
            CREATE TABLE promo_realtime (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_id INTEGER NOT NULL,
                scene TEXT NOT NULL DEFAULT '',
                scene_name TEXT NOT NULL DEFAULT '',
                data_date TEXT NOT NULL,
                hour TEXT NOT NULL,
                impressions INTEGER NOT NULL DEFAULT 0,
                clicks INTEGER NOT NULL DEFAULT 0,
                ctr REAL NOT NULL DEFAULT 0,
                spend REAL NOT NULL DEFAULT 0,
                sales REAL NOT NULL DEFAULT 0,
                roi REAL NOT NULL DEFAULT 0,
                orders INTEGER NOT NULL DEFAULT 0,
                conversion_rate REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(store_id, scene, data_date, hour)
            )
            """
        )
        conn.commit()


def _seed_gifts(conn: sqlite3.Connection) -> None:
    """首次运行时给每家演示店铺写入几笔礼品单（仅当仍是演示店铺时，避免真实店铺下重建示例数据）。"""
    count = conn.execute("SELECT COUNT(*) AS c FROM gifts").fetchone()["c"]
    if count > 0:
        return
    demo = conn.execute("SELECT COUNT(*) AS c FROM stores WHERE id IN (1, 2, 3, 4)").fetchone()["c"]
    if demo < 4:
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
            CREATE TABLE IF NOT EXISTS store_daily_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_id INTEGER NOT NULL,
                data_date TEXT NOT NULL,
                visitors INTEGER NOT NULL DEFAULT 0,
                pv INTEGER NOT NULL DEFAULT 0,
                sales REAL NOT NULL DEFAULT 0,
                orders INTEGER NOT NULL DEFAULT 0,
                conversion_rate REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(store_id, data_date)
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
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL DEFAULT '默认模型',
                provider TEXT NOT NULL DEFAULT 'openai',
                base_url TEXT NOT NULL DEFAULT '',
                api_key TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                temperature REAL NOT NULL DEFAULT 0.7,
                is_default INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS promo_daily_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_id INTEGER NOT NULL,
                scene TEXT NOT NULL,
                scene_name TEXT NOT NULL DEFAULT '',
                data_date TEXT NOT NULL,
                impressions INTEGER NOT NULL DEFAULT 0,
                clicks INTEGER NOT NULL DEFAULT 0,
                ctr REAL NOT NULL DEFAULT 0,
                spend REAL NOT NULL DEFAULT 0,
                sales REAL NOT NULL DEFAULT 0,
                roi REAL NOT NULL DEFAULT 0,
                orders INTEGER NOT NULL DEFAULT 0,
                add_cart INTEGER NOT NULL DEFAULT 0,
                conversion_rate REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(store_id, scene, data_date)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS promo_realtime (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_id INTEGER NOT NULL,
                scene TEXT NOT NULL DEFAULT '',
                scene_name TEXT NOT NULL DEFAULT '',
                data_date TEXT NOT NULL,
                hour TEXT NOT NULL,
                impressions INTEGER NOT NULL DEFAULT 0,
                clicks INTEGER NOT NULL DEFAULT 0,
                ctr REAL NOT NULL DEFAULT 0,
                spend REAL NOT NULL DEFAULT 0,
                sales REAL NOT NULL DEFAULT 0,
                roi REAL NOT NULL DEFAULT 0,
                orders INTEGER NOT NULL DEFAULT 0,
                conversion_rate REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(store_id, scene, data_date, hour)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_promo_daily ON promo_daily_data(store_id, data_date)
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS promo_plan_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_id INTEGER NOT NULL,
                campaign_id TEXT NOT NULL,
                mode TEXT NOT NULL,
                spend REAL NOT NULL DEFAULT 0,
                sales REAL NOT NULL DEFAULT 0,
                roi REAL NOT NULL DEFAULT 0,
                clicks INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                UNIQUE(store_id, campaign_id, mode)
            )
            """
        )
        _plan_stats_cols = [r[1] for r in conn.execute("PRAGMA table_info(promo_plan_stats)").fetchall()]
        for _pc, _pt in (
            ("prev_spend", "REAL NOT NULL DEFAULT 0"),
            ("prev_sales", "REAL NOT NULL DEFAULT 0"),
            ("prev_roi", "REAL NOT NULL DEFAULT 0"),
            ("prev_clicks", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if _pc not in _plan_stats_cols:
                conn.execute(f"ALTER TABLE promo_plan_stats ADD COLUMN {_pc} {_pt}")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS promo_plan_daily (
                store_id INTEGER NOT NULL,
                campaign_id TEXT NOT NULL,
                data_date TEXT NOT NULL,
                spend REAL NOT NULL DEFAULT 0,
                sales REAL NOT NULL DEFAULT 0,
                roi REAL NOT NULL DEFAULT 0,
                clicks INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                UNIQUE(store_id, campaign_id, data_date)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS promo_plan_items (
                store_id INTEGER NOT NULL,
                campaign_id TEXT NOT NULL,
                item_id TEXT NOT NULL DEFAULT '',
                item_title TEXT NOT NULL DEFAULT '',
                image TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                UNIQUE(store_id, campaign_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS promo_item_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_id INTEGER NOT NULL,
                item_id TEXT NOT NULL,
                item_title TEXT NOT NULL DEFAULT '',
                mode TEXT NOT NULL,
                spend REAL NOT NULL DEFAULT 0,
                sales REAL NOT NULL DEFAULT 0,
                roi REAL NOT NULL DEFAULT 0,
                clicks INTEGER NOT NULL DEFAULT 0,
                orders INTEGER NOT NULL DEFAULT 0,
                impressions INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'report',
                updated_at TEXT NOT NULL,
                UNIQUE(store_id, item_id, mode)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_promo_item_stats ON promo_item_stats(store_id, item_id, mode)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS promo_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_id INTEGER NOT NULL,
                scene TEXT NOT NULL DEFAULT '',
                scene_name TEXT NOT NULL DEFAULT '',
                campaign_id TEXT NOT NULL,
                plan_name TEXT NOT NULL DEFAULT '',
                day_budget REAL NOT NULL DEFAULT 0,
                bid_type TEXT NOT NULL DEFAULT '',
                bid_value REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT '',
                gmt_create TEXT NOT NULL DEFAULT '',
                spend REAL NOT NULL DEFAULT 0,
                sales REAL NOT NULL DEFAULT 0,
                roi REAL NOT NULL DEFAULT 0,
                clicks INTEGER NOT NULL DEFAULT 0,
                note TEXT NOT NULL DEFAULT '',
                tag TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                UNIQUE(store_id, campaign_id)
            )
            """
        )
        conn.commit()
        _migrate(conn)
        _migrate_model_configs(conn)
        _migrate_sycm(conn)
        _migrate_products(conn)
        _migrate_item_daily(conn)
        _migrate_products_realtime(conn)
        _migrate_analytics(conn)
        _migrate_promo_realtime(conn)
        _seed_stores(conn)
        _migrate_logs(conn)
        _seed_gifts(conn)
        _migrate_gifts(conn)
    finally:
        conn.close()

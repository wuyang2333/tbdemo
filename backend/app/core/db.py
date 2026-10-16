"""SQLite 数据层：账号、令牌持久化。"""

from __future__ import annotations

import os
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 测试/多实例可通过环境变量 TAOBAO_DB_PATH 指定数据库位置
DB_PATH = Path(
    os.environ.get("TAOBAO_DB_PATH")
    or (Path(__file__).resolve().parent.parent.parent / "data" / "taobao.db")
)


def connect_db() -> sqlite3.Connection:
    """统一的数据库连接：允许跨线程 + 10 秒锁等待，避免并发写入报 database is locked。"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = connect_db()
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
    if "failed_count" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN failed_count INTEGER NOT NULL DEFAULT 0")
    if "locked_until" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN locked_until TEXT")
    if "last_login_at" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN last_login_at TEXT")
    if "last_login_ip" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN last_login_ip TEXT")
    if "expires_at" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN expires_at TEXT")
    if "parent_id" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN parent_id INTEGER")
    if "sub_account_quota" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN sub_account_quota INTEGER NOT NULL DEFAULT 2")
    if "store_quota" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN store_quota INTEGER NOT NULL DEFAULT 3")
    # 万相台预算写入需要同时携带预算类型（dmcType）。老库没有该字段时，
    # 现有有金额的计划按日预算处理；后续同步会用平台返回值覆盖。
    try:
        promo_cols = {row[1] for row in conn.execute("PRAGMA table_info(promo_plans)")}
        if promo_cols and "budget_type" not in promo_cols:
            conn.execute("ALTER TABLE promo_plans ADD COLUMN budget_type TEXT NOT NULL DEFAULT 'normal'")
            conn.execute(
                "UPDATE promo_plans SET budget_type = CASE WHEN COALESCE(day_budget, 0) <= 0 THEN 'unlimited' ELSE 'normal' END "
                "WHERE TRIM(COALESCE(budget_type, '')) = '' OR (budget_type = 'normal' AND COALESCE(day_budget, 0) <= 0)"
            )
        if promo_cols and "platform_presence" not in promo_cols:
            conn.execute("ALTER TABLE promo_plans ADD COLUMN platform_presence TEXT NOT NULL DEFAULT 'active'")
        if promo_cols and "platform_last_seen_at" not in promo_cols:
            conn.execute("ALTER TABLE promo_plans ADD COLUMN platform_last_seen_at TEXT")
        if promo_cols and "platform_missing_at" not in promo_cols:
            conn.execute("ALTER TABLE promo_plans ADD COLUMN platform_missing_at TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        tcols = {row[1] for row in conn.execute("PRAGMA table_info(tokens)")}
        if "expires_at" not in tcols:
            conn.execute("ALTER TABLE tokens ADD COLUMN expires_at TEXT")
        if "ip" not in tcols:
            conn.execute("ALTER TABLE tokens ADD COLUMN ip TEXT")
        if "user_agent" not in tcols:
            conn.execute("ALTER TABLE tokens ADD COLUMN user_agent TEXT")
    except sqlite3.OperationalError:
        pass
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS login_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            action TEXT NOT NULL,
            ip TEXT NOT NULL DEFAULT '',
            user_agent TEXT NOT NULL DEFAULT '',
            detail TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            created_by INTEGER,
            created_at TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS promo_ai_diagnoses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            diagnostic_id TEXT NOT NULL,
            plan_id INTEGER NOT NULL,
            store_id INTEGER NOT NULL,
            channel TEXT NOT NULL DEFAULT '',
            rule_code TEXT NOT NULL DEFAULT '',
            data_fingerprint TEXT NOT NULL,
            result_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, diagnostic_id, data_fingerprint)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_promo_ai_diagnoses_lookup
        ON promo_ai_diagnoses(user_id, diagnostic_id, updated_at DESC)
        """
    )
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



def _migrate_promo_action_executed_at(conn: sqlite3.Connection) -> None:
    columns = {row[1]: row for row in conn.execute("PRAGMA table_info(promo_action_records)").fetchall()}
    executed_at = columns.get("executed_at")
    if executed_at and executed_at[3]:
        conn.execute("ALTER TABLE promo_action_records RENAME TO promo_action_records_legacy")
        conn.execute(
            """
            CREATE TABLE promo_action_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                store_id INTEGER NOT NULL,
                plan_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                before_value REAL,
                after_value REAL,
                before_spend REAL NOT NULL DEFAULT 0,
                before_sales REAL NOT NULL DEFAULT 0,
                before_roi REAL NOT NULL DEFAULT 0,
                expected TEXT NOT NULL DEFAULT '',
                observation_hours INTEGER NOT NULL DEFAULT 48,
                status TEXT NOT NULL DEFAULT 'observing',
                result TEXT NOT NULL DEFAULT '',
                executed_at TEXT,
                verified_at TEXT,
                after_spend REAL NOT NULL DEFAULT 0,
                after_sales REAL NOT NULL DEFAULT 0,
                after_roi REAL NOT NULL DEFAULT 0,
                baseline_start TEXT,
                baseline_end TEXT,
                observation_due_at TEXT,
                data_quality TEXT NOT NULL DEFAULT '',
                created_at TEXT,
                decision_id TEXT,
                strategy_id INTEGER,
                success_criteria TEXT NOT NULL DEFAULT '{}',
                interference_notes TEXT NOT NULL DEFAULT '',
                manual_conclusion TEXT NOT NULL DEFAULT '',
                confidence TEXT NOT NULL DEFAULT '',
                baseline_days INTEGER NOT NULL DEFAULT 0,
                after_days INTEGER NOT NULL DEFAULT 0,
                metric_summary TEXT NOT NULL DEFAULT '{}',
                rollback_condition TEXT NOT NULL DEFAULT '',
                decision_record_id INTEGER,
                decision_tier TEXT NOT NULL DEFAULT '',
                change_pct REAL,
                platform_status TEXT NOT NULL DEFAULT 'not_submitted',
                platform_submitted_at TEXT,
                platform_checked_at TEXT,
                platform_check_note TEXT NOT NULL DEFAULT '',
                lifecycle_status TEXT NOT NULL DEFAULT 'active',
                lifecycle_reason TEXT NOT NULL DEFAULT '',
                lifecycle_updated_at TEXT
            )
            """
        )
        column_names = ", ".join(columns)
        conn.execute(
            f"INSERT INTO promo_action_records ({column_names}) SELECT {column_names} FROM promo_action_records_legacy"
        )
        conn.execute("DROP TABLE promo_action_records_legacy")
    conn.execute(
        "UPDATE promo_action_records SET executed_at = NULL "
        "WHERE status = 'planned' AND observation_due_at IS NULL"
    )


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
    if "remark_status" not in cols:
        conn.execute("ALTER TABLE gifts ADD COLUMN remark_status TEXT NOT NULL DEFAULT 'unremarked'")
    if "order_time" not in cols:
        conn.execute("ALTER TABLE gifts ADD COLUMN order_time TEXT")
    if "qr_code" not in cols:
        conn.execute("ALTER TABLE gifts ADD COLUMN qr_code TEXT NOT NULL DEFAULT ''")
    if "image" not in cols:
        conn.execute("ALTER TABLE gifts ADD COLUMN image TEXT NOT NULL DEFAULT ''")
    if "store_name" not in cols:
        conn.execute("ALTER TABLE gifts ADD COLUMN store_name TEXT NOT NULL DEFAULT ''")
    if "tencent_row" not in cols:
        conn.execute("ALTER TABLE gifts ADD COLUMN tencent_row INTEGER")
    if "tencent_synced_at" not in cols:
        conn.execute("ALTER TABLE gifts ADD COLUMN tencent_synced_at TEXT")
    if "tencent_sync_error" not in cols:
        conn.execute("ALTER TABLE gifts ADD COLUMN tencent_sync_error TEXT NOT NULL DEFAULT ''")
    if "tencent_image_synced" not in cols:
        conn.execute("ALTER TABLE gifts ADD COLUMN tencent_image_synced TEXT NOT NULL DEFAULT ''")
    if "remark_auto_pending" not in cols:
        conn.execute("ALTER TABLE gifts ADD COLUMN remark_auto_pending INTEGER NOT NULL DEFAULT 0")
    if "remark_attempts" not in cols:
        conn.execute("ALTER TABLE gifts ADD COLUMN remark_attempts INTEGER NOT NULL DEFAULT 0")
    if "remark_attempted_at" not in cols:
        conn.execute("ALTER TABLE gifts ADD COLUMN remark_attempted_at TEXT")
    if "remarked_at" not in cols:
        conn.execute("ALTER TABLE gifts ADD COLUMN remarked_at TEXT")
    if "remark_error" not in cols:
        conn.execute("ALTER TABLE gifts ADD COLUMN remark_error TEXT NOT NULL DEFAULT ''")
    if "remark_next_retry_at" not in cols:
        conn.execute("ALTER TABLE gifts ADD COLUMN remark_next_retry_at TEXT")
    if "qianniu_price" not in cols:
        conn.execute("ALTER TABLE gifts ADD COLUMN qianniu_price REAL")
    if "price_before_qianniu" not in cols:
        conn.execute("ALTER TABLE gifts ADD COLUMN price_before_qianniu REAL")
    if "price_synced_at" not in cols:
        conn.execute("ALTER TABLE gifts ADD COLUMN price_synced_at TEXT")
    if "price_sync_error" not in cols:
        conn.execute("ALTER TABLE gifts ADD COLUMN price_sync_error TEXT NOT NULL DEFAULT ''")
    if "owner_nickname" not in cols:
        conn.execute("ALTER TABLE gifts ADD COLUMN owner_nickname TEXT NOT NULL DEFAULT ''")
    buyer_lookup_added = False
    if "remark_lookup_order_no" not in cols:
        conn.execute("ALTER TABLE gifts ADD COLUMN remark_lookup_order_no TEXT NOT NULL DEFAULT ''")
        buyer_lookup_added = True
    if "remark_match_source" not in cols:
        conn.execute("ALTER TABLE gifts ADD COLUMN remark_match_source TEXT NOT NULL DEFAULT ''")
    if buyer_lookup_added:
        conn.execute(
            """
            UPDATE gifts
            SET remark_auto_pending = 1, remark_status = 'unremarked',
                remark_error = '', remark_next_retry_at = NULL
            WHERE order_no = '' AND TRIM(wangwang) != '' AND store_id > 0
            """
        )
    for gift in conn.execute("SELECT id, created_at FROM gifts WHERE owner_nickname = ''").fetchall():
        creator = conn.execute(
            """
            SELECT COALESCE(NULLIF(u.nickname, ''), l.username, '') AS owner_nickname
            FROM op_logs l
            LEFT JOIN users u ON u.id = l.user_id
            WHERE l.module = 'gifts' AND l.action = 'create'
              AND ABS((julianday(l.created_at) - julianday(?)) * 86400) <= 5
            ORDER BY ABS((julianday(l.created_at) - julianday(?)) * 86400)
            LIMIT 1
            """,
            (gift["created_at"], gift["created_at"]),
        ).fetchone()
        if creator and creator["owner_nickname"]:
            conn.execute(
                "UPDATE gifts SET owner_nickname = ? WHERE id = ?",
                (creator["owner_nickname"], gift["id"]),
            )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS gift_price_sync_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gift_id INTEGER NOT NULL,
            order_no TEXT NOT NULL,
            system_price_before REAL NOT NULL,
            qianniu_price REAL NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    try:
        action_cols = {row[1] for row in conn.execute("PRAGMA table_info(promo_action_records)")}
        for name, definition in (
            ("after_spend", "REAL NOT NULL DEFAULT 0"),
            ("after_sales", "REAL NOT NULL DEFAULT 0"),
            ("after_roi", "REAL NOT NULL DEFAULT 0"),
            ("baseline_start", "TEXT"),
            ("baseline_end", "TEXT"),
            ("observation_due_at", "TEXT"),
            ("data_quality", "TEXT NOT NULL DEFAULT ''"),
            ("created_at", "TEXT"),
            ("decision_id", "TEXT"),
            ("strategy_id", "INTEGER"),
            ("success_criteria", "TEXT NOT NULL DEFAULT '{}'"),
            ("interference_notes", "TEXT NOT NULL DEFAULT ''"),
            ("manual_conclusion", "TEXT NOT NULL DEFAULT ''"),
            ("confidence", "TEXT NOT NULL DEFAULT ''"),
            ("baseline_days", "INTEGER NOT NULL DEFAULT 0"),
            ("after_days", "INTEGER NOT NULL DEFAULT 0"),
            ("metric_summary", "TEXT NOT NULL DEFAULT '{}'"),
            ("rollback_condition", "TEXT NOT NULL DEFAULT ''"),
            ("decision_record_id", "INTEGER"),
            ("decision_tier", "TEXT NOT NULL DEFAULT ''"),
            ("change_pct", "REAL"),
            ("platform_status", "TEXT NOT NULL DEFAULT 'not_submitted'"),
            ("platform_submitted_at", "TEXT"),
            ("platform_checked_at", "TEXT"),
            ("platform_check_note", "TEXT NOT NULL DEFAULT ''"),
            ("lifecycle_status", "TEXT NOT NULL DEFAULT 'active'"),
            ("lifecycle_reason", "TEXT NOT NULL DEFAULT ''"),
            ("lifecycle_updated_at", "TEXT"),
        ):
            if name not in action_cols:
                conn.execute(f"ALTER TABLE promo_action_records ADD COLUMN {name} {definition}")
    except sqlite3.OperationalError:
        pass
    _migrate_promo_action_executed_at(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS promo_strategies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            store_id INTEGER NOT NULL,
            source_action_id INTEGER,
            name TEXT NOT NULL,
            action_type TEXT NOT NULL DEFAULT '',
            conditions TEXT NOT NULL DEFAULT '',
            evidence TEXT NOT NULL DEFAULT '',
            use_count INTEGER NOT NULL DEFAULT 0,
            success_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            outcome TEXT NOT NULL DEFAULT 'success',
            scene TEXT NOT NULL DEFAULT '',
            min_roi REAL,
            max_roi REAL,
            source_type TEXT NOT NULL DEFAULT 'verified',
            verification_status TEXT NOT NULL DEFAULT 'verified',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS promo_decision_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            store_id INTEGER NOT NULL,
            plan_id INTEGER NOT NULL,
            strategy_id INTEGER,
            recommended_tier TEXT NOT NULL DEFAULT '',
            selected_tier TEXT NOT NULL DEFAULT '',
            feedback_status TEXT NOT NULL DEFAULT 'adopted',
            workflow_status TEXT NOT NULL DEFAULT 'selected',
            ai_field TEXT NOT NULL DEFAULT '',
            ai_change_pct REAL,
            final_field TEXT NOT NULL DEFAULT '',
            final_change_pct REAL,
            ai_success_criteria TEXT NOT NULL DEFAULT '{}',
            final_success_criteria TEXT NOT NULL DEFAULT '{}',
            ai_observation_hours INTEGER NOT NULL DEFAULT 48,
            final_observation_hours INTEGER NOT NULL DEFAULT 48,
            rollback_condition TEXT NOT NULL DEFAULT '',
            feedback_reason TEXT NOT NULL DEFAULT '',
            feedback_note TEXT NOT NULL DEFAULT '',
            action_record_id INTEGER,
            result_status TEXT NOT NULL DEFAULT '',
            result_summary TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(decision_id, plan_id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_promo_decisions_store_updated ON promo_decision_records(store_id, updated_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_promo_decisions_action ON promo_decision_records(action_record_id)")
    try:
        strategy_cols = {row[1] for row in conn.execute("PRAGMA table_info(promo_strategies)")}
        for name, definition in (
            ("outcome", "TEXT NOT NULL DEFAULT 'success'"),
            ("scene", "TEXT NOT NULL DEFAULT ''"),
            ("min_roi", "REAL"),
            ("max_roi", "REAL"),
            ("source_type", "TEXT NOT NULL DEFAULT 'verified'"),
            ("verification_status", "TEXT NOT NULL DEFAULT 'verified'"),
        ):
            if name not in strategy_cols:
                conn.execute(f"ALTER TABLE promo_strategies ADD COLUMN {name} {definition}")
    except sqlite3.OperationalError:
        pass
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_gift_price_sync_logs_gift ON gift_price_sync_logs(gift_id, created_at DESC)"
    )
    conn.execute("UPDATE gifts SET order_time = created_at WHERE order_time IS NULL OR order_time = ''")
    conn.execute("UPDATE gifts SET wangwang = recipient WHERE wangwang = '' AND recipient != ''")
    conn.execute("UPDATE gifts SET image = qr_code WHERE image = '' AND qr_code != ''")
    conn.execute("UPDATE gifts SET keyword = gift_name WHERE keyword = '' AND gift_name != ''")
    conn.commit()


def _migrate_reviews(conn: sqlite3.Connection) -> None:
    """商品评论：原始评论、分析标签和每日聚合统计。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS product_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER NOT NULL,
            review_id TEXT NOT NULL,
            item_id TEXT NOT NULL DEFAULT '',
            item_title TEXT NOT NULL DEFAULT '',
            sku_id TEXT NOT NULL DEFAULT '',
            order_id_hash TEXT NOT NULL DEFAULT '',
            rating INTEGER NOT NULL DEFAULT 0,
            content TEXT NOT NULL DEFAULT '',
            append_content TEXT NOT NULL DEFAULT '',
            image_urls TEXT NOT NULL DEFAULT '[]',
            review_time TEXT NOT NULL,
            reply_status TEXT NOT NULL DEFAULT 'none',
            reply_content TEXT NOT NULL DEFAULT '',
            reply_error TEXT NOT NULL DEFAULT '',
            reply_approved_at TEXT,
            reply_published_at TEXT,
            reply_platform_response TEXT NOT NULL DEFAULT '',
            process_status TEXT NOT NULL DEFAULT 'pending',
            source TEXT NOT NULL DEFAULT 'import',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(store_id, review_id)
        )
        """
    )
    review_cols = {row[1] for row in conn.execute("PRAGMA table_info(product_reviews)")}
    if "reply_error" not in review_cols:
        conn.execute("ALTER TABLE product_reviews ADD COLUMN reply_error TEXT NOT NULL DEFAULT ''")
    if "reply_approved_at" not in review_cols:
        conn.execute("ALTER TABLE product_reviews ADD COLUMN reply_approved_at TEXT")
    if "reply_published_at" not in review_cols:
        conn.execute("ALTER TABLE product_reviews ADD COLUMN reply_published_at TEXT")
    if "reply_platform_response" not in review_cols:
        conn.execute("ALTER TABLE product_reviews ADD COLUMN reply_platform_response TEXT NOT NULL DEFAULT ''")
    if "reply_ai_draft" not in review_cols:
        conn.execute("ALTER TABLE product_reviews ADD COLUMN reply_ai_draft TEXT NOT NULL DEFAULT ''")
    if "reply_template_id" not in review_cols:
        conn.execute("ALTER TABLE product_reviews ADD COLUMN reply_template_id INTEGER")
    conn.execute("UPDATE product_reviews SET process_status = 'replied' WHERE reply_status = 'published' AND process_status != 'replied'")
    conn.execute("UPDATE product_reviews SET process_status = 'pending' WHERE process_status IN ('contacted', 'resolved') AND reply_status != 'published'")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS review_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            review_id INTEGER NOT NULL UNIQUE,
            sentiment TEXT NOT NULL DEFAULT 'neutral',
            confidence REAL NOT NULL DEFAULT 0,
            aspects_json TEXT NOT NULL DEFAULT '[]',
            keywords_json TEXT NOT NULL DEFAULT '[]',
            severity TEXT NOT NULL DEFAULT 'normal',
            review_status TEXT NOT NULL DEFAULT 'auto',
            analysis_reason TEXT NOT NULL DEFAULT '',
            analysis_source TEXT NOT NULL DEFAULT 'rules',
            routing_reason TEXT NOT NULL DEFAULT '',
            model_version TEXT NOT NULL DEFAULT 'rules-v1',
            analyzed_at TEXT NOT NULL
        )
        """
    )
    analysis_cols = {row[1] for row in conn.execute("PRAGMA table_info(review_analysis)")}
    if "review_status" not in analysis_cols:
        conn.execute("ALTER TABLE review_analysis ADD COLUMN review_status TEXT NOT NULL DEFAULT 'auto'")
    if "analysis_reason" not in analysis_cols:
        conn.execute("ALTER TABLE review_analysis ADD COLUMN analysis_reason TEXT NOT NULL DEFAULT ''")
    if "analysis_source" not in analysis_cols:
        conn.execute("ALTER TABLE review_analysis ADD COLUMN analysis_source TEXT NOT NULL DEFAULT 'rules'")
    if "routing_reason" not in analysis_cols:
        conn.execute("ALTER TABLE review_analysis ADD COLUMN routing_reason TEXT NOT NULL DEFAULT ''")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS review_daily_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER NOT NULL,
            item_id TEXT NOT NULL DEFAULT '',
            data_date TEXT NOT NULL,
            total_count INTEGER NOT NULL DEFAULT 0,
            positive_count INTEGER NOT NULL DEFAULT 0,
            neutral_count INTEGER NOT NULL DEFAULT 0,
            negative_count INTEGER NOT NULL DEFAULT 0,
            avg_rating REAL NOT NULL DEFAULT 0,
            UNIQUE(store_id, item_id, data_date)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS review_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER NOT NULL,
            review_id INTEGER NOT NULL,
            alert_type TEXT NOT NULL DEFAULT 'negative_review',
            title TEXT NOT NULL,
            message TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open',
            notified_at TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(review_id, alert_type)
        )
        """
    )
    alert_cols = {row[1] for row in conn.execute("PRAGMA table_info(review_alerts)")}
    if "notified_at" not in alert_cols:
        conn.execute("ALTER TABLE review_alerts ADD COLUMN notified_at TEXT")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS review_reply_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            category TEXT NOT NULL DEFAULT '通用',
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS review_sentiment_corrections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            review_id INTEGER NOT NULL UNIQUE,
            store_id INTEGER NOT NULL,
            content_hash TEXT NOT NULL,
            original_sentiment TEXT NOT NULL,
            corrected_sentiment TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS review_custom_terms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER NOT NULL DEFAULT 0,
            term TEXT NOT NULL,
            sentiment TEXT NOT NULL,
            weight REAL NOT NULL DEFAULT 1.5,
            source TEXT NOT NULL DEFAULT 'manual',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(store_id, term)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS review_trend_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER NOT NULL,
            alert_date TEXT NOT NULL,
            current_count INTEGER NOT NULL DEFAULT 0,
            current_negative INTEGER NOT NULL DEFAULT 0,
            current_rate REAL NOT NULL DEFAULT 0,
            baseline_count INTEGER NOT NULL DEFAULT 0,
            baseline_rate REAL NOT NULL DEFAULT 0,
            level TEXT NOT NULL DEFAULT 'warning',
            status TEXT NOT NULL DEFAULT 'open',
            message TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(store_id, alert_date)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS review_weekly_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER NOT NULL,
            week_start TEXT NOT NULL,
            week_end TEXT NOT NULL,
            report_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(store_id, week_start)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS review_knowledge_articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER NOT NULL DEFAULT 0,
            title TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT '通用',
            problem_terms TEXT NOT NULL DEFAULT '[]',
            solution TEXT NOT NULL,
            reply_template TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(store_id, title)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS review_knowledge_matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            review_id INTEGER NOT NULL,
            article_id INTEGER NOT NULL,
            confidence REAL NOT NULL DEFAULT 0,
            matched_terms_json TEXT NOT NULL DEFAULT '[]',
            updated_at TEXT NOT NULL,
            UNIQUE(review_id, article_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS review_reply_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            review_id INTEGER NOT NULL UNIQUE,
            store_id INTEGER NOT NULL,
            item_id TEXT NOT NULL DEFAULT '',
            item_title TEXT NOT NULL DEFAULT '',
            review_content TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT '通用',
            knowledge_ids TEXT NOT NULL DEFAULT '[]',
            ai_draft TEXT NOT NULL DEFAULT '',
            final_reply TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            published_at TEXT NOT NULL
        )
        """
    )
    sample_cols = {row[1] for row in conn.execute("PRAGMA table_info(review_reply_samples)")}
    if "review_content" not in sample_cols:
        conn.execute("ALTER TABLE review_reply_samples ADD COLUMN review_content TEXT NOT NULL DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_review_reply_samples_lookup ON review_reply_samples(store_id, enabled, updated_at)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS review_knowledge_suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER NOT NULL DEFAULT 0,
            title TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT '通用',
            problem_terms TEXT NOT NULL DEFAULT '[]',
            solution TEXT NOT NULL DEFAULT '',
            reply_template TEXT NOT NULL DEFAULT '',
            evidence_count INTEGER NOT NULL DEFAULT 0,
            sample_review_ids TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'approved', 'rejected')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(store_id, title)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_review_knowledge_suggestions_store_status ON review_knowledge_suggestions(store_id, status, updated_at)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS review_improvement_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER NOT NULL,
            item_id TEXT NOT NULL DEFAULT '',
            item_title TEXT NOT NULL DEFAULT '',
            topic TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            owner TEXT NOT NULL DEFAULT '',
            plan TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'diagnosed', 'implemented', 'observing', 'improved', 'ignored')),
            started_at TEXT,
            due_at TEXT,
            before_negative_rate REAL,
            after_negative_rate REAL,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    improvement_cols = {row[1] for row in conn.execute("PRAGMA table_info(review_improvement_actions)")}
    for column, definition in {
        "item_id": "TEXT NOT NULL DEFAULT ''",
        "item_title": "TEXT NOT NULL DEFAULT ''",
        "topic": "TEXT NOT NULL DEFAULT ''",
        "title": "TEXT NOT NULL DEFAULT ''",
        "description": "TEXT NOT NULL DEFAULT ''",
        "owner": "TEXT NOT NULL DEFAULT ''",
        "plan": "TEXT NOT NULL DEFAULT ''",
        "status": "TEXT NOT NULL DEFAULT 'pending'",
        "started_at": "TEXT",
        "due_at": "TEXT",
        "before_negative_rate": "REAL",
        "after_negative_rate": "REAL",
        "note": "TEXT NOT NULL DEFAULT ''",
        "created_at": "TEXT NOT NULL DEFAULT ''",
        "updated_at": "TEXT NOT NULL DEFAULT ''",
    }.items():
        if column not in improvement_cols:
            conn.execute(f"ALTER TABLE review_improvement_actions ADD COLUMN {column} {definition}")
    now = datetime.now(timezone.utc).isoformat()
    for name, category, content in (
        ("通用感谢", "好评", "感谢您的认可与支持！我们会继续做好产品和服务，期待再次为您服务。"),
        ("质量问题", "质量", "非常抱歉给您带来不好的体验。我们已记录您反馈的质量问题，请联系我们的售后客服，我们会尽快核实并妥善处理。"),
        ("物流包装", "物流", "很抱歉商品在配送或包装环节给您带来困扰。请将具体情况告知客服，我们会尽快核实并协助处理。"),
        ("使用体验", "体验", "感谢您的真实反馈。我们非常重视您的使用感受，已记录相关建议并会持续改进产品体验。"),
    ):
        conn.execute("INSERT OR IGNORE INTO review_reply_templates (name, category, content, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", (name, category, content, now, now))
    for title, category, terms, solution, reply_template in (
        ("包装破损处理", "包装", ["包装破损", "盒子破了", "压坏", "包装坏"], "核对评价图片和订单包装批次，联系买家确认商品是否受损；如商品受损，按售后政策补发或退款，并登记包装改进。", "很抱歉包装问题影响了您的体验。我们已记录并会核查包装环节，请联系在线客服并提供订单信息，我们会尽快为您妥善处理。"),
        ("物流延迟处理", "物流", ["物流慢", "快递慢", "一直没到", "发货慢"], "先查询物流轨迹和异常节点，主动告知预计送达时间；长时间无更新时联系承运商并向买家同步进展。", "很抱歉物流时效没有达到预期。我们会立即核查物流进度并持续跟进，请联系在线客服提供订单信息。"),
        ("商品质量问题", "质量", ["质量问题", "坏了", "开胶", "漏液", "瑕疵"], "确认具体故障、使用场景和图片证据，排查同批次商品；符合售后条件时优先提供退换货方案。", "非常抱歉给您带来不好的使用体验。我们很重视您反馈的质量问题，请联系在线客服，我们会尽快核实并提供售后方案。"),
        ("尺码不合适", "尺码", ["太小", "太大", "偏小", "偏大", "尺码不合适"], "核对买家选择的规格与商品尺码表，提供换码指引，并将高频偏差反馈给商品团队校准尺码说明。", "很抱歉尺码没有达到您的预期。请联系在线客服告知订单和实际穿着情况，我们会协助您选择更合适的尺码。"),
        ("客服响应问题", "客服", ["不回复", "态度差", "客服慢", "没人处理"], "查询会话记录和响应时长，由专人主动回访并说明处理进度；同步复盘服务话术和排班。", "很抱歉我们的服务响应给您带来困扰。我们已记录您的反馈，请联系在线客服并提供订单信息，我们会安排专人跟进。"),
    ):
        conn.execute(
            """INSERT OR IGNORE INTO review_knowledge_articles
            (store_id, title, category, problem_terms, solution, reply_template, enabled, created_at, updated_at)
            VALUES (0, ?, ?, ?, ?, ?, 1, ?, ?)""",
            (title, category, json.dumps(terms, ensure_ascii=False), solution, reply_template, now, now),
        )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_review_alerts_store_status ON review_alerts(store_id, status, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_review_corrections_store ON review_sentiment_corrections(store_id, updated_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_review_corrections_hash ON review_sentiment_corrections(store_id, content_hash)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_review_terms_store ON review_custom_terms(store_id, enabled)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_review_trend_alerts_store ON review_trend_alerts(store_id, status, alert_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_review_knowledge_store ON review_knowledge_articles(store_id, enabled)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_review_knowledge_matches_review ON review_knowledge_matches(review_id, confidence)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reviews_store_date ON product_reviews(store_id, review_time)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reviews_item ON product_reviews(store_id, item_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_review_improvement_store_status ON review_improvement_actions(store_id, status, updated_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_review_improvement_item ON review_improvement_actions(store_id, item_id, updated_at)")
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
    if "buyers" not in cols:
        conn.execute("ALTER TABLE store_daily_data ADD COLUMN buyers INTEGER NOT NULL DEFAULT 0")
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
    # 分发版跳过演示数据（TAOBAO_NO_SEED=1，由 start.bat 设置），朋友从零开始
    if os.environ.get("TAOBAO_NO_SEED"):
        return
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
        "pay_pct": "REAL NOT NULL DEFAULT 0",
        "item_clt_byr_cnt": "INTEGER NOT NULL DEFAULT 0",
        "uv_avg_value": "REAL NOT NULL DEFAULT 0",
        "stay_time_avg": "REAL NOT NULL DEFAULT 0",
        "itm_bounce_rate": "REAL NOT NULL DEFAULT 0",
        "se_guide_uv": "INTEGER NOT NULL DEFAULT 0",
        "se_guide_pay_byr_cnt": "INTEGER NOT NULL DEFAULT 0",
        "se_guide_pay_rate": "REAL NOT NULL DEFAULT 0",
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
    for col in (
        "visitors_cycle", "pv_cycle", "buyers_cycle", "orders_cycle", "sales_cycle", "conversion_cycle", "add_cart_cycle",
        "pay_pct", "item_clt_byr_cnt", "uv_avg_value", "stay_time_avg", "itm_bounce_rate",
        "se_guide_uv", "se_guide_pay_byr_cnt", "se_guide_pay_rate",
    ):
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
    # 分发版跳过演示数据（TAOBAO_NO_SEED=1，由 start.bat 设置）
    if os.environ.get("TAOBAO_NO_SEED"):
        return
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
    conn = connect_db()
    conn.execute("PRAGMA journal_mode = WAL")
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
                allowed_store_ids TEXT,
                failed_count INTEGER NOT NULL DEFAULT 0,
                locked_until TEXT,
                last_login_at TEXT,
                last_login_ip TEXT,
                expires_at TEXT,
                parent_id INTEGER,
                sub_account_quota INTEGER NOT NULL DEFAULT 2,
                store_quota INTEGER NOT NULL DEFAULT 3
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tokens (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT,
                ip TEXT,
                user_agent TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS login_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                action TEXT NOT NULL,
                ip TEXT NOT NULL DEFAULT '',
                user_agent TEXT NOT NULL DEFAULT '',
                detail TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS announcements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                created_by INTEGER,
                created_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS invite_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                note TEXT NOT NULL DEFAULT '',
                created_by INTEGER,
                created_at TEXT NOT NULL,
                expires_at TEXT,
                max_uses INTEGER NOT NULL DEFAULT 1,
                used_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                link TEXT NOT NULL DEFAULT '',
                type TEXT NOT NULL DEFAULT 'info',
                is_read INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS changelog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS flow_source_top (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_id INTEGER NOT NULL,
                data_date TEXT NOT NULL,
                rank INTEGER NOT NULL DEFAULT 0,
                source_name TEXT NOT NULL DEFAULT '',
                uv INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(store_id, data_date, rank)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS refund_today (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_id INTEGER NOT NULL,
                data_date TEXT NOT NULL,
                amount REAL NOT NULL DEFAULT 0,
                pay_amt REAL NOT NULL DEFAULT 0,
                rate REAL NOT NULL DEFAULT 0,
                ord_rate REAL NOT NULL DEFAULT 0,
                cycle REAL,
                yest_amount REAL NOT NULL DEFAULT 0,
                yest_pay_amt REAL NOT NULL DEFAULT 0,
                yest_rate REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                UNIQUE(store_id, data_date)
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
            CREATE TABLE IF NOT EXISTS promo_action_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            store_id INTEGER NOT NULL,
            plan_id INTEGER NOT NULL,
            action_type TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            before_value REAL,
            after_value REAL,
            before_spend REAL NOT NULL DEFAULT 0,
            before_sales REAL NOT NULL DEFAULT 0,
            before_roi REAL NOT NULL DEFAULT 0,
            expected TEXT NOT NULL DEFAULT '',
            observation_hours INTEGER NOT NULL DEFAULT 48,
            status TEXT NOT NULL DEFAULT 'observing',
            result TEXT NOT NULL DEFAULT '',
            executed_at TEXT,
            verified_at TEXT,
            decision_id TEXT,
            strategy_id INTEGER,
            success_criteria TEXT NOT NULL DEFAULT '{}',
            interference_notes TEXT NOT NULL DEFAULT '',
            manual_conclusion TEXT NOT NULL DEFAULT '',
            confidence TEXT NOT NULL DEFAULT '',
            baseline_days INTEGER NOT NULL DEFAULT 0,
            after_days INTEGER NOT NULL DEFAULT 0,
            metric_summary TEXT NOT NULL DEFAULT '{}',
            rollback_condition TEXT NOT NULL DEFAULT '',
            decision_record_id INTEGER,
            decision_tier TEXT NOT NULL DEFAULT '',
            change_pct REAL,
            platform_status TEXT NOT NULL DEFAULT 'not_submitted',
            platform_submitted_at TEXT,
            platform_checked_at TEXT,
            platform_check_note TEXT NOT NULL DEFAULT '',
            lifecycle_status TEXT NOT NULL DEFAULT 'active',
            lifecycle_reason TEXT NOT NULL DEFAULT '',
            lifecycle_updated_at TEXT
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
                buyers INTEGER NOT NULL DEFAULT 0,
                conversion_rate REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(store_id, data_date)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sync_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                trigger TEXT NOT NULL DEFAULT 'auto',
                store_id INTEGER,
                started_at TEXT,
                finished_at TEXT NOT NULL,
                duration REAL NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sync_runs_name_finished ON sync_runs(name, finished_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sync_runs_store_finished ON sync_runs(store_id, finished_at DESC)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS store_operational_status (
                store_id INTEGER PRIMARY KEY,
                pending_shipments INTEGER NOT NULL DEFAULT 0,
                product_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS store_products (
                store_id INTEGER NOT NULL,
                item_id TEXT NOT NULL,
                category_id TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                image TEXT NOT NULL DEFAULT '',
                price REAL NOT NULL DEFAULT 0,
                stock INTEGER NOT NULL DEFAULT 0,
                sold_quantity INTEGER NOT NULL DEFAULT 0,
                monthly_sold INTEGER NOT NULL DEFAULT 0,
                quality_score REAL NOT NULL DEFAULT 0,
                shelf_at TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '出售中',
                detail_url TEXT NOT NULL DEFAULT '',
                edit_url TEXT NOT NULL DEFAULT '',
                synced_at TEXT NOT NULL,
                PRIMARY KEY (store_id, item_id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_store_products_title ON store_products(title)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_store_products_synced_at ON store_products(synced_at)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS product_aliases (
                store_id INTEGER NOT NULL,
                item_id TEXT NOT NULL,
                alias TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (store_id, item_id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_product_aliases_item ON product_aliases(item_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_product_aliases_alias ON product_aliases(alias)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS gifts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_id INTEGER NOT NULL,
                order_no TEXT NOT NULL,
                owner_nickname TEXT NOT NULL DEFAULT '',
                remark_lookup_order_no TEXT NOT NULL DEFAULT '',
                remark_match_source TEXT NOT NULL DEFAULT '',
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
            ("prev_scope", "TEXT NOT NULL DEFAULT 'unknown'"),
            ("alipay_dir", "REAL NOT NULL DEFAULT 0"),
            ("alipay_indir", "REAL NOT NULL DEFAULT 0"),
            ("retained_sales", "REAL NOT NULL DEFAULT 0"),
            ("retained_roi", "REAL NOT NULL DEFAULT 0"),
            ("refund_amt", "REAL NOT NULL DEFAULT 0"),
            ("extra_json", "TEXT NOT NULL DEFAULT ''"),
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
            CREATE TABLE IF NOT EXISTS promo_item_daily (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_id INTEGER NOT NULL,
                item_id TEXT NOT NULL,
                item_title TEXT NOT NULL DEFAULT '',
                data_date TEXT NOT NULL,
                spend REAL NOT NULL DEFAULT 0,
                sales REAL NOT NULL DEFAULT 0,
                roi REAL NOT NULL DEFAULT 0,
                clicks INTEGER NOT NULL DEFAULT 0,
                orders INTEGER NOT NULL DEFAULT 0,
                impressions INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'report',
                updated_at TEXT NOT NULL,
                UNIQUE(store_id, item_id, data_date)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_promo_item_daily ON promo_item_daily(store_id, data_date, item_id)"
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
                budget_type TEXT NOT NULL DEFAULT 'normal',
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
                platform_presence TEXT NOT NULL DEFAULT 'active',
                platform_last_seen_at TEXT,
                platform_missing_at TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE(store_id, campaign_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS competitor_shops (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT NOT NULL DEFAULT '',
                competitor_type TEXT NOT NULL DEFAULT 'direct',
                priority TEXT NOT NULL DEFAULT '重点',
                category TEXT NOT NULL DEFAULT '',
                price_band TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                monitor_frequency TEXT NOT NULL DEFAULT '每日',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS competitor_products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL DEFAULT '',
                own_product TEXT NOT NULL DEFAULT '',
                price REAL,
                coupon_price REAL,
                review_count INTEGER,
                review_count_text TEXT NOT NULL DEFAULT '',
                rating REAL,
                good_rate REAL,
                review_tags TEXT NOT NULL DEFAULT '[]',
                review_samples TEXT NOT NULL DEFAULT '[]',
                review_highlights TEXT NOT NULL DEFAULT '{}',
                negative_keywords TEXT NOT NULL DEFAULT '[]',
                negative_review_samples TEXT NOT NULL DEFAULT '[]',
                sku_options TEXT NOT NULL DEFAULT '[]',
                sku_prices TEXT NOT NULL DEFAULT '[]',
                stock_status TEXT NOT NULL DEFAULT 'unknown',
                promotion_tags TEXT NOT NULL DEFAULT '[]',
                service_tags TEXT NOT NULL DEFAULT '[]',
                selling_points TEXT NOT NULL DEFAULT '[]',
                sales_text TEXT NOT NULL DEFAULT '',
                image_url TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                last_snapshot_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (shop_id) REFERENCES competitor_shops(id)
            )
            """
        )
        shop_columns = {row[1] for row in conn.execute("PRAGMA table_info(competitor_shops)")}
        for column, definition in (
            ("last_scan_attempt_at", "TEXT"),
            ("last_scanned_at", "TEXT"),
            ("last_scan_status", "TEXT NOT NULL DEFAULT 'pending'"),
            ("last_scan_error", "TEXT NOT NULL DEFAULT ''"),
            ("last_scan_product_count", "INTEGER NOT NULL DEFAULT 0"),
            ("last_new_product_count", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if column not in shop_columns:
                conn.execute(f"ALTER TABLE competitor_shops ADD COLUMN {column} {definition}")
        product_columns = {row[1] for row in conn.execute("PRAGMA table_info(competitor_products)")}
        for column, definition in (
            ("alias", "TEXT NOT NULL DEFAULT ''"),
            ("discovery_source", "TEXT NOT NULL DEFAULT 'manual'"),
            ("platform_item_id", "TEXT NOT NULL DEFAULT ''"),
            ("first_seen_at", "TEXT"),
            ("last_seen_at", "TEXT"),
            ("collection_status", "TEXT NOT NULL DEFAULT 'pending'"),
            ("collection_error", "TEXT NOT NULL DEFAULT ''"),
            ("last_collected_at", "TEXT"),
            ("last_success_at", "TEXT"),
            ("collection_source", "TEXT NOT NULL DEFAULT ''"),
            ("review_count_text", "TEXT NOT NULL DEFAULT ''"),
            ("rating", "REAL"),
            ("good_rate", "REAL"),
            ("review_tags", "TEXT NOT NULL DEFAULT '[]'"),
            ("review_samples", "TEXT NOT NULL DEFAULT '[]'"),
            ("review_highlights", "TEXT NOT NULL DEFAULT '{}'"),
            ("negative_keywords", "TEXT NOT NULL DEFAULT '[]'"),
            ("negative_review_samples", "TEXT NOT NULL DEFAULT '[]'"),
            ("sku_options", "TEXT NOT NULL DEFAULT '[]'"),
            ("sku_prices", "TEXT NOT NULL DEFAULT '[]'"),
            ("stock_status", "TEXT NOT NULL DEFAULT 'unknown'"),
            ("promotion_tags", "TEXT NOT NULL DEFAULT '[]'"),
            ("service_tags", "TEXT NOT NULL DEFAULT '[]'"),
            ("selling_points", "TEXT NOT NULL DEFAULT '[]'"),
        ):
            if column not in product_columns:
                conn.execute(f"ALTER TABLE competitor_products ADD COLUMN {column} {definition}")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS competitor_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_id INTEGER,
                product_id INTEGER,
                event_type TEXT NOT NULL,
                title TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '',
                severity TEXT NOT NULL DEFAULT 'medium',
                status TEXT NOT NULL DEFAULT 'new',
                observed_at TEXT NOT NULL,
                FOREIGN KEY (shop_id) REFERENCES competitor_shops(id),
                FOREIGN KEY (product_id) REFERENCES competitor_products(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS competitor_product_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                price REAL,
                coupon_price REAL,
                review_count INTEGER,
                review_count_text TEXT NOT NULL DEFAULT '',
                rating REAL,
                good_rate REAL,
                review_tags TEXT NOT NULL DEFAULT '[]',
                review_samples TEXT NOT NULL DEFAULT '[]',
                review_highlights TEXT NOT NULL DEFAULT '{}',
                negative_keywords TEXT NOT NULL DEFAULT '[]',
                negative_review_samples TEXT NOT NULL DEFAULT '[]',
                sku_options TEXT NOT NULL DEFAULT '[]',
                sku_prices TEXT NOT NULL DEFAULT '[]',
                stock_status TEXT NOT NULL DEFAULT 'unknown',
                promotion_tags TEXT NOT NULL DEFAULT '[]',
                service_tags TEXT NOT NULL DEFAULT '[]',
                selling_points TEXT NOT NULL DEFAULT '[]',
                sales_text TEXT NOT NULL DEFAULT '',
                image_url TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                observed_at TEXT NOT NULL,
                FOREIGN KEY (product_id) REFERENCES competitor_products(id)
            )
            """
        )
        snapshot_columns = {row[1] for row in conn.execute("PRAGMA table_info(competitor_product_snapshots)")}
        for column, definition in (
            ("review_count_text", "TEXT NOT NULL DEFAULT ''"),
            ("rating", "REAL"),
            ("good_rate", "REAL"),
            ("review_tags", "TEXT NOT NULL DEFAULT '[]'"),
            ("review_samples", "TEXT NOT NULL DEFAULT '[]'"),
            ("review_highlights", "TEXT NOT NULL DEFAULT '{}'"),
            ("negative_keywords", "TEXT NOT NULL DEFAULT '[]'"),
            ("negative_review_samples", "TEXT NOT NULL DEFAULT '[]'"),
            ("sku_options", "TEXT NOT NULL DEFAULT '[]'"),
            ("sku_prices", "TEXT NOT NULL DEFAULT '[]'"),
            ("stock_status", "TEXT NOT NULL DEFAULT 'unknown'"),
            ("promotion_tags", "TEXT NOT NULL DEFAULT '[]'"),
            ("service_tags", "TEXT NOT NULL DEFAULT '[]'"),
            ("selling_points", "TEXT NOT NULL DEFAULT '[]'"),
        ):
            if column not in snapshot_columns:
                conn.execute(f"ALTER TABLE competitor_product_snapshots ADD COLUMN {column} {definition}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_competitor_products_shop ON competitor_products(shop_id)")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_competitor_products_shop_item ON competitor_products(shop_id, platform_item_id) WHERE platform_item_id != ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_competitor_events_observed ON competitor_events(observed_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_competitor_snapshots_product ON competitor_product_snapshots(product_id, observed_at DESC)")
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
        _migrate_reviews(conn)
        from backend.app.api.promotions.collaboration import ensure_promo_collaboration_tables

        ensure_promo_collaboration_tables(conn)
        conn.commit()
    finally:
        conn.close()

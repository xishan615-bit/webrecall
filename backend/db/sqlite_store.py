"""
db/sqlite_store.py — WebRecall SQLite 存储层

数据库路径：~/.webrecall/pages.db
所有操作均通过此模块，lite_server 和 MCP server 共用。
"""
import os
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Optional

DB_PATH = os.path.expanduser("~/.webrecall/pages.db")
_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        _local.conn = conn
    return _local.conn


def init_sqlite():
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pages (
            url           TEXT PRIMARY KEY,
            title         TEXT,
            domain        TEXT,
            platform      TEXT,
            content       TEXT,
            summary       TEXT,
            saved_at      TEXT,
            saved_at_ts   REAL,
            tags          TEXT,          -- JSON array, e.g. ["科技","Agent"]
            classified_at TEXT           -- ISO 时间戳，NULL = 未分类
        )
    """)
    # 兼容旧库：如果字段不存在则新增
    for col, typedef in [("tags", "TEXT"), ("classified_at", "TEXT")]:
        try:
            conn.execute(f"ALTER TABLE pages ADD COLUMN {col} {typedef}")
        except Exception:
            pass

    conn.execute("CREATE INDEX IF NOT EXISTS idx_platform ON pages(platform)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_saved_at_ts ON pages(saved_at_ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_classified ON pages(classified_at)")

    # ── 分类专家记忆表 ────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS taxonomy_categories (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_id INTEGER REFERENCES taxonomy_categories(id),
            name      TEXT NOT NULL UNIQUE,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS taxonomy_keywords (
            keyword     TEXT NOT NULL,
            category_id INTEGER NOT NULL REFERENCES taxonomy_categories(id),
            weight      REAL DEFAULT 1.0,
            source      TEXT DEFAULT 'auto',  -- auto|user|query
            updated_at  TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (keyword, category_id)
        )
    """)
    conn.commit()


def save_page(*, url: str, title: str, domain: str, platform: str,
              content: str, saved_at: str, saved_at_ts: float,
              summary: str = None):
    conn = _get_conn()
    conn.execute("""
        INSERT INTO pages (url, title, domain, platform, content, summary, saved_at, saved_at_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(url) DO UPDATE SET
            title       = excluded.title,
            domain      = excluded.domain,
            platform    = excluded.platform,
            content     = excluded.content,
            summary     = COALESCE(excluded.summary, pages.summary),
            saved_at    = excluded.saved_at,
            saved_at_ts = excluded.saved_at_ts
    """, (url, title, domain, platform, content, summary, saved_at, saved_at_ts))
    conn.commit()


def delete_page(url: str) -> bool:
    conn = _get_conn()
    cur = conn.execute("DELETE FROM pages WHERE url = ?", (url,))
    conn.commit()
    return cur.rowcount > 0


def get_page(url: str) -> Optional[dict]:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM pages WHERE url = ?", (url,)).fetchone()
    return dict(row) if row else None


def list_pages(limit: int = 200, platform: str = None,
               days: int = None, offset: int = 0) -> list:
    conn = _get_conn()
    sql = "SELECT url, title, domain, platform, summary, saved_at, tags, classified_at FROM pages"
    params = []
    conditions = []
    if platform:
        conditions.append("platform = ?")
        params.append(platform)
    if days:
        since_ts = (datetime.now() - timedelta(days=days)).timestamp()
        conditions.append("saved_at_ts >= ?")
        params.append(since_ts)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY saved_at_ts DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def search_pages(query: str = None, platform: str = None,
                 days: int = None, limit: int = 10) -> list:
    conn = _get_conn()
    base_conditions = []
    base_params = []

    if platform:
        base_conditions.append("platform = ?")
        base_params.append(platform)
    if days:
        since_ts = (datetime.now() - timedelta(days=days)).timestamp()
        base_conditions.append("saved_at_ts >= ?")
        base_params.append(since_ts)

    if query:
        # 用 + 拆成多个必须同时满足的词（AND语义）
        terms = [t.strip() for t in query.split("+") if t.strip()]

        match_params = []
        for term in terms:
            like = f"%{term}%"
            # 每个词：标题 OR 标签 OR 摘要 OR 正文都算命中
            base_conditions.append(
                "(title LIKE ? OR tags LIKE ? OR summary LIKE ? OR content LIKE ?)"
            )
            base_params += [like, like, like, like]
            match_params.append(like)

        # 打分：title 命中词数×3 + tags 命中词数×2，越高越靠前
        # 用 CASE 累加：每个词各贡献一分，title=3 tags=2
        score_parts = []
        score_params = []
        for like in match_params:
            score_parts.append(
                "(CASE WHEN title LIKE ? THEN 3 WHEN tags LIKE ? THEN 2 ELSE 1 END)"
            )
            score_params += [like, like]
        score_expr = " + ".join(score_parts) if score_parts else "1"

        where_clause = (" WHERE " + " AND ".join(base_conditions)) if base_conditions else ""
        sql = (
            f"SELECT url, title, domain, platform, summary, saved_at, tags, classified_at, "
            f"({score_expr}) AS _score "
            f"FROM pages{where_clause} "
            f"ORDER BY _score DESC, saved_at_ts DESC LIMIT ?"
        )
        params = score_params + base_params + [limit]
    else:
        where_clause = (" WHERE " + " AND ".join(base_conditions)) if base_conditions else ""
        sql = (
            "SELECT url, title, domain, platform, summary, saved_at, tags, classified_at "
            f"FROM pages{where_clause} ORDER BY saved_at_ts DESC LIMIT ?"
        )
        params = base_params + [limit]

    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_stats() -> dict:
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
    top_domains = [r[0] for r in conn.execute(
        "SELECT domain, COUNT(*) as c FROM pages GROUP BY domain ORDER BY c DESC LIMIT 5"
    ).fetchall()]
    return {"total_pages": total, "top_domains": top_domains}


def get_overview() -> dict:
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]

    # 平台分布
    platforms = {}
    for row in conn.execute(
        "SELECT platform, COUNT(*) FROM pages WHERE platform != '' GROUP BY platform ORDER BY COUNT(*) DESC"
    ).fetchall():
        platforms[row[0]] = row[1]

    # 时间分布
    now = datetime.now()
    def count_since(days):
        ts = (now - timedelta(days=days)).timestamp()
        return conn.execute("SELECT COUNT(*) FROM pages WHERE saved_at_ts >= ?", (ts,)).fetchone()[0]

    return {
        "total_pages": total,
        "platforms": platforms,
        "time_distribution": {
            "本周": count_since(7),
            "上周": count_since(14) - count_since(7),
            "本月": count_since(30),
        }
    }


# ── 分类专家相关 ──────────────────────────────────────────────

def get_unclassified_pages(limit: int = 50) -> list:
    """返回尚未分类的页面（classified_at IS NULL），只含 url/title/summary。"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT url, title, summary, platform, saved_at FROM pages "
        "WHERE classified_at IS NULL ORDER BY saved_at_ts DESC LIMIT ?",
        (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def batch_update_tags(updates: list) -> int:
    """批量写 tags + classified_at。
    updates: [{"url": str, "tags": ["科技", "AI"], "category": "科技"}]
    返回成功更新的行数。
    """
    import json
    conn = _get_conn()
    now = datetime.now().isoformat()
    count = 0
    for item in updates:
        url  = item.get("url")
        tags = item.get("tags", [])
        if not url:
            continue
        cur = conn.execute(
            "UPDATE pages SET tags = ?, classified_at = ? WHERE url = ?",
            (json.dumps(tags, ensure_ascii=False), now, url)
        )
        count += cur.rowcount
    conn.commit()
    return count


def get_taxonomy() -> dict:
    """读取分类树和关键词绑定（分类专家的长期记忆）。"""
    conn = _get_conn()
    categories = {}
    for row in conn.execute(
        "SELECT id, parent_id, name FROM taxonomy_categories ORDER BY id"
    ).fetchall():
        categories[row["id"]] = {
            "id": row["id"], "parent_id": row["parent_id"], "name": row["name"],
            "keywords": []
        }
    for row in conn.execute(
        "SELECT keyword, category_id, weight, source FROM taxonomy_keywords ORDER BY weight DESC"
    ).fetchall():
        cid = row["category_id"]
        if cid in categories:
            categories[cid]["keywords"].append({
                "keyword": row["keyword"],
                "weight": row["weight"],
                "source": row["source"]
            })
    return {"categories": list(categories.values())}


def update_taxonomy(changes: dict) -> dict:
    """更新分类专家记忆。
    changes 结构:
    {
      "upsert_categories": [{"name": "科技", "parent": ""}],
      "upsert_keywords":   [{"keyword": "Agent", "category": "AI", "weight": 1.0, "source": "user"}],
      "delete_keywords":   ["旧关键词"]
    }
    """
    conn = _get_conn()
    now = datetime.now().isoformat()
    stats = {"categories_upserted": 0, "keywords_upserted": 0, "keywords_deleted": 0}

    # 类目 upsert
    for cat in changes.get("upsert_categories", []):
        parent_id = None
        if cat.get("parent"):
            row = conn.execute(
                "SELECT id FROM taxonomy_categories WHERE name = ?", (cat["parent"],)
            ).fetchone()
            if row:
                parent_id = row["id"]
        conn.execute(
            "INSERT INTO taxonomy_categories (name, parent_id) VALUES (?, ?) "
            "ON CONFLICT(name) DO UPDATE SET parent_id = excluded.parent_id",
            (cat["name"], parent_id)
        )
        stats["categories_upserted"] += 1

    # 关键词 upsert
    for kw in changes.get("upsert_keywords", []):
        cat_row = conn.execute(
            "SELECT id FROM taxonomy_categories WHERE name = ?", (kw["category"],)
        ).fetchone()
        if not cat_row:
            continue
        conn.execute(
            "INSERT INTO taxonomy_keywords (keyword, category_id, weight, source, updated_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(keyword, category_id) DO UPDATE SET "
            "weight = excluded.weight, source = excluded.source, updated_at = excluded.updated_at",
            (kw["keyword"], cat_row["id"], kw.get("weight", 1.0), kw.get("source", "auto"), now)
        )
        stats["keywords_upserted"] += 1

    # 关键词删除
    for kw in changes.get("delete_keywords", []):
        conn.execute("DELETE FROM taxonomy_keywords WHERE keyword = ?", (kw,))
        stats["keywords_deleted"] += 1

    conn.commit()
    return stats

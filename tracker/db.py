import sqlite3
from pathlib import Path

from tracker.models import WindowEvent

SCHEMA = """
CREATE TABLE IF NOT EXISTS window_events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    app_name         TEXT    NOT NULL,
    window_title     TEXT    NOT NULL,
    started_at       TEXT    NOT NULL,
    duration_seconds INTEGER NOT NULL,
    category         TEXT,
    sub_category     TEXT
);
"""

SCHEMA_RULES = """
CREATE TABLE IF NOT EXISTS category_rules (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    field        TEXT NOT NULL,
    pattern      TEXT NOT NULL,
    category     TEXT NOT NULL,
    sub_category TEXT
);
"""

SCHEMA_CATEGORIES = """
CREATE TABLE IF NOT EXISTS categories (
    name TEXT PRIMARY KEY
);
"""

SCHEMA_SUB_CATEGORIES = """
CREATE TABLE IF NOT EXISTS sub_categories (
    category TEXT NOT NULL,
    name     TEXT NOT NULL,
    PRIMARY KEY (category, name)
);
"""

_MIGRATIONS = [
    "ALTER TABLE window_events ADD COLUMN category TEXT;",
    "ALTER TABLE window_events ADD COLUMN sub_category TEXT;",
]


def open_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.execute(SCHEMA)
    conn.execute(SCHEMA_RULES)
    conn.execute(SCHEMA_CATEGORIES)
    conn.execute(SCHEMA_SUB_CATEGORIES)
    conn.commit()
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Add new columns to existing databases that pre-date the schema update."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(window_events)")}
    for stmt in _MIGRATIONS:
        col = stmt.split("ADD COLUMN")[1].split()[0]
        if col not in existing:
            conn.execute(stmt)
    conn.commit()


def insert_event(conn: sqlite3.Connection, event: WindowEvent) -> int:
    cur = conn.execute(
        "INSERT INTO window_events (app_name, window_title, started_at, duration_seconds) VALUES (?, ?, ?, ?)",
        (
            event.app_name,
            event.window_title,
            event.started_at.isoformat(),
            event.duration_seconds,
        ),
    )
    conn.commit()
    return cur.lastrowid


def update_event_category(
    conn: sqlite3.Connection,
    event_id: int,
    category: str | None,
    sub_category: str | None,
) -> None:
    conn.execute(
        "UPDATE window_events SET category = ?, sub_category = ? WHERE id = ?",
        (category or None, sub_category or None, event_id),
    )
    conn.commit()


def get_event_dates(conn: sqlite3.Connection) -> list[str]:
    """Return distinct calendar dates (YYYY-MM-DD) that have events, newest first."""
    cur = conn.execute(
        "SELECT DISTINCT DATE(started_at) AS d FROM window_events ORDER BY d DESC"
    )
    return [row[0] for row in cur.fetchall()]


def get_all_events(conn: sqlite3.Connection, date: str | None = None) -> list[dict]:
    if date:
        cur = conn.execute(
            "SELECT id, app_name, window_title, started_at, duration_seconds, category, sub_category "
            "FROM window_events WHERE DATE(started_at) = ? ORDER BY started_at DESC",
            (date,),
        )
    else:
        cur = conn.execute(
            "SELECT id, app_name, window_title, started_at, duration_seconds, category, sub_category "
            "FROM window_events ORDER BY started_at DESC"
        )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_known_categories(conn: sqlite3.Connection) -> list[str]:
    cur = conn.execute(
        """
        SELECT DISTINCT name FROM (
            SELECT name FROM categories
            UNION
            SELECT category AS name FROM window_events WHERE category IS NOT NULL
        ) ORDER BY name
        """
    )
    return [row[0] for row in cur.fetchall()]


def get_known_sub_categories(conn: sqlite3.Connection, category: str | None = None) -> list[str]:
    if category:
        cur = conn.execute(
            """
            SELECT DISTINCT name FROM (
                SELECT name FROM sub_categories WHERE category = ?
                UNION
                SELECT sub_category AS name FROM window_events
                WHERE sub_category IS NOT NULL AND category = ?
            ) ORDER BY name
            """,
            (category, category),
        )
    else:
        cur = conn.execute(
            """
            SELECT DISTINCT name FROM (
                SELECT name FROM sub_categories
                UNION
                SELECT sub_category AS name FROM window_events WHERE sub_category IS NOT NULL
            ) ORDER BY name
            """
        )
    return [row[0] for row in cur.fetchall()]


def get_uncategorized_count(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM window_events WHERE category IS NULL"
    ).fetchone()[0]


def create_category(conn: sqlite3.Connection, name: str) -> None:
    conn.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (name,))
    conn.commit()


def rename_category(conn: sqlite3.Connection, old_name: str, new_name: str) -> None:
    conn.execute(
        "UPDATE window_events SET category = ? WHERE category = ?", (new_name, old_name)
    )
    conn.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (new_name,))
    conn.execute("DELETE FROM categories WHERE name = ?", (old_name,))
    conn.commit()


def delete_category(conn: sqlite3.Connection, name: str) -> None:
    conn.execute(
        "UPDATE window_events SET category = NULL, sub_category = NULL WHERE category = ?",
        (name,),
    )
    conn.execute("DELETE FROM categories WHERE name = ?", (name,))
    conn.commit()


def create_sub_category(conn: sqlite3.Connection, category: str, name: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO sub_categories (category, name) VALUES (?, ?)", (category, name)
    )
    conn.commit()


def rename_sub_category(
    conn: sqlite3.Connection, category: str, old_name: str, new_name: str
) -> None:
    conn.execute(
        "UPDATE window_events SET sub_category = ? WHERE category = ? AND sub_category = ?",
        (new_name, category, old_name),
    )
    conn.execute(
        "INSERT OR IGNORE INTO sub_categories (category, name) VALUES (?, ?)", (category, new_name)
    )
    conn.execute(
        "DELETE FROM sub_categories WHERE category = ? AND name = ?", (category, old_name)
    )
    conn.commit()


def delete_sub_category(conn: sqlite3.Connection, category: str, name: str) -> None:
    conn.execute(
        "UPDATE window_events SET sub_category = NULL WHERE category = ? AND sub_category = ?",
        (category, name),
    )
    conn.execute(
        "DELETE FROM sub_categories WHERE category = ? AND name = ?", (category, name)
    )
    conn.commit()


def bulk_update_categories(
    conn: sqlite3.Connection, pending: dict[int, tuple[str | None, str | None]]
) -> None:
    for event_id, (cat, sub) in pending.items():
        conn.execute(
            "UPDATE window_events SET category = ?, sub_category = ? WHERE id = ?",
            (cat, sub, event_id),
        )
    conn.commit()


def get_rules(conn: sqlite3.Connection) -> list[dict]:
    cur = conn.execute(
        "SELECT id, field, pattern, category, sub_category FROM category_rules ORDER BY id"
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def insert_rule(
    conn: sqlite3.Connection,
    field: str,
    pattern: str,
    category: str,
    sub_category: str | None,
) -> None:
    conn.execute(
        "INSERT INTO category_rules (field, pattern, category, sub_category) VALUES (?, ?, ?, ?)",
        (field, pattern, category, sub_category or None),
    )
    conn.commit()


def delete_rule(conn: sqlite3.Connection, rule_id: int) -> None:
    conn.execute("DELETE FROM category_rules WHERE id = ?", (rule_id,))
    conn.commit()


def auto_categorize_event(
    conn: sqlite3.Connection, event_id: int, app_name: str, window_title: str
) -> bool:
    """Apply the first matching rule to a single event. Returns True if a rule matched."""
    for rule in get_rules(conn):
        value = app_name if rule["field"] == "app_name" else window_title
        if rule["pattern"].lower() in value.lower():
            update_event_category(conn, event_id, rule["category"], rule["sub_category"])
            return True
    return False


def apply_rules_to_uncategorized(conn: sqlite3.Connection) -> int:
    """Apply rules to every uncategorized event. Returns the number newly categorized."""
    rules = get_rules(conn)
    if not rules:
        return 0
    rows = conn.execute(
        "SELECT id, app_name, window_title FROM window_events WHERE category IS NULL"
    ).fetchall()
    count = 0
    for event_id, app_name, window_title in rows:
        for rule in rules:
            value = app_name if rule["field"] == "app_name" else window_title
            if rule["pattern"].lower() in value.lower():
                update_event_category(conn, event_id, rule["category"], rule["sub_category"])
                count += 1
                break
    return count


def get_summary(conn: sqlite3.Connection, date: str | None = None) -> list[dict]:
    if date:
        cur = conn.execute(
            """
            SELECT
                COALESCE(category, '(Uncategorized)') AS category,
                COALESCE(sub_category, '')             AS sub_category,
                SUM(duration_seconds)                  AS total_seconds,
                COUNT(*)                               AS event_count
            FROM window_events
            WHERE DATE(started_at) = ?
            GROUP BY category, sub_category
            ORDER BY total_seconds DESC
            """,
            (date,),
        )
    else:
        cur = conn.execute(
            """
            SELECT
                COALESCE(category, '(Uncategorized)') AS category,
                COALESCE(sub_category, '')             AS sub_category,
                SUM(duration_seconds)                  AS total_seconds,
                COUNT(*)                               AS event_count
            FROM window_events
            GROUP BY category, sub_category
            ORDER BY total_seconds DESC
            """
        )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]

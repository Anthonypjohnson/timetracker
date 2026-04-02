import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from tracker.models import WindowEvent


def _tz_modifier() -> str:
    """SQLite datetime modifier string for the local UTC offset, e.g. '+330 minutes'."""
    offset = datetime.now(timezone.utc).astimezone().utcoffset()
    minutes = int(offset.total_seconds() / 60)
    return f"{minutes:+d} minutes"

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
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    app_name_pattern     TEXT,
    window_title_pattern TEXT,
    category             TEXT NOT NULL,
    sub_category         TEXT,
    priority             INTEGER NOT NULL DEFAULT 0
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

SCHEMA_SETTINGS = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Ordered list of schema migrations. Each entry corresponds to a schema version.
# IMPORTANT: Never edit or reorder existing entries — only append new ones.
# The index (0-based) + 1 is the version number written to PRAGMA user_version.
_MIGRATIONS: list[str] = [
    # v1
    "ALTER TABLE window_events ADD COLUMN category TEXT;",
    # v2
    "ALTER TABLE window_events ADD COLUMN sub_category TEXT;",
    # v3
    "ALTER TABLE category_rules ADD COLUMN app_name_pattern TEXT;",
    # v4
    "ALTER TABLE category_rules ADD COLUMN window_title_pattern TEXT;",
    # v5
    "ALTER TABLE category_rules ADD COLUMN priority INTEGER NOT NULL DEFAULT 0;",
    # v6
    "ALTER TABLE categories ADD COLUMN excluded INTEGER NOT NULL DEFAULT 0;",
    # v7
    "ALTER TABLE sub_categories ADD COLUMN excluded INTEGER NOT NULL DEFAULT 0;",
]


def open_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(SCHEMA)
    conn.execute(SCHEMA_RULES)
    conn.execute(SCHEMA_CATEGORIES)
    conn.execute(SCHEMA_SUB_CATEGORIES)
    conn.execute(SCHEMA_SETTINGS)
    conn.commit()
    _migrate(conn)
    _seed_defaults(conn)
    return conn


_DEFAULT_CATEGORIES: list[tuple[str, list[str]]] = [
    ("Work",         ["Email", "Meetings", "Coding", "Documents", "Research"]),
    ("Communication",["Messaging", "Video Calls"]),
    ("Productivity", ["Planning", "Notes"]),
    ("Entertainment",["Video", "Music", "Gaming", "Social Media"]),
    ("Utilities",    ["File Management", "Settings", "Terminal"]),
    ("Web Browsing", []),
    ("Other",        []),
]

# (app_name_pattern, window_title_pattern, category, sub_category, priority)
_DEFAULT_RULES: list[tuple[str | None, str | None, str, str | None, int]] = [
    # --- Communication ---
    ("outlook.exe",       None,                    "Work",          "Email",        10),
    ("thunderbird.exe",   None,                    "Work",          "Email",        10),
    (None,                "Gmail",                 "Work",          "Email",         8),
    ("teams.exe",         None,                    "Communication", "Meetings",     10),
    ("zoom.exe",          None,                    "Communication", "Video Calls",  10),
    ("slack.exe",         None,                    "Communication", "Messaging",    10),
    ("discord.exe",       None,                    "Communication", "Messaging",    10),
    ("msteams.exe",       None,                    "Communication", "Meetings",     10),
    # --- Coding ---
    ("code.exe",          None,                    "Work",          "Coding",       10),
    ("devenv.exe",        None,                    "Work",          "Coding",       10),
    ("idea64.exe",        None,                    "Work",          "Coding",       10),
    ("pycharm64.exe",     None,                    "Work",          "Coding",       10),
    ("windowsterminal.exe", None,                  "Utilities",     "Terminal",     10),
    ("cmd.exe",           None,                    "Utilities",     "Terminal",      8),
    ("powershell.exe",    None,                    "Utilities",     "Terminal",      8),
    # --- Documents / Office ---
    ("winword.exe",       None,                    "Work",          "Documents",    10),
    ("excel.exe",         None,                    "Work",          "Documents",    10),
    ("powerpnt.exe",      None,                    "Work",          "Documents",    10),
    ("onenote.exe",       None,                    "Productivity",  "Notes",        10),
    ("notion.exe",        None,                    "Productivity",  "Notes",        10),
    ("obsidian.exe",      None,                    "Productivity",  "Notes",        10),
    # --- Entertainment ---
    ("vlc.exe",           None,                    "Entertainment", "Video",        10),
    ("netflix.exe",       None,                    "Entertainment", "Video",        10),
    (None,                "YouTube",               "Entertainment", "Video",         7),
    ("spotify.exe",       None,                    "Entertainment", "Music",        10),
    ("steam.exe",         None,                    "Entertainment", "Gaming",       10),
    # --- Utilities ---
    ("explorer.exe",      None,                    "Utilities",     "File Management", 10),
    # --- Web browsing (low priority — catches browser windows not matched above) ---
    ("chrome.exe",        None,                    "Web Browsing",  None,            1),
    ("firefox.exe",       None,                    "Web Browsing",  None,            1),
    ("msedge.exe",        None,                    "Web Browsing",  None,            1),
    ("brave.exe",         None,                    "Web Browsing",  None,            1),
    ("opera.exe",         None,                    "Web Browsing",  None,            1),
]


def _seed_defaults(conn: sqlite3.Connection) -> None:
    """Insert default categories and rules on a fresh database (no-op if data already exists)."""
    has_cats = conn.execute("SELECT 1 FROM categories LIMIT 1").fetchone()
    has_rules = conn.execute("SELECT 1 FROM category_rules LIMIT 1").fetchone()
    if has_cats or has_rules:
        return
    for category, subs in _DEFAULT_CATEGORIES:
        conn.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (category,))
        for sub in subs:
            conn.execute(
                "INSERT OR IGNORE INTO sub_categories (category, name) VALUES (?, ?)",
                (category, sub),
            )
    for app_pat, title_pat, cat, sub, priority in _DEFAULT_RULES:
        conn.execute(
            "INSERT INTO category_rules (app_name_pattern, window_title_pattern, category, sub_category, priority)"
            " VALUES (?, ?, ?, ?, ?)",
            (app_pat, title_pat, cat, sub, priority),
        )
    conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """Run any pending schema migrations using PRAGMA user_version for tracking."""
    current: int = conn.execute("PRAGMA user_version").fetchone()[0]

    # Bootstrap: existing databases pre-date versioning — detect their current state
    # by inspecting columns so we don't re-run already-applied migrations.
    if current == 0:
        we_cols = {row[1] for row in conn.execute("PRAGMA table_info(window_events)")}
        cr_cols = {row[1] for row in conn.execute("PRAGMA table_info(category_rules)")}
        if "priority" in cr_cols:
            current = 5
        elif "window_title_pattern" in cr_cols:
            current = 4
        elif "app_name_pattern" in cr_cols:
            current = 3
        elif "sub_category" in we_cols:
            current = 2
        elif "category" in we_cols:
            current = 1
        conn.execute(f"PRAGMA user_version = {current}")
        conn.commit()

    for version, stmt in enumerate(_MIGRATIONS[current:], start=current + 1):
        conn.execute(stmt)
        # One-time data migration: after adding the new pattern columns, copy data
        # from the old field/pattern columns if they existed in legacy databases.
        if version == 4:
            cr_cols = {row[1] for row in conn.execute("PRAGMA table_info(category_rules)")}
            if "field" in cr_cols:
                conn.execute(
                    "UPDATE category_rules SET app_name_pattern = pattern WHERE field = 'app_name'"
                )
                conn.execute(
                    "UPDATE category_rules SET window_title_pattern = pattern WHERE field = 'window_title'"
                )
        conn.execute(f"PRAGMA user_version = {version}")
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
    tz = _tz_modifier()
    cur = conn.execute(
        "SELECT DISTINCT DATE(datetime(started_at, ?)) AS d FROM window_events ORDER BY d DESC",
        (tz,),
    )
    return [row[0] for row in cur.fetchall()]


def get_all_events(conn: sqlite3.Connection, date: str | None = None) -> list[dict]:
    tz = _tz_modifier()
    if date:
        cur = conn.execute(
            "SELECT id, app_name, window_title, started_at, duration_seconds, category, sub_category "
            "FROM window_events WHERE DATE(datetime(started_at, ?)) = ? ORDER BY started_at DESC",
            (tz, date),
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


def get_category_excluded(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute("SELECT excluded FROM categories WHERE name = ?", (name,)).fetchone()
    return bool(row[0]) if row else False


def set_category_excluded(conn: sqlite3.Connection, name: str, excluded: bool) -> None:
    conn.execute("UPDATE categories SET excluded = ? WHERE name = ?", (int(excluded), name))
    conn.commit()


def get_sub_category_excluded(conn: sqlite3.Connection, category: str, name: str) -> bool:
    row = conn.execute(
        "SELECT excluded FROM sub_categories WHERE category = ? AND name = ?", (category, name)
    ).fetchone()
    return bool(row[0]) if row else False


def set_sub_category_excluded(
    conn: sqlite3.Connection, category: str, name: str, excluded: bool
) -> None:
    conn.execute(
        "UPDATE sub_categories SET excluded = ? WHERE category = ? AND name = ?",
        (int(excluded), category, name),
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
        "SELECT id, app_name_pattern, window_title_pattern, category, sub_category, priority"
        " FROM category_rules ORDER BY priority DESC, id ASC"
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def ensure_category_exists(
    conn: sqlite3.Connection, category: str, sub_category: str | None
) -> None:
    """Insert category (and optional sub-category) if they don't already exist."""
    if not category:
        return
    conn.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (category,))
    if sub_category:
        conn.execute(
            "INSERT OR IGNORE INTO sub_categories (category, name) VALUES (?, ?)",
            (category, sub_category),
        )
    conn.commit()


def insert_rule(
    conn: sqlite3.Connection,
    app_name_pattern: str | None,
    window_title_pattern: str | None,
    category: str,
    sub_category: str | None,
    priority: int = 0,
) -> None:
    ensure_category_exists(conn, category, sub_category or None)
    conn.execute(
        "INSERT INTO category_rules"
        " (app_name_pattern, window_title_pattern, category, sub_category, priority)"
        " VALUES (?, ?, ?, ?, ?)",
        (app_name_pattern or None, window_title_pattern or None, category, sub_category or None, priority),
    )
    conn.commit()


def delete_rule(conn: sqlite3.Connection, rule_id: int) -> None:
    conn.execute("DELETE FROM category_rules WHERE id = ?", (rule_id,))
    conn.commit()


def update_rule(
    conn: sqlite3.Connection,
    rule_id: int,
    app_name_pattern: str | None,
    window_title_pattern: str | None,
    category: str,
    sub_category: str | None,
    priority: int = 0,
) -> None:
    ensure_category_exists(conn, category, sub_category or None)
    conn.execute(
        "UPDATE category_rules"
        " SET app_name_pattern=?, window_title_pattern=?, category=?, sub_category=?, priority=?"
        " WHERE id=?",
        (app_name_pattern or None, window_title_pattern or None, category, sub_category or None, priority, rule_id),
    )
    conn.commit()


def export_data(conn: sqlite3.Connection) -> dict:
    """Return all categories, sub-categories, and rules as a JSON-serializable dict."""
    cats: dict[str, list[str]] = {}
    for cat in get_known_categories(conn):
        cats[cat] = get_known_sub_categories(conn, cat)
    rules = [
        {
            "app_name_pattern": r["app_name_pattern"],
            "window_title_pattern": r["window_title_pattern"],
            "category": r["category"],
            "sub_category": r["sub_category"],
            "priority": r["priority"],
        }
        for r in get_rules(conn)
    ]
    return {"categories": cats, "rules": rules}


def import_data(conn: sqlite3.Connection, data: dict) -> tuple[int, int]:
    """
    Merge categories and rules from *data* into the database.
    Returns (categories_added, rules_added).
    Categories/sub-categories use INSERT OR IGNORE (no duplicates).
    Rules are always inserted (the user can delete duplicates manually).
    """
    cats_added = 0
    for cat, subs in data.get("categories", {}).items():
        if not cat:
            continue
        before = conn.execute(
            "SELECT 1 FROM categories WHERE name = ?", (cat,)
        ).fetchone()
        conn.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (cat,))
        if not before:
            cats_added += 1
        for sub in subs or []:
            if not sub:
                continue
            before_sub = conn.execute(
                "SELECT 1 FROM sub_categories WHERE category = ? AND name = ?", (cat, sub)
            ).fetchone()
            conn.execute(
                "INSERT OR IGNORE INTO sub_categories (category, name) VALUES (?, ?)", (cat, sub)
            )
            if not before_sub:
                cats_added += 1
    rules_added = 0
    for rule in data.get("rules", []):
        cat = rule.get("category", "")
        if not cat:
            continue
        app_pat = rule.get("app_name_pattern") or None
        title_pat = rule.get("window_title_pattern") or None
        sub = rule.get("sub_category") or None
        priority = int(rule.get("priority") or 0)
        conn.execute(
            "INSERT INTO category_rules"
            " (app_name_pattern, window_title_pattern, category, sub_category, priority)"
            " VALUES (?, ?, ?, ?, ?)",
            (app_pat, title_pat, cat, sub, priority),
        )
        rules_added += 1
    conn.commit()
    return cats_added, rules_added


def _rule_matches(rule: dict, app_name: str, window_title: str) -> bool:
    """Return True if all non-null patterns in the rule match the given fields."""
    app_pat = rule["app_name_pattern"]
    title_pat = rule["window_title_pattern"]
    if not app_pat and not title_pat:
        return False
    if app_pat and app_pat.lower() not in app_name.lower():
        return False
    if title_pat and title_pat.lower() not in window_title.lower():
        return False
    return True


def auto_categorize_event(
    conn: sqlite3.Connection, event_id: int, app_name: str, window_title: str
) -> bool:
    """Apply the highest-priority matching rule to a single event. Returns True if matched."""
    for rule in get_rules(conn):  # already sorted by priority DESC
        if _rule_matches(rule, app_name, window_title):
            update_event_category(conn, event_id, rule["category"], rule["sub_category"])
            return True
    return False


def apply_rules_to_uncategorized(conn: sqlite3.Connection) -> int:
    """Apply rules to every uncategorized event. Returns the number newly categorized."""
    rules = get_rules(conn)  # already sorted by priority DESC
    if not rules:
        return 0
    rows = conn.execute(
        "SELECT id, app_name, window_title FROM window_events WHERE category IS NULL"
    ).fetchall()
    count = 0
    for event_id, app_name, window_title in rows:
        for rule in rules:
            if _rule_matches(rule, app_name, window_title):
                update_event_category(conn, event_id, rule["category"], rule["sub_category"])
                count += 1
                break
    return count


def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
    )
    conn.commit()


def get_summary(conn: sqlite3.Connection, date: str | None = None) -> list[dict]:
    tz = _tz_modifier()
    date_clause = "AND DATE(datetime(started_at, ?)) = ?" if date else ""
    params = (tz, date) if date else ()
    cur = conn.execute(
        f"""
        SELECT
            COALESCE(category, '(Uncategorized)') AS category,
            COALESCE(sub_category, '')             AS sub_category,
            SUM(duration_seconds)                  AS total_seconds,
            COUNT(*)                               AS event_count
        FROM window_events
        WHERE NOT EXISTS (
            SELECT 1 FROM categories
            WHERE name = window_events.category AND excluded = 1
        )
        AND NOT EXISTS (
            SELECT 1 FROM sub_categories
            WHERE category = window_events.category
            AND name = window_events.sub_category
            AND excluded = 1
        )
        {date_clause}
        GROUP BY category, sub_category
        ORDER BY total_seconds DESC
        """,
        params,
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]
